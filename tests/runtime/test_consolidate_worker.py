"""ConsolidateWorker — PR6 tests."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session as DbSession

from echovessel.core.types import MessageRole, SessionStatus
from echovessel.memory import (
    Persona,
    RecallMessage,
    Session,
    User,
    create_all_tables,
    create_engine,
)
from echovessel.memory.backends.sqlite import SQLiteBackend
from echovessel.memory.consolidate import ExtractedEvent
from echovessel.runtime.consolidate_worker import ConsolidateWorker
from echovessel.runtime.llm.errors import LLMPermanentError, LLMTransientError


def _embed(text: str) -> list[float]:
    v = [0.0] * 384
    v[hash(text) % 384] = 1.0
    return v


def _seed(engine) -> None:
    with DbSession(engine) as db:
        db.add(Persona(id="p", display_name="x"))
        db.add(User(id="self", display_name="Alan"))
        db.commit()


def _add_closing_session(engine, sid: str, message_contents: list[str]) -> None:
    with DbSession(engine) as db:
        sess = Session(
            id=sid,
            persona_id="p",
            user_id="self",
            channel_id="t",
            status=SessionStatus.CLOSING,
            message_count=len(message_contents),
            total_tokens=sum(len(c) for c in message_contents),
        )
        db.add(sess)
        db.commit()

        for i, c in enumerate(message_contents):
            db.add(
                RecallMessage(
                    session_id=sid,
                    persona_id="p",
                    user_id="self",
                    channel_id="t",
                    role=MessageRole.USER if i % 2 == 0 else MessageRole.PERSONA,
                    content=c,
                    day=date.today(),
                    token_count=len(c),
                )
            )
        db.commit()


async def _noop_reflect(nodes, reason):
    return []


async def test_worker_processes_closing_session_and_marks_closed():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    backend = SQLiteBackend(engine)
    _seed(engine)
    _add_closing_session(
        engine,
        "s_1",
        [
            "今天我家狗子跑丢了",
            "还好邻居帮忙找到",
            "虚惊一场",
            "回家就给他奖励了肉干",
            "差点吓死我",
        ],
    )

    async def extractor(msgs):
        return [
            ExtractedEvent(
                description="用户的狗短暂走失后被邻居找回",
                emotional_impact=3,
                emotion_tags=["relief"],
            )
        ]

    def db_factory():
        return DbSession(engine)

    worker = ConsolidateWorker(
        db_factory=db_factory,
        backend=backend,
        extract_fn=extractor,
        reflect_fn=_noop_reflect,
        embed_fn=_embed,
    )
    processed = await worker.drain_once()
    assert processed == 1

    with DbSession(engine) as db:
        sess = db.get(Session, "s_1")
        assert sess is not None
        assert sess.status == SessionStatus.CLOSED
        assert sess.extracted is True


async def test_worker_idempotent_on_already_extracted():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    backend = SQLiteBackend(engine)
    _seed(engine)
    _add_closing_session(
        engine,
        "s_iden",
        [
            "闲聊一",
            "闲聊二",
            "闲聊三",
            "闲聊四",
            "闲聊五",
        ],
    )

    extract_calls: list[int] = []

    async def extractor(msgs):
        extract_calls.append(len(msgs))
        return []

    def db_factory():
        return DbSession(engine)

    worker = ConsolidateWorker(
        db_factory=db_factory,
        backend=backend,
        extract_fn=extractor,
        reflect_fn=_noop_reflect,
        embed_fn=_embed,
    )
    await worker.drain_once()
    # A second drain should be a no-op — session is now CLOSED.
    await worker.drain_once()

    assert extract_calls == [5]


async def test_worker_marks_failed_after_transient_exhaustion(monkeypatch):
    engine = create_engine(":memory:")
    create_all_tables(engine)
    backend = SQLiteBackend(engine)
    _seed(engine)
    _add_closing_session(
        engine,
        "s_flake",
        ["raw" * 40, "raw2" * 40, "raw3" * 40, "raw4" * 40, "raw5" * 40],
    )

    async def flaky(msgs):
        raise LLMTransientError("boom")

    def db_factory():
        return DbSession(engine)

    worker = ConsolidateWorker(
        db_factory=db_factory,
        backend=backend,
        extract_fn=flaky,
        reflect_fn=_noop_reflect,
        embed_fn=_embed,
        max_retries=2,
    )

    import asyncio as _asyncio

    orig_sleep = _asyncio.sleep

    async def fast(_t):
        return None

    _asyncio.sleep = fast  # type: ignore[assignment]
    try:
        await worker.drain_once()
    finally:
        _asyncio.sleep = orig_sleep  # type: ignore[assignment]

    with DbSession(engine) as db:
        sess = db.get(Session, "s_flake")
        assert sess is not None
        assert sess.status == SessionStatus.FAILED


async def test_worker_marks_failed_on_permanent_error():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    backend = SQLiteBackend(engine)
    _seed(engine)
    _add_closing_session(
        engine,
        "s_perm",
        ["aaaaaaaa" * 50, "bbbbbbbb" * 50, "cccccccc" * 50, "dddddddd" * 50, "eeeeeeee" * 50],
    )

    async def perm(msgs):
        raise LLMPermanentError("auth dead")

    def db_factory():
        return DbSession(engine)

    worker = ConsolidateWorker(
        db_factory=db_factory,
        backend=backend,
        extract_fn=perm,
        reflect_fn=_noop_reflect,
        embed_fn=_embed,
    )
    await worker.drain_once()

    with DbSession(engine) as db:
        sess = db.get(Session, "s_perm")
        assert sess is not None
        assert sess.status == SessionStatus.FAILED


async def test_worker_initial_session_ids_are_processed_first():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    backend = SQLiteBackend(engine)
    _seed(engine)
    _add_closing_session(
        engine,
        "s_init",
        ["one two three four", "reply one", "two", "three", "four"],
    )

    called: list[str] = []

    async def extractor(msgs):
        called.append(msgs[0].session_id)
        return []

    def db_factory():
        return DbSession(engine)

    worker = ConsolidateWorker(
        db_factory=db_factory,
        backend=backend,
        extract_fn=extractor,
        reflect_fn=_noop_reflect,
        embed_fn=_embed,
        initial_session_ids=("s_init",),
    )
    processed = await worker.drain_once()
    assert processed == 1
    assert called == ["s_init"]
