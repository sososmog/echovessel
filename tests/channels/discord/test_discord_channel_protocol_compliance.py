"""Structural Protocol compliance + construction smoke test.

Verifies that :class:`DiscordChannel` satisfies
:class:`echovessel.channels.base.Channel` structurally and that every
required attribute / method is present with the expected shape.
"""

from __future__ import annotations

import inspect

import pytest

# ``discord.py`` is an optional extra — skip this file cleanly when
# the library is not installed so ``uv run pytest tests/`` (without
# ``--extra discord``) still collects the rest of the suite.
pytest.importorskip("discord")

from echovessel.channels.base import Channel  # noqa: E402
from echovessel.channels.discord import DiscordChannel  # noqa: E402


def test_discord_channel_satisfies_channel_protocol():
    ch = DiscordChannel(token="xxx.fake.token")
    assert isinstance(ch, Channel)


def test_discord_channel_has_expected_class_identity():
    ch = DiscordChannel(token="xxx.fake.token")
    assert ch.channel_id == "discord"
    assert ch.name == "Discord"
    assert ch.in_flight_turn_id is None


def test_discord_channel_init_accepts_three_kwargs():
    """Main thread's runtime wiring depends on the exact kwarg names
    ``token`` / ``debounce_ms`` / ``allowed_user_ids``. If any of them
    is renamed this test fails loudly so the rename is caught before
    runtime integration lands.
    """
    sig = inspect.signature(DiscordChannel.__init__)
    params = sig.parameters
    assert "token" in params
    assert "debounce_ms" in params
    assert "allowed_user_ids" in params
    # All three should be keyword-only so positional misuse cannot
    # reorder them accidentally.
    assert params["token"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["debounce_ms"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["allowed_user_ids"].kind is inspect.Parameter.KEYWORD_ONLY


def test_discord_channel_default_debounce_matches_web():
    """2000 ms debounce window — keep in sync with the WebChannel
    default so the behaviour is identical across transports.
    """
    sig = inspect.signature(DiscordChannel.__init__)
    assert sig.parameters["debounce_ms"].default == 2000


def test_discord_channel_exposes_required_methods():
    ch = DiscordChannel(token="xxx.fake.token")
    for method_name in ("start", "stop", "incoming", "send", "on_turn_done"):
        assert hasattr(ch, method_name)
    # ``push_user_message`` is not in the Protocol but is our
    # internal entry point from the bot wrapper. Verify it exists.
    assert hasattr(ch, "push_user_message")
