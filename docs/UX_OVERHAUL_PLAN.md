# AgentGymnasium — UX Overhaul Plan (for the LLM / robotics researcher)

**Status:** proposed (2026-07-08). Not yet started.
**Goal:** turn AgentGymnasium from a "configure-once, launch-once, watch-once" demo into a
**reproducible experimentation loop** for someone probing how well LLMs reason about the
physical world. Read this alongside `docs/COMPREHENSIVE_PLAN.md` (original spec) and
`docs/remaining_gaps.md` (deferred items). This plan supersedes none of the architecture
invariants in `CLAUDE.md` — every item below still routes design mutations through
`apply_tool_call`, renders only from `EpisodeTrace`, and treats `LaunchConfig` as the
single source of truth.

---

## 1. Who we are building for

The target user is not an end consumer clicking "play." It is a **researcher / robotics
engineer running experiments**: "How does Qwen-8B vs GPT-class vs a local model do at
building a bridge? Is it stable across seeds? Did my prompt change help?" Their loop is:

1. **Define** a task + pick a model/settings.
2. **Run** it and watch the agent build + the physics play out.
3. **Reproduce / re-run** — the same config, or the same config with *one thing changed*.
4. **Compare** models/settings/seeds on the *same* task.
5. **Sweep** across a matrix (models × seeds × tasks × repeats) and read aggregate stats.
6. **Export / share** a reproducible record of what happened.

Grounding for what this class of user expects from an eval harness (external sources):
reproducibility via captured resolved config + versions, **multiple seeds reported as
mean ± std**, batched runs, and standardized per-run "rollout cards" — see
[lm-evaluation-harness](https://qaskills.sh/blog/lm-evaluation-harness-tutorial-2026),
[EleutherAI on evaluating LLMs](https://www.eleuther.ai/projects/large-language-model-evaluation),
[Rollout Cards: A Reproducibility Standard for Agent Research](https://arxiv.org/pdf/2605.12131),
and comparison-UI conventions (URL-shareable filters, per-task success rates, group-by-model)
from public leaderboards like [BenchLM](https://benchlm.ai/) and
[Artificial Analysis](https://artificialanalysis.ai/leaderboards/models).

---

## 2. Where the current UX breaks (grounded in the code)

| # | Friction | Evidence in code |
|---|----------|------------------|
| F1 | **Cannot repeat an attempt.** To re-run a past run you must hand-rebuild the whole config in Setup. | `RunSummary` (`api/routes_runs.py:24`) stores no `LaunchConfig`; the only launch path is `POST /setup/launch` taking a fresh config (`routes_setup.py:66`). No `relaunch`, no `GET /runs/{id}/config`. |
| F2 | **Config reuse is clunky.** One shared `workspace_config.json` autosaves over itself; named presets are manual and hidden behind a modal. | `SetupScreen.tsx` workspace-sync effects (lines 151–266); `SavePresetModal`. No per-run capture. |
| F3 | **Setup is a wall of ~40 fields in 3 dense columns.** The two things that actually matter (task, model) are buried among constraints/outputs/memory/mutation-strategy. | `SetupScreen.tsx` 3-column grid; `DEFAULT_CONFIG` has 6 nested groups. |
| F4 | **No comparison.** You cannot put two runs (or two models on one task) side by side. | `HistoryScreen.tsx` is a flat table + single-score leaderboard; Studio is single-run. |
| F5 | **No batch / sweep.** One run at a time; no matrix, no repeats, no aggregates. | Orchestrator `create_run(config)` is 1 config → 1 run (`orchestrator.py:142`). |
| F6 | **Weak observability for an LLM tester.** No view of the prompt sent, the raw model response, token usage, latency, or cost per attempt. | Studio surfaces `ToolCallLog` + scorecard only; no prompt/response/token panel. |
| F7 | **"Attempt History" replays a trace but can't re-run the model.** The one place that looks like "repeat" only re-plays existing frames. | `AttemptHistory.tsx` `onReplay` → `replayTraceRunId` (fetch trace, no new run). |
| F8 | **History is not experiment-oriented.** No filter by model, no success rate, no mean±std, no grouping, no shareable view. | `HistoryScreen.tsx` leaderboard is `score_total` sorted rows. |

---

## 3. The plan (phased, each phase shippable on its own)

Ordering is deliberate: **Phase 0 unblocks everything else**, and Phase 1 directly kills
the pain the user named ("repeat attempts easily"). Later phases are progressively bigger
bets; we can stop after any phase and still have shipped something coherent.

### Phase 0 — Reproducibility foundation (backend, no UI) — *prerequisite*

Nothing downstream (re-run, compare, sweep, share) works until a run remembers how it was
launched. Today it doesn't.

- **Persist the full resolved `LaunchConfig` with every run**, plus provenance: model id,
  provider, `temperature`, `world.seed`, prompt-template identifier, engine, app version /
  git sha, and timestamp. Store it in the existing SQLite (`runs/agentarium.db`) next to
  the run record and in the run's artifact dir as `config.json`.
- **New endpoints:**
  - `GET /runs/{id}/config` → the stored `LaunchConfig`.
  - `POST /runs/{id}/relaunch` → re-create a run from the stored config, accepting an
    optional JSON-merge **patch** (e.g. `{ "agents": { "participants": [{ "model": … }] } }`)
    so "re-run but change only the model/seed" is one call. Re-validates via the existing
    `validate_launch_config` chokepoint before launching.
- Add `model`, `provider`, `seed` columns to `RunSummary` so lists/leaderboards can group
  and filter without loading each config.
- **Tests:** relaunch reproduces an identical config; relaunch-with-patch changes only the
  patched field; `GET /config` round-trips; old runs without a stored config degrade
  gracefully (relaunch disabled, not 500). Use the `mock` provider.

### Phase 1 — One-click re-run & tweak-and-rerun (kills F1, F7)

The headline fix. Once Phase 0 lands, wire it into every place a run is shown.

- **History rows + leaderboard:** each row gets **"Run again"** (relaunch as-is →
  navigate to new Studio run) and **"Duplicate & edit"** (open Setup pre-filled from that
  run's config).
- **Studio header:** **"Re-run"** button, and **"Re-run with changes"** opening a small
  inline popover to change just Model / Seed / Attempts / Temperature — the 4 knobs a
  researcher flips most — without visiting Setup.
- **Attempt History panel:** relabel so replay-vs-rerun is unambiguous; keep trace replay,
  add a per-run "Re-run this configuration."
- **Setup:** a **"Load from a past run"** picker at the top (alongside presets).
- **Tests:** relaunch button issues the right POST and routes to the new run id; patch
  popover sends only changed fields.

### Phase 2 — Setup redesign: progressive disclosure (kills F3, F2)

Make the 20% that matters instant and hide the rest until asked.

- **Quick Start card** at the top: **Task** (gallery of challenge cards with a thumbnail +
  one-line objective, not a dropdown), **Model** (recently-used + provider quick-connect
  with inline "Test connection"), **Attempts**, and a big **Launch**. That alone should let
  a new user launch in ~15s.
- **Advanced** (collapsed by default): the current constraints / outputs / memory /
  mutation-strategy fields, unchanged in behavior — just demoted.
- Replace the always-on `workspace_config.json` status chip with an explicit
  **Import / Export config** control (download the `LaunchConfig` JSON, drag one back in).
  Keep autosave under the hood but stop making it the headline of the screen.
- Auto-seed required tools on task select already works (`P4`, `remaining_gaps.md`) — keep
  it and surface *why* a tool is on ("required by Sorter").
- Keep the 3-column advanced layout for power users behind the disclosure.

### Phase 3 — Compare & experiments (kills F4, F5, F8) — *the big bet*

This is what turns it into a research tool. Two connected features:

- **Run comparison view** (`/compare?runs=a,b,c`): pick 2–N runs → columns of scorecards,
  metric bars, a **config diff** (what actually differed), and **synced replay** (scrub one
  timeline, all viewports move together). URL-encoded so it's shareable.
- **Experiment / batch runner** (`/experiments`):
  - Define a **matrix**: tasks × models × seeds × repeats-per-cell.
  - Backend job queue runs cells sequentially (respecting the single-engine constraint),
    streaming progress; each cell is a normal run (reuses the orchestrator).
  - **Aggregate table**: per (task, model) cell shows **success rate**, **mean ± std**
    score, and attempts-to-success, with drill-down to the individual runs and their
    replays. This is the mean±std-over-seeds pattern the eval-harness literature expects.
  - Export the whole experiment as one bundle (CSV + JSON + per-run cards).
- **Leaderboard upgrade** in History: group-by-model, show success rate + mean score ± std
  + n, filter by task/model/date, URL-shareable filters (BenchLM-style).

### Phase 4 — Observability for LLM testers (kills F6)

What a *model* tester needs beyond physics: see the model's actual behavior.

- **Per-attempt inspector:** the prompt sent, the raw model response, the parsed tool
  calls, and **validation rejections** (what `apply_tool_call` refused and why — this is
  gold for prompt debugging). Much of this already flows over the WS (`tool_call`,
  `design_snapshot.error`); we add prompt/response capture in the runner and a panel.
- **Cost/latency/token strip:** tokens in/out, wall-clock per attempt, and an estimated
  cost (configurable per-model rate). Aggregated per run and per experiment cell.
- **Run Card export:** a single Markdown + JSON artifact per run capturing config +
  provenance + scores + token/latency + a screenshot, matching the "rollout card"
  reproducibility standard so a run can be dropped straight into a paper or repo.

### Phase 5 — Programmatic / headless (power-user reach)

- **"Reproduce this run"** copy-buttons on every run: the exact `curl`, a `LaunchConfig`
  JSON, and a Python snippet hitting `POST /setup/launch`.
- **Headless CLI**: `agentarium run --config cfg.json --seeds 42,1337,2024` and
  `agentarium sweep --matrix matrix.yaml`, writing the same artifacts the UI produces, so
  experiments can live in a script / CI without opening a browser.

---

## 4. Sequencing, effort, and stop-points

| Phase | Effort | Ships on its own? | Depends on |
|-------|--------|-------------------|------------|
| 0 — Reproducibility backend | S–M | (no UI, but unblocks all) | — |
| 1 — One-click re-run | S | ✅ biggest UX win per line | 0 |
| 2 — Setup redesign | M | ✅ | (nice with 1) |
| 3 — Compare + experiments | L | ✅ (compare and batch are separable) | 0, 1 |
| 4 — Observability | M | ✅ | runner capture |
| 5 — Headless / programmatic | S–M | ✅ | 0 |

Recommended first slice: **Phase 0 + Phase 1** together — smallest change that removes the
named pain and makes the tool feel like an experimentation loop. Everything after is
optional and independently valuable.

---

## 5. Invariants & guardrails (must hold)

- Design mutations still go only through `apply_tool_call`; relaunch/patch re-validate via
  `validate_launch_config` before any run starts (same chokepoint as `/setup/launch`).
- Renderer still consumes only `EpisodeTrace`; comparison's synced replay is N independent
  traces, not engine reads.
- `LaunchConfig` stays the single source of truth; the stored per-run config **is** a
  `LaunchConfig`, and frontend `api/types.ts` stays in sync with the new endpoints.
- Every backend behavior change ships with a `mock`-provider test; sims stay ≤ ~2s.
- Batch runner respects existing attempt/duration caps (`_MAX_SIM_DURATION_SECONDS`,
  mode caps) — a sweep can't smuggle in an over-budget run.
- No new npm packages / CSS files / charting libs (inline SVG only), per `CLAUDE.md`.

## 6. Risks / open questions

- **Config schema drift:** a stored config from an old app version may not validate against
  a newer `LaunchConfig`. Mitigation: store the app version; on relaunch, validate and show
  a clear "this config predates field X" message rather than 500.
- **Batch resource use:** long sweeps against a real LLM are slow/expensive. Mitigation:
  sequential queue, cancelable, per-cell timeouts, and a cost estimate shown *before* launch.
- **Prompt/response capture size:** raw responses can be large. Mitigation: cap/truncate in
  the trace, keep full text in the artifact dir only.
- **Scope of Phase 3:** the experiment runner is the one genuinely large piece — it can be
  descoped to "compare view only" if a full matrix runner is more than wanted right now.
