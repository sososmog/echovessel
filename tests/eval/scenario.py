"""Scenario runner — replays the 14-day corpus against the real memory pipeline.

Timeline model:
    Day N's midnight = reference_date + (N-1) days. Session times from the
    corpus ("22:15", "09:20", ...) are layered on top, with messages inside
    a session spaced one second apart. This makes the run deterministic and
    keeps the 24h TIMER reflection logic inside consolidate behaving
    plausibly.

What runs for real:
    - memory.ingest_message  (real L2 writes)
    - memory.sessions.mark_session_closing (real lifecycle)
    - memory.consolidate_session (real CONSOLIDATE, fed with stub callables)
    - memory.retrieve.retrieve  (real retrieve pipeline — this IS what we measure)
    - memory.forget.delete_concept_node (real deletion, cascades into backend)

What is stubbed:
    - extract_fn  (returns canned events from llm_stub_recordings)
    - reflect_fn  (always returns [] — thoughts aren't needed for MVP metrics)
    - embed_fn    (deterministic keyword embedder from fixtures)
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlmodel import Session as DbSession

from echovessel.core.types import MessageRole
from echovessel.memory import ConceptNode, RecallMessage, Session
from echovessel.memory.backends.sqlite import SQLiteBackend
from echovessel.memory.consolidate import (
    ConsolidateResult,
    ExtractedEvent,
    ExtractedThought,
    consolidate_session,
)
from echovessel.memory.forget import DeletionChoice, delete_concept_node
from echovessel.memory.ingest import ingest_message
from echovessel.memory.retrieve import retrieve
from echovessel.memory.sessions import mark_session_closing
from tests.eval.corpus_loader import Corpus, GoldenQuestion
from tests.eval.fixtures import build_backend, build_engine, seed_persona, stub_embed
from tests.eval.llm_stub_recordings import SESSION_EXTRACTIONS

PERSONA_ID = "p_eval"
USER_ID = "self"
REFERENCE_DATE = date(2026, 4, 1)  # Corpus Day 1 lands on 2026-04-01


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class RetrievedMemory:
    """Plain snapshot of a ScoredMemory, detached from the ORM session.

    We materialize at capture time so the ScenarioResult can outlive the
    DbSession and be poked at by metrics / report / tests without hitting
    DetachedInstanceError.
    """

    node_id: int
    description: str
    emotional_impact: int
    emotion_tags: tuple[str, ...]
    relational_tags: tuple[str, ...]
    source_session_id: str | None
    score: float


@dataclass(slots=True)
class GoldenResult:
    """Retrieved memories captured at a golden question's asked_at moment."""

    question: GoldenQuestion
    retrieved: list[RetrievedMemory]

    @property
    def descriptions(self) -> list[str]:
        return [m.description for m in self.retrieved]


@dataclass(slots=True)
class ExtractionRecord:
    """What the stub extract_fn emitted for one corpus session and the DB
    node ids it produced. Lets metrics walk from gt_id → concept_node."""

    corpus_session_id: str
    db_session_id: str
    gt_ids: list[str | None]
    node_ids: list[int]


@dataclass(slots=True)
class ScenarioResult:
    """Everything a metrics module needs to score the run."""

    # Per gt_id → concept_node_id (after dedup; last write wins on collision)
    gt_to_node: dict[str, int]

    # Flat log of every extraction
    extractions: list[ExtractionRecord] = field(default_factory=list)

    # Golden question retrieval captures
    golden_results: list[GoldenResult] = field(default_factory=list)

    # Deletion targets that were actually found in the DB and deleted
    deletions_applied: list[str] = field(default_factory=list)
    deletions_missing: list[str] = field(default_factory=list)

    # Corpus session → DB session id (for §3.2 peak retention lookups)
    session_id_map: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stub callables
# ---------------------------------------------------------------------------


class _ExtractContext:
    """Tiny mutable holder so the extract_fn closure knows which corpus
    session it is currently consolidating."""

    __slots__ = ("current_session_id",)

    def __init__(self) -> None:
        self.current_session_id: str | None = None


def _make_extract_fn(ctx: _ExtractContext) -> Callable:
    async def extract_fn(
        _messages: list[RecallMessage],
    ) -> list[ExtractedEvent]:
        sid = ctx.current_session_id
        if sid is None:
            return []
        entries = SESSION_EXTRACTIONS.get(sid, [])
        return [
            ExtractedEvent(
                description=e["description"],
                emotional_impact=e["emotional_impact"],
                emotion_tags=list(e.get("emotion_tags", [])),
                relational_tags=list(e.get("relational_tags", [])),
            )
            for e in entries
        ]

    return extract_fn


async def _reflect_fn_noop(
    _nodes: list[ConceptNode], _reason: str
) -> list[ExtractedThought]:
    """MVP baseline does not exercise the reflection content path. Returning
    empty keeps the pipeline honest: SHOCK still triggers (Day 3, Day 9),
    reflect_fn is still called, but no thought nodes are written. That's
    fine — the four MVP metrics live on event nodes only."""
    return []


# ---------------------------------------------------------------------------
# Timeline helpers
# ---------------------------------------------------------------------------


def _parse_clock(clock: str) -> time:
    """Parse a 'HH:MM' string into a datetime.time. Seconds default to 0."""
    hh, mm = clock.split(":")
    return time(int(hh), int(mm))


def _day_base(day_num: int) -> datetime:
    """Midnight of corpus Day N (Day 1 → 2026-04-01 00:00)."""
    return datetime.combine(
        REFERENCE_DATE + timedelta(days=day_num - 1), time(0, 0)
    )


def _session_start(day_num: int, clock: str) -> datetime:
    """Compose day + clock into an absolute datetime.

    Clocks like '00:15' or '00:40' that appear in the corpus represent the
    very late end of the *previous* night's conversation (e.g. s_011b at
    00:15 is a continuation of the 23:10 session). We treat any HH < 5 as
    'day_num.00:00 offset' — which in absolute terms still lands inside the
    same calendar day as day_num's base. This is a corpus-specific
    convention; the eval only requires monotone timestamps within a session,
    and ingest_message enforces nothing else."""
    return _day_base(day_num) + timedelta(
        hours=_parse_clock(clock).hour, minutes=_parse_clock(clock).minute
    )


def _role(raw: str) -> MessageRole:
    return MessageRole.USER if raw == "user" else MessageRole.PERSONA


# ---------------------------------------------------------------------------
# Main replay
# ---------------------------------------------------------------------------


def run_scenario(corpus: Corpus) -> ScenarioResult:
    """Sync entrypoint. Wraps the async replay in a fresh event loop."""
    return asyncio.run(_run_scenario_async(corpus))


async def _run_scenario_async(corpus: Corpus) -> ScenarioResult:
    engine = build_engine()
    backend = build_backend(engine)
    ctx = _ExtractContext()
    extract_fn = _make_extract_fn(ctx)

    result = ScenarioResult(gt_to_node={})

    with DbSession(engine) as db:
        seed_persona(db, PERSONA_ID, USER_ID)

        for day in corpus.days:
            await _replay_day(
                db=db,
                backend=backend,
                corpus=corpus,
                day_num=day.day,
                ctx=ctx,
                extract_fn=extract_fn,
                result=result,
            )

            # After ingesting & consolidating all sessions for the day, run
            # any golden questions that were asked on this day. We do this
            # per-day so that retrieval only sees what would have existed
            # at that point in time.
            _run_golden_questions_for_day(
                db=db,
                backend=backend,
                corpus=corpus,
                day_num=day.day,
                result=result,
            )

            # Day 13 is the explicit forgetting-rights day. After Day 13's
            # sessions + golden questions are processed, apply the deletes
            # that the user requested in s_013 / s_013b, so Day 14's
            # deletion_check golden questions hit an already-deleted state.
            if day.day == 13:
                _apply_day_13_deletions(
                    db=db,
                    backend=backend,
                    corpus=corpus,
                    result=result,
                )

    return result


async def _replay_day(
    *,
    db: DbSession,
    backend: SQLiteBackend,
    corpus: Corpus,
    day_num: int,
    ctx: _ExtractContext,
    extract_fn: Callable[..., Awaitable],
    result: ScenarioResult,
) -> None:
    day = next(d for d in corpus.days if d.day == day_num)

    for corpus_session in day.sessions:
        session_time = _session_start(day_num, corpus_session.time)

        ctx.current_session_id = corpus_session.session_id

        last_session_obj: Session | None = None
        for i, msg in enumerate(corpus_session.messages):
            ingest_result = ingest_message(
                db=db,
                persona_id=PERSONA_ID,
                user_id=USER_ID,
                channel_id=corpus_session.channel_id,
                role=_role(msg.role),
                content=msg.content,
                now=session_time + timedelta(seconds=i),
            )
            last_session_obj = ingest_result.session

        if last_session_obj is None:
            continue  # empty session, shouldn't happen in corpus but be safe

        close_at = session_time + timedelta(
            seconds=len(corpus_session.messages) + 1
        )
        mark_session_closing(
            db, last_session_obj, trigger="explicit", now=close_at
        )
        db.add(last_session_obj)
        db.commit()
        db.refresh(last_session_obj)

        consolidate_result = await consolidate_session(
            db=db,
            backend=backend,
            session=last_session_obj,
            extract_fn=extract_fn,
            reflect_fn=_reflect_fn_noop,
            embed_fn=stub_embed,
            now=close_at,
        )

        _record_extraction(
            corpus_session_id=corpus_session.session_id,
            db_session_id=last_session_obj.id,
            consolidate_result=consolidate_result,
            result=result,
        )


def _record_extraction(
    *,
    corpus_session_id: str,
    db_session_id: str,
    consolidate_result: ConsolidateResult,
    result: ScenarioResult,
) -> None:
    """Pair the canned entries with the newly created nodes by position."""
    canned = SESSION_EXTRACTIONS.get(corpus_session_id, [])
    created_nodes = consolidate_result.events_created

    gt_ids: list[str | None] = []
    node_ids: list[int] = []

    # When extract_fn was called the canned list was the source of events,
    # so create order matches canned order 1:1 — strict=True enforces the
    # invariant that extraction didn't drop or reorder anything.
    for entry, node in zip(canned, created_nodes, strict=True):
        gt_id = entry.get("gt_id")
        gt_ids.append(gt_id)
        node_ids.append(node.id)
        if gt_id is not None:
            result.gt_to_node[gt_id] = node.id

    result.extractions.append(
        ExtractionRecord(
            corpus_session_id=corpus_session_id,
            db_session_id=db_session_id,
            gt_ids=gt_ids,
            node_ids=node_ids,
        )
    )
    result.session_id_map[corpus_session_id] = db_session_id


def _run_golden_questions_for_day(
    *,
    db: DbSession,
    backend: SQLiteBackend,
    corpus: Corpus,
    day_num: int,
    result: ScenarioResult,
) -> None:
    for gq in corpus.golden_questions:
        if gq.day != day_num:
            continue
        # Skip the same-day sanity pseudo-question; it is a marker, not a
        # real retrieval call (see corpus file golden_questions gq_020).
        if gq.type == "same_day_sanity":
            continue

        # Anchor the retrieve call to late evening of the asked_at day so
        # recency decay is consistent across questions asked on the same day.
        anchor = _day_base(day_num) + timedelta(hours=23, minutes=0)

        retrieval = retrieve(
            db=db,
            backend=backend,
            persona_id=PERSONA_ID,
            user_id=USER_ID,
            query_text=gq.question,
            embed_fn=stub_embed,
            top_k=10,
            now=anchor,
            expand_session_context=False,
        )

        materialized = [
            RetrievedMemory(
                node_id=sm.node.id,
                description=sm.node.description,
                emotional_impact=sm.node.emotional_impact,
                emotion_tags=tuple(sm.node.emotion_tags or ()),
                relational_tags=tuple(sm.node.relational_tags or ()),
                source_session_id=sm.node.source_session_id,
                score=sm.total,
            )
            for sm in retrieval.memories
        ]
        result.golden_results.append(
            GoldenResult(question=gq, retrieved=materialized)
        )


def _apply_day_13_deletions(
    *,
    db: DbSession,
    backend: SQLiteBackend,
    corpus: Corpus,
    result: ScenarioResult,
) -> None:
    """Execute the deletion targets the user asked to forget on Day 13.

    For each del_NNN, we look up the ConceptNode id that the stub extraction
    associated with it (via gt_to_node) and delete it with ORPHAN choice so
    any thoughts built on top survive (none in baseline, but forward-safe).
    A missing node is a corpus/extraction wiring bug and is recorded as a
    compliance issue rather than silently ignored.
    """
    for target in corpus.ground_truth.deletion_targets:
        node_id = result.gt_to_node.get(target.id)
        if node_id is None:
            result.deletions_missing.append(target.id)
            continue
        delete_concept_node(
            db=db,
            node_id=node_id,
            choice=DeletionChoice.ORPHAN,
            backend=backend,
        )
        result.deletions_applied.append(target.id)
