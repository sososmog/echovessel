"""`imported_from` field round-trip for L3 events and L4 thoughts.

Ensures that:
- import_content writes `imported_from` correctly
- bulk_create_events / bulk_create_thoughts set the field
- count_*_by_imported_from correctly counts by file hash
"""

from __future__ import annotations

from sqlmodel import Session as DbSession
from sqlmodel import select

from echovessel.core.types import NodeType
from echovessel.memory import (
    ConceptNode,
    EventInput,
    Persona,
    ThoughtInput,
    User,
    bulk_create_events,
    bulk_create_thoughts,
    count_events_by_imported_from,
    count_thoughts_by_imported_from,
    create_all_tables,
    create_engine,
    import_content,
)


def _seed(db: DbSession) -> None:
    db.add(Persona(id="p_test", display_name="Test"))
    db.add(User(id="self", display_name="Alan"))
    db.commit()


def test_bulk_create_events_sets_imported_from():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        ids = bulk_create_events(
            db,
            events=[
                EventInput(
                    persona_id="p_test",
                    user_id="self",
                    description="imported event A",
                    imported_from="hash-abc",
                ),
                EventInput(
                    persona_id="p_test",
                    user_id="self",
                    description="imported event B",
                    imported_from="hash-abc",
                ),
            ],
        )
        assert len(ids) == 2

        nodes = list(
            db.exec(
                select(ConceptNode).where(
                    ConceptNode.imported_from == "hash-abc"
                )
            )
        )
        assert len(nodes) == 2
        assert all(n.source_session_id is None for n in nodes)
        assert all(n.imported_from == "hash-abc" for n in nodes)


def test_bulk_create_thoughts_sets_imported_from():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        ids = bulk_create_thoughts(
            db,
            thoughts=[
                ThoughtInput(
                    persona_id="p_test",
                    user_id="self",
                    description="imported reflection",
                    imported_from="hash-xyz",
                ),
            ],
        )
        assert len(ids) == 1

        rows = list(
            db.exec(
                select(ConceptNode).where(
                    ConceptNode.imported_from == "hash-xyz",
                    ConceptNode.type == NodeType.THOUGHT.value,
                )
            )
        )
        assert len(rows) == 1


def test_import_content_user_events_sets_imported_from():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        result = import_content(
            db,
            source="file-hash-xx",
            content_type="user_events",
            payload={
                "persona_id": "p_test",
                "user_id": "self",
                "events": [
                    {
                        "description": "imported via dispatcher",
                        "emotional_impact": 2,
                        "emotion_tags": ["relief"],
                        "relational_tags": [],
                    }
                ],
            },
        )
        assert len(result.event_ids) == 1

        nodes = list(
            db.exec(
                select(ConceptNode).where(
                    ConceptNode.imported_from == "file-hash-xx"
                )
            )
        )
        assert len(nodes) == 1
        assert nodes[0].description == "imported via dispatcher"


def test_count_by_imported_from_distinguishes_events_and_thoughts():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        bulk_create_events(
            db,
            events=[
                EventInput(
                    persona_id="p_test",
                    user_id="self",
                    description=f"ev {i}",
                    imported_from="hash-count",
                )
                for i in range(3)
            ],
        )
        bulk_create_thoughts(
            db,
            thoughts=[
                ThoughtInput(
                    persona_id="p_test",
                    user_id="self",
                    description=f"th {i}",
                    imported_from="hash-count",
                )
                for i in range(2)
            ],
        )

        assert count_events_by_imported_from(db, imported_from="hash-count") == 3
        assert count_thoughts_by_imported_from(db, imported_from="hash-count") == 2
        assert count_events_by_imported_from(db, imported_from="nonsense") == 0
