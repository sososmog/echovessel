"""Idempotent-migration guarantee for `ensure_schema_up_to_date`.

Running the migration twice on the same database must be a no-op (same
table/column set, no exceptions, no duplicate columns). This is the
review M4 safety net — `ensure_schema_up_to_date` is called on every
daemon start, so it MUST be safe to call repeatedly.
"""

from __future__ import annotations

from sqlalchemy import text

from echovessel.memory import create_all_tables, create_engine
from echovessel.memory.migrations import ensure_schema_up_to_date


def _column_names(engine, table: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return [r[1] for r in rows]


def _table_exists(engine, name: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
            ),
            {"n": name},
        ).first()
    return row is not None


def test_migrations_rerun_is_noop_on_fresh_db():
    engine = create_engine(":memory:")
    create_all_tables(engine)  # this already runs migrations once

    cols_before = _column_names(engine, "recall_messages")
    concept_before = _column_names(engine, "concept_nodes")

    # Run the migration a second time — should complete silently
    ensure_schema_up_to_date(engine)
    ensure_schema_up_to_date(engine)  # and a third for good measure

    cols_after = _column_names(engine, "recall_messages")
    concept_after = _column_names(engine, "concept_nodes")

    assert cols_before == cols_after
    assert concept_before == concept_after


def test_migrations_rerun_preserves_new_table():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    assert _table_exists(engine, "core_block_appends")

    ensure_schema_up_to_date(engine)
    assert _table_exists(engine, "core_block_appends")


def test_migrations_v03_columns_present_after_create_all():
    """After create_all_tables on a fresh DB, the v0.3 additive columns
    must all appear. This proves the ORM model declarations include
    them (if they didn't, the migrations alone wouldn't add them on
    fresh DBs)."""
    engine = create_engine(":memory:")
    create_all_tables(engine)

    recall_cols = _column_names(engine, "recall_messages")
    concept_cols = _column_names(engine, "concept_nodes")

    assert "turn_id" in recall_cols
    assert "source_turn_id" in concept_cols
    assert "imported_from" in concept_cols
