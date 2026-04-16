# EchoVessel Web Frontend

React 19 + Vite + TypeScript single-page app. This is the source for the
chat, onboarding, and admin UI that EchoVessel ships to end users.

## How it ships

End users do not touch this directory. The daemon serves a pre-built
bundle from `../static/` on `http://127.0.0.1:7777/`, and
`hatch_build.py` packages that directory into the wheel. A user running
`echovessel` gets the compiled SPA automatically — no Node install
required.

## Contributor workflow

### Rebuild the shipped bundle

```
npm install
npm run build
```

`vite build` writes the output to `../static/`. Commit the result
alongside your source changes so the wheel stays in sync.

### Iterate with hot reload

```
npm run dev
```

Vite serves at <http://localhost:5173> and proxies `/api/*` to the
running daemon (default `http://127.0.0.1:7777`). Start the daemon
separately in another terminal (`echovessel run` or
`uv run python -m echovessel.cli run`). Proxy config lives in
`vite.config.ts`.

## Backend contract

All network calls go through the daemon. The HTTP + SSE routes live in:

- `../routes/chat.py` — `POST /api/chat/send`, `GET /api/chat/events`
  (SSE), `GET /api/chat/voice/{message_id}.mp3`
- `../routes/admin.py` — `GET /api/state`, `GET /api/admin/persona`,
  `POST /api/admin/persona`, `POST /api/admin/persona/onboarding`,
  `POST /api/admin/persona/voice-toggle`

Onboarding writes real rows into the SQLite persona/memory tables.
Persona edits persist to `config.toml` and the database. Chat turns
hit the live LLM turn loop.

Typed client wrappers are in `src/api/client.ts`; SSE event shapes are
in `src/api/types.ts`.
