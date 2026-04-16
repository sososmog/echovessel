"""Voice file HTTP endpoint tests (Stage 7).

Tests 7-9: the ``GET /api/chat/voice/{message_id}.mp3`` route that
serves cached voice files produced by ``VoiceService.generate_voice``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx

from echovessel.channels.web.channel import WebChannel
from echovessel.channels.web.routes.chat import build_chat_router
from echovessel.channels.web.sse import SSEBroadcaster

# httpx.ASGITransport lets us test a FastAPI app without binding a
# socket. The router is mounted on a minimal FastAPI instance.


def _make_app(*, voice_service=None):
    from fastapi import FastAPI

    ch = WebChannel(debounce_ms=50)
    broadcaster = SSEBroadcaster()
    router = build_chat_router(
        channel=ch,
        broadcaster=broadcaster,
        voice_service=voice_service,
    )
    app = FastAPI()
    app.include_router(router)
    return app


async def test_voice_route_serves_cached_file():
    """Create a file at the expected cache path, GET the endpoint,
    assert 200 + correct content type + correct body."""
    with tempfile.TemporaryDirectory() as tmp:
        cache_dir = Path(tmp)
        mp3_content = b"\xff\xfb\x90\x00" + b"\x00" * 100  # fake MP3 header
        (cache_dir / "999.mp3").write_bytes(mp3_content)

        voice_service = SimpleNamespace(_voice_cache_dir=cache_dir)
        app = _make_app(voice_service=voice_service)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            r = await client.get("/api/chat/voice/999.mp3")
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/mpeg"
        assert r.content == mp3_content
        assert "immutable" in r.headers.get("cache-control", "")


async def test_voice_route_404_missing_file():
    """File doesn't exist → 404."""
    with tempfile.TemporaryDirectory() as tmp:
        voice_service = SimpleNamespace(_voice_cache_dir=Path(tmp))
        app = _make_app(voice_service=voice_service)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            r = await client.get("/api/chat/voice/0.mp3")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()


async def test_voice_route_404_no_voice_service():
    """voice_service is None → 404."""
    app = _make_app(voice_service=None)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        r = await client.get("/api/chat/voice/123.mp3")
    assert r.status_code == 404
    assert "not configured" in r.json()["detail"].lower()
