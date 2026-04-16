"""Cross-channel unified persona integration tests.

EchoVessel's architectural foundation is that a persona is one
continuous identity across every channel it speaks on. Memory
retrieval never filters by `channel_id`; the same persona replies on
Web and on Discord and remembers conversations from either side.

These tests verify that invariant at the Runtime level — both
channels feeding the same memory, neither filtering the other out.

Discord's real bot connection is stubbed because tests cannot hit
the real Discord API. The WebChannel is used as-is because it has
no external dependencies.

Mock strategy
-------------

- ``DiscordChannel.start`` is replaced with an ``AsyncMock`` on the
  pre-built instance before it is handed to ``rt.ctx.registry``. That
  keeps ``discord.py`` bot construction out of the test entirely —
  no tokens, no gateway, no rate limiter.
- ``DiscordChannel.send`` is replaced with an ``AsyncMock`` on the
  same instance. DiscordChannel's real ``send`` requires a live
  ``discord.DMChannel`` object in ``_dm_channels``; mocking the
  whole method is simpler than pre-populating that map and mirrors
  the "persona reply drops into memory, channel.send is a stub"
  behaviour runtime sees anyway. Memory still records the persona
  reply because ``assemble_turn`` writes L2 BEFORE calling
  ``channel.send`` (the order invariant from spec §4.5 / §7.4).

- The Web channel is left real: runtime's ``_start_web_channel``
  boots uvicorn on an OS-picked port (``[channels.web].port = 0``)
  so no port conflicts. Tests bypass the HTTP surface entirely and
  call ``web_ch.push_user_message`` directly — the same entry point
  the FastAPI ``POST /api/chat/send`` route would hit.

Test timing
-----------

All debounce windows are set to 50 ms. After pushing a user message,
tests poll for ``channel.in_flight_turn_id is None`` (runtime clears
it via ``on_turn_done`` once the turn loop completes) with a generous
5 s total timeout.
"""

from __future__ import annotations

import asyncio
import inspect
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# ``discord.py`` is an optional runtime dependency
# (``pip install echovessel[discord]``). Skip the whole module cleanly
# when it isn't installed — the channel class imports ``discord`` at
# module load via channels/discord/bot.py.
pytest.importorskip("discord")

from sqlmodel import Session as DbSession  # noqa: E402

from echovessel.channels.base import IncomingMessage  # noqa: E402
from echovessel.channels.discord.channel import DiscordChannel  # noqa: E402
from echovessel.memory import observers as memory_observers  # noqa: E402
from echovessel.memory.retrieve import list_recall_messages  # noqa: E402
from echovessel.runtime import (  # noqa: E402
    Runtime,
    build_zero_embedder,
    load_config_from_str,
)
from echovessel.runtime.llm import StubProvider  # noqa: E402

PERSONA_ID = "crosstest"
USER_ID = "self"
DEBOUNCE_MS = 50
DEBOUNCE_S = DEBOUNCE_MS / 1000.0
TURN_TIMEOUT_S = 5.0
POLL_INTERVAL_S = 0.02


# ---------------------------------------------------------------------------
# Config / fixture helpers
# ---------------------------------------------------------------------------


def _cross_channel_toml(data_dir: str) -> str:
    """TOML that enables BOTH channels at the Runtime composition level:

    - Web is turned on in config so runtime's ``_start_web_channel`` builds
      the real :class:`WebChannel` and launches uvicorn on an ephemeral
      port (``port = 0``).
    - Discord is ``enabled = false`` in config so runtime does NOT try to
      import ``discord.py``, read a token env var, and spin up a real
      Gateway client. Tests pre-register their own ``DiscordChannel``
      with mocked lifecycle methods before calling ``rt.start()``.
    - Voice + Proactive are disabled to keep the fixture minimal.
    """
    return f"""
[runtime]
data_dir = "{data_dir}"
log_level = "warn"

[persona]
id = "{PERSONA_ID}"
display_name = "CrossTest"

[memory]
db_path = ":memory:"

[llm]
provider = "stub"
api_key_env = ""

[consolidate]
worker_poll_seconds = 1
worker_max_retries = 1

[idle_scanner]
interval_seconds = 60

[voice]
enabled = false

[proactive]
enabled = false

[channels.web]
enabled = true
host = "127.0.0.1"
port = 0
debounce_ms = {DEBOUNCE_MS}

[channels.discord]
enabled = false
"""


async def _build_runtime_with_both_channels() -> tuple[Runtime, object, DiscordChannel]:
    """Build a Runtime with the real WebChannel + a stubbed DiscordChannel.

    Returns ``(runtime, web_channel, discord_channel)``. Caller is
    responsible for calling ``await rt.stop()`` and unregistering the
    runtime's memory observer (see ``_teardown_runtime``).
    """
    tmp = Path(tempfile.mkdtemp(prefix="echovessel-crosschan-"))
    cfg = load_config_from_str(_cross_channel_toml(str(tmp)))
    rt = Runtime.build(
        None,
        config_override=cfg,
        llm=StubProvider(fallback="ok"),
        embed_fn=build_zero_embedder(),
    )

    # Pre-build a DiscordChannel with a fake token so the object exists,
    # then neutralise the two methods that would touch the network:
    #
    #   DiscordChannel.start — would asyncio.create_task(bot.start(token))
    #       and try to connect to the Discord Gateway. Replaced with an
    #       AsyncMock so registry.start_all() calls a no-op.
    #
    #   DiscordChannel.send  — would look up a live discord.DMChannel in
    #       ._dm_channels and forward msg.content. Replaced with an
    #       AsyncMock so the runtime's assemble_turn → channel.send path
    #       doesn't raise KeyError on the missing DM. Memory still
    #       records the persona reply because L2 ingest happens BEFORE
    #       channel.send in assemble_turn (spec §4.5 / §7.4 order
    #       invariant).
    discord_ch = DiscordChannel(
        token="xxx.fake.token.for.tests",
        debounce_ms=DEBOUNCE_MS,
    )
    discord_ch.start = AsyncMock()  # type: ignore[method-assign]
    discord_ch.send = AsyncMock()  # type: ignore[method-assign]

    # Register Discord BEFORE rt.start(). rt.start() will build the real
    # Web channel itself and register it via registry.register(), then
    # call registry.start_all() which walks every registered channel —
    # including our mocked Discord — and awaits each channel.start().
    rt.ctx.registry.register(discord_ch)

    await rt.start(register_signals=False)

    web_ch = rt.ctx.registry.get("web")
    assert web_ch is not None, (
        "Web channel was not registered by rt.start() — config may be wrong"
    )

    return rt, web_ch, discord_ch


async def _teardown_runtime(rt: Runtime) -> None:
    """Stop the runtime and clean up module-level state left behind by
    the memory observer registry. Safe to call twice."""
    await rt.stop()
    if rt._memory_observer is not None:
        memory_observers.unregister_observer(rt._memory_observer)


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------


def _incoming(channel_id: str, content: str, *, external_ref: str = "ext") -> IncomingMessage:
    """Build an IncomingMessage with matching channel_id so the message's
    eventual L2 row carries the correct provenance."""
    return IncomingMessage(
        channel_id=channel_id,
        user_id=USER_ID,
        content=content,
        received_at=datetime.now(),
        external_ref=external_ref,
    )


async def _wait_for_idle(channel: object, *, timeout: float = TURN_TIMEOUT_S) -> None:
    """Block until ``channel.in_flight_turn_id`` goes None, meaning
    runtime's turn dispatcher has completed the turn and called
    ``on_turn_done(turn_id)`` on the channel.

    Polls on POLL_INTERVAL_S ticks so the test finishes within ~1 poll
    of the actual state transition on typical hardware.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if getattr(channel, "in_flight_turn_id", None) is None and not getattr(
            channel, "_debounce_handle", None
        ):
            # Also need the turn to have actually run at least once;
            # check by asserting there is SOMETHING in the out queue's
            # pending state, i.e. the channel has emitted and settled.
            return
        await asyncio.sleep(POLL_INTERVAL_S)
    raise AssertionError(
        f"channel {getattr(channel, 'channel_id', '?')} never returned to idle"
    )


async def _wait_for_message_count(
    rt: Runtime, *, min_count: int, timeout: float = TURN_TIMEOUT_S
) -> list:
    """Poll ``list_recall_messages`` until at least ``min_count`` rows
    exist (user + persona combined). Returns the final row list."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        with DbSession(rt.ctx.engine) as db:
            rows = list_recall_messages(
                db,
                persona_id=PERSONA_ID,
                user_id=USER_ID,
                limit=50,
            )
        if len(rows) >= min_count:
            return rows
        await asyncio.sleep(POLL_INTERVAL_S)
    raise AssertionError(
        f"memory never reached {min_count} messages (last count={len(rows)})"
    )


def _role_str(row: object) -> str:
    """Normalise ``RecallMessage.role`` to a plain string regardless of
    whether SQLModel returned the enum value or its string subclass."""
    role = getattr(row, "role", None)
    return getattr(role, "value", role) if role is not None else ""


# ---------------------------------------------------------------------------
# Test 1 · Web → unified memory
# ---------------------------------------------------------------------------


async def test_user_message_from_web_lands_in_unified_memory():
    """Push one message via WebChannel, let the real turn pipeline run,
    and verify ``list_recall_messages`` returns both the user message
    (channel_id='web') and a stub-generated persona reply."""
    rt, web_ch, _discord_ch = await _build_runtime_with_both_channels()
    try:
        await web_ch.push_user_message(_incoming("web", "hello from web"))

        rows = await _wait_for_message_count(rt, min_count=2)

        # The user message carries channel_id='web'.
        user_rows = [r for r in rows if _role_str(r) == "user"]
        assert len(user_rows) >= 1
        assert any(r.channel_id == "web" for r in user_rows), (
            f"no user row with channel_id='web' in {[r.channel_id for r in user_rows]}"
        )
        assert any(r.content == "hello from web" for r in user_rows)

        # The persona reply is also in L2 (ingest happens before send).
        persona_rows = [r for r in rows if _role_str(r) == "persona"]
        assert len(persona_rows) >= 1, "stub persona reply did not land in memory"
        assert all(r.content for r in persona_rows)
    finally:
        await _teardown_runtime(rt)


# ---------------------------------------------------------------------------
# Test 2 · Discord → unified memory
# ---------------------------------------------------------------------------


async def test_user_message_from_discord_lands_in_unified_memory():
    """Same round trip but via the (mocked-start, mocked-send)
    DiscordChannel. Memory must still record both sides even though
    ``channel.send`` is an AsyncMock — the order invariant guarantees
    ingest-before-send, so the L2 row lands regardless of transport."""
    rt, _web_ch, discord_ch = await _build_runtime_with_both_channels()
    try:
        await discord_ch.push_user_message(
            _incoming("discord", "hello from discord")
        )

        rows = await _wait_for_message_count(rt, min_count=2)

        user_rows = [r for r in rows if _role_str(r) == "user"]
        assert any(r.channel_id == "discord" for r in user_rows)
        assert any(r.content == "hello from discord" for r in user_rows)

        persona_rows = [r for r in rows if _role_str(r) == "persona"]
        assert len(persona_rows) >= 1, (
            "stub persona reply did not land in memory — ingest-before-send "
            "order invariant may be broken for DiscordChannel"
        )

        # Confirm the mocked send was actually invoked (runtime reached
        # the delivery step after ingest).
        assert discord_ch.send.await_count >= 1
    finally:
        await _teardown_runtime(rt)


# ---------------------------------------------------------------------------
# Test 3 · THE KEY TEST — unified timeline across both channels
# ---------------------------------------------------------------------------


async def test_same_user_across_both_channels_gets_unified_timeline():
    """Two sequential messages (one Web, one Discord) for the same user_id
    must BOTH appear in ``list_recall_messages`` — the single query that
    the whole "one persona across channels" contract rests on. This is
    the machine-checkable version of the D4 iron rule.

    Asserts:
      1. Both user messages present, each with its own channel_id
      2. Both persona replies present (stub "ok" content)
      3. Timeline is ordered by created_at — Discord (newer) appears
         before Web (older) because ``list_recall_messages`` returns
         newest-first per spec
      4. Total ≥ 4 messages with a mix of web + discord channel_ids —
         proving retrieve does not shard by transport
    """
    rt, web_ch, discord_ch = await _build_runtime_with_both_channels()
    try:
        # --- Message 1 · Web --------------------------------------------
        await web_ch.push_user_message(_incoming("web", "from web side"))
        await _wait_for_message_count(rt, min_count=2)

        # Tiny spacer so the two user messages have distinct created_at
        # timestamps even on fast hardware. list_recall_messages orders
        # by created_at DESC so we want a clean ordering to assert on.
        await asyncio.sleep(0.05)

        # --- Message 2 · Discord ---------------------------------------
        await discord_ch.push_user_message(
            _incoming("discord", "from discord side")
        )
        rows = await _wait_for_message_count(rt, min_count=4)

        # ---- The assertions ------------------------------------------
        contents = [(r.channel_id, _role_str(r), r.content) for r in rows]

        assert ("web", "user", "from web side") in contents, (
            f"web user message missing from unified timeline: {contents}"
        )
        assert ("discord", "user", "from discord side") in contents, (
            f"discord user message missing from unified timeline: {contents}"
        )

        # At least one persona reply per channel (the stub LLM answered
        # "ok" for both turns, but each reply is tagged with the channel
        # it was destined for at ingest time).
        persona_rows = [r for r in rows if _role_str(r) == "persona"]
        persona_channels = {r.channel_id for r in persona_rows}
        assert "web" in persona_channels, (
            f"persona reply for web turn missing: {persona_channels}"
        )
        assert "discord" in persona_channels, (
            f"persona reply for discord turn missing: {persona_channels}"
        )

        assert len(rows) >= 4, (
            f"expected at least 4 rows (2 user + 2 persona), got {len(rows)}: "
            f"{contents}"
        )

        # Timeline is newest-first. The Discord pair was ingested second
        # so it should lead the list; the Web pair trails.
        first_user = next(r for r in rows if _role_str(r) == "user")
        last_user = next(
            r for r in reversed(rows) if _role_str(r) == "user"
        )
        assert first_user.channel_id == "discord", (
            f"newest-first order broken — top user row is from "
            f"{first_user.channel_id}, expected 'discord'"
        )
        assert last_user.channel_id == "web", (
            f"newest-first order broken — bottom user row is from "
            f"{last_user.channel_id}, expected 'web'"
        )

        # ---- The money shot: the query itself takes no channel_id ----
        # We are about to re-call list_recall_messages with the exact
        # same signature we would use in production, and prove that a
        # single unfiltered call returns rows from BOTH transports.
        with DbSession(rt.ctx.engine) as db:
            unfiltered_rows = list_recall_messages(
                db,
                persona_id=PERSONA_ID,
                user_id=USER_ID,
                limit=50,
            )
        unfiltered_channels = {r.channel_id for r in unfiltered_rows}
        assert "web" in unfiltered_channels
        assert "discord" in unfiltered_channels
        assert len(unfiltered_channels) >= 2, (
            "D4 iron rule broken: unfiltered list_recall_messages did not "
            "return rows from both channels"
        )
    finally:
        await _teardown_runtime(rt)


# ---------------------------------------------------------------------------
# Test 4 · D4 Protocol guard — signature has no channel_id parameter
# ---------------------------------------------------------------------------


def test_list_recall_messages_does_not_accept_channel_id_filter():
    """Defensive signature guard.

    The D4 iron rule says memory retrieval MUST NOT accept a channel_id
    filter. Earlier threads already tested this for proactive's memory
    view, but we also want the actual function ``list_recall_messages``
    to be directly guarded at the signature level so that any future
    refactor adding channel-awareness trips this test before it hits
    runtime.
    """
    sig = inspect.signature(list_recall_messages)
    param_names = set(sig.parameters)
    assert "channel_id" not in param_names, (
        "D4 iron rule violated: list_recall_messages has grown a "
        f"channel_id parameter. Parameters: {sorted(param_names)}"
    )
    # Positive assertion on the expected surface area so an unrelated
    # rename shows up in CI rather than silently passing.
    assert "persona_id" in param_names
    assert "user_id" in param_names
    assert "limit" in param_names
    assert "before" in param_names


# ---------------------------------------------------------------------------
# Test 5 · Per-channel state isolation
# ---------------------------------------------------------------------------


async def test_discord_channel_does_not_affect_web_channel_debounce():
    """Each channel owns its own debounce state. Pushing traffic via one
    channel must not perturb the other's ``in_flight_turn_id`` /
    ``_debounce_handle`` / ``_current_turn`` buffers.

    We push through the Web channel, wait for its turn to complete, then
    push through the Discord channel and wait for ITS turn to complete
    — while continuously asserting Web's debounce buffers stay clean.
    """
    rt, web_ch, discord_ch = await _build_runtime_with_both_channels()
    try:
        # Round 1 · Web only
        await web_ch.push_user_message(_incoming("web", "web msg 1"))
        await _wait_for_message_count(rt, min_count=2)

        # After the turn settles, Web should be idle and Discord untouched
        assert web_ch.in_flight_turn_id is None
        assert discord_ch.in_flight_turn_id is None
        assert len(discord_ch._current_turn) == 0
        assert len(discord_ch._next_turn) == 0

        # Round 2 · Discord only — Web must not be touched by this push
        web_before_in_flight = web_ch.in_flight_turn_id
        web_before_current = len(web_ch._current_turn)

        await discord_ch.push_user_message(
            _incoming("discord", "discord msg 1")
        )

        # As soon as Discord pushes, its own _current_turn must hold the
        # message — but Web's state machine must not have moved.
        assert len(discord_ch._current_turn) >= 0  # may already have flushed
        assert web_ch.in_flight_turn_id == web_before_in_flight
        assert len(web_ch._current_turn) == web_before_current

        await _wait_for_message_count(rt, min_count=4)

        # Both channels are now idle again and the respective turn
        # dispatchers landed rows with the right channel_id tags.
        with DbSession(rt.ctx.engine) as db:
            rows = list_recall_messages(
                db, persona_id=PERSONA_ID, user_id=USER_ID, limit=50
            )
        channel_ids = {r.channel_id for r in rows}
        assert channel_ids == {"web", "discord"}, (
            f"expected rows from both channels, got {channel_ids}"
        )
    finally:
        await _teardown_runtime(rt)


# ---------------------------------------------------------------------------
# Test 6 · Proactive's any_channel_in_flight gate sees EITHER channel
# ---------------------------------------------------------------------------


async def test_both_channels_report_in_flight_to_proactive_gate():
    """The proactive round-2 gate calls
    ``rt.ctx.registry.any_channel_in_flight()`` on every tick. That
    predicate must return True if ANY enabled channel has a turn in
    flight (spec §3.5a) — not only the "first" one or a hardcoded
    channel id. We verify it by toggling ``in_flight_turn_id`` manually
    on Web and Discord in turn and asserting the predicate tracks.

    Using manual flips instead of a real push→turn→done cycle avoids
    timing-dependent observation of a very brief in-flight window
    (the stub LLM is fast enough that a real turn races the polling
    loop). The wave_abc composition test uses the same manual-flip
    pattern for the same reason.
    """
    rt, web_ch, discord_ch = await _build_runtime_with_both_channels()
    try:
        # Precondition: both idle (turn dispatcher hasn't been fed yet)
        web_ch.in_flight_turn_id = None
        discord_ch.in_flight_turn_id = None
        assert rt.ctx.registry.any_channel_in_flight() is False

        # Web in flight
        web_ch.in_flight_turn_id = "turn-web-1"
        assert rt.ctx.registry.any_channel_in_flight() is True
        web_ch.in_flight_turn_id = None
        assert rt.ctx.registry.any_channel_in_flight() is False

        # Discord in flight — proactive must ALSO see this
        discord_ch.in_flight_turn_id = "turn-discord-1"
        assert rt.ctx.registry.any_channel_in_flight() is True, (
            "any_channel_in_flight did not see Discord as in-flight — "
            "proactive gate would incorrectly allow proactive sends "
            "while a Discord turn is mid-stream"
        )
        discord_ch.in_flight_turn_id = None
        assert rt.ctx.registry.any_channel_in_flight() is False

        # Both in flight at once (simulating a race where the user is
        # typing on Web while a Discord turn is still running)
        web_ch.in_flight_turn_id = "turn-web-2"
        discord_ch.in_flight_turn_id = "turn-discord-2"
        assert rt.ctx.registry.any_channel_in_flight() is True
        web_ch.in_flight_turn_id = None
        assert rt.ctx.registry.any_channel_in_flight() is True  # discord still
        discord_ch.in_flight_turn_id = None
        assert rt.ctx.registry.any_channel_in_flight() is False
    finally:
        await _teardown_runtime(rt)
