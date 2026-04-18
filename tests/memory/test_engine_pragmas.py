"""SQLite engine PRAGMA wiring.

The memory daemon shares one SQLite file across multiple async actors
(Web + Discord ingest, idle scanner, consolidate worker, proactive
scheduler). Without WAL journaling and a non-zero busy timeout the
default rollback-journal mode immediately raises
``OperationalError: database is locked`` whenever two of those actors
hit the writer at the same time, which is what was killing catchup
consolidate when discord ingest happened to commit in the same
window.

These tests pin the connect-time PRAGMAs so that fix can't silently
regress.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import text

from echovessel.memory import create_engine


def _pragma(engine, name: str):
    with engine.connect() as conn:
        return conn.execute(text(f"PRAGMA {name}")).scalar()


def test_file_backed_engine_uses_wal_journaling() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(Path(tmp) / "memory.db")
        assert _pragma(engine, "journal_mode") == "wal"


def test_file_backed_engine_sets_busy_timeout() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(Path(tmp) / "memory.db")
        # 5 seconds — generous enough to absorb a single foreground
        # commit but short enough that a real deadlock surfaces.
        assert _pragma(engine, "busy_timeout") == 5000


def test_file_backed_engine_uses_normal_synchronous() -> None:
    """WAL + ``synchronous = NORMAL`` is the recommended pairing — full
    durability on COMMIT after the next checkpoint, no per-write fsync
    cost. ``2`` is the SQLite enum value for ``FULL``; ``1`` is
    ``NORMAL``."""

    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(Path(tmp) / "memory.db")
        assert _pragma(engine, "synchronous") == 1


def test_in_memory_engine_pragmas_do_not_crash() -> None:
    """``:memory:`` cannot really switch to WAL (no file), but the PRAGMA
    call must not raise — tests rely on the in-memory path."""

    engine = create_engine(":memory:")
    # ``memory`` is what SQLite reports for an in-memory DB; the call
    # succeeded as long as we got back any string.
    assert _pragma(engine, "journal_mode") in {"memory", "wal"}
    assert _pragma(engine, "busy_timeout") == 5000
