#!/usr/bin/env bash
#
# build_frontend.sh — build the React frontend for embedded distribution.
#
# Runs `npm ci` (if node_modules is missing) and `npm run build` in the
# frontend directory, producing static files in
# `src/echovessel/channels/web/static/`.
#
# Run this manually before `uv build` if you want to see the vite output
# independent of the hatch build hook, or if the hook fails. In normal
# packaging flow you do NOT need to call this yourself — `uv build`
# invokes `hatch_build.py` which runs the same steps internally.
#
# Exit codes:
#   0   — success
#   1   — node / npm not found, or build failed
#   2   — static directory empty after build (vite misconfigured)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/src/echovessel/channels/web/frontend"
STATIC_DIR="$REPO_ROOT/src/echovessel/channels/web/static"

if ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: npm not found on PATH. Install Node.js and retry." >&2
    exit 1
fi

if [ ! -d "$FRONTEND_DIR" ]; then
    echo "ERROR: frontend directory missing: $FRONTEND_DIR" >&2
    exit 1
fi

cd "$FRONTEND_DIR"

if [ ! -d node_modules ]; then
    echo "Installing npm dependencies (npm ci)..."
    npm ci
fi

echo "Running vite build..."
npm run build

if [ ! -d "$STATIC_DIR" ] || [ -z "$(ls -A "$STATIC_DIR" 2>/dev/null | grep -v '^\.gitkeep$' || true)" ]; then
    echo "ERROR: static directory is empty after build: $STATIC_DIR" >&2
    echo "Check src/echovessel/channels/web/frontend/vite.config.ts build.outDir." >&2
    exit 2
fi

echo ""
echo "Frontend build complete."
echo "Static files in: $STATIC_DIR"
ls -la "$STATIC_DIR"
