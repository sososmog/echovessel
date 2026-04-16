"""Discord channel — DM-only adapter for EchoVessel personas.

Implements Channel Protocol v0.2 for direct messages. Guild channels,
slash commands, and voice message uploads are explicitly out of scope
for v1.x; see ``develop-docs/web-v1/06-stage-6-tracker.md`` for the
current roadmap.

Public API:

    from echovessel.channels.discord import DiscordChannel

The ``discord.py`` dependency is an **optional extra** — users who only
enable the Web channel do not need to install it. Importing this module
while ``discord.py`` is missing raises ``ModuleNotFoundError`` at import
time; runtime wiring catches that and logs a friendly error when
``[channels.discord].enabled = true``.
"""

from echovessel.channels.discord.channel import DiscordChannel

__all__ = ["DiscordChannel"]
