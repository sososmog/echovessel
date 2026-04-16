"""CHECK constraint: `imported_from` and `source_session_id` are mutually
exclusive on concept_nodes.

Setting both to non-NULL values at the DB layer must fail. The constraint
is implemented as a SQLite table-level CHECK
(`CHECK (imported_from IS NULL OR source_session_id IS NULL)`).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session as DbSession

from echovessel.core.types import NodeType
from echovessel.memory import (
    ConceptNode,
    Persona,
    User,
    create_all_tables,
    create_engine,
)
from echovessel.memory.models import Session as SessionRow


def _seed_with_session(db: DbSession) -> str:
    db.add(Persona(id="p_test", display_name="Test"))
    db.add(User(id="self", display_name="Alan"))
    session_id = "s_mutex_test"
    db.add(
        SessionRow(
            id=session_id,
            persona_id="p_test",
            user_id="self",
            channel_id="web",
        )
    )
    db.commit()
    return session_id


def test_both_sources_rejected():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        session_id = _seed_with_session(db)

        node = ConceptNode(
            persona_id="p_test",
            user_id="self",
            type=NodeType.EVENT,
            description="mutex violator",
            source_session_id=session_id,
            imported_from="should-not-coexist",
        )
        db.add(node)
        with pytest.raises(IntegrityError):
            db.commit()


def test_only_imported_from_is_ok():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed_with_session(db)
        node = ConceptNode(
            persona_id="p_test",
            user_id="self",
            type=NodeType.EVENT,
            description="import only",
            imported_from="hash-1",
        )
        db.add(node)
        db.commit()  # must succeed
        db.refresh(node)
        assert node.id is not None
        assert node.source_session_id is None
        assert node.imported_from == "hash-1"


def test_only_source_session_is_ok():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        session_id = _seed_with_session(db)
        node = ConceptNode(
            persona_id="p_test",
            user_id="self",
            type=NodeType.EVENT,
            description="session only",
            source_session_id=session_id,
        )
        db.add(node)
        db.commit()
        db.refresh(node)
        assert node.id is not None
        assert node.imported_from is None
        assert node.source_session_id == session_id


def test_both_null_is_ok():
    """Thoughts produced by reflection have neither source set — this
    is the existing v0.2 behaviour and must keep working."""
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed_with_session(db)
        node = ConceptNode(
            persona_id="p_test",
            user_id="self",
            type=NodeType.THOUGHT,
            description="no source at all",
        )
        db.add(node)
        db.commit()
        db.refresh(node)
        assert node.id is not None
