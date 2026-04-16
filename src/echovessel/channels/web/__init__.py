"""Web channel — FastAPI backend + React frontend.

Stage 1 (see ``develop-docs/web-v1/01-stage-1-tracker.md``) lands the
:class:`WebChannel` class with a debounce state machine and a stub
``send`` buffer. Later stages replace the stub with real HTTP / SSE
wire-up and add the FastAPI routes under this package.

The React frontend lives under ``channels/web/frontend/`` and is
excluded from the Python wheel build — it runs independently via
``npm run dev`` during Stage 1, and Stage 4 will bundle it via
``vite build`` into ``channels/web/static/``.
"""

from echovessel.channels.web.app import build_web_app
from echovessel.channels.web.channel import WebChannel
from echovessel.channels.web.sse import SSEBroadcaster

__all__ = ["WebChannel", "SSEBroadcaster", "build_web_app"]
