"""INGEST pipeline tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session as DbSession
from sqlmodel import select

from echovessel.core.types import MessageRole, SessionStatus
from echovessel.memory import (
    Persona,
    RecallMessage,
    Session,
    User,
    create_all_tables,
    create_engine,
)
from echovessel.memory.ingest import ingest_message
from echovessel.memory.sessions import (
    SESSION_IDLE_MINUTES,
    SESSION_MAX_MESSAGES,
    catch_up_stale_sessions,
)


def _seed(db: DbSession) -> None:
    db.add(Persona(id="p_test", display_name="Test"))
    db.add(User(id="self", display_name="Alan"))
    db.commit()


def test_ingest_creates_session_on_first_message():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        _seed(db)

        result = ingest_message(
            db, "p_test", "self", "test", MessageRole.USER, "Hi there"
        )

        assert result.message.id is not None
        assert result.message.channel_id == "test"
        assert result.session.channel_id == "test"
        assert result.session.message_count == 1
        assert result.session.total_tokens > 0
        assert result.session.status == SessionStatus.OPEN
        assert not result.session_closed


def test_ingest_reuses_fresh_session():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        _seed(db)

        r1 = ingest_message(db, "p_test", "self", "test", MessageRole.USER, "one")
        r2 = ingest_message(db, "p_test", "self", "test", MessageRole.USER, "two")
        r3 = ingest_message(
            db, "p_test", "self", "test", MessageRole.PERSONA, "three"
        )

        assert r1.session.id == r2.session.id == r3.session.id
        assert r3.session.message_count == 3


def test_ingest_closes_stale_session_and_creates_new():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    t0 = datetime(2026, 4, 14, 9, 0, 0)

    with DbSession(engine) as db:
        _seed(db)

        r1 = ingest_message(
            db, "p_test", "self", "test", MessageRole.USER, "morning", now=t0
        )
        old_session_id = r1.session.id

        # Advance clock past idle threshold
        t1 = t0 + timedelta(minutes=SESSION_IDLE_MINUTES + 1)
        r2 = ingest_message(
            db,
            "p_test",
            "self",
            "test",
            MessageRole.USER,
            "back after lunch",
            now=t1,
        )

        assert r2.session.id != old_session_id

        # Old session should be in closing state, marked idle
        old = db.exec(select(Session).where(Session.id == old_session_id)).one()
        assert old.status == SessionStatus.CLOSING
        assert old.close_trigger == "idle"


def test_max_length_triggers_closing():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        _seed(db)

        # Write right up to the limit
        for i in range(SESSION_MAX_MESSAGES - 1):
            ingest_message(
                db, "p_test", "self", "test", MessageRole.USER, f"msg {i}"
            )

        # The boundary-crossing message should trigger closing
        result = ingest_message(
            db, "p_test", "self", "test", MessageRole.USER, "last one"
        )
        assert result.session_closed
        assert result.session.status == SessionStatus.CLOSING
        assert result.session.close_trigger == "max_length"


def test_catch_up_marks_stale_open_sessions_closing():
    engine = create_engine(":memory:")
    create_all_tables(engine)

    t0 = datetime(2026, 4, 14, 9, 0, 0)

    with DbSession(engine) as db:
        _seed(db)
        ingest_message(
            db, "p_test", "self", "test", MessageRole.USER, "hi", now=t0
        )

        # Simulate restart days later
        t_later = t0 + timedelta(days=2)
        stale = catch_up_stale_sessions(db, now=t_later)
        db.commit()

        assert len(stale) == 1
        assert stale[0].status == SessionStatus.CLOSING
        assert stale[0].close_trigger == "catchup"


def test_multi_user_isolation():
    """Each (persona, user) pair has its own session stream."""
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        db.add(Persona(id="p_test", display_name="Test"))
        db.add(User(id="alice", display_name="Alice"))
        db.add(User(id="bob", display_name="Bob"))
        db.commit()

        r_alice = ingest_message(
            db, "p_test", "alice", "test", MessageRole.USER, "alice here"
        )
        r_bob = ingest_message(
            db, "p_test", "bob", "test", MessageRole.USER, "bob here"
        )

        assert r_alice.session.id != r_bob.session.id

        all_msgs = list(db.exec(select(RecallMessage)))
        alice_msgs = [m for m in all_msgs if m.user_id == "alice"]
        bob_msgs = [m for m in all_msgs if m.user_id == "bob"]
        assert len(alice_msgs) == 1
        assert len(bob_msgs) == 1


def test_ingest_different_channels_get_separate_sessions():
    """Same (persona, user) across different channels = different sessions.

    Per DISCUSSION.md 2026-04-14 D6: sessions are sharded by channel so that
    physical signals (IDLE / MAX_LENGTH) fire independently per channel.
    """
    engine = create_engine(":memory:")
    create_all_tables(engine)

    with DbSession(engine) as db:
        _seed(db)

        r_web = ingest_message(
            db, "p_test", "self", "web", MessageRole.USER, "via web"
        )
        r_discord = ingest_message(
            db,
            "p_test",
            "self",
            "discord:guild123",
            MessageRole.USER,
            "via discord",
        )

        assert r_web.session.id != r_discord.session.id
        assert r_web.session.channel_id == "web"
        assert r_discord.session.channel_id == "discord:guild123"

        # Both messages landed, with channel_id stored redundantly on L2
        web_msgs = list(
            db.exec(
                select(RecallMessage).where(RecallMessage.channel_id == "web")
            )
        )
        discord_msgs = list(
            db.exec(
                select(RecallMessage).where(
                    RecallMessage.channel_id == "discord:guild123"
                )
            )
        )
        assert len(web_msgs) == 1
        assert len(discord_msgs) == 1


def test_ingest_web_idle_does_not_close_discord():
    """DISCUSSION.md D6: channel-independent lifecycle.

    A stale web session must not cause the live Discord session to be
    marked closing just because the IDLE scan crosses both.
    """
    engine = create_engine(":memory:")
    create_all_tables(engine)

    t0 = datetime(2026, 4, 14, 9, 0, 0)
    t_after_idle = t0 + timedelta(minutes=SESSION_IDLE_MINUTES + 5)

    with DbSession(engine) as db:
        _seed(db)

        # Web message at t0 (will go stale)
        ingest_message(
            db, "p_test", "self", "web", MessageRole.USER, "morning", now=t0
        )

        # Discord message at t_after_idle (fresh activity)
        r_discord = ingest_message(
            db,
            "p_test",
            "self",
            "discord:g1",
            MessageRole.USER,
            "still live",
            now=t_after_idle,
        )

        # Discord session should remain OPEN — different channel, fresh activity
        assert r_discord.session.status == SessionStatus.OPEN

        # Another write to the web channel at the same 'now' should detect
        # the stale web session and close it, independent of discord
        r_web_back = ingest_message(
            db,
            "p_test",
            "self",
            "web",
            MessageRole.USER,
            "back on web",
            now=t_after_idle,
        )
        assert r_web_back.session.status == SessionStatus.OPEN  # new session

        # The old web session should be in closing state
        all_web_sessions = list(
            db.exec(select(Session).where(Session.channel_id == "web"))
        )
        assert len(all_web_sessions) == 2
        closing_web = [
            s for s in all_web_sessions if s.status == SessionStatus.CLOSING
        ]
        assert len(closing_web) == 1
        assert closing_web[0].close_trigger == "idle"

        # Discord session untouched
        discord_sess = db.exec(
            select(Session).where(Session.channel_id == "discord:g1")
        ).one()
        assert discord_sess.status == SessionStatus.OPEN
