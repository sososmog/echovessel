"""Corpus loader — parse docs/memory/05-eval-corpus-v0.1.yaml into strict models.

The corpus file is Thread E's frozen deliverable. We NEVER mutate it; this
loader only reads and validates. Any schema mismatch should raise loudly so
main thread can flag Thread E — per 02-eval-harness-tracker.md §10.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Canonical path of the corpus in the repo (relative to project root).
# Moved from ``docs/memory/`` to ``develop-docs/memory/`` in the
# public/dev doc split; keep the old location as a fallback so this
# loader survives future reorgs.
_CORPUS_CANDIDATES = [
    Path("develop-docs/memory/05-eval-corpus-v0.1.yaml"),
    Path("docs/memory/05-eval-corpus-v0.1.yaml"),
]


def _resolve_corpus_path() -> Path:
    for p in _CORPUS_CANDIDATES:
        if p.exists():
            return p
    # Fall back to the first candidate so the original loader error
    # surfaces with a meaningful path in the exception message.
    return _CORPUS_CANDIDATES[0]


CORPUS_PATH = _resolve_corpus_path()


# ---------------------------------------------------------------------------
# Dataclass schema
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Fact:
    id: str
    content: str
    category: str


@dataclass(slots=True, frozen=True)
class EmotionalPeak:
    id: str
    day: int
    session: str
    impact: int
    content: str
    emotion_tags: tuple[str, ...]
    relational_tags: tuple[str, ...]
    shock_trigger: bool


@dataclass(slots=True, frozen=True)
class IdentityBearingFact:
    id: str
    content: str


@dataclass(slots=True, frozen=True)
class TurningPoint:
    id: str
    day: int
    session: str
    content: str


@dataclass(slots=True, frozen=True)
class RedHerring:
    id: str
    day: int
    session: str
    content: str


@dataclass(slots=True, frozen=True)
class DeletionTarget:
    id: str
    planted_day: int
    planted_session: str
    content: str
    delete_on_day: int


@dataclass(slots=True, frozen=True)
class GroundTruth:
    facts: tuple[Fact, ...]
    peaks: tuple[EmotionalPeak, ...]
    identity_bearing: tuple[IdentityBearingFact, ...]
    turning_points: tuple[TurningPoint, ...]
    red_herrings: tuple[RedHerring, ...]
    deletion_targets: tuple[DeletionTarget, ...]


@dataclass(slots=True, frozen=True)
class Message:
    role: str
    content: str
    tags: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class Session:
    session_id: str
    channel_id: str
    time: str
    messages: tuple[Message, ...]


@dataclass(slots=True, frozen=True)
class Day:
    day: int
    sessions: tuple[Session, ...]


@dataclass(slots=True, frozen=True)
class GoldenQuestion:
    id: str
    day: int
    session: str
    question: str
    type: str  # factual_recall / emotional_peak_recall / over_recall_trap / deletion_check / same_day_sanity
    expected_facts: tuple[str, ...] = ()
    expected_emotional_peak: str | None = None
    intrusion_check: bool = False
    deletion_check: bool = False
    deleted_target: str | None = None
    post_deletion: bool = False


@dataclass(slots=True, frozen=True)
class Corpus:
    name: str
    version: str
    total_days: int
    channel_id: str
    ground_truth: GroundTruth
    days: tuple[Day, ...]
    golden_questions: tuple[GoldenQuestion, ...]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _tuple(v: Any) -> tuple[str, ...]:
    if v is None:
        return ()
    if isinstance(v, list):
        return tuple(v)
    raise ValueError(f"expected list or None, got {type(v)}")


def _load_facts(raw: list[dict]) -> tuple[Fact, ...]:
    return tuple(
        Fact(id=e["id"], content=e["content"], category=e["category"])
        for e in raw
    )


def _load_peaks(raw: list[dict]) -> tuple[EmotionalPeak, ...]:
    return tuple(
        EmotionalPeak(
            id=e["id"],
            day=e["day"],
            session=e["session"],
            impact=e["impact"],
            content=e["content"],
            emotion_tags=_tuple(e.get("emotion_tags")),
            relational_tags=_tuple(e.get("relational_tags")),
            shock_trigger=bool(e.get("shock_trigger", False)),
        )
        for e in raw
    )


def _load_identity(raw: list[dict]) -> tuple[IdentityBearingFact, ...]:
    return tuple(
        IdentityBearingFact(id=e["id"], content=e["content"]) for e in raw
    )


def _load_turning_points(raw: list[dict]) -> tuple[TurningPoint, ...]:
    return tuple(
        TurningPoint(
            id=e["id"], day=e["day"], session=e["session"], content=e["content"]
        )
        for e in raw
    )


def _load_red_herrings(raw: list[dict]) -> tuple[RedHerring, ...]:
    return tuple(
        RedHerring(
            id=e["id"], day=e["day"], session=e["session"], content=e["content"]
        )
        for e in raw
    )


def _load_deletion_targets(raw: list[dict]) -> tuple[DeletionTarget, ...]:
    out = []
    for e in raw:
        planted = e["planted_at"]
        out.append(
            DeletionTarget(
                id=e["id"],
                planted_day=planted["day"],
                planted_session=planted["session"],
                content=e["content"],
                delete_on_day=e["delete_on_day"],
            )
        )
    return tuple(out)


def _load_messages(raw: list[dict]) -> tuple[Message, ...]:
    return tuple(
        Message(role=m["role"], content=m["content"], tags=_tuple(m.get("tags")))
        for m in raw
    )


def _load_sessions(raw: list[dict]) -> tuple[Session, ...]:
    return tuple(
        Session(
            session_id=s["session_id"],
            channel_id=s["channel_id"],
            time=s["time"],
            messages=_load_messages(s["messages"]),
        )
        for s in raw
    )


def _load_days(raw: list[dict]) -> tuple[Day, ...]:
    return tuple(
        Day(day=d["day"], sessions=_load_sessions(d["sessions"])) for d in raw
    )


def _load_golden_questions(raw: list[dict]) -> tuple[GoldenQuestion, ...]:
    out = []
    for q in raw:
        asked_at = q["asked_at"]
        out.append(
            GoldenQuestion(
                id=q["id"],
                day=asked_at["day"],
                session=asked_at["session"],
                question=q["question"],
                type=q["type"],
                expected_facts=_tuple(q.get("expected_facts")),
                expected_emotional_peak=q.get("expected_emotional_peak"),
                intrusion_check=bool(q.get("intrusion_check", False)),
                deletion_check=bool(q.get("deletion_check", False)),
                deleted_target=q.get("deleted_target"),
                post_deletion=bool(q.get("post_deletion", False)),
            )
        )
    return tuple(out)


def load_corpus(path: Path | str = CORPUS_PATH) -> Corpus:
    """Load and validate the eval corpus YAML file.

    Returns an immutable Corpus. Raises on any missing required field.
    """
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    root = raw["eval_corpus"]
    md = root["metadata"]
    gt_raw = root["ground_truth"]

    ground_truth = GroundTruth(
        facts=_load_facts(gt_raw["facts"]),
        peaks=_load_peaks(gt_raw["emotional_peaks"]),
        identity_bearing=_load_identity(gt_raw["identity_bearing_facts"]),
        turning_points=_load_turning_points(gt_raw["turning_points"]),
        red_herrings=_load_red_herrings(gt_raw["red_herrings"]),
        deletion_targets=_load_deletion_targets(gt_raw["deletion_targets"]),
    )

    days = _load_days(root["days"])
    golden_questions = _load_golden_questions(root["golden_questions"])

    return Corpus(
        name=md["name"],
        version=md["version"],
        total_days=md["days"],
        channel_id=md["channel_id"],
        ground_truth=ground_truth,
        days=days,
        golden_questions=golden_questions,
    )


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------


def sessions_by_id(corpus: Corpus) -> dict[str, Session]:
    """Flat map of session_id → Session across all days."""
    return {s.session_id: s for d in corpus.days for s in d.sessions}


def day_of_session(corpus: Corpus, session_id: str) -> int:
    for d in corpus.days:
        for s in d.sessions:
            if s.session_id == session_id:
                return d.day
    raise KeyError(f"session {session_id} not found")
