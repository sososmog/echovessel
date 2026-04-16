"""Lifecycle hook `on_mood_updated` fires after `update_mood_block`
commits the new mood content.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session as DbSession
from sqlmodel import select

from echovessel.core.types import BlockLabel
from echovessel.memory import (
    CoreBlock,
    Persona,
    User,
    create_all_tables,
    create_engine,
    register_observer,
    unregister_observer,
    update_mood_block,
)


class _Spy:
    def __init__(self) -> None:
        self.mood_updates: list[tuple[str, str, str]] = []

    def on_mood_updated(
        self, persona_id: str, user_id: str, new_mood_text: str
    ) -> None:
        self.mood_updates.append((persona_id, user_id, new_mood_text))


@pytest.fixture
def spy():
    s = _Spy()
    register_observer(s)
    try:
        yield s
    finally:
        unregister_observer(s)


def _seed(db: DbSession) -> None:
    db.add(Persona(id="p_mood", display_name="Mood"))
    db.add(User(id="self", display_name="Alan"))
    db.commit()


def test_first_mood_update_creates_block_and_fires_hook(spy):
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        block = update_mood_block(
            db,
            persona_id="p_mood",
            new_mood_text="quiet, a bit tired",
        )

        assert block.content == "quiet, a bit tired"
        assert block.label == BlockLabel.MOOD
        assert block.user_id is None  # shared block

    assert len(spy.mood_updates) == 1
    persona_id, user_id, new_text = spy.mood_updates[0]
    assert persona_id == "p_mood"
    assert user_id == "self"
    assert new_text == "quiet, a bit tired"


def test_second_mood_update_replaces_content(spy):
    """Mood is a replacement, not an append."""
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        update_mood_block(
            db, persona_id="p_mood", new_mood_text="old mood"
        )
        update_mood_block(
            db, persona_id="p_mood", new_mood_text="new mood"
        )

        blocks = list(
            db.exec(
                select(CoreBlock).where(
                    CoreBlock.persona_id == "p_mood",
                    CoreBlock.label == BlockLabel.MOOD.value,
                )
            )
        )
        # Still a single row (replacement, not append)
        assert len(blocks) == 1
        assert blocks[0].content == "new mood"

    # Two fires, one per update
    assert len(spy.mood_updates) == 2
    assert spy.mood_updates[0][2] == "old mood"
    assert spy.mood_updates[1][2] == "new mood"


def test_empty_mood_rejected():
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        with pytest.raises(ValueError, match="non-empty"):
            update_mood_block(
                db, persona_id="p_mood", new_mood_text="   "
            )


def test_hook_not_fired_when_validation_fails():
    """Validation error raises BEFORE commit, so no hook should fire."""
    engine = create_engine(":memory:")
    create_all_tables(engine)

    class _Recording:
        fires: list[tuple[str, str, str]] = []

        def on_mood_updated(self, pid, uid, txt):  # noqa: D401
            _Recording.fires.append((pid, uid, txt))

    rec = _Recording()
    register_observer(rec)
    try:
        with DbSession(engine) as db:
            _seed(db)
            with pytest.raises(ValueError):
                update_mood_block(
                    db, persona_id="p_mood", new_mood_text=""
                )
        assert rec.fires == []
    finally:
        unregister_observer(rec)
