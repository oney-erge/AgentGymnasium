# CLAUDE.md

@AGENTS.md

Guidance for Claude (and subagents) working in the AgentGymnasium repository. Read this at
the start of every session and follow it.

## What this is

AgentGymnasium is a visual AI physics sandbox: LLM agents pick explicit tools to build
designs in an isometric world, the backend simulates with Pymunk2D, and the Studio
replays scored attempts. Plan and progress live in `docs/COMPREHENSIVE_PLAN.md` (master
plan + UI spec) and `docs/IMPLEMENTATION_STEPS.md` (numbered Step 1–27 build guide).
Reference these rather than re-deriving the plan.

All 27 build steps are complete (MVP shipped). Forward work is tracked in two docs —
read them before picking up new work:

- `docs/remaining_gaps.md` — day-to-day deferred items and their status.
- `docs/IMPROVEMENTS.md` — the bigger bets (the **PyBullet 3D engine** plan) and the
  record of the post-MVP code-review findings (what was fixed vs. left documented).

Keep both current: when you finish a deferred item or find a new bug/gap, update the
matching table in the same change rather than letting these drift.

## Commands (run from repo root `/home/user/AgentGymnasium`)

- Install: `uv sync --all-groups`
- One-command launch (end users): `./run.sh` (macOS/Linux) or `./run.ps1` (Windows) —
  installs uv, syncs deps, builds the UI if missing, serves, and opens the browser.
- Lint: `uv run ruff check .`
- Test: `uv run pytest`
- Backend server: `uv run agentgymnasium serve` (127.0.0.1:8765; `--open` opens a browser,
  `--no-reload` for a clean non-dev run)
- Frontend build: `cd frontend && npm run build`
- Frontend dev: `cd frontend && npm run dev` (5173, proxies /api + /ws to 8765)

## Definition of done (every change)

A change is not done until all three gates pass, and a code change is not done without
a test:

1. `uv run ruff check .` is clean.
2. `uv run pytest` passes.
3. `cd frontend && npm run build` compiles — **if** frontend files changed.

**YOU MUST add or update tests for any backend behavior change.** Use the `mock`
provider so tests need no network; keep simulations short (≤ ~2s sim time).

## How to work (working agreement)

- **Implement the minimum that satisfies the task.** Do not add speculative
  abstractions, options, or files "for later." Match the surrounding code's style and
  altitude. A one-line fix stays a one-line fix.
- **Do not hallucinate.** Read the actual code before calling an API, schema field, or
  function. If you're unsure something exists, grep for it. Never invent endpoints,
  props, or fields — verify against the source.
- **Surface gaps, don't silently fill them.** As you read code to make a change, note
  bugs, missing validation, dead code, or risks you spot. List them; don't expand scope
  to fix them unless asked.
- **Keep the user in the loop.** End every working turn with three short parts:
  1. **Did** — what changed and the gate results (tests/lint/build).
  2. **Next** — what the next phase is and, before starting it, what you intend to do.
  3. **Suggestions** — gaps you noticed and options worth considering.
- Prefer the dedicated tools (Read/Grep/Glob/Edit) over shell `cat`/`sed`/`grep`.

## Architecture invariants (do not violate)

1. **Agents only emit validated tool calls.** Every design mutation goes through the
   single chokepoint `backend/agentgymnasium/tools/apply.py::apply_tool_call`. Agents never
   touch the engine, renderer, or filesystem directly. High-risk tools default off.
2. **The renderer consumes only `EpisodeTrace`.** Never read engine internals in the
   frontend. This keeps the engine swappable (Pymunk2D now, PyBullet3D later).
3. **`LaunchConfig` is the single source of truth** from the Setup screen; the backend
   Pydantic models and the frontend `api/types.ts` must stay in sync.
4. **Scoring derives metrics from the trace**, via named pluggable rewards — never from
   the engine.
5. **Multi-agent attribution:** per-tool-call `agent_id`, per-part `created_by`, and
   per-agent events carry `agent_id`. Colors: A = `--agent-a` (violet),
   B = `--agent-b` (sky).

## Layout

- `backend/agentgymnasium/` — `core/schemas` (Pydantic v2), `api` (routers), `tools`
  (registry + apply chokepoint), `engines` (base + pymunk2d), `agents` (providers +
  runner + prompts), `services` (run/scoring/preset/orchestrator), `worlds`,
  `challenges`.
- `frontend/src/` — `screens` (Setup, Studio), `components/setup`, `components/studio`,
  `phaser` (iso renderer), `api` (client + types).
- `runs/` is generated — gitignored, never commit.
- `backend/agentgymnasium/static/` is the built web UI. It is **intentionally committed** so
  the app runs with no Node step (see `run.sh`). When you change the frontend, rebuild
  (`cd frontend && npm run build`) and commit the regenerated bundle in the same change.
  `uv.lock` is committed too, for deterministic installs.

## Conventions

- **Backend:** Python 3.11+, Pydantic v2 (`model_dump`, `model_config`), async routes,
  ruff (line length 100; E/F/I/UP/B). Prefer stdlib over new runtime deps (e.g. manual
  lightweight JSON-schema validation, not a `jsonschema` dependency).
- **Frontend:** React + TypeScript. Style with the CSS-variable design tokens in
  `index.css` (`--bg`, `--surface-1/2`, `--border`, `--text-1/2`, `--accent`,
  `--ok/warn/danger`, `--agent-a/b`). Negative rules: no Tailwind utility classes in
  components, no new CSS files, no charting library (inline SVG only), no new npm
  packages without a clear need.
- **Determinism:** seeded worlds, fixed `dt`; a trace must be replayable on its own.

## Git workflow

- Work on the designated feature branch; never push to `main` directly.
- Commit per step with a descriptive message; end the body with the session URL line.
- Do **not** create or merge PRs unless explicitly asked.
- **PRs here are squash-merged**, which puts a brand-new commit on `main` that shares no
  history with the feature branch. So **immediately after a PR merges, re-sync the branch
  to main before doing more work**:
  `git fetch origin main && git checkout <branch> && git reset --hard origin/main && git push --force-with-lease`.
  Skipping this makes the branch look "ahead" with already-merged commits and the next PR
  hits phantom merge conflicts. Confirm content parity first with
  `git diff <branch> origin/main` (should be empty before resetting).

## Operational notes

- **Never use `pkill` / `pkill -f uvicorn`** here — it has killed the shell session.
  Verify backend behavior in-process (`uv run python -c ...`) or with `TestClient`
  instead of launching a background server.
- When delegating to a subagent, give it: the files to read, the acceptance checks, the
  constraints above, and a pointer to this file. Keep backend-only and frontend-only
  work on non-overlapping files when running agents in parallel.
