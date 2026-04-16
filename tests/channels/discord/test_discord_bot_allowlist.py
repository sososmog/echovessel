"""Tests for :class:`DiscordBot` allowlist + filter logic.

``DiscordBot.on_message`` filters every incoming ``discord.Message``
through a chain of rules (DM-only / not-self / not-bot / allowlisted
/ non-empty body) before dispatching to the callback. These tests
mock the ``discord.py`` types so the logic runs without talking to
the real Discord API.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Optional ``discord.py`` extra — skip cleanly when not installed.
discord = pytest.importorskip("discord")

from echovessel.channels.base import IncomingMessage  # noqa: E402
from echovessel.channels.discord.bot import DiscordBot  # noqa: E402


def _make_message(
    *,
    channel: object,
    author_id: int,
    author_is_bot: bool = False,
    content: str = "hello",
    message_id: int = 12345,
    author_is_client_user: bool = False,
    client_user: object | None = None,
) -> MagicMock:
    """Build a ``discord.Message`` mock with the fields the filter reads."""
    message = MagicMock(spec=discord.Message)
    message.channel = channel
    author = MagicMock()
    author.id = author_id
    author.bot = author_is_bot
    # ``author == self.user`` comparison relies on equality. When we
    # want the author to match the bot's own user, we pass the same
    # mock object the client's ``.user`` property returns.
    if author_is_client_user and client_user is not None:
        author = client_user
    message.author = author
    message.content = content
    message.id = message_id
    return message


def _make_dm_channel() -> MagicMock:
    return MagicMock(spec=discord.DMChannel)


def _make_guild_channel() -> MagicMock:
    # Anything that is not a DMChannel — using a plain MagicMock
    # means ``isinstance(channel, discord.DMChannel)`` returns False.
    return MagicMock()


async def _run_on_message(
    bot: DiscordBot,
    message: MagicMock,
    *,
    client_user: object | None = None,
) -> None:
    """Call ``on_message`` with ``self.user`` stubbed out."""
    # ``discord.Client.user`` is a property populated after login; in
    # tests we override it via a SimpleNamespace so the comparison
    # ``message.author == self.user`` resolves cleanly.
    object.__setattr__(bot, "_DiscordBot__test_user", client_user)
    # Monkey-patch the ``user`` attribute via a descriptor workaround:
    # discord.Client uses a property, so assignment via object.__setattr__
    # on the instance wouldn't shadow the descriptor. We replace the
    # ``user`` attribute with a simple attribute on the instance dict
    # through ``type(bot)`` — easier approach: stub out the whole
    # ``on_message`` author check by replacing ``self.user`` at the
    # class level for the test's duration.
    #
    # Simplest mechanism that actually works: assign the mock to the
    # protected ``_connection.user`` path used by discord.py's
    # property, OR just set the descriptor override. We use the
    # short route of replacing the property at the subclass level.
    await bot.on_message(message)


class _TestBot(DiscordBot):
    """Subclass that exposes a settable ``user`` attribute.

    ``discord.Client.user`` is a read-only property; overriding it
    in the subclass lets tests set a fake authenticated user without
    touching ``discord.py`` internals.
    """

    _fake_user: object | None = None

    @property
    def user(self) -> object | None:  # type: ignore[override]
        return self._fake_user

    @user.setter
    def user(self, value: object | None) -> None:
        self._fake_user = value


def _build_bot(
    *,
    callback: AsyncMock,
    allowed: set[int] | None = None,
) -> _TestBot:
    # discord.py's Client.__init__ wants an event loop; constructing
    # it synchronously inside a pytest-asyncio test is fine because
    # a loop is already running.
    return _TestBot(on_dm_received=callback, allowed_user_ids=allowed)


async def test_dm_from_allowlisted_user_is_dispatched():
    callback = AsyncMock()
    bot = _build_bot(callback=callback, allowed={1001})
    dm = _make_dm_channel()
    msg = _make_message(channel=dm, author_id=1001, content="hi there")
    await bot.on_message(msg)
    # Callback called once with an IncomingMessage + the DMChannel
    assert callback.await_count == 1
    envelope, passed_channel = callback.await_args.args
    assert isinstance(envelope, IncomingMessage)
    assert envelope.channel_id == "discord"
    assert envelope.user_id == "1001"
    assert envelope.content == "hi there"
    assert envelope.external_ref == "12345"
    assert passed_channel is dm


async def test_dm_from_non_allowlisted_user_is_dropped():
    callback = AsyncMock()
    bot = _build_bot(callback=callback, allowed={1001})
    dm = _make_dm_channel()
    msg = _make_message(channel=dm, author_id=9999, content="sneaky")
    await bot.on_message(msg)
    assert callback.await_count == 0


async def test_dm_is_dispatched_when_allowlist_is_none():
    callback = AsyncMock()
    bot = _build_bot(callback=callback, allowed=None)
    dm = _make_dm_channel()
    msg = _make_message(channel=dm, author_id=42, content="hello world")
    await bot.on_message(msg)
    assert callback.await_count == 1


async def test_guild_channel_message_is_dropped():
    callback = AsyncMock()
    bot = _build_bot(callback=callback, allowed=None)
    guild = _make_guild_channel()
    msg = _make_message(channel=guild, author_id=1001, content="in a server")
    await bot.on_message(msg)
    assert callback.await_count == 0


async def test_bot_self_message_is_dropped():
    callback = AsyncMock()
    bot = _build_bot(callback=callback, allowed=None)
    fake_self = SimpleNamespace(id=5555, bot=False)
    bot.user = fake_self
    dm = _make_dm_channel()
    # Force the message author to be the same object as bot.user.
    msg = _make_message(
        channel=dm,
        author_id=5555,
        author_is_client_user=True,
        client_user=fake_self,
    )
    await bot.on_message(msg)
    assert callback.await_count == 0


async def test_other_bot_message_is_dropped():
    callback = AsyncMock()
    bot = _build_bot(callback=callback, allowed=None)
    dm = _make_dm_channel()
    msg = _make_message(channel=dm, author_id=42, author_is_bot=True)
    await bot.on_message(msg)
    assert callback.await_count == 0


async def test_empty_dm_body_is_dropped():
    callback = AsyncMock()
    bot = _build_bot(callback=callback, allowed=None)
    dm = _make_dm_channel()
    msg = _make_message(channel=dm, author_id=42, content="")
    await bot.on_message(msg)
    assert callback.await_count == 0
