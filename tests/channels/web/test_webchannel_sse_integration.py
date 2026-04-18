"""WebChannel × SSEBroadcaster integration tests.

Verifies the channel correctly fans out through the attached
broadcaster for:

- ``push_user_message`` → ``chat.message.user_appended``
- ``send(OutgoingMessage)`` → ``chat.message.done``
- ``push_sse(...)`` direct → whatever event was passed

The historical per-token streaming path (``on_token_callback`` →
``chat.message.token``) was removed when the UX switched to a typing
indicator; see tests/runtime/test_cross_channel_sse.py for the
``chat.message.typing_started`` regression.
"""

from __future__ import annotations

from datetime import datetime

from echovessel.channels.base import IncomingMessage, OutgoingMessage
from echovessel.channels.web.channel import WebChannel
from echovessel.channels.web.sse import SSEBroadcaster


def _make() -> tuple[WebChannel, SSEBroadcaster]:
    broadcaster = SSEBroadcaster()
    channel = WebChannel(debounce_ms=50)
    channel.attach_broadcaster(broadcaster)
    return channel, broadcaster


async def test_push_sse_fans_out_through_broadcaster() -> None:
    channel, broadcaster = _make()
    q = await broadcaster.register()

    await channel.push_sse("chat.settings.updated", {"voice_enabled": True})
    frame = q.get_nowait()
    assert frame["event"] == "chat.settings.updated"
    assert frame["data"] == {"voice_enabled": True}


async def test_send_broadcasts_chat_message_done() -> None:
    channel, broadcaster = _make()
    q = await broadcaster.register()

    msg = OutgoingMessage(
        content="hello world",
        in_reply_to="ext-1",
        in_reply_to_turn_id="turn-abc",
        kind="reply",
        delivery="text",
    )
    await channel.send(msg)

    frame = q.get_nowait()
    assert frame["event"] == "chat.message.done"
    data = frame["data"]
    assert data["content"] == "hello world"
    assert data["in_reply_to_turn_id"] == "turn-abc"
    assert data["delivery"] == "text"
    assert "kind" not in data
    # When a broadcaster IS attached, `send` must NOT fall back to the
    # Stage 1 `self.sent` buffer — real fan-out replaces it.
    assert channel.sent == []


async def test_send_without_broadcaster_falls_back_to_sent_list() -> None:
    channel = WebChannel(debounce_ms=50)  # no broadcaster attached
    msg = OutgoingMessage(content="stub", kind="reply", delivery="text")
    await channel.send(msg)
    assert len(channel.sent) == 1
    assert channel.sent[0].content == "stub"


async def test_push_user_message_broadcasts_user_appended() -> None:
    channel, broadcaster = _make()
    q = await broadcaster.register()

    msg = IncomingMessage(
        channel_id="web",
        user_id="self",
        content="hi there",
        received_at=datetime(2026, 4, 15, 12, 0, 0),
        external_ref="client-tag",
    )
    await channel.push_user_message(msg)

    frame = q.get_nowait()
    assert frame["event"] == "chat.message.user_appended"
    assert frame["data"]["content"] == "hi there"
    assert frame["data"]["user_id"] == "self"
    assert frame["data"]["external_ref"] == "client-tag"


