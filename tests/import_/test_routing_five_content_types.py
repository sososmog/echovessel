"""All 5 memory content_types get dispatched correctly + self_block side path."""

from __future__ import annotations

from sqlmodel import Session as DbSession
from sqlmodel import select

from echovessel.core.types import BlockLabel, NodeType
from echovessel.import_.models import Chunk, ContentItem
from echovessel.import_.routing import dispatch_item, translate_llm_write
from echovessel.memory.models import ConceptNode, CoreBlock, CoreBlockAppend


def _chunk_with(content: str) -> Chunk:
    return Chunk(chunk_index=0, total_chunks=1, content=content, source_label="test")


def test_persona_traits_dispatch(db_session_factory, engine):
    item = ContentItem(
        content_type="persona_traits",
        payload={
            "persona_id": "p_test",
            "user_id": "self",
            "content": "她很怕鬼但对她爱的人极其坚定",
        },
    )
    with db_session_factory() as db:
        result, new_ids = dispatch_item(item, db=db, source="hash-1")
    assert result.content_type == "persona_traits"
    assert new_ids == []
    with DbSession(engine) as db:
        appends = list(db.exec(select(CoreBlockAppend)))
        assert len(appends) == 1
        assert appends[0].label == BlockLabel.PERSONA.value


def test_user_identity_facts_dispatch(db_session_factory, engine):
    item = ContentItem(
        content_type="user_identity_facts",
        payload={
            "persona_id": "p_test",
            "user_id": "self",
            "content": "用户是数据科学家",
            "category": "work",
        },
    )
    with db_session_factory() as db:
        result, new_ids = dispatch_item(item, db=db, source="hash-2")
    assert result.content_type == "user_identity_facts"
    with DbSession(engine) as db:
        appends = list(db.exec(select(CoreBlockAppend)))
        assert any(a.label == BlockLabel.USER.value for a in appends)


def test_user_events_dispatch_creates_event_node(db_session_factory, engine):
    item = ContentItem(
        content_type="user_events",
        payload={
            "persona_id": "p_test",
            "user_id": "self",
            "events": [
                {
                    "description": "Mochi 去世那天",
                    "emotional_impact": -7,
                    "emotion_tags": ["grief"],
                    "relational_tags": ["unresolved"],
                }
            ],
        },
    )
    with db_session_factory() as db:
        result, new_ids = dispatch_item(item, db=db, source="hash-3")
    assert result.content_type == "user_events"
    assert len(new_ids) == 1
    with DbSession(engine) as db:
        nodes = list(db.exec(select(ConceptNode)))
        assert len(nodes) == 1
        assert nodes[0].type == NodeType.EVENT.value
        assert nodes[0].imported_from == "hash-3"


def test_user_reflections_dispatch_creates_thought_node(
    db_session_factory, engine
):
    item = ContentItem(
        content_type="user_reflections",
        payload={
            "persona_id": "p_test",
            "user_id": "self",
            "thoughts": [
                {
                    "description": "我总是在退一步",
                    "emotional_impact": 0,
                    "emotion_tags": [],
                    "relational_tags": [],
                }
            ],
        },
    )
    with db_session_factory() as db:
        result, new_ids = dispatch_item(item, db=db, source="hash-4")
    assert result.content_type == "user_reflections"
    assert len(new_ids) == 1
    with DbSession(engine) as db:
        nodes = list(db.exec(select(ConceptNode)))
        assert len(nodes) == 1
        assert nodes[0].type == NodeType.THOUGHT.value


def test_relationship_facts_dispatch(db_session_factory, engine):
    item = ContentItem(
        content_type="relationship_facts",
        payload={
            "persona_id": "p_test",
            "user_id": "self",
            "content": "Alan 是她男友",
            "person_label": "Alan",
        },
    )
    with db_session_factory() as db:
        result, _ = dispatch_item(item, db=db, source="hash-5")
    assert result.content_type == "relationship_facts"
    with DbSession(engine) as db:
        appends = list(db.exec(select(CoreBlockAppend)))
        assert any(a.label == BlockLabel.RELATIONSHIP.value for a in appends)


def test_self_block_side_path(db_session_factory, engine):
    # translate an L1.self_block write end-to-end
    chunk = _chunk_with("我容易在半夜醒来然后想太多这是一句话")
    raw = {
        "target": "L1.self_block",
        "content": "我容易在半夜醒来然后想太多",
        "confidence": 0.9,
        "evidence_quote": "我容易在半夜醒来然后想太多",
    }
    item = translate_llm_write(
        raw,
        chunk=chunk,
        persona_id="p_test",
        user_id="self",
    )
    assert item is not None
    assert item.payload.get("_self_block") is True
    with db_session_factory() as db:
        result, new_ids = dispatch_item(item, db=db, source="hash-self")
    # Self-block is the only dispatch that reports the internal marker
    assert result.content_type == "persona_self_traits"
    assert new_ids == []
    with DbSession(engine) as db:
        blocks = list(db.exec(select(CoreBlock)))
        self_blocks = [b for b in blocks if b.label == BlockLabel.SELF]
        assert len(self_blocks) == 1
        assert "我容易在半夜醒来" in self_blocks[0].content
