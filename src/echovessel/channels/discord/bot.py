"""Thin wrapper around ``discord.py`` ``Client`` for DM ingestion.

This module isolates every ``import discord`` statement behind a stable
interface so the rest of EchoVessel does not depend on the
``discord.py`` library. It is the **only** file inside
``src/echovessel/channels/discord/`` that touches ``discord.py``
classes — the outer ``DiscordChannel`` in ``channel.py`` treats
``DiscordBot`` as a black box and passes in a callback that accepts
:class:`echovessel.channels.base.IncomingMessage`.

Responsibilities
----------------

1. Own the ``discord.Client`` instance with the correct intents for DM
   content ingestion.
2. Filter events so only direct messages (``discord.DMChannel``) reach
   the callback — guild channel messages, system notifications, own
   messages and bots are silently dropped.
3. Enforce the optional ``allowed_user_ids`` allowlist before the
   callback fires, so the upstream channel does not have to re-check.
4. Translate every surviving DM into an
   :class:`echovessel.channels.base.IncomingMessage` with
   ``channel_id="discord"``, ``user_id=<snowflake str>``, and the
   originating ``discord.Message.id`` mirrored onto ``external_ref``
   for downstream reply-threading.

What this wrapper does **not** do:

- Debounce. That is ``DiscordChannel``'s job — see ``channel.py``.
- Persist anything. Memory writes happen in the runtime turn loop
  after debounce flushes.
- Retry on transport errors. Errors bubble up to ``discord.Client``'s
  own reconnect logic.
- Handle slash commands, guild messages, attachments, or voice
  messages. All explicitly deferred to v1.x (tracker §5).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

import discord

from echovessel.channels.base import IncomingMessage

log = logging.getLogger(__name__)


#: Callback shape invoked for every allowlisted DM. The channel passes
#: both the :class:`IncomingMessage` envelope and the underlying
#: ``discord.DMChannel`` so the caller can remember the DM channel
#: object for outbound sends keyed by ``user_id``.
OnDmCallback = Callable[[IncomingMessage, "discord.DMChannel"], Awaitable[None]]


class DiscordBot(discord.Client):
    """Minimal ``discord.py`` client scoped to DM ingestion.

    Event flow:

    1. ``on_ready`` — logs the bot's display name so operators can
       confirm the token resolved to the right application.
    2. ``on_message`` — filters out non-DMs, own messages, and
       non-allowlisted senders, then calls ``on_dm_received`` with the
       translated envelope.

    Construction
    ------------

    ``allowed_user_ids`` is an optional allow-list of Discord user
    snowflakes. ``None`` means "every DM is accepted" — fine for
    private bots where only the operator knows the bot token. Setting
    an explicit allowlist is strongly recommended for any bot that
    might receive unsolicited DMs.
    """

    def __init__(
        self,
        *,
        on_dm_received: OnDmCallback,
        allowed_user_ids: set[int] | None = None,
    ) -> None:
        intents = discord.Intents.default()
        # ``message_content`` is a privileged intent; the operator must
        # enable it in the Discord Developer Portal for the bot to read
        # DM text. Without it, ``message.content`` arrives as an empty
        # string and every DM looks blank.
        intents.message_content = True
        # DM-only bots still need the ``dm_messages`` intent; it is on
        # by default but we set it explicitly for clarity.
        intents.dm_messages = True
        super().__init__(intents=intents)
        self._on_dm_received = on_dm_received
        self._allowed_user_ids = allowed_user_ids

    async def on_ready(self) -> None:
        """Log the bot identity once the websocket handshake completes."""
        log.info("Discord bot connected as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        """Handle one incoming ``discord.Message``.

        Early-outs in declaration order:

        1. Non-DM channel → drop (guild / group-DM / voice state
           updates all land here).
        2. Message authored by the bot itself → drop (prevents echo
           loops if the bot DMs itself or responds in its own thread).
        3. Non-allowlisted author → drop with a warning log so
           operators can spot probing attempts.
        4. Empty body → drop (attachments / embeds / stickers only).
           v1.x will revisit attachments, but v1 text-only must
           short-circuit to avoid feeding empty strings into the
           debounce state machine.
        """
        if not isinstance(message.channel, discord.DMChannel):
            return
        if self.user is not None and message.author == self.user:
            return
        if message.author.bot:
            # Silently ignore other bots — unsolicited AI↔AI chat is
            # not in scope.
            return
        if (
            self._allowed_user_ids is not None
            and message.author.id not in self._allowed_user_ids
        ):
            log.warning(
                "discord bot rejected DM from non-allowlisted user: "
                "author_id=%s",
                message.author.id,
            )
            return
        if not message.content:
            log.debug(
                "discord bot dropping empty DM (likely attachment-only) "
                "from author_id=%s message_id=%s",
                message.author.id,
                message.id,
            )
            return

        envelope = IncomingMessage(
            channel_id="discord",
            # Discord snowflakes are 64-bit integers; we store them as
            # strings so they share the ``user_id: str`` contract with
            # every other EchoVessel channel and memory row.
            user_id=str(message.author.id),
            content=message.content,
            received_at=datetime.now(),
            # external_ref keeps the originating message id for reply
            # threading. Runtime does not persist it in memory, but a
            # future Discord reply that threads to the originating
            # message can pull it from the envelope.
            external_ref=str(message.id),
        )
        await self._on_dm_received(envelope, message.channel)


__all__ = ["DiscordBot", "OnDmCallback"]
