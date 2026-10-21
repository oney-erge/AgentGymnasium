## Summary

-

## Checks

- [ ] `uv run ruff check .`
- [ ] `uv run pytest`
- [ ] Frontend changes: `npm run build` and `npm run lint`, with the rebuilt `backend/agentgymnasium/static/` committed
- [ ] Launcher changes: `bash -n run.sh run.command` and `scripts/test-launcher-helpers.ps1`

## Project rules

- [ ] The typed tool boundary is intact: invalid tool arguments are still rejected before the physics engine.
- [ ] Simulation, scoring, and replay stay deterministic, or the change says why it does not.
- [ ] Tests are offline and use the `mock` provider, not a real model.
- [ ] Nothing from `runs/`, no model files, and no credentials are committed.
