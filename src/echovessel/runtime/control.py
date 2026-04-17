"""Daemon control plane — an independent HTTP listener for operator-level
lifecycle operations (health / shutdown / reload).

This module is *orthogonal* to the Web channel that serves the React UI.
It lives on its own uvicorn instance bound to a **separate TCP port**
picked by the kernel (`127.0.0.1:0`). It is intended to be consumed only
by CLI / scripts / supervisors — never by a browser. The `/api/admin/*`
surface on the Web channel is the right home for anything browser-driven;
do not add endpoints here that will ever be hit from a `<button>` click.

## Trust boundary

The control plane binds strictly to `127.0.0.1`. That single fact is the
trust boundary: any process on this host running as this user can connect
and drive the daemon. That is the same boundary as `docker.sock` in TCP
mode and is fine for a single-user personal daemon.

Defence layers beyond loopback:

1. `_CONTROL_BIND_HOST` is a module-level constant · it is **never read
   from config**. A future PR that exposes it as a user setting flips CI
   red (see `tests/runtime/test_control_plane.py::test_bind_host_is_hardcoded`).
2. A `Host`-header middleware rejects any request whose `Host` is not
   `localhost` or `127.0.0.1`. This defends against DNS-rebinding
   attacks that trick a browser into POSTing to the control port.
3. No `Access-Control-Allow-Origin` header is emitted, so browsers'
   default same-origin policy blocks most direct attacks.

## Port assignment

The server binds `(_CONTROL_BIND_HOST, 0)` so the kernel picks a free
port at startup. After bind we read the real port back via
`server.servers[0].sockets[0].getsockname()[1]` and publish it via
`RuntimeContext.control_port` so the CLI (see `runtime/launcher.py`) can
pick it up from the pidfile.

Stage 1 ships `/health` only. `/shutdown` and `/reload` land in stage 2.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from echovessel.runtime.app import Runtime

log = logging.getLogger("echovessel.runtime.control")

#: The only host the control plane ever binds to. **Never** promote this
#: to a configuration field — doing so would defeat the trust boundary.
#: A regression test asserts the literal value.
_CONTROL_BIND_HOST: str = "127.0.0.1"

#: Accepted `Host:` header values. Anything else is rejected with 403.
#: We accept `localhost` for ergonomic curl/CLI use and the raw IP for
#: everything else. Port suffix is stripped by the middleware before
#: comparison.
_ACCEPTED_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1"})


def build_control_app(runtime: Runtime) -> FastAPI:
    """Construct the control-plane FastAPI application.

    Separate from the Web channel's FastAPI app. Keeps its own lifespan,
    its own middleware stack, and its own routes. The passed-in
    ``runtime`` reference is captured via closure so endpoint handlers
    can drive runtime lifecycle (stage 2+).
    """

    app = FastAPI(
        title="EchoVessel control plane",
        description=(
            "Operator-facing daemon lifecycle endpoints. Loopback-only; "
            "never exposed to the Web UI."
        ),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def enforce_localhost_host(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        raw_host = request.headers.get("host", "")
        # Strip any port suffix so "127.0.0.1:54321" compares as "127.0.0.1".
        host = raw_host.split(":", 1)[0].strip().lower()
        if host not in _ACCEPTED_HOSTS:
            return JSONResponse(
                {"error": "invalid host", "got": raw_host or None},
                status_code=403,
            )
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        started_at = getattr(runtime, "_started_at", None)
        return {
            "ok": True,
            "pid": os.getpid(),
            "started_at": (
                started_at.isoformat()
                if isinstance(started_at, datetime)
                else None
            ),
        }

    return app


async def start_control_server(
    runtime: Runtime,
) -> tuple[asyncio.Task[Any], Any, int]:
    """Bind the control plane to a kernel-assigned loopback port and
    launch uvicorn as an asyncio task in the current event loop.

    Returns ``(task, server, port)`` so the caller can keep references
    for shutdown (see :func:`stop_control_server`).
    """

    import uvicorn

    app = build_control_app(runtime)

    config = uvicorn.Config(
        app,
        host=_CONTROL_BIND_HOST,
        port=0,  # kernel picks a free port
        log_level="warning",
        loop="asyncio",
        lifespan="on",
        access_log=False,
    )
    server = uvicorn.Server(config)

    task = asyncio.create_task(server.serve(), name="control_plane_server")

    # Wait for the server to actually bind before returning the port.
    # `uvicorn.Server.serve()` sets `started` after socket creation; we
    # poll at a short cadence because there is no public Event API here.
    # Cap the wait so a hang in uvicorn startup surfaces as an error
    # instead of blocking the whole daemon boot.
    for _ in range(100):  # ~1s
        if server.started and server.servers:
            break
        await asyncio.sleep(0.01)
    else:
        task.cancel()
        raise RuntimeError(
            "control plane: uvicorn did not finish starting within 1s"
        )

    sockets = server.servers[0].sockets
    if not sockets:
        task.cancel()
        raise RuntimeError(
            "control plane: uvicorn started but exposes no sockets"
        )
    port: int = sockets[0].getsockname()[1]

    log.info(
        "control plane: serving on http://%s:%d",
        _CONTROL_BIND_HOST,
        port,
    )

    return task, server, port


async def stop_control_server(
    task: asyncio.Task[Any] | None,
    server: Any | None,
    *,
    timeout: float = 5.0,
) -> None:
    """Teardown counterpart to :func:`start_control_server`.

    Signals graceful shutdown via ``server.should_exit = True`` (the
    documented uvicorn knob) and awaits the task with a timeout. Cancels
    the task if uvicorn does not exit in time.
    """

    if server is not None:
        try:
            server.should_exit = True
        except Exception as e:  # noqa: BLE001
            log.warning("control plane: should_exit set failed: %s", e)

    if task is None:
        return

    try:
        await asyncio.wait_for(task, timeout=timeout)
    except TimeoutError:
        log.warning("control plane: stop timeout; cancelling task")
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    except (asyncio.CancelledError, Exception) as e:  # noqa: BLE001
        log.debug("control plane: task exited: %s", e)


__all__ = [
    "build_control_app",
    "start_control_server",
    "stop_control_server",
]
