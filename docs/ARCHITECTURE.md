# Architecture

AgentGymnasium is a setup-first loop: you configure a run, an LLM agent builds a
design by emitting **validated tool calls**, a physics engine simulates it into
an engine-neutral **trace**, the trace is scored by a named **reward**, and the
Studio replays the trace while streaming live events. This document maps the
pieces and the invariants that keep them swappable.

## The loop

```
Setup → LaunchConfig → validate → launch → agent tool calls → DesignSpec
      → engine.simulate → EpisodeTrace → reward → ScoreCard → replay + score
      → (memory) → next attempt
```

```mermaid
flowchart TD
    subgraph Frontend [Frontend · React + Phaser]
        S[Setup screen] -->|LaunchConfig| V[/POST /api/setup/validate/]
        S -->|LaunchConfig| L[/POST /api/setup/launch/]
        ST[Studio screen] <-->|WS /ws/runs/id| WS
        ST -->|GET /api/exports/...| EX
    end

    subgraph Backend [Backend · FastAPI + Pymunk2D]
        L --> RM[RunManager<br/>background task]
        RM --> RUN[runner: build attempt]
        RUN -->|provider.generate + typed tools| P[LLM provider<br/>mock / local / OpenAI-compat]
        P -->|tool_calls JSON| RUN
        RUN -->|apply_tool_call<br/>chokepoint| D[DesignSpec]
        D --> ENG[Pymunk2D engine]
        ENG -->|EpisodeTrace| SC[scoring: named reward]
        SC -->|ScoreCard| RM
        RM -->|typed events| WS[(event stream)]
        ENG --> STORE[(RUNS / SCORES / DESIGNS<br/>+ runs/id/ artifacts)]
        EX[exports] --> STORE
    end
```

## Components

| Layer | Path | Responsibility |
| --- | --- | --- |
| Schemas | `backend/agentarium/core/schemas` | Pydantic v2 models for launches, models, experiments, designs, traces, scores, tools, and embodiment. |
| Tools | `backend/agentarium/tools` | Registry of 24 tools + the single `apply_tool_call` mutation chokepoint. |
| Engines | `backend/agentarium/engines` | `EngineAdapter` base + Pymunk2D engine producing engine-neutral traces. |
| Agents | `backend/agentarium/agents` | Providers (mock / localdeploy / OpenAI-compatible / manual), prompts, and the attempt runner. |
| Services | `backend/agentarium/services` | Run/experiment orchestration, scoring, presets, durable storage, exports, embodiment supervision and episodes. |
| API | `backend/agentarium/api` | Routers for setup, tools, presets, runs, experiments, embodiments, exports, and WebSocket. |
| Renderer | `frontend/src/phaser` | Side-view + isometric Phaser visual system that consumes **only** `EpisodeTrace`; deterministic themes, semantic props, joints, effects, beauty/engineering overlays. |
| Screens | `frontend/src/screens` | Setup, Studio, History, Experiments, Compare, Physical Lab, and the deterministic Visual Catalog. |

## Invariants (do not violate)

1. **Agents only emit validated tool calls.** Every design mutation goes through
   `tools/apply.py::apply_tool_call`. Agents never touch the engine, renderer, or
   filesystem directly; out-of-range/non-finite args are rejected before they can
   reach (and crash) the physics engine. High-risk tools default off.
2. **The renderer consumes only `EpisodeTrace`.** No engine internals leak to the
   frontend, so the engine stays swappable (Pymunk2D now, PyBullet3D later).
3. **`LaunchConfig` is the single source of truth** from the Setup screen; the
   backend Pydantic models and the frontend `api/types.ts` stay in sync.
4. **Scoring derives metrics from the trace**, via named pluggable rewards — never
   from the engine.
5. **Multi-agent attribution** is carried end to end: per-call `agent_id`,
   per-part `created_by`, and per-agent events.
6. **Physical actions cross a separate safety boundary.** Models receive only
   normalized observations and high-level actions. Arming, control tokens,
   geofences, action limits, watchdogs, and a latched emergency stop remain
   outside the model/provider.

## Replay and visual contract

`EpisodeTrace` version 3 remains backwards compatible with version-2 replay
payloads. In addition to body transforms and semantic `kind`, it carries:

- the selected `visual_style` and deterministic `visual_seed`;
- per-prop/body `VisualSpec` metadata (variant, material, condition, emission,
  label, and animation state);
- renderer-facing joint metadata (body ids, local anchors, type, motor rate);
- frame events for creation, contacts, stress, goal entry, sorting, and falls.

These fields are cosmetic/observational. They never mutate physics and do not
enter reward calculation. `visualTheme.ts`, `props.ts`, `isoProps.ts`, and
`visualOverlays.ts` are the shared render layers. `/visuals` supplies seeded
City/Bridge/Crawl/Sorter reference scenes across every supported style.

## Model interaction protocol

`AgentProvider.generate(ModelRequest)` returns a normalized `ModelResult`.
OpenAI-compatible providers pass native function definitions and a seed when
the endpoint supports them, then normalize usage, retries, request id, finish
reason, latency, and tool calls. Prompt-JSON parsing remains the compatibility
fallback.

Real providers can perform a bounded observe → revise loop inside an attempt.
Inspection calls produce score/state/failure output that is included in the next
model turn. Each `ModelInteraction` is persisted to
`model_interactions.json`; API, Studio, Compare, run metadata, and experiments
consume the same record.

## Tools

24 tools across five categories, gated per run by `LaunchConfig.tools.enabled`.
Each tool declares an honest **status** so the UI and the chokepoint never imply
behavior that isn't there:

- **implemented** — mutates the design and takes real effect.
- **inspection** — read-only / informational; legitimately does not mutate.
- **experimental** — not yet implemented; **off by default**, badged in the UI,
  and **rejected** at the chokepoint with a clear message if called (never a
  silent no-op success).

| Category | Tools (status) | On by default |
| --- | --- | --- |
| building | all 7 implemented: `create_body`, `add_joint`, `add_motor`, `add_beam`, `add_ramp`, `add_ball`, `add_bin` | 7 / 7 |
| sensors_control | `get_state` (inspection); `add_sensor`, `set_controller` (experimental) | 1 / 3 |
| physics_materials | `set_material`, `set_friction`, `set_density`, `set_gravity` (implemented); `set_collision_group` (experimental) | 2 / 5 |
| simulation_inspection | all inspection: `run_simulation`, `inspect_score`, `inspect_failure_events`, `compare_attempts` | 3 / 4 |
| evolution_utilities | `name_design` (implemented); `save_best_design`, `export_design` (inspection); `mutate_design`, `repair_invalid_design` (experimental) | 2 / 5 |

Each tool has a JSON-schema `input_schema`; `apply_tool_call` enforces required
fields, types, enums, numeric bounds, finiteness, and array lengths before
mutating the design.

### Constraint honesty

`LaunchConfig.constraints` `max_parts` / `max_joints` / `max_motors` are enforced
at the chokepoint. `energy_budget`, `material_budget`, `collision_safety`,
`world_bounds`, and `world.seed` are **configurable but not yet enforced** — the
Setup UI badges them "soon" / "coming soon" so they don't imply control the engine
doesn't have.

## Scoring

`compute_metrics(trace, design)` derives a flat, deterministic metrics dict
(distance, stability, falls, energy, spread, bin containment, …). A **named
reward** maps that to `(score_total, success, summary)`:

| Reward | Used by | Idea |
| --- | --- | --- |
| `bridge_transport` | Bridge Builder | Goal progress + reaching the goal zone + stability − falls − excess-part penalty. |
| `crawl_locomotion` | Crawl | Net forward travel + crossing the threshold line − falls (no part bonus → favours motion). |
| `sorting_accuracy` | Sorter | True object-class-to-bin matching (ball color vs bin `accepts`); falls back to plain containment when no class is declared. |
| `city_score` | Tiny City | Structure count + spread + nearest-neighbour spacing (livability) + stability. |
| `distance_plus_stability` | (legacy) | Horizontal travel + stability − falls. |
| `default` | baseline | Distance-only fallback. |

Rewards are pure functions registered in a `REWARDS` dict, so adding one is a
single function plus a name — no engine or renderer changes. A challenge preset's
`goal` params (e.g. `goal_x`, `threshold_x`, `min_spacing`) are injected into the
design metadata at scoring time, so rewards can be goal-aware without the engine or
renderer knowing about challenges.

## Multi-agent modes

Set via `LaunchConfig.agents.mode`. Each tool call carries its author's
`agent_id`; each created part carries `created_by`.

| Mode | Status | Behavior |
| --- | --- | --- |
| `single` | ✅ live | One agent iterates over capped attempts. |
| `competitive` | ✅ live | Each participant runs its own attempts; highest score wins (A = violet, B = sky). |
| `cooperative` | ✅ live | All participants build **one shared design**, scored once; parts attributed per agent. |
| `relay` | ✅ live | Participants alternate through one attempt lineage; the previous scored lesson is forced into the next agent's context. |
| `sandbox` | ✅ live | Every participant receives one independent trial and no artificial winner is declared. |

## Experiments

`ExperimentManager` expands model × paired seed × repeat matrices into ordinary
run launches. Local JSON experiment records survive restart, API keys are
redacted, and every trace remains replayable. Aggregates include descriptive
statistics and pairwise deltas on matching seed/repeat cells. See
[`EXPERIMENTS.md`](EXPERIMENTS.md).

## Embodiment

`EmbodimentAdapter` has four operations: reset, observe, execute one typed
high-level action, and emergency stop. `MockRoverAdapter` is deterministic;
`ROS2GatewayAdapter` speaks an authenticated HTTP contract to a robot-side ROS 2
process. `SafetySupervisor` owns the host-side state machine and watchdog.
Bounded model episodes use the same normalized provider telemetry as simulation
runs. See [`EMBODIMENT.md`](EMBODIMENT.md).

## Persistence

Run artifacts are written to `runs/{run_id}/` (`design.yaml`, `trace.json`,
`toolcalls.jsonl`, `score.json`, `build_snapshots.json`,
`model_interactions.json`) and kept in bounded in-memory stores
(`RUNS` / `SCORES` / `DESIGNS`, oldest evicted past a cap; the orchestrator evicts
oldest *finished* runs).

`build_snapshots.json` stores labelled `BuildStepRecord` rows: accepted,
rejected, no-op, and synthetic repair-pass steps each carry mutation metadata and
an un-simulated one-frame trace. `GET /api/runs/{run_id}/snapshots` returns those
steps for historical Studio replay; older runs without the file return `[]`.

**SQLite** (`runs/agentarium.db`) write-throughs the trace, score, and design for
every run plus a queryable `run_meta` row (challenge, mode, reward, score, success,
artifact dir, timestamp). `get_trace/score/design` fall back to the DB when a run is
evicted from memory, and the last ~200 runs reload on startup — so replay, run
**history** (`GET /api/runs/history`) and **leaderboards**
(`GET /api/runs/leaderboard?challenge=…`) survive a restart. Access is guarded by a
process lock; conversion to async `aiosqlite` is a possible follow-up (the sync
layer is simpler and test-friendly today).

## Determinism

Worlds are seeded and `dt` is fixed, so a trace is replayable on its own. Tests
use the `mock` provider (no network) and short simulations, so the full suite is
fast and deterministic.

## See also

- [`remaining_gaps.md`](remaining_gaps.md) — current backlog and deferred items.
- [`EXPERIMENTS.md`](EXPERIMENTS.md) — reproducible model matrices and statistics.
- [`EMBODIMENT.md`](EMBODIMENT.md) — physical safety and ROS 2 gateway contract.
- [`IMPROVEMENTS.md`](IMPROVEMENTS.md) — review notes, shipped improvements, and roadmap.
- [`archive/`](archive/) — historical product plan, build guide, and early gap analysis.
- [`examples/`](examples/) — a real generated run report + scorecard.
