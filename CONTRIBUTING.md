# Contributing

AgentGymnasium gives an AI agent a physics challenge, validates every design change through a typed
tool boundary, runs the simulation, and records the result so attempts can be replayed and compared.
Changes should keep that loop deterministic and inspectable.

## Set up a development checkout

```bash
git clone https://github.com/oney-erge/AgentGymnasium.git
cd AgentGymnasium
uv sync --all-groups --frozen
```

`./run.sh` (macOS: `./run.command`, Windows: `.\run.bat`) starts the Studio at
`http://localhost:8765` using the offline `mock` agent, so you can try a change without a model or
an API key. See [Setup and automation](docs/GETTING_STARTED.md) for the other routes.

The backend lives in `backend/agentgymnasium/` and its tests in `backend/tests/`. The browser UI is
in `frontend/`; its production build is committed in `backend/agentgymnasium/static/` so a checkout
runs without Node.

## Check your change

```bash
uv run ruff check .      # backend lint
uv run pytest            # backend tests (CPU, offline, no real provider calls)
```

If you changed `frontend/`:

```bash
cd frontend
npm ci
npm run build            # also rewrites backend/agentgymnasium/static/
npm run lint
```

Commit the rebuilt `static/` bundle together with the source change, and use Node 20.19 or newer
(22.12 or newer on the 22 line). If you changed a launcher (`run.bat`, `run.ps1`, `run.sh`,
`run.command`), run `bash -n run.sh run.command` and, on Windows,
`powershell -NoProfile -File scripts/test-launcher-helpers.ps1`. CI runs all of these, including the
launcher helpers under Windows PowerShell 5.1.

## Pull request expectations

- Keep the typed tool boundary: invalid tool arguments are rejected before they reach the physics
  engine, and every design change is validated and recorded.
- Keep simulation paths deterministic and keep replay evidence, scorecards, and run history
  durable. A change to scoring or physics should say so, and add or update a test.
- Keep tests offline. Do not call a real model provider in a deterministic check; use the `mock`
  provider.
- Keep backend, frontend, and documentation behavior aligned, and add focused tests for changed
  behavior.
- Keep `run.bat`, `run.ps1`, `run.command`, and `run.sh` as the stable entry points with the same
  `run`, `doctor`, `repair`, `docker`, `logs`, and `stop` actions.
- Do not commit anything from `runs/` (run history and your workspace configuration, which can
  contain an API key), model files, or credentials.

## Reporting problems

Use the issue templates for bugs and feature requests. For anything security-related, read
[SECURITY.md](SECURITY.md) first and do not post details in a public issue.
