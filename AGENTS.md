# AgentGymnasium Repository Instructions

AgentGymnasium is a visual AI physics sandbox. The Python backend and simulation
code live under `src/agentgymnasium/`; the browser interface lives under
`frontend/`; tests live under `tests/`. Preserve the typed tool boundary,
deterministic simulation paths, replay evidence, safety limits, and durable run
history.

## Focused commands

- Backend lint: `uv run ruff check .`
- Backend tests: `uv run pytest`
- Frontend build: `cd frontend && npm run build`
- Native application: `./run.sh` or `.\run.ps1`
- Docker application: `./run.sh docker` or `.\run.ps1 docker`

Keep backend, frontend, and documentation behavior aligned. Add focused tests
for changed behavior, avoid real provider calls in deterministic checks, and
preserve unrelated worktree changes.


## Install and run contract

- Keep `run.bat`, `run.ps1`, `run.command`, and `run.sh` as the stable
  user entry points. They must keep the same `run`, `doctor`, `repair`,
  `docker`, `logs`, and `stop` actions where the application supports them.
- Use the `native-app-delivery` Codex skill when changing first-run setup,
  repair, Docker, or launcher behavior. That is an internal workflow name and
  must not appear in product copy or the public README.
- Keep shared install mechanics in `scripts/install-utils.ps1` and
  `scripts/install-utils.sh`. Preserve idempotent reruns, bounded transient
  retries, install locking, disk checks, user state, and `.setup/install.log`.
- Verify launcher changes with PowerShell parsing, `bash -n`, the focused
  delivery audit, and `docker compose config`. Do not run the full application
  test suite unless the change affects application behavior.
