"""Stage 1 channel Protocol structural smoke test.

Verifies the concrete channel implementations shipped in Stage 1 — at
this point that's only :class:`WebChannel` — structurally satisfy
:class:`echovessel.channels.base.Channel`. Later stages add Discord /
iMessage / WeChat and can extend this file with their own isinstance
checks.
"""

from __future__ import annotations

from echovessel.channels.base import Channel
from echovessel.channels.web import WebChannel


def test_webchannel_is_protocol_compliant():
    ch = WebChannel(debounce_ms=50)
    assert isinstance(ch, Channel)


def test_webchannel_required_attributes_present():
    ch = WebChannel(debounce_ms=50)
    assert hasattr(ch, "channel_id")
    assert hasattr(ch, "name")
    assert hasattr(ch, "in_flight_turn_id")
    assert hasattr(ch, "start")
    assert hasattr(ch, "stop")
    assert hasattr(ch, "incoming")
    assert hasattr(ch, "send")
    assert hasattr(ch, "on_turn_done")
