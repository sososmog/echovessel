"""Lifecycle hook `on_new_session_started` fires after the first
ingest in a fresh session commits.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session as DbSession

from echovessel.core.types import MessageRole
from echovessel.memory import (
    Persona,
    User,
    create_all_tables,
    create_engine,
    register_observer,
    unregister_observer,
)
from echovessel.memory.ingest import ingest_message


class _Spy:
    def __init__(self) -> None:
        self.new_sessions: list[tuple[str, str, str]] = []
        self.closed_sessions: list[tuple[str, str, str]] = []
        self.mood_updates: list[tuple[str, str, str]] = []

    def on_new_session_started(
        self, session_id: str, persona_id: str, user_id: str
    ) -> None:
        self.new_sessions.append((session_id, persona_id, user_id))

    def on_session_closed(
        self, session_id: str, persona_id: str, user_id: str
    ) -> None:
        self.closed_sessions.append((session_id, persona_id, user_id))

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
    db.add(Persona(id="p_life", display_name="Life"))
    db.add(User(id="self", display_name="Alan"))
    db.commit()


def test_first_ingest_fires_new_session_started_once(spy):
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        result = ingest_message(
            db, "p_life", "self", "web", MessageRole.USER, "first"
        )

        assert len(spy.new_sessions) == 1
        sid, pid, uid = spy.new_sessions[0]
        assert sid == result.session.id
        assert pid == "p_life"
        assert uid == "self"
        # Closed hook must not fire — the session is still OPEN
        assert spy.closed_sessions == []


def test_subsequent_ingests_do_not_fire_new_session(spy):
    """A continuing conversation must NOT refire `on_new_session_started`
    every message. Only the first message in a fresh session triggers
    the hook."""
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        ingest_message(db, "p_life", "self", "web", MessageRole.USER, "a")
        ingest_message(db, "p_life", "self", "web", MessageRole.USER, "b")
        ingest_message(db, "p_life", "self", "web", MessageRole.USER, "c")

    assert len(spy.new_sessions) == 1


def test_separate_channels_fire_independently(spy):
    """D6: each channel has its own session lifecycle. Two channels
    → two `on_new_session_started` events."""
    engine = create_engine(":memory:")
    create_all_tables(engine)
    with DbSession(engine) as db:
        _seed(db)
        ingest_message(db, "p_life", "self", "web", MessageRole.USER, "hi")
        ingest_message(
            db, "p_life", "self", "discord:g1", MessageRole.USER, "hi"
        )

    assert len(spy.new_sessions) == 2
    channels = {entry[0] for entry in spy.new_sessions}
    assert len(channels) == 2  # two distinct session ids
