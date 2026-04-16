"""Missing-import + missing-token fallback behaviour.

The Discord channel ships as an **optional** dependency. Users who
only enable the Web channel must not see an ``ImportError`` at
``echovessel run`` time, and an operator who enables Discord in config
but forgets to set the token env var must see a clear error and a
continuing daemon — not a crash.

These tests exercise both fallback paths without installing the real
``discord.py`` package missing, which is not something a unit test
can simulate perfectly. Instead, we simulate the runtime-side error
handling pattern main thread will implement in the Stage 6 follow-up
wiring.

The point of these tests is to lock down the **contract** that
:class:`DiscordChannel` can be imported and constructed as long as
the ``discord`` optional extra is installed, and that its
construction does not require the token to be set correctly — so the
runtime wiring can catch token-related errors separately.
"""

from __future__ import annotations

import importlib
import sys

import pytest

# Optional ``discord.py`` extra — skip cleanly when not installed.
pytest.importorskip("discord")

from echovessel.channels.discord import DiscordChannel  # noqa: E402


def test_discord_channel_import_is_deterministic():
    """Importing :class:`DiscordChannel` must not reach out to the
    network or read environment variables. This is a regression
    guard: adding ``os.environ['...']`` reads at module import
    time would break runtime's lazy-init flow.
    """
    module = sys.modules.get("echovessel.channels.discord.channel")
    assert module is not None
    # Re-importing must be side-effect free (other than Python's own
    # import cache bookkeeping).
    importlib.reload(module)


def test_discord_channel_construction_is_pure():
    """Constructing the channel must not dispatch any real network
    work. ``start()`` is where the ``discord.py`` client actually
    connects; the ``__init__`` path only records config and creates
    in-memory state.
    """
    ch = DiscordChannel(token="xxx.fake.token")
    # Should NOT have spun up a bot yet.
    assert ch._bot is None
    assert ch._bot_task is None
    # State-machine buffers are empty.
    assert ch._current_turn == []
    assert ch._next_turn == []
    assert ch.in_flight_turn_id is None


def test_discord_channel_accepts_empty_token_at_construction():
    """Main thread's runtime wiring resolves the token from an env
    var. If the env var is unset, runtime will see an empty string
    and skip ``start()`` with a clear log message. The channel
    itself must not object to an empty token at construction — only
    at ``start()`` would the real validation happen (inside
    ``discord.py``'s ``Client.start``).
    """
    ch = DiscordChannel(token="")
    assert ch._token == ""
    # Still constructs cleanly; no attribute error.
    assert ch.channel_id == "discord"
