"""Control-plane HTTP server — /health endpoint, Host middleware, bind
invariants.

Stage 1 scope:
- Server binds 127.0.0.1 on a kernel-assigned port and exposes /health
- Host header middleware rejects off-host requests with 403
- `_CONTROL_BIND_HOST` is locked to 127.0.0.1 (regression guard)
- Server shuts down cleanly via `stop_control_server`

Stage 2+ will add /shutdown and /reload — those are tested separately.
"""

from __future__ import annotations

import httpx
import pytest

from echovessel.runtime.control import (
    _ACCEPTED_HOSTS,
    _CONTROL_BIND_HOST,
    build_control_app,
    start_control_server,
    stop_control_server,
)


class _DummyRuntime:
    """Minimal Runtime stand-in for control-plane tests.

    The real Runtime is heavy (opens a DB, builds providers, starts
    workers). For stage 1 we only exercise the FastAPI app + uvicorn
    plumbing, which touches Runtime only to read `_started_at`. A
    dummy with the right attributes is faster and keeps failures
    localised.
    """

    def __init__(self) -> None:
        self._started_at = None


def test_bind_host_is_hardcoded():
    """Regression: the control plane must never be bindable to anything
    other than loopback. If a PR makes this configurable the line below
    flips red.
    """
    assert _CONTROL_BIND_HOST == "127.0.0.1"
    assert "localhost" in _ACCEPTED_HOSTS
    assert "127.0.0.1" in _ACCEPTED_HOSTS


async def test_health_endpoint_returns_ok():
    rt = _DummyRuntime()
    task, server, port = await start_control_server(rt)
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as c:
            r = await c.get("/health")
        assert r.status_code == 200
        payload = r.json()
        assert payload["ok"] is True
        assert isinstance(payload["pid"], int)
        # Dummy runtime has _started_at=None → serialised as null.
        assert payload["started_at"] is None
    finally:
        await stop_control_server(task, server)


async def test_host_header_middleware_rejects_evil_host():
    rt = _DummyRuntime()
    task, server, port = await start_control_server(rt)
    try:
        # httpx sends `Host: <target>` by default; override explicitly.
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as c:
            r = await c.get("/health", headers={"Host": "evil.example.com"})
        assert r.status_code == 403
        assert "invalid host" in r.json()["error"]
    finally:
        await stop_control_server(task, server)


async def test_host_header_accepts_localhost_alias():
    rt = _DummyRuntime()
    task, server, port = await start_control_server(rt)
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as c:
            r = await c.get("/health", headers={"Host": f"localhost:{port}"})
        assert r.status_code == 200
    finally:
        await stop_control_server(task, server)


async def test_kernel_assigns_different_port_each_start():
    """Sanity: port=0 means we don't collide if another copy of the
    daemon is already running (in a test fixture leak scenario)."""
    rt = _DummyRuntime()
    task1, server1, port1 = await start_control_server(rt)
    try:
        task2, server2, port2 = await start_control_server(rt)
        try:
            assert port1 != port2
        finally:
            await stop_control_server(task2, server2)
    finally:
        await stop_control_server(task1, server1)


async def test_stop_control_server_idempotent_on_none():
    # Calling stop with None task/server should be a no-op, not raise.
    await stop_control_server(None, None)


async def test_build_control_app_exposes_known_routes():
    app = build_control_app(_DummyRuntime())
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/health" in paths
    # /shutdown and /reload are stage 2. If they appear here stage 1
    # was rushed.
    assert "/shutdown" not in paths
    assert "/reload" not in paths


@pytest.fixture(autouse=True)
def _event_loop_quieted(caplog):
    """Keep uvicorn's startup noise out of the captured log unless a
    test explicitly asks for it."""
    import logging

    caplog.set_level(logging.ERROR, logger="uvicorn")
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    yield
