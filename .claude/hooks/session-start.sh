#!/bin/bash
# AgentGymnasium SessionStart hook — install deps so tests/linters work in
# Claude Code on the web. Synchronous and idempotent.
set -euo pipefail

# Only run in remote (Claude Code on the web) sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Backend: managed Python + dependencies (uv reads uv.lock; idempotent).
uv sync --all-groups

# Frontend: node_modules so `npm run build` / eslint work. `npm install`
# (not `npm ci`) so the cached container state speeds up re-runs.
if [ -d frontend ]; then
  (cd frontend && npm install)
fi
