"""WebChannel debounce state machine tests (Stage 1).

Scope: verify the state machine described in
``develop-docs/channels/01-spec-v0.1.md`` §2.3a as implemented in
``echovessel.channels.web.channel.WebChannel``.

Tests run with a 50 ms debounce window to keep them fast. Every test
exercises the channel through its public entry points
(``push_user_message``, ``on_turn_done``, ``incoming``) — no private
attribute poking except where the spec explicitly describes buffer
state that a test must set up before exercising a transition (like
the ``in_flight`` + non-empty ``next_turn`` case for the review M1
iron rule).
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from echovessel.channels.base import (
    Channel,
    IncomingMessage,
    IncomingTurn,
    OutgoingMessage,
)
from echovessel.channels.web.channel import WebChannel

DEBOUNCE_MS = 50
DEBOUNCE_S = DEBOUNCE_MS / 1000.0
# A little slack on top of the debounce window so timer firing
# races cleanly even on slow CI.
SETTLE_S = DEBOUNCE_S * 0.75


def _msg(content: str, *, external_ref: str | None = None) -> IncomingMessage:
    return IncomingMessage(
        channel_id="web",
        user_id="self",
        content=content,
        received_at=datetime.now(),
        external_ref=external_ref,
    )


async def _next_turn(ch: WebChannel, *, timeout: float = 1.0) -> IncomingTurn:
    """Pull the next IncomingTurn off ``ch.incoming()`` with a timeout."""

    async def _pull() -> IncomingTurn:
        async for turn in ch.incoming():
            return turn
        raise AssertionError("incoming() exhausted before a turn arrived")

    return await asyncio.wait_for(_pull(), timeout=timeout)


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_webchannel_protocol_compliance():
    """WebChannel structurally satisfies Channel Protocol v0.2."""

    ch = WebChannel(debounce_ms=DEBOUNCE_MS)
    assert isinstance(ch, Channel)
    assert ch.channel_id == "web"
    assert ch.name == "Web"
    assert ch.in_flight_turn_id is None


# ---------------------------------------------------------------------------
# Single-message flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webchannel_single_message_flushes_after_debounce():
    """One push → one IncomingTurn with that single message after
    the debounce window elapses. turn_id is stamped on both the turn
    and the wrapped message."""

    ch = WebChannel(debounce_ms=DEBOUNCE_MS)
    await ch.push_user_message(_msg("hello"))

    turn = await _next_turn(ch)

    assert len(turn.messages) == 1
    assert turn.messages[0].content == "hello"
    assert turn.turn_id is not None
    assert turn.turn_id.startswith("turn-")
    assert turn.messages[0].turn_id == turn.turn_id
    assert turn.channel_id == "web"
    assert turn.user_id == "self"
    # The channel should now be in-flight from the runtime's perspective.
    assert ch.in_flight_turn_id == turn.turn_id


# ---------------------------------------------------------------------------
# Burst grouping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webchannel_burst_groups_messages():
    """Three messages within the debounce window → one IncomingTurn
    containing all three, all stamped with the same turn_id."""

    ch = WebChannel(debounce_ms=DEBOUNCE_MS)
    await ch.push_user_message(_msg("one"))
    await ch.push_user_message(_msg("two"))
    await ch.push_user_message(_msg("three"))

    turn = await _next_turn(ch)

    assert len(turn.messages) == 3
    contents = [m.content for m in turn.messages]
    assert contents == ["one", "two", "three"]
    # All three wrapped messages carry the same turn_id.
    ids = {m.turn_id for m in turn.messages}
    assert ids == {turn.turn_id}


@pytest.mark.asyncio
async def test_webchannel_new_message_resets_debounce_timer():
    """Pushing a new message mid-debounce-window resets the timer so
    the burst stays grouped into a single IncomingTurn instead of
    being split into two turns."""

    ch = WebChannel(debounce_ms=DEBOUNCE_MS)
    await ch.push_user_message(_msg("first"))
    # Wait half the debounce window then push again; the second push
    # should reset the timer.
    await asyncio.sleep(DEBOUNCE_S * 0.5)
    await ch.push_user_message(_msg("second"))
    # Wait the full debounce window again and verify both messages
    # arrive in one turn.
    turn = await _next_turn(ch)

    assert len(turn.messages) == 2
    assert [m.content for m in turn.messages] == ["first", "second"]


# ---------------------------------------------------------------------------
# In-flight routing + on_turn_done promotion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webchannel_in_flight_messages_go_to_next_turn():
    """While in-flight, new messages land in ``_next_turn`` and are
    NOT flushed through a debounce timer. They sit there until
    ``on_turn_done`` promotes them."""

    ch = WebChannel(debounce_ms=DEBOUNCE_MS)
    await ch.push_user_message(_msg("first"))
    # Let the first message flush so the channel transitions to
    # in-flight.
    first_turn = await _next_turn(ch)
    assert ch.in_flight_turn_id == first_turn.turn_id

    # Push a follow-up while still in-flight.
    await ch.push_user_message(_msg("mid-flight"))

    # Wait more than one debounce window. The follow-up must NOT
    # have flushed — it belongs to next_turn until on_turn_done.
    await asyncio.sleep(DEBOUNCE_S * 3)

    # incoming() should be empty (no new turn scheduled).
    with pytest.raises(asyncio.TimeoutError):
        await _next_turn(ch, timeout=DEBOUNCE_S * 2)

    # The message is parked on the channel's internal next_turn
    # buffer.
    assert len(ch._next_turn) == 1
    assert ch._next_turn[0].content == "mid-flight"
    assert ch._current_turn == []


@pytest.mark.asyncio
async def test_webchannel_on_turn_done_promotes_next_turn_via_normal_debounce():
    """Review M1 iron rule: ``on_turn_done`` must promote ``next_turn``
    back into ``current_turn`` and then schedule a **normal** debounce
    timer — it must NOT flush immediately.
    """

    ch = WebChannel(debounce_ms=DEBOUNCE_MS)

    # Drive the channel into an in-flight state with 2 queued messages
    # in next_turn by:
    #   1) pushing one → letting it flush (channel becomes in-flight)
    #   2) pushing two more while in-flight (they land in next_turn)
    await ch.push_user_message(_msg("kickoff"))
    kickoff_turn = await _next_turn(ch)
    await ch.push_user_message(_msg("follow-up 1"))
    await ch.push_user_message(_msg("follow-up 2"))

    # Sanity: next_turn carries the two follow-ups.
    assert len(ch._next_turn) == 2
    assert ch._current_turn == []

    # Trigger on_turn_done.
    await ch.on_turn_done(kickoff_turn.turn_id)

    # Channel is no longer in-flight.
    assert ch.in_flight_turn_id is None
    # next_turn was emptied into current_turn.
    assert ch._next_turn == []
    assert [m.content for m in ch._current_turn] == [
        "follow-up 1",
        "follow-up 2",
    ]

    # Critical: no IncomingTurn arrives immediately — the normal
    # debounce window is still running.
    with pytest.raises(asyncio.TimeoutError):
        await _next_turn(ch, timeout=DEBOUNCE_S * 0.5)

    # Once the debounce window elapses naturally, the follow-up
    # turn arrives.
    promoted_turn = await _next_turn(ch, timeout=DEBOUNCE_S * 4)
    assert len(promoted_turn.messages) == 2
    assert [m.content for m in promoted_turn.messages] == [
        "follow-up 1",
        "follow-up 2",
    ]
    assert promoted_turn.turn_id != kickoff_turn.turn_id


@pytest.mark.asyncio
async def test_webchannel_on_turn_done_with_empty_next_turn_is_noop():
    """If the user didn't send anything during in-flight, ``on_turn_done``
    just clears the in-flight flag and the channel goes idle. No new
    turn is scheduled."""

    ch = WebChannel(debounce_ms=DEBOUNCE_MS)
    await ch.push_user_message(_msg("solo"))
    turn = await _next_turn(ch)
    assert ch.in_flight_turn_id == turn.turn_id

    await ch.on_turn_done(turn.turn_id)

    assert ch.in_flight_turn_id is None
    assert ch._next_turn == []
    assert ch._current_turn == []

    with pytest.raises(asyncio.TimeoutError):
        await _next_turn(ch, timeout=DEBOUNCE_S * 3)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webchannel_stop_closes_incoming_stream():
    """``stop()`` cancels pending timers and terminates ``incoming()``
    cleanly."""

    ch = WebChannel(debounce_ms=DEBOUNCE_MS)

    consumed: list[IncomingTurn] = []

    async def _consume() -> None:
        async for turn in ch.incoming():
            consumed.append(turn)

    consumer = asyncio.create_task(_consume())

    # Push + let it flush.
    await ch.push_user_message(_msg("hi"))
    await asyncio.sleep(DEBOUNCE_S * 2)
    assert consumed, "expected one turn to land before stop"

    await ch.stop()
    # The consumer should terminate promptly once the sentinel arrives.
    await asyncio.wait_for(consumer, timeout=1.0)


# ---------------------------------------------------------------------------
# Send stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webchannel_send_records_outgoing():
    """Stage 1 ``send`` is a stub that appends to ``self.sent``."""

    ch = WebChannel(debounce_ms=DEBOUNCE_MS)
    msg = OutgoingMessage(
        content="hi from runtime",
        in_reply_to="ext-1",
        in_reply_to_turn_id="turn-abc",
        kind="reply",
        delivery="text",
    )
    await ch.send(msg)

    assert ch.sent == [msg]


@pytest.mark.asyncio
async def test_webchannel_send_records_proactive_outgoing():
    """Proactive pushes land on the same stub buffer."""

    ch = WebChannel(debounce_ms=DEBOUNCE_MS)
    msg = OutgoingMessage(
        content="thinking of you",
        in_reply_to=None,
        in_reply_to_turn_id=None,
        kind="proactive",
        delivery="text",
    )
    await ch.send(msg)

    assert ch.sent == [msg]
    assert ch.sent[0].kind == "proactive"
    assert ch.sent[0].in_reply_to_turn_id is None


# ---------------------------------------------------------------------------
# Hard-limit flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webchannel_hard_limit_messages_flushes_immediately():
    """Hitting ``MAX_MESSAGES_PER_TURN`` on ``current_turn`` triggers an
    immediate flush even before the debounce timer fires."""

    from echovessel.channels.web.channel import MAX_MESSAGES_PER_TURN

    # Pick a big debounce window so we are sure the flush happens
    # because of the cap and not because of the timer.
    ch = WebChannel(debounce_ms=60_000)
    for i in range(MAX_MESSAGES_PER_TURN):
        await ch.push_user_message(_msg(f"msg-{i}"))

    turn = await _next_turn(ch, timeout=0.5)
    assert len(turn.messages) == MAX_MESSAGES_PER_TURN
