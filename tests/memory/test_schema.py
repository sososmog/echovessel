"""Smoke test for the schema: does everything create without error?

This is the first test that should pass. It proves:
  1. sqlite-vec loads
  2. SQLite version is new enough for trigram FTS5
  3. All 7 entity tables can be created
  4. FTS5 virtual table + sync triggers can be created
  5. concept_nodes_vec virtual table can be created
  6. Basic insert + round-trip works
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import inspect, text
from sqlmodel import Session as DbSession
from sqlmodel import select

from echovessel.core.types import BlockLabel, MessageRole, NodeType, SessionStatus
from echovessel.memory import (
    ConceptNode,
    ConceptNodeFilling,
    CoreBlock,
    Persona,
    RecallMessage,
    Session,
    User,
    create_all_tables,
    create_engine,
)

# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------


def test_create_all_tables_in_memory():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    expected = {
        "personas",
        "users",
        "core_blocks",
        "sessions",
        "recall_messages",
        "concept_nodes",
        "concept_node_filling",
    }
    missing = expected - table_names
    assert not missing, f"missing entity tables: {missing}"


def test_virtual_tables_exist():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with engine.connect() as conn:
        # FTS5 virtual table is visible via sqlite_master with type='table'
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).all()
        names = {row[0] for row in rows}

        assert "recall_messages_fts" in names, "FTS5 virtual table not created"
        assert "concept_nodes_vec" in names, "sqlite-vec virtual table not created"


def test_fts_triggers_exist():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='trigger'")
        ).all()
        trigger_names = {row[0] for row in rows}

        assert "recall_fts_insert" in trigger_names
        assert "recall_fts_delete" in trigger_names
        assert "recall_fts_update" in trigger_names


# ---------------------------------------------------------------------------
# Basic round-trips
# ---------------------------------------------------------------------------


def _make_seed(db: DbSession) -> tuple[Persona, User]:
    persona = Persona(id="p_test", display_name="Test Persona")
    user = User(id="self", display_name="Alan")
    db.add(persona)
    db.add(user)
    db.commit()
    return persona, user


def test_persona_and_user_roundtrip():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        _make_seed(db)

        persona = db.exec(select(Persona).where(Persona.id == "p_test")).one()
        user = db.exec(select(User).where(User.id == "self")).one()

        assert persona.display_name == "Test Persona"
        assert user.display_name == "Alan"


def test_core_block_roundtrip():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        _make_seed(db)

        # Shared block: user_id NULL
        persona_block = CoreBlock(
            persona_id="p_test",
            user_id=None,
            label=BlockLabel.PERSONA,
            content="You are a warm, attentive friend.",
            char_count=35,
        )
        # Per-user block: user_id set
        user_block = CoreBlock(
            persona_id="p_test",
            user_id="self",
            label=BlockLabel.USER,
            content="User's name is Alan.",
            char_count=20,
        )
        db.add(persona_block)
        db.add(user_block)
        db.commit()

        rows = db.exec(select(CoreBlock)).all()
        assert len(rows) == 2
        labels = {r.label for r in rows}
        assert labels == {BlockLabel.PERSONA, BlockLabel.USER}


def test_recall_message_and_fts_sync():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        _make_seed(db)

        sess = Session(
            id="s_001",
            persona_id="p_test",
            user_id="self",
            channel_id="test",
            status=SessionStatus.OPEN,
        )
        db.add(sess)
        db.commit()

        msg = RecallMessage(
            session_id="s_001",
            persona_id="p_test",
            user_id="self",
            channel_id="test",
            role=MessageRole.USER,
            content="Mochi 今天又把我吵醒了",
            day=date.today(),
        )
        db.add(msg)
        db.commit()

    # FTS5 trigram search should find the message
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT rowid FROM recall_messages_fts WHERE recall_messages_fts MATCH 'Mochi'")
        ).all()
        assert len(rows) >= 1, "FTS5 trigram search for 'Mochi' should match"


def test_concept_node_with_tags():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        _make_seed(db)

        event = ConceptNode(
            persona_id="p_test",
            user_id="self",
            type=NodeType.EVENT,
            description="用户提到他的猫 Mochi 今天很调皮",
            emotional_impact=4,
            emotion_tags=["joy", "pet"],
            relational_tags=["identity-bearing"],
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        assert event.id is not None
        fetched = db.exec(select(ConceptNode).where(ConceptNode.id == event.id)).one()
        assert fetched.emotion_tags == ["joy", "pet"]
        assert fetched.relational_tags == ["identity-bearing"]
        assert fetched.emotional_impact == 4


def test_filling_link_between_thought_and_event():
    """L4 thought pointing back to L3 event via concept_node_filling."""
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        _make_seed(db)

        event = ConceptNode(
            persona_id="p_test",
            user_id="self",
            type=NodeType.EVENT,
            description="用户老板又骂他了",
            emotional_impact=-6,
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        thought = ConceptNode(
            persona_id="p_test",
            user_id="self",
            type=NodeType.THOUGHT,
            description="Alan 最近工作压力很大",
            emotional_impact=-3,
        )
        db.add(thought)
        db.commit()
        db.refresh(thought)

        link = ConceptNodeFilling(parent_id=thought.id, child_id=event.id)
        db.add(link)
        db.commit()

        # Query: find thoughts that depend on this event
        from sqlmodel import select

        stmt = (
            select(ConceptNode)
            .join(ConceptNodeFilling, ConceptNodeFilling.parent_id == ConceptNode.id)
            .where(
                ConceptNodeFilling.child_id == event.id,
                ConceptNodeFilling.orphaned == False,  # noqa: E712
                ConceptNode.deleted_at.is_(None),
            )
        )
        dependents = db.exec(stmt).all()
        assert len(dependents) == 1
        assert dependents[0].id == thought.id


def test_concept_nodes_vec_insert():
    """sqlite-vec virtual table should accept and return a vector."""
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        _make_seed(db)

        event = ConceptNode(
            persona_id="p_test",
            user_id="self",
            type=NodeType.EVENT,
            description="测试向量",
        )
        db.add(event)
        db.commit()
        db.refresh(event)

    # sqlite-vec needs the vector as raw bytes or via its serialize helper
    import struct

    vec = [0.0] * 384
    vec_bytes = struct.pack(f"{len(vec)}f", *vec)

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO concept_nodes_vec(id, embedding) VALUES (:id, :v)"),
            {"id": event.id, "v": vec_bytes},
        )
        rows = conn.execute(
            text("SELECT id FROM concept_nodes_vec WHERE id = :id"),
            {"id": event.id},
        ).all()
        assert len(rows) == 1
