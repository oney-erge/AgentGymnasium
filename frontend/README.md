# AgentGymnasium frontend

React + Vite client for the Setup and Studio screens. Most users do not need to
run this directly because `backend/agentgymnasium/static/` contains the committed
production bundle used by `./run.sh` and `./run.ps1`.

## Requirements

- Node 20.19+ or 22.12+
- npm

## Commands

```bash
npm install
npm run dev      # Vite dev server at http://localhost:5173
npm run build    # type-check and rebuild backend/agentgymnasium/static
npm run lint
```

The dev server proxies `/api` and `/ws` to `http://127.0.0.1:8765`, so start the
backend with:

```bash
uv run agentgymnasium serve --no-reload
```
