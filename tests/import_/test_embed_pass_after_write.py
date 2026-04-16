"""Embed pass runs after memory writes and populates concept_nodes_vec."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlmodel import Session as DbSession

from echovessel.import_.embed import run_embed_pass
from echovessel.import_.errors import EmbedError
from echovessel.memory.imports import EventInput, bulk_create_events


def _make_events(db_session_factory, count: int) -> list[int]:
    with db_session_factory() as db:
        events = [
            EventInput(
                persona_id="p_test",
                user_id="self",
                description=f"Event {i} about Mochi",
                emotional_impact=-i,
                imported_from="hash-import",
            )
            for i in range(count)
        ]
        return bulk_create_events(db, events=events)


def test_embed_pass_writes_to_vec_table(db_session_factory, backend, engine):
    ids = _make_events(db_session_factory, 5)
    assert len(ids) == 5

    calls: list[int] = []

    def fake_embed(texts: list[str]) -> list[list[float]]:
        calls.append(len(texts))
        # 384-dim unit-vector stub so sqlite-vec accepts the shape.
        return [[1.0 / 384.0] * 384 for _ in texts]

    with db_session_factory() as db:
        written = run_embed_pass(
            db=db,
            concept_node_ids=ids,
            embed_fn=fake_embed,
            vector_writer=backend.insert_vector,
        )
    assert written == 5
    assert calls == [5]  # one batched call for all 5 texts

    # concept_nodes_vec should now have 5 rows for these IDs.
    with DbSession(engine) as db:
        row_count = db.exec(
            text("SELECT COUNT(*) FROM concept_nodes_vec")
        ).one()
        assert row_count[0] == 5


def test_embed_pass_without_fn_raises_when_rows_present(db_session_factory):
    ids = _make_events(db_session_factory, 2)
    with pytest.raises(EmbedError), db_session_factory() as db:
        run_embed_pass(
            db=db,
            concept_node_ids=ids,
            embed_fn=None,
            vector_writer=None,
        )


def test_embed_pass_empty_id_list_is_noop(db_session_factory):
    with db_session_factory() as db:
        written = run_embed_pass(
            db=db,
            concept_node_ids=[],
            embed_fn=None,
            vector_writer=None,
        )
    assert written == 0
