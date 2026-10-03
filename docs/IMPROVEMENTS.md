# AgentGymnasium — Improvements & Forward Roadmap

Living document for larger improvements and the findings of the post-MVP repo
review. Day-to-day deferred items live in [`remaining_gaps.md`](remaining_gaps.md);
this file is for the bigger bets (3D engine) and a record of the review pass.

Status legend: 🟢 **Done** · 🟡 **Planned** · 🔵 **Needs a product call**.

---

## 0. Isometric city building: `citysim` engine (2026-07-22)

User ask: make city building look like an actual isometric city, with more
depth/goals, without the heavier PyBullet/Three.js bet (§1). Root cause of "it
doesn't look like a city" was architectural, not content: `TraceRenderer` is a
straight side view (x-right/y-up, no depth axis), and `city_score` scored a
spacing/spread proxy over rigid-body physics a city doesn't actually need.

**Direction taken:** add a depth axis to the trace contract, an isometric
projection path in the renderer, and a new **`CityEngine`** behind the existing
`EngineAdapter` seam — a layout + economy simulation (zoning, roads,
population, budget, pollution/happiness over discrete ticks), not rigid-body
physics. Additive only: `pymunk2d` and the existing 4 challenges (including the
original side-view `tiny_city_preview`) are completely untouched.

| Area | What shipped |
|------|--------------|
| Trace/design schema | `FrameBody.z`, `StaticProp.z` (ground-plane depth; 0 for side-view traces, backward compatible). `BodySpec.z` / `BodySpec.depth` (footprint depth), meaningful only to `citysim`. `EpisodeTrace.version` → 2. `PhysicsEngine.citysim`. `WorldTemplate.engine` / `WorldTemplate.starting_budget`. |
| Engine | `engines/citysim/` — `CityEngine` (no rigid-body motion; every body becomes a static iso prop) + `layout.py` (pure zoning/connectivity/footprint helpers, shared with scoring so the two never disagree). Registered in `engines/get_engine`. |
| Tools | `create_body` gained optional `z`/`depth` args (no new tool — reusing `create_body` + `kind` was simpler than the originally-sketched `place_zone`/`place_road`/`place_service` tools, which would have just duplicated it). |
| Scoring | `compute_city_metrics` (zoning/connectivity/overlap from the design + the final `city_tick` event from the trace, per the "scoring derives from the trace" invariant). Five new rewards: `city_planning`, `boomtown`, `budget_city`, `balanced_city`, `green_capital`. |
| Runner | `_seed_world` seeds `starting_budget` from the template (same pattern as `ground_spans`/`kill_y`) and now makes the **template authoritative for `world.engine`** — a no-op for every pre-existing template (default `pymunk2d`), but guards a stale/hand-built `LaunchConfig` from running a citysim template through the physics engine. `_world_context` gives the agent a citysim-specific world description (ground-plane x/z, zoning vocabulary) instead of the physics one. |
| Mock provider | New tailored city-builder build (`_CITY_BUILDER_TOOL_CALLS`) varying both x **and** z with a real zone/road mix — routed before the old single-row city check so the two city families don't collide. |
| Content | New world template `city_grid` (engine `citysim`) + **one** challenge, `city_builder`. Scaffold-free (agent builds roads and zoning itself) to avoid ambiguity between world-seeded and agent-built roads for connectivity scoring. |
| Renderer | `frontend/src/phaser/isoProps.ts` (new): 2:1 dimetric projection, 3-face extruded-box drawer + per-kind toppers (pitched roof/windows/awning/chimney/cross/road markings/tree canopy/fountain), painter's-algorithm depth sort. `TraceRenderer.ts` branches on `trace.camera === 'iso'` into a parallel set of methods (`buildIsoWorld`/`renderIsoFrame`/`isoFitToWorld`/…) — the side-view path is untouched. Setup screen's world-template selection now also carries `engine` (like terrain/map_size/gravity), and shows a real (non-"coming soon") City Sim radio option. |
| Tests | `backend/tests/test_citysim.py` (layout helpers, engine ticks/connectivity/budget, scoring, all 5 rewards, preset/template loading, end-to-end mock run through the real API validation path) + `create_body` z/depth tests in `test_apply_tool.py`. |

### Follow-up pass (same day): one challenge + a real visual overhaul

User feedback after the first cut: 5 separate city challenges should be **one** challenge with the goals as a setting, and the render still "doesn't look great" — flat boxes, no roads reading as a network, no ground texture.

**Consolidation.** Deleted `grid_city`/`boomtown`/`budget_city`/`balanced_city`/`green_capital` as separate presets; one `city_builder` challenge remains. `ScenarioPreset.reward_options: list[RewardOption]` (`{value, label, description}`) lets a challenge offer alternate scoring goals over the *same* build — `city_builder` lists all 5 rewards. The Setup screen renders a **City Goal** dropdown (only shown when a preset has `reward_options`) that just sets `scenario.reward`; nothing about the build changes. `test_presets.py`/`test_citysim.py` updated (9 presets → 5; new `test_city_builder_reward_option_selects_a_different_scoring_goal` proves the same build scores differently under a different goal).

**Visual overhaul**, verified with real Playwright screenshots against a live mock run (not just "it compiles") — this caught two real bugs a code read alone wouldn't have:
- **Consistent lighting + shadows.** One light direction across every extrusion (top/right/front face shade constants, pushed to a punchier `1.0/0.66/0.4` split — a subtle split reads as flat gray at typical zoom). Every structure/tree casts a soft offset ground shadow.
- **Sky gradient.** A screen-fixed vertical gradient (`skyLayer`, scroll-factor 0, redraws on resize) instead of a flat camera clear color.
- **Tiled ground + sidewalks.** `drawIsoGroundTiles` mottles the grass fill per-tile (deterministic pseudo-random shade + occasional tufts) and draws a lighter sidewalk strip bordering every road footprint — previously roads had nothing framing them.
- **Road network detail.** Solid edge lines added alongside the existing dashed centerline; `roadOverlap` + `drawIsoIntersectionPatch` paint a clean paved patch wherever two road props cross, instead of two dash patterns overlapping messily.
- **Richer facades.** Shop's awning was rebuilt as bold alternating red/white stripes + a bright storefront-glass band (the original plain near-white sliver was nearly invisible against the wall color); windows gained lit/unlit variety seeded from the body id (`seedFromId`) so a row of towers isn't identical clones.
- **Street furniture.** `computeStreetFurniture` scatters streetlights/parked cars along road edges client-side (derived from the trace's own roads/buildings, never sent to/from the backend — same spirit as the side view's parallax skyline), depth-sorted with everything else.
- **Two real bugs found via screenshot, not code review:** the hospital's cross was drawn at a hardcoded `z=0.02` instead of the building's actual front-face depth (rendered as a stray sliver at the wrong position); the tree canopy's ellipse radius was passed in **metres** to a Phaser call expecting **pixels** (a sub-pixel, invisible canopy). Both fixed and re-verified with another screenshot.
- Fixed the Studio's `PlaybackToolbar` camera label, which hardcoded "Side View" even for iso traces (`StudioScreen` now passes `cameraLabel` from `trace.camera`).

### Third pass (same day): fold the classic 2D city into City Builder as a setting

User feedback: the original side-view `tiny_city_preview` challenge was still showing as its **own card**, next to the new isometric `city_builder` — two confusing "city" cards. Rather than merging them on the backend (which would have touched ~10 test files, golden designs, and preview-image conventions across `test_visual_playwright.py`/`goldens.py`/`test_challenge_pack.py`/etc. for a preset that already works correctly), this was a **frontend-only** fix: `tiny_city_preview` stays a real, fully-independent backend preset (untouched — same world, reward, scoring, tests), but `ScenarioWorldColumn` no longer renders it as its own card. Selecting **City Builder** now shows a **City View** toggle (Isometric / Classic Side View); toggling calls the same `handleSelectPreset` used by the card list, swapping the whole world/engine/reward bundle. The City Goal dropdown (reward_options) naturally hides itself under Classic Side View, since `tiny_city_preview` has none. Also generated a real in-engine preview screenshot for the City Builder card (`frontend/public/presets/city-builder.png`, replacing the generic custom-scenario fallback it had no image for) using the same Playwright-screenshot convention as every other preset card.

### Noted, not built (documented simplifications)

| Item | Why |
|------|-----|
| Connectivity is "within ~3-4m of a road's footprint," not real road-graph pathfinding. | A proxy, same spirit as the existing spacing/overlap proxies elsewhere in scoring — good enough for "is this near a street," cheap, deterministic. |
| No per-tile zoning grid — structures place freely, classified by `kind` alone. | Keeps the tool surface identical to every other challenge (`create_body` + `kind`); a real grid/parcel system is a bigger follow-up if wanted. |
| CityEngine has no rigid-body motion at all (every body is a static prop, even ones the agent marks non-static). | A city's structures don't fall over — deliberate, not a gap — but it does mean a hypothetical "car" or "pedestrian" kind has no real movement yet; `FrameBody.z`/`renderIsoFrame` support animated iso bodies in principle, just nothing produces them today. |
| `active_physics_zones` on the `city_grid` template is `0` (no physics zones, since there's no physics). | Gives that previously-unused field real meaning for once — see `remaining_gaps.md`'s note that it was otherwise decorative. |
| The original `tiny_city_preview` / `city_score` (side-view, pymunk2d) is unchanged and still a spacing/spread proxy (`L1` in `remaining_gaps.md`). | Out of scope for this pass — it's a different, already-shipped product surface; the new isometric family is additive, not a replacement. |
| No automated visual regression test for the iso renderer (the fixes this pass relied on ad hoc Playwright screenshots, not a committed test). | Worth adding as a `test_visual_playwright.py`-style golden screenshot once the visual language settles further — flagged rather than silently skipped. |

---

## 1. PyBullet 3D engine (the big one)

**Goal:** add a second physics engine behind the existing `EngineAdapter`
interface without touching the renderer contract — Pymunk2D stays the default,
PyBullet3D becomes a selectable option (the Setup screen already shows it as a
disabled "Coming Soon" chip).

**Why it's a clean swap:** the architecture was built for this. The renderer
consumes only `EpisodeTrace`, scoring derives only from the trace, and the engine
is reached through `EngineAdapter.simulate(design, world, duration) -> EpisodeTrace`.
So 3D is an additive adapter, *not* a rewrite — but the trace and renderer need a
third dimension.

**Plan (incremental, each step shippable):**

1. **Trace schema → 3D-capable.** `FrameBody` is `{x, y, angle}`; extend to an
   optional `z` and a quaternion/`euler` for 3D orientation, kept backward-compatible
   (2D traces omit them; the renderer treats missing `z` as 0). Bump `EpisodeTrace.version`.
   *Touch points:* `core/schemas/trace.py`, every `FrameBody(...)` construction.
2. **`engines/pybullet3d/` adapter.** New `Pybullet3DEngine(EngineAdapter)` with
   `name = "pybullet3d"`, a `builder.py` that maps `DesignSpec` bodies/joints to
   PyBullet rigid bodies and constraints, and a `simulate()` that records frames at
   the same `_TARGET_FPS` sub-sampling the 2D engine uses. Register it in
   `engines/__init__.py::get_engine`.
3. **Determinism.** Fix the PyBullet timestep and solver iterations; seed any
   randomness. Add it to the determinism tests.
4. **Validator + Setup.** Flip `pybullet3d` from `unsupported_engine` to allowed in
   `setup/validators.py`; enable the Setup chip. Keep Pymunk2D the default.
5. **Renderer.** The Phaser iso scene is 2.5D. Two options — (a) project 3D → iso
   (cheapest: use `x`, `y+z` projection, keep Phaser), or (b) a Three.js scene
   selected when `trace.engine == "pybullet3d"`. Option (a) ships first; (b) is a
   later visual upgrade. The renderer still consumes only the trace.
6. **Tooling.** Most build tools map directly; 3D adds a depth axis to `position`
   and new joint DOFs. Gate 3D-only tool args behind the engine.

**Risks:** PyBullet is a heavier native dep (CI install time, wheels per platform);
the iso renderer only fakes depth. Mitigate by keeping PyBullet an **optional**
dependency group (`uv sync --group engines-3d`) so the default install and the
one-command launch stay lean.

**Estimate:** multi-session. Steps 1–4 (backend + a flat-projected replay) are a
solid first PR; the Three.js renderer is a separate follow-up.

🔵 **Needs a product call** before starting: ship 3D with the cheap iso projection
first, or hold until a proper Three.js renderer is ready?

---

## 2. Review findings (post-MVP skim, 2026-06-11)

A read-through of the critical path (apply chokepoint, runner, orchestrator,
scoring, engine builder, API routes, WS, static serving, Studio flow). The flow is
sound end-to-end: **Setup → /setup/launch → run_id → /studio/:runId → WS events
drive every panel → trace fetched & replayed → exports**. No crash-class bugs found.

### Fixed in this pass 🟢

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| R1 | **Bug** (cosmetic) | `/favicon.svg` (and any static-root file) hit the SPA catch-all and returned `index.html`, so the favicon never loaded. | `spa_fallback` now serves a real file from the static root when one exists (path-traversal guarded), else `index.html`. Tested. |
| R2 | **Robustness** | `POST /api/setup/launch` launched *any* config without re-validating, so an invalid one (e.g. a `manual` provider) could bypass the UI's disabled button and fail only mid-run. | `/launch` now re-runs `validate_launch_config` and returns `422` with the validation detail unless state is `ready`. Tested. Completes the P2 manual-provider guard. |

### Documented, not changed (low risk / by design)

| # | Severity | Issue | Notes |
|---|----------|-------|-------|
| R3 | Low | **`icons.svg` is an unused leftover** (social-media sprite from a starter template); not referenced anywhere in `frontend/src`. | Dead ~KB asset. Safe to delete from `frontend/public/` and rebuild. Left for a focused cleanup. |
| R4 | Low | **Stale-closure on `agents`** in `StudioScreen`'s WS effect — handlers read `agents[0]?.id` from the array captured when the effect ran (deps `[runId]`), which is the initial `[]`. | Harmless today: every relevant event (`tool_call`/`design_update`/`score`/`trace_ready`) carries its own `agent_id`, so the fallback is never reached. Fragile if an event ever omits `agent_id` — prefer a ref or include `agents` in deps. |
| R5 | Low | **`_default_world()` uses `template="flat_ground"`**, which isn't a real template id (valid: `flat_arena`, `hill_path`, `island_cliff_small`, …). | Harmless — the template string is a label; the engine uses `world.gravity`/`map_size` which default correctly. Only on the demo `POST /api/runs` path. Tidy the label. |
| R6 | Low | **WS breaks on `error` before delivering the following `run_finished`** (`routes_ws.py` breaks on the `error` event). | Known (gap `L6`); the frontend `onclose` handler already leaves the "Building…" state, so the UI doesn't hang. |
| R7 | Low | **`_design_summary` reports beams/ramps/sensors as 0** though beams/ramps exist as `segment` bodies; `total_parts` is still correct. | Fixed later: beams/ramps derive from `by_kind`; sensors remain 0 until sensors exist. |
| R8 | Low | **`sorting_accuracy` denominator** (`parts_used − bins_count`) counts static non-bin bodies (e.g. ramps) as "items to sort". | Reward is a documented proxy; fine for the Sorter demo. Refine when real per-object classification lands. |

---

## 3. Other improvements worth doing (beyond `remaining_gaps.md`)

- **Skip double-scoring** (gap `L2`): `create_run_from_design` always computes a
  `default` score, then the runner re-scores with the named reward. Pass the reward
  through (or skip the baseline on the runner path).
- **`relay` / `sandbox` modes**: hidden in Setup and rejected by validation until
  they are implemented as distinct modes.
- **Real-LLM integration test**: a test against a mock HTTP server exercising
  `OpenAICompatibleProvider.complete()` timeouts/error wrapping (no live key needed).
- **Bundle size**: the JS bundle is ~1.6 MB (442 KB gzipped). Code-split Phaser to
  cut first-load if the Studio screen is lazy-loaded.

---

## 5. Honesty + reliability + challenge pack (2026-06-15)

Three workstreams toward an honest, reliable, differentiated MVP:

1. **Honesty/consistency.** Every tool declares a status (implemented / inspection
   / experimental); experimental tools are off by default and rejected (never a
   silent no-op). `set_density`/`set_gravity` implemented for real. Unenforced
   constraints (`energy_budget`, `material_budget`, `collision_safety`,
   `world_bounds`, `world.seed`) are badged "coming soon" in the UI.
2. **Real-LLM reliability.** Configurable generation timeout + retry/backoff (env),
   structured `LLMError` kinds (auth/rate_limit/server/timeout/malformed/empty),
   auth-vs-unreachable messaging, and a 16-test provider-contract suite over
   `httpx.MockTransport`. The Studio overlay shows the real failure reason.
3. **Challenge pack differentiation.** Per-challenge goals injected into scoring;
   distinct rewards — `bridge_transport` (goal zone + lean + stability),
   `crawl_locomotion` (forward motion + threshold), `sorting_accuracy` (true
   object-class→bin matching via ball color vs bin `accepts`, containment
   fallback), `city_score` (count + spread + nearest-neighbour spacing/livability).

**Still open in the challenge pack (larger follow-ups):** example "gold" designs
per challenge; Tiny City real zoning/roads/budget (currently a spacing/livability
proxy); world-template goal *geometry* (goal zones are scoring thresholds, not yet
rendered markers); a richer Sorter taxonomy beyond color classes.

## 7. End-to-end bug audit (2026-06-15)

Three parallel read-only audits (backend correctness, frontend, contracts) over the
recently-added features. Contracts were clean (no severe type-vs-emit drift). Fixed:

| Sev | Issue | Fix |
|-----|-------|-----|
| HIGH | `run_meta` grew unbounded and orphaned trace rows → history/leaderboard dead links once >1000 runs. | Prune `run_meta` in lockstep with `runs` on every write. |
| HIGH | `sorting_accuracy` counted static support beams as items (a perfect 3/3 sort showed 3/5, 60%). | Denominator now uses `sortable_items` = dynamic (non-static, non-bin) bodies. |
| MED | Demo/`POST /api/runs` runs (null challenge) polluted the global leaderboard. | Unfiltered leaderboard excludes `challenge IS NULL`. |
| MED | Cooperative `score` event omitted `diff` (single/competitive included it). | Emit `diff` (None) for shape parity. |
| MED | "Select All" tools enabled experimental tools (disabled, un-uncheckable, sent to launch). | Select All now skips experimental tools. |
| LOW | `_db_upsert_meta` f-string column interpolation (latent injection pattern). | Allowlist of permitted columns. |
| LOW | `reached_goal` wrong if a goal were placed behind the start. | Direction-aware goal check. |

**Left as documented (low/cosmetic):** historical replay leaves Design Summary /
Attempt History panels empty (best-effort, score + replay work); `HistoryScreen`
doesn't flash "Loading…" on a filter refetch; the `attempts_cap` field is emitted +
typed but unused; frontend `ToolDefinition` omits `compatible_challenges`/`input_schema`
(extra wire fields, harmless).

## 6. Iteration, visible caps, run history (2026-06-15)

- **Attempt diff (#4).** Each attempt computes a structured diff vs. the previous
  one (parts/joints deltas, added/removed/moved part ids, score delta, failures),
  feeds it into the next prompt's memory ("last change: added 2 parts; score +3.1"),
  and shows a "What Changed" panel in Studio. Cooperative attempts don't thread
  lineage, so their diff stays empty.
- **Visible caps (#5).** `run_started` now reports requested vs. effective attempt
  caps and the 60s sim cap; ChallengeBriefing shows "Attempts: 3 max (you set 50)"
  and "Sim cap: 60s" only when the cap bites.
- **Run history + leaderboard (#6).** A `run_meta` SQLite table (challenge, mode,
  reward, score, success, artifact dir, timestamp) + `GET /api/runs/history` and
  `GET /api/runs/leaderboard?challenge=…`. Survives restart. **Still open:** a
  frontend run-history / leaderboard view (the API is the foundation); optional
  `aiosqlite` async conversion; pruning `run_meta` (tiny rows, currently unbounded).

## 4. Deep audit (2026-06-15) — four-part review

A four-agent parallel review (backend correctness, frontend UX/polish, onboarding,
API contracts). Priority order applied: **bugs → polish → improvements**. No
crash-class bugs were found; the issues were silent failures, placeholder-as-real,
onboarding robustness, and a few backend correctness nits.

### Fixed 🟢 (all HIGH bugs across the stack)

| Area | Fix |
|------|-----|
| Setup | Launch failures now surface a banner with the backend's 422 detail (`client.ts` `ApiError` carries status + body). |
| Setup | Validation reachability tracked; TopBar pill shows Connected/Connecting/Server-offline instead of a hardcoded "System Online". No more eternal "Validating…". |
| Setup | Tools auto-seed race fixed: checked tools derive from `config.tools.enabled` (single source), mount seed unions, preset selection merges `required_tools`. |
| Studio | Viewport overlay for loading / error / disconnected (was a blank black canvas). |
| Studio | WS drop → distinct `disconnected` status ("Connection lost"), not a fake "Finished". |
| Studio | ChallengeBriefing shows real reward + constraints (new `run_started` payload); unified project-name fallback; tab title `frontend`→`AgentGymnasium`. |
| Onboarding | `serve` defaults to no-reload; friendly port-in-use message; browser opens only after `/api/health` is ready; `run.sh`/`run.ps1` re-check `uv` after install. |
| Backend | `max_motors` enforced; stability `0.0` on <2 frames; engine always records the final frame; SQLite `scores`/`designs` pruned with `runs`; `save_preset` name sanitized (path-traversal); cooperative prompt instructs exact-id references. |

### Deferred 🟡 / re-assessed

| Item | Why |
|------|-----|
| **Event-loop offload** (`asyncio.to_thread` for simulate/IO) | Breaks the Starlette TestClient WS harness; it's a responsiveness optimization, not a correctness bug. Revisit with an integration-test approach. |
| **Cooperative cross-agent joints** (audit called it "broken") | Re-assessed: the remap already preserves cross-agent ids, and the prompt now instructs exact-id use. Works with a cooperating LLM; the mock doesn't form them (mock limitation, not a bug). |
| **Polish (priority 2)** | 🟢 Done in the polish pass: wired the Fullscreen button (viewport `requestFullscreen`); removed the dead no-op links ("How it works"/"About connections"/"View Details") and made TopBar "Docs" a real link; removed the redundant challenge dropdown (kept the cards); removed the unused Tailwind import + plugin + dep (CSS bundle 7.9 kB → 0.56 kB); replaced `window.prompt`/`alert` Save Preset with an inline styled modal; added an `--on-accent` token; added a model picker (`<datalist>`) from the connection check's model list; added keyboard playback (Space play/pause, ←/→ frame step); fixed the stale-agents closure with a ref. **Still open:** small-width responsiveness and the "World Preview" placeholder thumbnail. |
| **Improvements (priority 3)** | 🟢 Done: `attempt_started`/`attempt_finished` now handled (in-flight attempt surfaces live); `name_design` implemented (schema gained a `name` field; sets `design.name` instead of a false-success no-op); LLM probe distinguishes auth failure (401/403 → "rejected the API key") from unreachable; `WorldConfig.active_physics_zones` default aligned to `WorldTemplate` (1). **Still open:** LLM probe still hits `/models` not `/chat/completions` (a passing probe can still fail at generation); `mutate_design`/`repair_invalid_design` remain no-ops; per-agent LLM settings forced shared; double scoring (`L2`); `Frame.events` on the wire but unused; the PyBullet 3D engine (§1). |
| **Responsiveness** | 🟢 Done: Setup collapses 3→2→1 columns; Studio stacks its rails below ~1100px. Still open: the "World Preview" placeholder thumbnail. |

## 8. Tiny City visual overhaul (2026-07-05)

User complaint: "when I saw agents build a city it should look more like a city." Root
cause was the renderer, not the challenge content — `TraceRenderer.ts` only knew how to
draw `ground`/`circle`/`segment`/box, so every building (however well laid out) rendered
as an identical gray rectangle.

### Fixed 🟢

| Area | Fix |
|------|-----|
| Schema | Added an optional cosmetic `kind` field (`house`/`tower`/`shop`/`tree`/`road`/`park`/`water`/`goal`) to `BodySpec`, `BodyMeta`, and `StaticProp` — purely visual, no physics effect. |
| Tools | `create_body` gained an optional `kind` enum arg (no new tool — `_tool_line`'s existing enum-surfacing auto-documents it to agents). |
| Engine | `_build_static`/`body_meta` emit `kind = spec.kind or shape` so untagged bodies (every pre-existing challenge) render exactly as before. |
| Renderer | `TraceRenderer.drawByKind` procedurally draws each kind (house w/ triangular roof, tower/shop w/ window grid, tree w/ trunk+canopy, road w/ dashed centerline, park/water fill, goal flag) — no assets, one code path shared by static props and dynamic bodies. Added a faint parallax skyline backdrop for `terrain: city`. |
| Renderer bug found in visual verification | `worldBounds()` inflated the **Y** bound by a wide prop's **width** (`Math.max(w,h)` isotropic radius) — a 28m-wide road zoomed the whole scene out to a tiny strip. Replaced with a proper rotated-AABB half-extent calc. Pre-existing bug, newly exposed because Tiny City is the first world with a wide flat prop. |
| Prompt | Fixed a real contradiction: the system prompt unconditionally required "at least one MOVABLE body or score zero," which fights a static-scene challenge. `build_system_prompt` gained `movable_body_required`, false for `city_score`. |
| World/challenge content | `tiny_city_block.yaml` now seeds a road + 2 roadside trees (visual backdrop, `created_by="world"`, excluded from scoring). `tiny_city_preview.yaml`'s objective asks for buildings + a road + a park/plaza + trees, not just 6 boxes in a row. |
| Scoring | `city_score` adds an infra-variety bonus (road/park/tree counts + building height variety), computed only from the agent's own bodies (world backdrop excluded) so agents are pushed toward a real mix, not just spread-out boxes. |
| Mock provider | `MockProvider.complete()` recognizes a city objective (via the embedded "Objective: …" text) and emits a 9-part scene (road, park, 2 houses, 2 towers, 1 shop, 2 trees) instead of one box — the no-LLM demo now actually looks like a city. |

Verified visually: generated a mock Tiny City run and screenshotted the Studio replay
(Playwright) before/after the `worldBounds` fix — confirmed recognizable houses (roofs),
towers (windows), and a road render correctly and fill the viewport properly.

### Noted, not changed

| Item | Why |
|------|-----|
| `city_score` is still a metrics proxy (L1 in `remaining_gaps.md`), just a better one — it doesn't verify visual correctness (e.g. overlapping props). |

### Follow-up polish pass (2026-07-05, same day)

Closed out the naming gap noted above and found a second, more consequential bug while
regenerating the Setup screen's preset preview images.

| Area | Fix |
|------|-----|
| Naming | `IsometricWorldView` → `WorldView`; `PlaybackToolbar`'s "CAMERA: Isometric" → "Side View" (matches what `TraceRenderer` actually draws). Deleted `frontend/src/phaser/iso.ts` — a real isometric-projection module that was never imported anywhere (dead code left over from an abandoned earlier direction). |
| `kind` coverage | `bridge_builder.yaml` / `crawl_challenge.yaml` goal markers tagged `kind: goal` so they render as a flag instead of a plain green rectangle. |
| **Preset preview images** | All 5 Setup-screen preset cards (`bridge_builder`, `crawl_challenge`, `sorter`, `tiny_city_preview`, `custom`) showed polished 3D isometric mockup art (fountain, streetlights, low-poly robots) with **zero visual relationship** to the actual 2D side-view renderer. This is almost certainly the real source of "it should look more like a city" — the promo image promised a 3D isometric city, the delivered result was a simple 2D scene. Replaced all 5 with real screenshots of the actual Studio renderer (Playwright, mock provider, one generated run per challenge), confirmed with the user first since overwriting curated art is a one-way product call. New images are also ~2-6 KB each vs. the old ones' much larger file size. Added `data-hide-for-capture` to `WorldView`'s camera-control button cluster so future preview regeneration can hide UI chrome from the shot. |
| **Mock provider ground-tunneling bug** | Found while the "custom scenario" screenshot came out as an empty grid: the mock's placeholder body (`create_body`, no `position` → schema default `[0, 0]`) spawns fully embedded in the paper-thin (`radius=0.1`) ground segment and **tunnels through it forever** (`y -> -4412` by t=30s) instead of resting on top. This silently affected every non-city mock demo (bridge/crawl/sorter each had an invisible `b1` falling forever off-screen). Fixed by giving the mock's placeholder an explicit `position: [0, 3]` so it drops onto the ground normally. The underlying engine robustness gap (any body spawned embedded in the ground can tunnel through) is logged as `E5` in `remaining_gaps.md` — not fully fixed, since a general solution needs either a thicker ground collider or spawn-position validation. |

Verified visually again: screenshotted the full Setup screen with the new thumbnails in
place at real size (76×64, `object-fit: cover`) — all five read clearly at that scale.

## 9. Export, visual CI, docs, and bundle split (2026-07-05)

Closed out the non-visual-realism parts of the follow-up plan:

| Area | Fix |
|------|-----|
| **Studio video export** | `ReplayTimeline` now has an `Export WebM` action. It records the live Phaser canvas with browser-native `MediaRecorder`, downloads a `.webm`, and avoids a server encoder or new npm dependency. |
| **Visual test artifacts** | Added opt-in Playwright screenshot checks for Setup, all five challenge preview thumbnails, and a Studio replay. CI runs them in a dedicated job and uploads `visual-artifacts/` screenshots. |
| **Provider tests** | Added an explicit 429/rate-limit retry contract test and opt-in live OpenAI smoke tests behind `AGENTARIUM_LIVE_OPENAI_TESTS=1`; completion smoke is additionally gated by `AGENTARIUM_LIVE_OPENAI_MODEL`. |
| **Docs structure** | Moved original planning/build docs under `docs/archive/`; top-level docs are now the living set: `ARCHITECTURE.md`, `remaining_gaps.md`, `IMPROVEMENTS.md`, and examples. |
| **Bundle split** | Lazy-loaded `/studio/:runId`, so the Phaser-heavy Studio route is no longer part of the initial Setup bundle. |

Still deferred by product choice: visual-realism/content upgrades to challenge
assets and primitives, plus GIF/MP4 export beyond browser-native WebM.

## 10. Updated visual realism plan (2026-07-05)

This updates the attached "setup -> validated tools -> physical attempt -> trace
-> score" plan against the current repo. The core gap is still real, but narrower:
Tiny City now has semantic `kind` drawing, challenge/world YAML dressing, real
Setup thumbnails, WebM export, visual screenshots in CI, and lazy Studio loading.
The remaining weakness is consistency across every challenge and making interim
build states first-class.

### Fixed now

| Area | Fix |
|------|-----|
| Mock challenge demos | `MockProvider` now emits challenge-specific builds: Bridge uses beams, Crawl uses legs/joints/motors, Sorter uses bins/ramps, City uses roads/buildings/trees. The generic fallback remains one visible crate using only `create_body` + `run_simulation`. |
| Mock routing bug | Challenge selection now comes from the per-attempt user prompt, not the full system prompt. That avoids false positives from generic examples in the prompt. |
| Tests | Runner tests now assert the mock actually exercises the relevant tools and semantic body kinds for Bridge, Crawl, Sorter, and City. |

### Strong plan from here

1. **DesignSnapshot as the missing product primitive.** Add a tiny serializable
   `DesignSnapshot` record per attempt: attempt id, score, tool-call statuses,
   body/joint counts, added/removed/moved ids, optional screenshot path, and
   trace id. Start as derived metadata in the run store, not a new engine feature.
2. **Build timeline, not only replay timeline.** Studio should show snapshots as
   a sequence: prompt submitted -> tools accepted/rejected -> design changed ->
   simulation ready -> score. Reuse the existing attempt diff and screenshot
   capture; no new renderer required.
3. **Golden challenge traces.** For each preset, keep one deterministic mock run
   fixture and assert meaningful features: Bridge has spanning beams, Crawl has
   motorized joints, Sorter has matching bin metadata, City has roads/parks/trees.
   CI should upload the associated screenshots/video artifact on failure.
4. **Renderer polish by semantic kind.** Extend the existing `kind` renderer for
   the non-city challenge parts before adding any new engine: deck/support/beam,
   leg/foot/body, bin/ball/chute, goal/finish marker. This is the cheapest path
   to "looks like the task" without promising 3D.
5. **World dressing stays YAML-first.** Add small `static_bodies` context to
   non-city worlds only where it clarifies the task: bridge cliffs/goal marker,
   crawler start/finish hints, sorter table/bin zones. Keep `created_by="world"`
   so scoring remains honest.
6. **More realistic tests, minimal code.** Keep Playwright opt-in visual tests,
   but make them compare structured scene facts plus screenshot artifacts rather
   than brittle pixel diffs. Use the existing `visual-artifacts/` path and
   browser-native WebM export.
7. **Real LLM confidence.** Keep live OpenAI smoke tests opt-in. Add one local
   mock-HTTP completion test for malformed JSON, empty choices, timeout, and
   retry behavior so CI covers provider behavior without a real key.
8. **Docs/scripts cleanup stays conservative.** Keep one launch path per OS
   (`run.ps1`, `run.sh`, `Makefile serve`) and one living roadmap. Archive old
   planning docs; do not let duplicate "truth" files accumulate again.

This is intentionally smaller than a 3D rewrite: it uses the existing schemas,
runner events, attempt diffs, `kind` labels, Playwright screenshots, and browser
recording path. The larger PyBullet/Three.js work remains a separate product
decision.

## 11. Build Timeline, ground-tunneling fix, and scoring/test guardrails (2026-07-05)

Closes out §10's "strong plan" items 1–2 (`DesignSnapshot` + Build Timeline), plus
a real correctness bug found along the way and two lock-in guardrails.

### Fixed 🟢

| Area | Fix |
|------|-----|
| **Ground-tunneling bug** | `apply.py::_clamp_to_ground` clamps a new DYNAMIC body's spawn position to rest at/above the ground surface, for `create_body` and `add_ball`. Previously a body spawned embedded in the ground (e.g. the schema-default `position: [0, 0]`) could tunnel through it forever (`y -> -4412` by t=30s) — a real bug that could silently zero-score a genuine LLM agent's attempt with no error surfaced. Static bodies are untouched (terrain is allowed to be embedded on purpose, e.g. a hill segment). |
| **Challenge-identity guardrail** | `test_runner.py::test_challenge_kinds_do_not_leak_across_scenarios` asserts each challenge's mock-built kind set is *exactly* right and disjoint from every other challenge's (Bridge={beam}, Crawl={leg}, Sorter={bin,ramp}, City={road,park,house,tower,shop,tree}). Locks in the per-scenario mock work from §8/§10 against a future regression where every scenario starts looking the same. |
| **`city_score` overlap penalty** | Added `overlap_total` (sum of horizontal footprint overlaps between the agent's own bodies) to `compute_metrics`, and `city_score` now subtracts `overlap_total * 5.0`. Two buildings stacked at the same x-position — a bad, unreadable layout — now score worse than the same buildings well-spaced. Closes the last shallow spot in city scoring (L1 in `remaining_gaps.md`). |
| **`DesignSnapshot` + Build Timeline** (§10 plan items 1–2) | `AttemptResult` gained durable `BuildStepRecord` rows plus compatibility `snapshots`: one un-simulated, single-frame `EpisodeTrace`-shaped trace per tool call, built by reusing the real engine's `simulate(design, world, duration_seconds=0.0)` (zero physics steps = bodies stay exactly where placed). The orchestrator streams labelled `design_snapshot` events with tool/status/mutation metadata, and the runner persists `runs/{trace_run_id}/build_snapshots.json`. Studio has a **Build / Physics** toggle for live and historical traces and labels no-op/rejected/repair steps. |
| **Opt-in visual smoke tests** | `test_visual_smoke.py`: for each of the 4 challenges, runs a real mock attempt, starts the live FastAPI app in-process on an ephemeral port, and confirms the Phaser canvas actually mounts with a non-zero size at `/studio/{run_id}` in a real Chromium browser. Skipped by default (`AGENTARIUM_RUN_UI_SMOKE=1` to run) so `uv run pytest` stays fast/hermetic — this catches "the page crashed / canvas never mounted," not pixel-level regressions (that's what the kind-leak guardrail above is for). |

### Noted, not changed

| Item | Why |
|------|-----|
| Repair-pass additions now append a synthetic `repair_pass` / "Auto-repair" Build Timeline step when they mutate the design. The original rejected call stays visible. |
| `overlap_total` only checks horizontal (x-axis) footprint overlap, matching this being a side-view scene — not a true 2D top-down collision check. Sufficient for "buildings stacked on top of each other," not sub-pixel precision. |

## 12. Evaluation and embodiment foundation (2026-07-26)

The repo now has an end-to-end foundation for comparing LLM agents and moving
the same control discipline into physical test fixtures.

| Area | Shipped |
| --- | --- |
| Model runtime | Typed `ModelRequest` / `ModelResult` / `ModelInteraction`, native OpenAI-compatible tools, prompt-JSON fallback, seeds, usage, retries, request id, finish reason, and latency. |
| Iteration | Real providers can observe bounded simulation score/state/failures and revise for multiple turns inside an attempt. |
| Experiments | Durable paired model × seed × repeat matrices, aggregate statistics, pairwise score deltas, cancellation, CLI sweep, replay links, and side-by-side Compare. |
| Transparency | Studio Model Inspector and History metadata for provider/model/seed/tokens/latency/protocol/benchmark hash. |
| Constraints | Material/bounds/tool budgets are enforced before mutation; strict exact-placement collision safety is live; motor effort is measured and can fail the energy budget; selected output artifacts are generated. |
| Modes | Relay and sandbox join single/competitive/cooperative with real routing and tests. |
| Embodiment | Typed adapter contract, deterministic mock rover, env-configured ROS 2 HTTP gateway, explicit arming tokens, operator key for real devices, geofence/speed/duration checks, watchdog, latched E-stop, audit stream, and bounded scored LLM episodes. |
| Baseline | Fixed Bridge/Crawl deterministic physics regressions, redacted persisted credentials, frontend lint in CI, and React compiler lint failures. |

The honest next steps—reference ROS 2 gateway package, certified deployment
controls, physical reset fixtures, stronger statistical methods, 3D/digital
twin support, and worker-process execution—are maintained in
[`remaining_gaps.md`](remaining_gaps.md).

## 13. Unified visual system and challenge overhaul (2026-07-26)

The renderer is now a shared stylized technical-diorama system instead of a
collection of mostly flat challenge primitives.

| Area | Shipped |
| --- | --- |
| Trace contract | `EpisodeTrace` v3 adds backwards-compatible `visual_style`, `visual_seed`, per-object `VisualSpec`, attribution, and renderer-facing joint metadata. Materials/variants are deterministic from world seed + object id. |
| Visual events | Pymunk traces emit creation, joint/motor, first-contact, high-impulse stress, goal-entry, correct/incorrect sort, and fall events. Zero-duration Build Timeline snapshots deliberately keep empty event lists. |
| Themes | Realistic diorama, playful, blueprint, and neon-lab themes now change actual sky, terrain, grid, material, outline, hazard, accent, and shadow rendering. The Setup `visual_style` control is no longer decorative. |
| Renderer layers | Added screen-fixed atmosphere, terrain dressing, semantic props, dynamic contact shadows, visible joints/motors, motion/effect overlays, labels, and separate Beauty/Engineering modes. Reduced-motion preference disables ambient movement. |
| City | Modular façades, front/right windows, deterministic lit states, doors, floor bands, rooftop equipment, factory doors/signage, detailed parks/plazas/fountains, moving decorative traffic, expanded street furniture, and live city-pulse metrics. |
| Bridge | Grass-capped stratified cliffs, animated water detail, material-aware riveted/wooden members, circular wooden cargo, visible anchors, stress/contact effects, and clearer goal feedback. |
| Crawl | Articulated semantic torso/legs, rendered pivots and active motors, terrain cross-sections, contact shadows/trails, and corrected camera fitting that ignores the arena’s collision-floor extent. |
| Sorter | Factory skyline, roller conveyor, open labeled bins, patterned target pads, distinct ball markings, chutes, and correct/incorrect routing pulses. |
| Physical Lab | Replaced the floating square with a calibrated SVG instrument: axes/grid, geofence state, target vector, pose trail, robot footprint/heading, front-range cone, localization uncertainty, velocity, battery, and pose readout. |
| Visual catalog | Added `/visuals` with deterministic City/Bridge/Crawl/Sorter reference scenes and live theme switching, plus a top-level navigation entry. |
| QA and assets | Browser tests capture all four theme outputs and assert their rendered pixels differ, cover the Physical Lab instrument, and retain before/after golden challenge captures. Setup thumbnails were regenerated from the reviewed, chrome-free engine scenes. |
| Performance/accessibility | Ground tiling, ambience, labels, traffic, and street furniture are bounded; engineering labels reduce on dense traces; color is reinforced with shapes/patterns; reduced-motion and high-contrast blueprint modes are supported. |

Honest boundary: this is polished procedural 2.5D. A true 3D renderer and
simulation-driven city actors remain separate roadmap decisions rather than
being implied by decorative motion.
