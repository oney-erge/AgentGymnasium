# AgentGymnasium — Challenge Overhaul & Self‑Eval Plan

**Status: all phases below (1–6) implemented and merged to this branch.** See
`docs/remaining_gaps.md` (E6–E11) for the itemized fixes and what's still deferred
(gait smoothness, a couple of cosmetic zoom/kind-palette gaps). This doc is kept as the
design record; treat `remaining_gaps.md` as the live status source.

Goal: make the four agent challenges (Bridge, Crawl, Sorter, City) actually *look like* and
*test* what they claim, score against real physical outcomes, fix the OpenAI model dropdown,
and stand up a screenshot **self‑evaluation loop** so Claude can launch a challenge, look at
the result, and judge it without the user in the loop.

Scope note: this is a 2D / 2.5D pass on the existing Pymunk2D engine. It deliberately does
**not** wait on the PyBullet3D epic (`docs/IMPROVEMENTS.md`). Every change respects the
architecture invariants in `CLAUDE.md` (agents emit validated tool calls only; renderer
consumes `EpisodeTrace` only; scoring derives from the trace; worlds are templates).

---

## 0. Root‑cause findings (why it looks wrong today)

These were confirmed by reading the code and the shipped preview PNGs.

| # | Finding | Evidence | Consequence |
|---|---------|----------|-------------|
| R1 | **A single continuous static ground segment spans the whole map at y=0** for *every* world. | `backend/agentarium/engines/pymunk2d/builder.py:139‑147` (`pymunk.Segment((-map_width,0),(map_width,0))`). | No challenge can have a real gap/pit/chasm. The Bridge "gap" is empty air above a solid invisible floor — the ball can never fall in, so a bridge is never physically required (at best a curb‑climb). |
| R2 | **The renderer paints one continuous ground band** from y=0 down, full width. | `frontend/src/phaser/TraceRenderer.ts:230 drawGround`. | Even if physics had a chasm, the UI would hide it. Bridge/pit challenges can't read visually. |
| R3 | **Scores are metric proxies, only loosely tied to the physical goal.** | `services/scoring_service.py` — `city_score` is a layout heuristic; bridge/crawl read "furthest‑travelling dynamic body"; no "fell into chasm", no deck‑deflection, no per‑ball correct‑bin certainty when bins are unlabeled. | An attempt can score without looking right; the number doesn't match what the eye sees. |
| R4 | **World scaffolds are thin gray primitives with tiny/again‑gray goal markers.** | `worlds/templates/*.yaml`, `challenges/*.yaml`; goal is a 0.4‑wide box, rendered as a faint ring/flag (`props.ts drawGoal`). | Nothing reads as a cliff, ravine, hopper, finish line, or labeled bin. See `frontend/public/presets/bridge-builder.png`. |
| R5 | **The OpenAI `/models` list is returned raw, unfiltered.** | `agents/openai_compatible.py:170‑183` returns every `id` from `/v1/models`. | The model dropdown shows embeddings, tts, whisper, dall‑e, moderation, realtime — none usable for tool‑calling generation. |
| R6 | **No closed self‑eval loop.** The Playwright harness screenshots the Setup screen and one *mock* run's Studio, but never drives a *recognizable* design per challenge to its end‑state. | `backend/tests/test_visual_playwright.py`; `mock_provider` builds a single placeholder body. | Claude can't currently look at "a finished Bridge attempt" and say "that's not a bridge." |

**R1 is the keystone.** Fix the ground first; the rest of the visual/scoring work depends on it.

---

## Phase 1 — Terrain with real gaps (unblocks everything)

Make the ground **per‑world**, not a universal slab, so a world can carve a chasm/pit and
declare a lethal zone. Keep the current behavior as the default (flat worlds unaffected).

1. **Engine (`engines/pymunk2d/builder.py`)** — replace the single full‑width ground segment
   with a **list of ground spans** derived from the world template. New optional world field
   `ground_spans: [[x0, x1], ...]` (metres). When absent, default to one full‑width span
   (100% backward compatible). Each listed span becomes its own `pymunk.Segment`; the ranges
   *between* spans are open air (the chasm). Add an optional `kill_y` (world floor of the
   ravine) used by scoring, not physics.
   - Add a test in `backend/tests/` asserting a body dropped over a gap keeps falling past
     y=0 (no phantom floor) while a body over a span rests on it. Keep sim ≤ 2s, mock only.
2. **World schema (`core/schemas/…world`)** — add `ground_spans` and `kill_y` (both optional).
   Mirror in any Pydantic world model and the world YAML loader.
3. **Renderer (`TraceRenderer.ts drawGround`)** — draw ground **only across the world's
   `ground_spans`**, leaving the chasm as sky, and paint a **water/lava band + hazard hatch**
   in the gap between `kill_y` and 0. The trace must carry `ground_spans`/`kill_y` (extend the
   trace payload; renderer stays trace‑only per invariant #2). Add a `chasm`/`water` prop.
4. Frontend `api/types.ts` stays in sync with the new trace fields (invariant #3).

Acceptance: a Bridge world renders as two cliffs with a visible ravine + water between them;
a ball placed over the ravine falls below `kill_y` instead of resting on invisible ground.

---

## Phase 2 — Redesign the four challenges

Each challenge gets: (a) a world that reads as its theme, (b) clearer start/goal props,
(c) a reward tied to the *physical* outcome, (d) a "golden" scripted design used by the
self‑eval loop (Phase 5) to prove the happy path is achievable and looks right.

### 2A. Bridge Builder — *the worst offender*
- **World `island_cliff_small`**: two solid cliffs (left high @ ~y6, right goal cliff), a real
  ravine between them via `ground_spans`, `kill_y` at the ravine floor, water in the gap, a
  bold **goal flag/platform** on the right (kind `goal`, larger, colored).
- **Start**: a `kind: ball`/`crate` that rolls off the left cliff toward the gap.
- **Reward `bridge_transport`** (rewrite): reward = crate reaching goal x on the right cliff
  **and staying above `kill_y`**; hard **fail + `fell_into_chasm` event** if crate y < `kill_y`;
  reward span **structural integrity** (bonus for low max deck deflection of the agent's beams
  over the gap; penalty if any agent beam sags below the cliff‑top line = collapse). Keep the
  parts‑efficiency penalty. Success = reached goal AND no chasm fall AND deck didn't collapse.
- **Objective text + `recommended_tools`**: nudge trusses (`add_beam` + `add_joint` diagonals).
- Consider a `max_parts` that forces a truss rather than a solid wall of blocks.

### 2B. Sorter
- **World `sorting_table`**: a **hopper/dispenser** up top that drops a stream of colored balls,
  a central splitter, and **two labeled target bins** pre‑drawn as colored zones (red / blue),
  each a `kind: bin` with `accepts` set and a color‑matched label band. More balls (e.g. 4–6,
  mixed) so accuracy is meaningful.
- **Reward `sorting_accuracy`**: already does class‑match when bins are labeled — keep, but make
  the seeded target bins labeled by default (so it's always the strict path, not containment),
  and add a small penalty for balls that leave the table (fell off, unsorted).
- Renderer: give `bin` a clearer open‑top container look + accept‑color rim (`props.ts drawBin`).

### 2C. Crawl Challenge
- **World `hill_path`**: a readable **start pad → uneven terrain (bumps/steps via ground_spans
  heights or segment props) → finish line** with a bold checkered/`goal` finish and a distance
  ruler. Torso "seed" clearly rendered as a creature body.
- **Reward `crawl_locomotion`**: keep net forward distance + threshold cross, but add a **gait
  bonus** (rewards sustained forward velocity / periodic leg motion via motor usage in the
  trace) and a fall penalty, so a creature that actually walks beats one that tips forward once.
- Prompt/scaffold: strengthen the objective + `recommended_tools` so a real jointed+motored
  creature is the obvious build; ensure `add_motor` torque actually moves the seed.

### 2D. Tiny City ("not super bad, needs enhancement")
- **World `tiny_city_block`**: add a subtle **street grid / lot markers** so "a city block" is
  legible and spacing has meaning.
- **Reward `city_score`**: keep the infra‑variety + spacing + overlap terms, but add
  (i) a **road‑connectivity / frontage** term (buildings should sit along the road, not float),
  (ii) a **skyline‑variety** term already partly present (height variety) — weight it, and
  (iii) cap the raw parts term so "20 identical boxes" can't out‑score a real mixed block.
  Success should require the *mix* (≥1 road, ≥1 park, ≥2 trees, ≥6 buildings, spaced), not
  just part count.
- Renderer: minor polish to `house`/`tower`/`park` so a block reads as a skyline.

Each sub‑phase updates `docs/remaining_gaps.md` (L1 city proxy, etc.) and adds/updates tests
in `backend/tests/` (mock provider, short sims). **Backend behavior change ⇒ test, per CLAUDE.md.**

---

## Phase 3 — Fix the model dropdown (R5)

- In `agents/openai_compatible.py::test_connection`, **filter the `/models` list to
  chat/generation‑capable ids** before returning. Heuristic (no new deps, stdlib only):
  drop ids whose family matches a denylist — `embedding`, `tts`, `whisper`, `audio`,
  `dall-e`, `image`, `moderation`, `realtime`, `search`, `similarity`, `edit`, `rerank`,
  `-vision-` only‑embeddings, etc. Keep everything else (so local/unknown chat models on
  LocalDeploy and OpenAI‑compatible servers still appear).
- Keep it provider‑agnostic and conservative: unknown → keep (don't hide a user's real model),
  known‑non‑chat → drop. Optionally sort chat‑likely families (gpt‑, o1/o3/o4, qwen, llama,
  mistral, deepseek, gemma) to the top.
- Add a unit test feeding a realistic OpenAI `/models` payload and asserting embeddings/tts/etc.
  are filtered and `gpt-4o-mini` survives. (`backend/tests/test_agents_api.py` or provider test.)
- Update `docs/remaining_gaps.md` with the fix.

---

## Phase 4 — Regenerate stale preset preview images (R4)

The card thumbnails in `frontend/public/presets/*.png` (and the committed copies under
`backend/agentarium/static/presets/`) are old renders that no longer match the redesigned
worlds. Regenerate them from the **golden designs** via the self‑eval harness (Phase 5) so the
Setup cards show the real, improved scenes, and commit the regenerated PNGs.

---

## Phase 5 — The self‑evaluation loop (R6) — *build this early, use it throughout*

The point: Claude launches a challenge, drives it to a recognizable end‑state, screenshots it,
and **reads the PNG back with vision** to judge "does this look like a bridge / city / sorter?"
— then iterates. Build on the existing Playwright harness rather than inventing a new one.

1. **Golden designs.** For each challenge, add a scripted "known‑good" `DesignSpec` (a fixture,
   e.g. `backend/tests/goldens/<challenge>.json` or a small Python builder) that represents a
   correct solution (a real truss bridge, a sorted run, a walking creature, a mixed city block).
   These feed both scoring tests and the screenshot harness, and are the source for Phase 4.
2. **Headless render + final‑frame capture.** Extend `test_visual_playwright.py` (or a sibling
   `scripts/self_eval.py`) to, per challenge: create a run from the golden design via the
   existing `POST /api/runs` path, open `/studio/<run_id>`, **seek the replay to the last frame**,
   and screenshot the canvas to `visual-artifacts/<challenge>-final.png`. Also capture t=0 so a
   before/after pair shows the crate crossing, balls in bins, creature at the line, block built.
3. **Self‑assessment step.** A thin runner (Make target / `scripts/self_eval.sh`) that: launches
   the server in‑process, runs the capture, and drops PNGs in a known dir. Claude then `Read`s
   each PNG and writes a short verdict ("bridge spans the ravine ✅ / goal flag readable ✅ /
   deck sags ❌"). This closes the loop the user asked for.
4. **Make it cheap to run.** One command (documented in `CLAUDE.md` Commands), gated so normal
   `pytest` stays fast (reuse `AGENTARIUM_VISUAL_TESTS=1`). Chromium is preinstalled
   (`/opt/pw-browsers`), so no download.

Acceptance: running the loop produces `*-final.png` for all four challenges that visibly read
as their theme, and Claude's written verdict matches.

---

## Phase 6 — Sequencing, gates, tracking

**Order:** Phase 1 (ground) → Phase 5 scaffolding (harness + golden stubs) → Phase 2 per
challenge (Bridge first, it's the worst) with the harness proving each → Phase 3 (dropdown,
independent, can land anytime) → Phase 4 (regenerate previews, last) .

**Definition of done (every change), per `CLAUDE.md`:**
1. `uv run ruff check .` clean.
2. `uv run pytest` passes (new/updated tests for each backend behavior change).
3. `cd frontend && npm run build` compiles when frontend changed; **commit the regenerated
   `backend/agentarium/static/` bundle in the same change.**
4. For visual work: the Phase‑5 self‑eval screenshots reviewed and judged acceptable.

**Docs to keep current in the same commits:** `docs/remaining_gaps.md` (L1, and new rows for
ground/chasm, model filter, self‑eval), `docs/IMPROVEMENTS.md` if scoring semantics shift.

**Branch/workflow:** work on `claude/agent-challenges-plan-h14y69`; commit per phase with the
session URL line; no PR unless asked.

---

## Risks / open questions

- **Trace payload growth:** carrying `ground_spans`/`kill_y` into the trace is required for the
  renderer (invariant #2) — small, but touches `schemas/trace`, the engine emit, and `api/types.ts`.
- **Deck‑deflection scoring** needs per‑part trace positions over time; verify beams are tracked
  as bodies in the trace (they are — beams are `segment` bodies) before relying on deflection.
- **Backward compat:** existing saved runs/traces without `ground_spans` must still render (treat
  missing as one full‑width span) — keep the default.
- **Motor efficacy for Crawl:** confirm `add_motor` produces enough torque to move the seed before
  tuning the gait reward, else the challenge stays unwinnable regardless of scoring.
- **Preview regen** must run after the worlds are final, or the thumbnails drift again.
</content>
</invoke>
