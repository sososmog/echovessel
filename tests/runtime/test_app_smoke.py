"""End-to-end smoke test of Runtime.build + start + one turn + stop.

Uses :memory: DB + StubProvider + zero embedder so nothing touches disk
and no real LLM is called.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlmodel import Session as DbSession
from sqlmodel import select

from echovessel.channels.base import IncomingMessage, OutgoingMessage
from echovessel.core.types import MessageRole
from echovessel.memory.models import RecallMessage
from echovessel.runtime import (
    Runtime,
    build_zero_embedder,
    load_config_from_str,
)
from echovessel.runtime.llm import StubProvider

SMOKE_TOML = """
[runtime]
data_dir = "/tmp/echovessel-smoke-test"
log_level = "warn"

[persona]
id = "smoke"
display_name = "Smoke"

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
"""


class FakeChannel:
    """Channel Protocol v0.2 stub for smoke tests."""

    channel_id = "web"
    name = "Web"

    def __init__(self) -> None:
        self._queue: asyncio.Queue[IncomingMessage | None] = asyncio.Queue()
        self.in_flight_turn_id: str | None = None
        self.sent: list[tuple[str, str]] = []
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False
        await self._queue.put(None)

    async def incoming(self):
        while True:
            env = await self._queue.get()
            if env is None:
                return
            yield env

    async def send(self, msg: OutgoingMessage) -> None:
        self.sent.append((msg.in_reply_to or "", msg.content))

    async def on_turn_done(self, turn_id: str) -> None:
        self.in_flight_turn_id = None

    async def push(self, content: str) -> None:
        await self._queue.put(
            IncomingMessage(
                channel_id=self.channel_id,
                user_id="self",
                content=content,
                received_at=datetime.now(),
                external_ref="ref-1",
            )
        )


async def test_runtime_smoke_full_turn():
    cfg = load_config_from_str(SMOKE_TOML)
    stub = StubProvider(fallback="hey, i hear you")
    rt = Runtime.build(None, config_override=cfg, llm=stub, embed_fn=build_zero_embedder())

    channel = FakeChannel()
    await rt.start(channels=[channel], register_signals=False)
    try:
        await channel.push("hi there")

        # Wait for the dispatcher to run assemble_turn and channel.send.
        for _ in range(50):
            if channel.sent:
                break
            await asyncio.sleep(0.05)

        assert channel.sent, "channel did not receive the persona reply"
        assert channel.sent[0][1] == "hey, i hear you"

        # Verify the turn was persisted.
        with DbSession(rt.ctx.engine) as db:
            msgs = list(db.exec(select(RecallMessage).order_by(RecallMessage.id)))
            assert len(msgs) == 2
            assert msgs[0].role == MessageRole.USER
            assert msgs[1].role == MessageRole.PERSONA
    finally:
        await rt.stop()
