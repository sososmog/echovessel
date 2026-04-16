"""Deletion Compliance tests — the MVP SLA from architecture v0.3 §4.12.

This is the FIRST CI gate per docs/memory/03-memory-eval.md §3.6:
    "Deletion Compliance must = 1.0 (100%)"

If any of these fail, the delete path is broken and no release can ship.
"""

from __future__ import annotations

from datetime import date

from sqlmodel import Session as DbSession
from sqlmodel import select

from echovessel.core.types import MessageRole, NodeType
from echovessel.memory import (
    ConceptNode,
    ConceptNodeFilling,
    Persona,
    RecallMessage,
    Session,
    User,
    create_all_tables,
    create_engine,
)
from echovessel.memory.forget import (
    DeletionChoice,
    delete_concept_node,
    delete_recall_message,
    delete_recall_session,
    preview_concept_node_deletion,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_world(db: DbSession):
    db.add(Persona(id="p_test", display_name="Test"))
    db.add(User(id="self", display_name="Alan"))
    db.commit()

    sess = Session(
        id="s_001", persona_id="p_test", user_id="self", channel_id="test"
    )
    db.add(sess)
    db.commit()

    msg1 = RecallMessage(
        session_id="s_001",
        persona_id="p_test",
        user_id="self",
        channel_id="test",
        role=MessageRole.USER,
        content="我爸两年前走了",
        day=date.today(),
    )
    msg2 = RecallMessage(
        session_id="s_001",
        persona_id="p_test",
        user_id="self",
        channel_id="test",
        role=MessageRole.PERSONA,
        content="谢谢你告诉我这些",
        day=date.today(),
    )
    db.add(msg1)
    db.add(msg2)
    db.commit()

    event = ConceptNode(
        persona_id="p_test",
        user_id="self",
        type=NodeType.EVENT,
        description="用户分享父亲两年前去世",
        emotional_impact=-8,
        emotion_tags=["grief", "loss"],
        relational_tags=["identity-bearing", "vulnerability"],
        source_session_id="s_001",
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    thought = ConceptNode(
        persona_id="p_test",
        user_id="self",
        type=NodeType.THOUGHT,
        description="Alan 习惯把重要的事压在心底，需要被温柔地问才会说",
        emotional_impact=-4,
        emotion_tags=["vulnerability-window"],
        relational_tags=["identity-bearing"],
    )
    db.add(thought)
    db.commit()
    db.refresh(thought)

    link = ConceptNodeFilling(parent_id=thought.id, child_id=event.id)
    db.add(link)
    db.commit()

    return {
        "session_id": "s_001",
        "msg1_id": msg1.id,
        "msg2_id": msg2.id,
        "event_id": event.id,
        "thought_id": thought.id,
        "link_id": link.id,
    }


# ---------------------------------------------------------------------------
# 4.12.1 · Delete L2 message(s)
# ---------------------------------------------------------------------------


def test_delete_recall_message_soft_deletes_and_flags_events():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        w = _make_world(db)

        delete_recall_message(db, w["msg1_id"])

        msg = db.exec(
            select(RecallMessage).where(RecallMessage.id == w["msg1_id"])
        ).one()
        assert msg.deleted_at is not None, "L2 message should be soft-deleted"

        event = db.exec(
            select(ConceptNode).where(ConceptNode.id == w["event_id"])
        ).one()
        assert event.source_deleted is True, (
            "L3 event derived from this session should be flagged source_deleted"
        )
        # Event itself is NOT deleted — users didn't ask to forget the event
        assert event.deleted_at is None


def test_delete_recall_session_flags_all_derived_events():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        w = _make_world(db)

        delete_recall_session(db, w["session_id"])

        # All messages in the session are soft-deleted
        msgs = list(
            db.exec(
                select(RecallMessage).where(
                    RecallMessage.session_id == w["session_id"]
                )
            )
        )
        assert all(m.deleted_at is not None for m in msgs)
        assert len(msgs) == 2

        # Derived event is flagged
        event = db.exec(
            select(ConceptNode).where(ConceptNode.id == w["event_id"])
        ).one()
        assert event.source_deleted is True


# ---------------------------------------------------------------------------
# 4.12.2 · Delete L3 event with dependents — preview
# ---------------------------------------------------------------------------


def test_preview_shows_dependent_thoughts():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        w = _make_world(db)

        preview = preview_concept_node_deletion(db, w["event_id"])

        assert preview.target_id == w["event_id"]
        assert w["thought_id"] in preview.dependent_thought_ids
        assert len(preview.dependent_thought_descriptions) == 1


def test_preview_empty_when_no_dependents():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        w = _make_world(db)

        # Thought has no parents, preview should be empty
        preview = preview_concept_node_deletion(db, w["thought_id"])
        assert preview.dependent_thought_ids == []


# ---------------------------------------------------------------------------
# 4.12.2 · Cascade choice
# ---------------------------------------------------------------------------


def test_delete_concept_node_cascade_removes_dependents():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        w = _make_world(db)

        delete_concept_node(db, w["event_id"], choice=DeletionChoice.CASCADE)

        event = db.exec(
            select(ConceptNode).where(ConceptNode.id == w["event_id"])
        ).one()
        thought = db.exec(
            select(ConceptNode).where(ConceptNode.id == w["thought_id"])
        ).one()

        assert event.deleted_at is not None
        assert thought.deleted_at is not None, (
            "Dependent thought should be soft-deleted in cascade mode"
        )


# ---------------------------------------------------------------------------
# 4.12.2 · Orphan choice (default) — "forget event, keep lesson"
# ---------------------------------------------------------------------------


def test_delete_concept_node_orphan_preserves_thought_as_insight():
    """This is 4.12.3 — "forget event but keep the lesson".

    The user wants to remove the specific event from memory but still let
    persona carry the pattern it learned.
    """
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        w = _make_world(db)

        delete_concept_node(db, w["event_id"], choice=DeletionChoice.ORPHAN)

        event = db.exec(
            select(ConceptNode).where(ConceptNode.id == w["event_id"])
        ).one()
        thought = db.exec(
            select(ConceptNode).where(ConceptNode.id == w["thought_id"])
        ).one()
        link = db.exec(
            select(ConceptNodeFilling).where(ConceptNodeFilling.id == w["link_id"])
        ).one()

        # Event is gone
        assert event.deleted_at is not None

        # But thought survives
        assert thought.deleted_at is None

        # Filling link is marked orphaned — provenance chain acknowledges
        # the missing evidence
        assert link.orphaned is True
        assert link.orphaned_at is not None


def test_delete_concept_node_cancel_raises():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        w = _make_world(db)

        import pytest

        with pytest.raises(ValueError):
            delete_concept_node(db, w["event_id"], choice=DeletionChoice.CANCEL)


def test_delete_concept_node_without_dependents_just_works():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        w = _make_world(db)

        # Delete the thought directly — it has no dependents above it
        delete_concept_node(db, w["thought_id"])

        thought = db.exec(
            select(ConceptNode).where(ConceptNode.id == w["thought_id"])
        ).one()
        assert thought.deleted_at is not None

        # The event below is untouched
        event = db.exec(
            select(ConceptNode).where(ConceptNode.id == w["event_id"])
        ).one()
        assert event.deleted_at is None


# ---------------------------------------------------------------------------
# Retrieval must respect soft-delete
# ---------------------------------------------------------------------------


def test_deleted_messages_excluded_from_fts():
    """After soft-delete, FTS should not return the deleted row."""
    from echovessel.memory.backends.sqlite import SQLiteBackend

    engine = create_engine(":memory:")
    create_all_tables(engine)
    backend = SQLiteBackend(engine)

    with DbSession(engine) as db:
        w = _make_world(db)

        # Sanity: FTS finds it first
        hits_before = backend.fts_search("两年前", "p_test", "self", top_k=10)
        assert any(h.recall_message_id == w["msg1_id"] for h in hits_before)

        delete_recall_message(db, w["msg1_id"])

        hits_after = backend.fts_search("两年前", "p_test", "self", top_k=10)
        assert all(h.recall_message_id != w["msg1_id"] for h in hits_after), (
            "Deleted message should not appear in FTS results"
        )


def test_deleted_concept_nodes_excluded_from_vector_search():
    """After soft-delete, the vector_search JOIN filter should exclude deleted nodes."""

    from echovessel.memory.backends.sqlite import SQLiteBackend

    engine = create_engine(":memory:")
    create_all_tables(engine)
    backend = SQLiteBackend(engine)

    with DbSession(engine) as db:
        w = _make_world(db)

        # Give the event a vector
        vec = [0.0] * 384
        vec[0] = 1.0  # arbitrary
        backend.insert_vector(w["event_id"], vec)
        backend.insert_vector(w["thought_id"], vec)

        hits_before = backend.vector_search(
            query_embedding=vec,
            persona_id="p_test",
            user_id="self",
            types=("event", "thought"),
            top_k=10,
        )
        hit_ids_before = {h.concept_node_id for h in hits_before}
        assert w["event_id"] in hit_ids_before

        # Cascade delete removes event + thought
        delete_concept_node(db, w["event_id"], choice=DeletionChoice.CASCADE)

        hits_after = backend.vector_search(
            query_embedding=vec,
            persona_id="p_test",
            user_id="self",
            types=("event", "thought"),
            top_k=10,
        )
        hit_ids_after = {h.concept_node_id for h in hits_after}
        assert w["event_id"] not in hit_ids_after
        assert w["thought_id"] not in hit_ids_after
