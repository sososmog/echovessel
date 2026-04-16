"""Worker ζ · cost_logger module unit tests.

Coverage:

- :class:`CostRecorder` writes a row and returns a populated
  :class:`LLMCallRecord`
- :class:`CostTrackingProvider` records on every ``complete`` call
  and on every ``stream`` consumption
- :func:`feature_context` propagates the feature label into the
  recorded row
- :func:`summarize` aggregates by feature and by day across the
  ``today`` / ``7d`` / ``30d`` ranges
- :func:`list_recent` returns newest-first up to its cap
- Stub-provider records are zero-cost (free tier short-circuit)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session as DbSession

from echovessel.memory import create_all_tables, create_engine
from echovessel.runtime.cost_logger import (
    CostRecorder,
    CostTrackingProvider,
    feature_context,
    list_recent,
    summarize,
)
from echovessel.runtime.llm.base import LLMTier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_engine_and_recorder():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    def _factory() -> DbSession:
        return DbSession(engine)

    return engine, CostRecorder(_factory)


class _FakeProvider:
    """Tiny LLMProvider stub: records every call's args and returns
    a deterministic body so tests can assert on token counts."""

    def __init__(self, *, name: str = "openai_compat", model: str = "gpt-4o") -> None:
        self.provider_name = name
        self._model = model
        self.complete_calls: list[dict] = []
        self.stream_calls: list[dict] = []

    def model_for(self, tier: LLMTier) -> str:
        return self._model

    async def complete(
        self,
        system: str,
        user: str,
        *,
        tier: LLMTier = LLMTier.MEDIUM,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> str:
        self.complete_calls.append({"system": system, "user": user, "tier": tier})
        return "ok response"

    async def stream(
        self,
        system: str,
        user: str,
        *,
        tier: LLMTier = LLMTier.MEDIUM,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        self.stream_calls.append({"system": system, "user": user, "tier": tier})
        for piece in ("hel", "lo ", "wor", "ld"):
            yield piece


# ---------------------------------------------------------------------------
# CostRecorder direct
# ---------------------------------------------------------------------------


def test_recorder_persists_row_and_returns_record() -> None:
    _engine, recorder = _build_engine_and_recorder()
    record = recorder.record(
        provider="openai_compat",
        model="gpt-4o",
        feature="chat",
        tier="large",
        input_text="hello system\nhello user",
        output_text="here is a reply",
        turn_id="turn-abc",
    )
    assert record is not None
    assert record.provider == "openai_compat"
    assert record.model == "gpt-4o"
    assert record.feature == "chat"
    assert record.tier == "large"
    assert record.tokens_in > 0
    assert record.tokens_out > 0
    assert record.cost_usd > 0  # non-stub provider has a non-zero rate
    assert record.turn_id == "turn-abc"
    assert record.timestamp  # ISO 8601 string


def test_recorder_stub_provider_yields_zero_cost() -> None:
    _engine, recorder = _build_engine_and_recorder()
    record = recorder.record(
        provider="stub",
        model="stub-model",
        feature="consolidate",
        tier="small",
        input_text="x" * 500,
        output_text="y" * 500,
    )
    assert record is not None
    assert record.cost_usd == 0.0
    # Tokens are still counted so the admin tab can show usage even
    # for free providers.
    assert record.tokens_in > 0
    assert record.tokens_out > 0


# ---------------------------------------------------------------------------
# CostTrackingProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tracking_provider_records_complete_call() -> None:
    engine, recorder = _build_engine_and_recorder()
    inner = _FakeProvider()
    wrapped = CostTrackingProvider(inner, recorder)

    with feature_context("chat", turn_id="turn-1"):
        result = await wrapped.complete("sys", "usr", tier=LLMTier.LARGE)
    assert result == "ok response"
    assert inner.complete_calls  # delegated

    with DbSession(engine) as db:
        rows = list_recent(db, limit=10)
    assert len(rows) == 1
    assert rows[0].feature == "chat"
    assert rows[0].turn_id == "turn-1"
    assert rows[0].tier == "large"


@pytest.mark.asyncio
async def test_tracking_provider_records_stream_after_full_consume() -> None:
    engine, recorder = _build_engine_and_recorder()
    inner = _FakeProvider()
    wrapped = CostTrackingProvider(inner, recorder)

    with feature_context("import"):
        chunks = []
        async for piece in wrapped.stream("sys", "usr", tier=LLMTier.SMALL):
            chunks.append(piece)
    assert "".join(chunks) == "hello world"

    with DbSession(engine) as db:
        rows = list_recent(db, limit=10)
    assert len(rows) == 1
    assert rows[0].feature == "import"
    assert rows[0].tier == "small"
    # tokens_out reflects the joined stream output, not just one chunk.
    assert rows[0].tokens_out >= 1


@pytest.mark.asyncio
async def test_feature_context_default_when_unset() -> None:
    engine, recorder = _build_engine_and_recorder()
    wrapped = CostTrackingProvider(_FakeProvider(), recorder)

    # No feature_context wrapper — call still records, label is "unknown".
    await wrapped.complete("a", "b")
    with DbSession(engine) as db:
        rows = list_recent(db, limit=5)
    assert len(rows) == 1
    assert rows[0].feature == "unknown"


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def _seed_call(
    recorder: CostRecorder,
    *,
    feature: str,
    when: datetime,
    cost_provider: str = "openai_compat",
) -> None:
    recorder.record(
        provider=cost_provider,
        model="gpt-4o",
        feature=feature,
        tier="medium",
        input_text="hello world " * 5,
        output_text="reply " * 8,
        timestamp=when,
    )


def test_summarize_groups_by_feature_within_30d_window() -> None:
    engine, recorder = _build_engine_and_recorder()
    today = datetime.now()
    _seed_call(recorder, feature="chat", when=today)
    _seed_call(recorder, feature="chat", when=today - timedelta(days=2))
    _seed_call(recorder, feature="import", when=today - timedelta(days=5))
    _seed_call(recorder, feature="proactive", when=today - timedelta(days=15))

    with DbSession(engine) as db:
        summary = summarize(db, range_label="30d", now=today)
    assert summary["range"] == "30d"
    assert summary["total_tokens"] > 0
    assert summary["total_usd"] > 0
    assert set(summary["by_feature"].keys()) == {"chat", "import", "proactive"}
    assert summary["by_feature"]["chat"]["calls"] == 2
    assert summary["by_feature"]["import"]["calls"] == 1
    assert summary["by_feature"]["proactive"]["calls"] == 1
    # by_day is ordered ASC by date and has at least 3 distinct dates
    dates = [b["date"] for b in summary["by_day"]]
    assert dates == sorted(dates)
    assert len(dates) >= 3


def test_summarize_today_excludes_yesterday() -> None:
    engine, recorder = _build_engine_and_recorder()
    today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    _seed_call(recorder, feature="chat", when=today)
    _seed_call(recorder, feature="chat", when=today - timedelta(days=1))

    with DbSession(engine) as db:
        summary = summarize(db, range_label="today", now=today)
    assert summary["by_feature"]["chat"]["calls"] == 1


def test_summarize_unknown_range_raises() -> None:
    engine, _recorder = _build_engine_and_recorder()
    with DbSession(engine) as db, pytest.raises(ValueError):
        summarize(db, range_label="all-time")


def test_list_recent_orders_newest_first_and_caps_limit() -> None:
    engine, recorder = _build_engine_and_recorder()
    base = datetime(2026, 4, 16, 12, 0, 0)
    for i in range(5):
        _seed_call(
            recorder,
            feature="chat",
            when=base + timedelta(minutes=i),
        )
    with DbSession(engine) as db:
        rows = list_recent(db, limit=3)
    assert len(rows) == 3
    # ISO timestamps strictly decreasing.
    times = [r.timestamp for r in rows]
    assert times == sorted(times, reverse=True)


# ---------------------------------------------------------------------------
# Smoke: contextvars survive asyncio.create_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feature_context_propagates_through_create_task() -> None:
    engine, recorder = _build_engine_and_recorder()
    wrapped = CostTrackingProvider(_FakeProvider(), recorder)

    async def _inner_call() -> None:
        await wrapped.complete("sys", "usr")

    with feature_context("proactive"):
        # asyncio.create_task copies the current context, so the
        # feature label "proactive" must reach the cost row even
        # though the call happens inside a fresh task.
        task = asyncio.create_task(_inner_call())
        await task

    with DbSession(engine) as db:
        rows = list_recent(db, limit=5)
    assert len(rows) == 1
    assert rows[0].feature == "proactive"
