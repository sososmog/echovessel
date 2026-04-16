"""Channel registry — where runtime keeps live channel instances.

See docs/runtime/01-spec-v0.1.md §2.4 / §3 steps 11-13.

The registry owns the lifecycle of a heterogeneous set of Channel
implementations (`channels/web`, `channels/discord`, ...). Stage 1 of
the web v1 release collapsed the previous runtime-local `ChannelLike`
Protocol into the canonical :class:`echovessel.channels.base.Channel`
Protocol so runtime and channels agree on one shape.

``ChannelLike`` is retained as a module-level alias for the Channel
Protocol so any legacy imports of ``ChannelLike`` still resolve.

Runtime only touches this registry; background tasks call
`registry.all_incoming()` to get a merged async iterator of turn
envelopes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from echovessel.channels.base import Channel, IncomingTurn

log = logging.getLogger(__name__)


# Legacy alias — pre-Stage-1 code imported ``ChannelLike`` from this
# module. It is the same Protocol; the rename simply promotes it to
# its canonical home in ``echovessel.channels.base``.
ChannelLike = Channel


@dataclass
class ChannelRegistry:
    """Keeps track of live channels.

    Runtime uses three methods:
    - `register(channel)` — add a channel
    - `start_all()` / `stop_all()` — lifecycle
    - `all_incoming()` — merged async iterator of IncomingMessage
    """

    _channels: dict[str, Any] = field(default_factory=dict)
    _started: set[str] = field(default_factory=set)

    def register(self, channel: Any) -> None:
        cid = getattr(channel, "channel_id", None) or channel.__class__.__name__
        if cid in self._channels:
            raise ValueError(f"channel already registered: {cid}")
        self._channels[cid] = channel

    def unregister(self, channel_id: str) -> None:
        self._channels.pop(channel_id, None)
        self._started.discard(channel_id)

    def get(self, channel_id: str) -> Any | None:
        return self._channels.get(channel_id)

    def all_channels(self) -> list[Any]:
        return list(self._channels.values())

    def channel_ids(self) -> list[str]:
        return list(self._channels.keys())

    def any_channel_in_flight(self) -> bool:
        """v0.4 · Spec §17a.1 + proactive spec §3.5a.

        Returns True if any currently-registered channel exposes an
        `in_flight_turn_id` attribute that is not None. This is the data
        source for the proactive `is_turn_in_flight` gate — runtime
        injects a closure over this method into
        `build_proactive_scheduler(is_turn_in_flight=...)` so the
        scheduler can skip ticks when the user is mid-exchange.

        Channels that do not expose the attribute are treated as "not
        in flight" (the getattr default). This matches the
        `ChannelProtocol` in `proactive/base.py` which marks
        `in_flight_turn_id` as an optional capability.
        """
        for ch in self._channels.values():
            if getattr(ch, "in_flight_turn_id", None) is not None:
                return True
        return False

    async def start_all(self) -> list[str]:
        """Start every registered channel. Returns the list of ids that
        successfully started; errors are logged per channel so one bad
        channel cannot block the rest."""
        ok: list[str] = []
        for cid, ch in list(self._channels.items()):
            if cid in self._started:
                ok.append(cid)
                continue
            try:
                start = getattr(ch, "start", None)
                if start is not None:
                    await start()
                self._started.add(cid)
                ok.append(cid)
            except Exception as e:  # noqa: BLE001
                log.error("failed to start channel %s: %s", cid, e, exc_info=True)
        return ok

    async def stop_all(self) -> None:
        for cid, ch in list(self._channels.items()):
            try:
                stop = getattr(ch, "stop", None)
                if stop is not None:
                    await stop()
            except Exception as e:  # noqa: BLE001
                log.error("failed to stop channel %s: %s", cid, e, exc_info=True)
            finally:
                self._started.discard(cid)

    async def all_incoming(self) -> AsyncIterator[IncomingTurn]:
        """Merge every started channel's `incoming()` into a single stream.

        v0.2 channels yield :class:`IncomingTurn` (debounced bursts);
        legacy stub channels that still yield a bare ``IncomingMessage``
        are tolerated by the turn dispatcher, which auto-wraps them into
        a 1-element ``IncomingTurn`` before handing the envelope to
        the runtime handler.

        Uses asyncio.Queue as the merge point so bored channels don't
        starve busy ones. Stops when every source has exhausted its
        iterator (or the caller cancels).
        """
        queue: asyncio.Queue[Any | None] = asyncio.Queue()
        sources: list[asyncio.Task[None]] = []

        async def _drain(channel_id: str, ch: Any) -> None:
            try:
                gen = ch.incoming()
                async for env in gen:
                    await queue.put(env)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.error(
                    "channel %s incoming() errored: %s",
                    channel_id,
                    e,
                    exc_info=True,
                )
            finally:
                await queue.put(None)  # sentinel

        for cid, ch in self._channels.items():
            if cid not in self._started:
                continue
            sources.append(asyncio.create_task(_drain(cid, ch)))

        live = len(sources)
        try:
            while live > 0:
                item = await queue.get()
                if item is None:
                    live -= 1
                    continue
                yield item
        finally:
            for t in sources:
                t.cancel()
            for t in sources:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t


__all__ = ["ChannelRegistry", "ChannelLike", "Channel"]
