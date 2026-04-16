"""`turn_id` on RecallMessage — ingest + list_recall_messages round-trip."""

from __future__ import annotations

from sqlmodel import Session as DbSession

from echovessel.core.types import MessageRole
from echovessel.memory import (
    Persona,
    User,
    create_all_tables,
    create_engine,
    list_recall_messages,
)
from echovessel.memory.ingest import ingest_message


def _seed(db: DbSession) -> None:
    db.add(Persona(id="p_test", display_name="Test"))
    db.add(User(id="self", display_name="Alan"))
    db.commit()


def test_ingest_stores_turn_id_when_provided():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)

        result = ingest_message(
            db,
            "p_test",
            "self",
            "web",
            MessageRole.USER,
            "first burst line",
            turn_id="turn-abc-1",
        )

        assert result.message.turn_id == "turn-abc-1"


def test_ingest_defaults_turn_id_to_none():
    """Callers that don't know about turns (legacy / simple channels) pass
    no turn_id — the column must default to None, not raise."""
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        result = ingest_message(
            db, "p_test", "self", "web", MessageRole.USER, "simple msg"
        )
        assert result.message.turn_id is None


def test_list_recall_messages_returns_turn_id():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        ingest_message(
            db,
            "p_test",
            "self",
            "web",
            MessageRole.USER,
            "line A",
            turn_id="turn-x",
        )
        ingest_message(
            db,
            "p_test",
            "self",
            "web",
            MessageRole.USER,
            "line B",
            turn_id="turn-x",
        )
        ingest_message(
            db,
            "p_test",
            "self",
            "web",
            MessageRole.PERSONA,
            "persona reply",
            turn_id="turn-x",
        )

        rows = list_recall_messages(db, "p_test", "self", limit=10)
        assert len(rows) == 3
        turn_ids = {r.turn_id for r in rows}
        assert turn_ids == {"turn-x"}


def test_turn_id_coexists_with_null_legacy_rows():
    """A mix of turn_id=None and turn_id=<str> must be fine — both come
    back from list_recall_messages."""
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        ingest_message(
            db, "p_test", "self", "web", MessageRole.USER, "no turn"
        )
        ingest_message(
            db,
            "p_test",
            "self",
            "web",
            MessageRole.USER,
            "with turn",
            turn_id="turn-y",
        )
        rows = list_recall_messages(db, "p_test", "self", limit=10)
        ids = {r.content: r.turn_id for r in rows}
        assert ids["no turn"] is None
        assert ids["with turn"] == "turn-y"
