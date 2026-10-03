"""Scoring service: derive metrics from a trace and apply a named reward.

The pipeline is:

1. ``compute_metrics`` turns an :class:`EpisodeTrace` (plus the
   :class:`DesignSpec`) into a flat ``dict[str, float]`` of deterministic
   metrics.
2. A named reward function in :data:`REWARDS` maps that metrics dict to a
   ``(score_total, success, summary)`` tuple.
3. ``score_attempt`` ties the two together and produces a
   :class:`ScoreCard`.

All math is defensive: empty frames, missing bodies and designs with no
dynamic bodies must never raise.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from agentgymnasium.core.schemas.design import WORLD_AUTHOR, DesignSpec
from agentgymnasium.core.schemas.score import ScoreCard
from agentgymnasium.core.schemas.trace import EpisodeTrace

# y position (in world units) below which the primary body is considered to
# have fallen off / collapsed below the ground line.
_FALL_Y_THRESHOLD = -0.5


def _dynamic_bodies(design: DesignSpec) -> list[str]:
    """Ids of bodies that can actually move (non-static)."""
    return [b.id for b in design.bodies if not b.static]


def _agent_bodies(design: DesignSpec) -> list:
    """Bodies the agent built — excludes seeded world/terrain/task parts.

    Effort metrics (part count, city layout spread/spacing) must credit only what
    the agent placed, not the crate/cliffs/goal markers seeded by the challenge.
    """
    return [b for b in design.bodies if b.created_by != WORLD_AUTHOR]


def _primary_body_id(trace: EpisodeTrace, design: DesignSpec) -> str | None:
    """Pick the body whose horizontal travel we treat as "the result".

    Rule: among dynamic bodies present in the trace, choose the one that
    travelled the furthest in x (first vs last frame). Falls back to the
    first dynamic body, then the first body present in the trace.
    """
    if not trace.frames:
        return None

    first = trace.frames[0].bodies
    last = trace.frames[-1].bodies
    dynamic = [bid for bid in _dynamic_bodies(design) if bid in first and bid in last]

    if dynamic:
        return max(dynamic, key=lambda bid: abs(last[bid].x - first[bid].x))

    # No dynamic bodies known from the design; use anything in the trace.
    candidates = [bid for bid in first if bid in last]
    if candidates:
        return max(candidates, key=lambda bid: abs(last[bid].x - first[bid].x))
    return None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_metrics(trace: EpisodeTrace, design: DesignSpec) -> dict[str, float]:
    """Derive a flat metrics dict from ``trace`` and ``design``.

    Always returns floats and never raises on empty / short traces.

    Energy proxy: total path length travelled by all dynamic bodies summed
    across consecutive frames (Manhattan distance per step). This is a
    deterministic, monotonic stand-in for "effort expended".
    """
    # Part count credits only agent-built bodies (excludes seeded world/terrain).
    agent_bodies = _agent_bodies(design)
    parts_used = float(len(agent_bodies))
    joints = float(len(design.joints))

    bins = design.metadata.get("bins", [])
    challenge = design.metadata.get("challenge", {})
    metrics: dict[str, float] = {
        "parts_used": parts_used,
        "joints": joints,
        "distance_m": 0.0,
        "max_distance_m": 0.0,
        "falls": 0.0,
        "stability": 1.0,
        "energy": 0.0,
        "duration_s": 0.0,
        "spread_area": 0.0,
        "bins_count": float(len(bins)),
        "bins_in_target": 0.0,
        "bins_correct": 0.0,
        # True count of items to sort = dynamic (non-static) bodies; bins and
        # static support beams are static and correctly excluded.
        "sortable_items": float(len(_dynamic_bodies(design))),
        # 1.0 when at least one bin declares an accepted class (matching intended).
        "bins_matchable": 1.0 if any(b.get("accepts") for b in bins) else 0.0,
        "reached_goal": 0.0,
        "goal_progress": 0.0,
        "crossed_threshold": 0.0,
        "min_spacing": 0.0,
        "avg_spacing": 0.0,
        "road_count": 0.0,
        "park_count": 0.0,
        "tree_count": 0.0,
        "building_count": 0.0,
        "height_variety": 0.0,
        "overlap_total": 0.0,
    }

    frames = trace.frames
    if not frames:
        # No simulation data: stability is meaningless, report 0.
        metrics["stability"] = 0.0
        return metrics

    metrics["duration_s"] = float(frames[-1].t)

    end_bodies = frames[-1].bodies

    # --- spread_area + livability spacing of the AGENT's placed layout ----------
    # Computed from where the agent placed structures (design positions), so a
    # city scores its intended layout whether the structures are static or fall,
    # and seeded world/terrain parts don't distort it.
    layout = [
        (b.position[0], b.position[1])
        for b in agent_bodies
        if len(b.position) >= 2
    ]
    if len(layout) >= 2:
        xs = [p[0] for p in layout]
        ys = [p[1] for p in layout]
        metrics["spread_area"] = max(0.0, (max(xs) - min(xs)) * (max(ys) - min(ys)))
        # Nearest-neighbour spacing: a livability proxy (well-spaced > clumped).
        nearest = []
        for i, (xi, yi) in enumerate(layout):
            dists = [
                math.hypot(xi - xj, yi - yj) for j, (xj, yj) in enumerate(layout) if j != i
            ]
            if dists:
                nearest.append(min(dists))
        if nearest:
            metrics["min_spacing"] = min(nearest)
            metrics["avg_spacing"] = sum(nearest) / len(nearest)

    # --- city kind variety: did the agent build infra, not just buildings? ------
    # Counted from the agent's OWN bodies only (seeded world backdrop, e.g. the
    # world template's road/trees, is excluded — this credits agent effort).
    kind_counts: dict[str, int] = {}
    for b in agent_bodies:
        if b.kind:
            kind_counts[b.kind] = kind_counts.get(b.kind, 0) + 1
    metrics["road_count"] = float(kind_counts.get("road", 0))
    metrics["park_count"] = float(kind_counts.get("park", 0) + kind_counts.get("plaza", 0))
    metrics["tree_count"] = float(kind_counts.get("tree", 0))
    buildings = [
        b
        for b in agent_bodies
        if b.static and len(b.size) >= 2 and b.kind in (None, "house", "tower", "shop")
    ]
    metrics["building_count"] = float(len(buildings))
    building_heights = [b.size[1] for b in buildings]
    if len(building_heights) >= 2:
        metrics["height_variety"] = max(building_heights) - min(building_heights)

    # --- overlap: BUILDING footprints that overlap each other --------------------
    # A side-view scene reads badly when two "buildings" occupy the same x-range
    # (they visually stack/intersect instead of forming a readable street). Only
    # buildings are checked — a road/park/tree is *supposed* to run along the
    # whole block underneath/beside building frontages, so counting those would
    # penalize a normal, correct city layout instead of a bad one.
    footprints = [
        (
            b.position[0] - (b.size[0] / 2.0 if b.size else 0.25),
            b.position[0] + (b.size[0] / 2.0 if b.size else 0.25),
        )
        for b in agent_bodies
        if len(b.position) >= 1 and b.kind in (None, "house", "tower", "shop")
    ]
    overlap_total = 0.0
    for i in range(len(footprints)):
        a_lo, a_hi = footprints[i]
        for j in range(i + 1, len(footprints)):
            b_lo, b_hi = footprints[j]
            overlap = min(a_hi, b_hi) - max(a_lo, b_lo)
            if overlap > 0:
                overlap_total += overlap
    metrics["overlap_total"] = overlap_total

    # --- bins: containment (bins_in_target) + correct class match (bins_correct) -
    if bins:
        colors = {b.id: b.color for b in design.bodies}
        dynamic_ids = set(_dynamic_bodies(design)) or set(end_bodies.keys())
        for bid in dynamic_ids:
            body = end_bodies.get(bid)
            if body is None:
                continue
            for bin_ in bins:
                half_w = bin_["width"] / 2.0
                half_h = bin_["height"] / 2.0
                if abs(body.x - bin_["x"]) <= half_w and abs(body.y - bin_["y"]) <= half_h:
                    metrics["bins_in_target"] += 1.0
                    accepts = bin_.get("accepts")
                    if accepts is not None and colors.get(bid) == accepts:
                        metrics["bins_correct"] += 1.0
                    break  # count each dynamic body at most once

    primary = _primary_body_id(trace, design)
    if primary is None:
        metrics["stability"] = 0.0
        return metrics

    # --- distance / max_distance -------------------------------------------------
    start = frames[0].bodies.get(primary)
    final_x = None
    if start is not None:
        start_x = start.x
        xs: list[float] = []
        for f in frames:
            body = f.bodies.get(primary)
            if body is None:
                continue
            xs.append(body.x)
            # A world with a real ground gap (kill_y set) has no floor to land
            # on below it — once the body passes kill_y it is in unbounded free
            # fall and can drift arbitrarily far in x. Stop crediting position
            # there, or a fall would read as "reached the goal"/"crossed the
            # threshold" purely from horizontal drift while plummeting.
            if trace.kill_y is not None and body.y < trace.kill_y:
                break
        if xs:
            final_x = xs[-1]
            metrics["distance_m"] = abs(xs[-1] - start_x)
            metrics["max_distance_m"] = max(abs(x - start_x) for x in xs)

    # --- goal zone / threshold (Bridge, Crawl) -----------------------------------
    if final_x is not None and start is not None:
        goal_x = challenge.get("goal_x")
        if isinstance(goal_x, (int, float)) and goal_x != start_x:
            # Direction-aware: works whether the goal is ahead of or behind start.
            progress = (final_x - start_x) / (goal_x - start_x)
            metrics["goal_progress"] = _clamp01(progress)
            reached = final_x >= goal_x if goal_x > start_x else final_x <= goal_x
            metrics["reached_goal"] = 1.0 if reached else 0.0
        threshold_x = challenge.get("threshold_x")
        if isinstance(threshold_x, (int, float)):
            metrics["crossed_threshold"] = 1.0 if final_x >= threshold_x else 0.0

    # --- falls (count fall events, i.e. transitions below threshold) -------------
    # A world with a real ground gap (Bridge's ravine) carries kill_y — the y
    # below which a body in the gap has fallen in, which is the physically
    # meaningful threshold there. Worlds without a gap fall back to the generic
    # "below ground" threshold.
    fall_threshold = trace.kill_y if trace.kill_y is not None else _FALL_Y_THRESHOLD
    falls = 0
    was_fallen = False
    for f in frames:
        body = f.bodies.get(primary)
        if body is None:
            continue
        fallen = body.y < fall_threshold
        if fallen and not was_fallen:
            falls += 1
        was_fallen = fallen
    metrics["falls"] = float(falls)

    # --- stability (1 - normalized angle oscillation) ----------------------------
    angles = [f.bodies[primary].angle for f in frames if primary in f.bodies]
    if len(angles) >= 2:
        mean = sum(angles) / len(angles)
        variance = sum((a - mean) ** 2 for a in angles) / len(angles)
        # Normalize: a variance of ~1 rad^2 already means very wobbly.
        metrics["stability"] = _clamp01(1.0 - variance)
    else:
        # Fewer than 2 recorded frames means nothing meaningful simulated, so a
        # "perfect 1.0" would falsely credit a degenerate design. Report 0.0,
        # consistent with the no-frames branch above.
        metrics["stability"] = 0.0

    # --- energy proxy: summed per-frame path length of all dynamic bodies --------
    dynamic_ids = _dynamic_bodies(design)
    if not dynamic_ids:
        dynamic_ids = list(frames[0].bodies.keys())
    energy = 0.0
    for prev, cur in zip(frames, frames[1:], strict=False):
        for bid in dynamic_ids:
            pb = prev.bodies.get(bid)
            cb = cur.bodies.get(bid)
            if pb is None or cb is None:
                continue
            energy += abs(cb.x - pb.x) + abs(cb.y - pb.y)
    metrics["energy"] = energy

    return metrics


def _final_city_tick(trace: EpisodeTrace) -> dict:
    """The last `city_tick` event on the trace (CityEngine's economy summary)."""
    for frame in reversed(trace.frames):
        for event in reversed(frame.events):
            if event.get("type") == "city_tick":
                return event
    return {}


def compute_city_metrics(trace: EpisodeTrace, design: DesignSpec) -> dict[str, float]:
    """Derive metrics for a `citysim` trace: zoning, connectivity, and the
    final tick's economy summary (population/budget/pollution/happiness).

    Unlike `compute_metrics` (rigid-body distance/stability/falls), a city has
    no physics outcome to read off frames — CityEngine already computed the
    economy tick-by-tick, so this only reads its final summary and derives
    zoning/connectivity/overlap from the design, per invariant #4 (scoring
    derives from the trace, never re-simulates the engine).
    """
    # Local import: only city-scored runs need the citysim layout helpers.
    from agentgymnasium.engines.citysim import layout

    agent_bodies = _agent_bodies(design)
    roads = [b for b in agent_bodies if layout.zone_of(b.kind) == "road"]
    residential = [b for b in agent_bodies if layout.zone_of(b.kind) == "residential"]
    commercial = [b for b in agent_bodies if layout.zone_of(b.kind) == "commercial"]
    industrial = [b for b in agent_bodies if layout.zone_of(b.kind) == "industrial"]
    civic = [b for b in agent_bodies if layout.zone_of(b.kind) == "civic"]
    green = [b for b in agent_bodies if layout.zone_of(b.kind) == "green"]
    zoned = residential + commercial + industrial

    connected = sum(1 for b in zoned if layout.is_connected(b, roads))
    connectivity_fraction = connected / len(zoned) if zoned else 0.0

    overlap_total = 0.0
    for i in range(len(zoned)):
        for j in range(i + 1, len(zoned)):
            overlap_total += layout.footprint_overlap_2d(zoned[i], zoned[j])

    tick = _final_city_tick(trace)
    return {
        "population": float(tick.get("population", 0.0)),
        "budget": float(tick.get("budget", 0.0)),
        "happiness": float(tick.get("happiness", 0.0)),
        "pollution": float(tick.get("pollution", 0.0)),
        "residential_count": float(len(residential)),
        "commercial_count": float(len(commercial)),
        "industrial_count": float(len(industrial)),
        "civic_count": float(len(civic)),
        "green_count": float(len(green)),
        "road_count": float(len(roads)),
        "zoned_count": float(len(zoned)),
        "connectivity_fraction": connectivity_fraction,
        "overlap_total": overlap_total,
        "parts_used": float(len(agent_bodies)),
    }


# --- reward functions ----------------------------------------------------------
# Each maps a metrics dict to (score_total, success, summary).
def _reward_distance_plus_stability(m: dict[str, float]) -> tuple[float, bool, str]:
    distance = m.get("distance_m", 0.0)
    stability = m.get("stability", 0.0)
    falls = m.get("falls", 0.0)
    score = distance * 10.0 + stability * 20.0 - falls * 5.0
    success = distance >= 3.0 and falls == 0
    summary = (
        f"Travelled {distance:.2f}m with stability {stability:.2f} "
        f"and {int(falls)} fall(s)."
    )
    return score, success, summary


def _reward_bridge_transport(m: dict[str, float]) -> tuple[float, bool, str]:
    """Bridge: carry the crate to the goal zone, stay standing, stay lean.

    Rewards goal progress and reaching the goal, plus stability; penalizes
    falling into the ravine (a real gap in the ground — see the world's
    ground_spans/kill_y) and excessive parts (a bridge should be efficient).
    """
    progress = m.get("goal_progress", 0.0)
    reached = m.get("reached_goal", 0.0)
    stability = m.get("stability", 0.0)
    falls = m.get("falls", 0.0)
    parts = m.get("parts_used", 0.0)
    part_penalty = max(0.0, parts - 12.0) * 2.0
    score = progress * 50.0 + reached * 30.0 + stability * 10.0 - falls * 10.0 - part_penalty
    success = reached >= 1.0 and falls == 0
    summary = (
        f"{'Reached goal' if reached else f'{progress:.0%} to goal'}; "
        f"stability {stability:.2f}, "
        f"{f'fell into the ravine {int(falls)}x' if falls else 'no falls'}, "
        f"{int(parts)} parts."
    )
    return score, success, summary


def _reward_crawl_locomotion(m: dict[str, float]) -> tuple[float, bool, str]:
    """Crawl: move the body forward and cross the threshold.

    Pure locomotion — rewards net forward travel and crossing the line, with a
    fall penalty. No part bonus (unlike a city), so it favours motion over bulk.
    """
    distance = m.get("distance_m", 0.0)
    crossed = m.get("crossed_threshold", 0.0)
    falls = m.get("falls", 0.0)
    score = distance * 12.0 + crossed * 25.0 - falls * 8.0
    success = crossed >= 1.0
    summary = (
        f"Crawled {distance:.2f}m"
        f"{' — crossed the line' if crossed else ''}; {int(falls)} fall(s)."
    )
    return score, success, summary


def _reward_sorting_accuracy(m: dict[str, float]) -> tuple[float, bool, str]:
    bins_count = m.get("bins_count", 0.0)
    bins_in_target = m.get("bins_in_target", 0.0)
    bins_correct = m.get("bins_correct", 0.0)
    stability = m.get("stability", 0.0)
    # Items to sort = dynamic bodies (excludes bins AND static support structure),
    # so adding beams no longer deflates the accuracy denominator.
    dynamic = m.get("sortable_items", 0.0)

    if bins_count <= 0 or dynamic <= 0:
        return (
            stability * 30.0,
            False,
            f"No bins placed — cannot score sorting. Stability proxy: {stability:.2f}.",
        )

    # True object-class-to-bin matching when bins declare an accepted class;
    # otherwise fall back to plain containment.
    if m.get("bins_matchable", 0.0) > 0:
        accuracy = bins_correct / dynamic
        score = accuracy * 90.0 + stability * 10.0
        success = accuracy >= 0.5
        summary = (
            f"Correctly sorted {int(bins_correct)}/{int(dynamic)} items into the "
            f"matching bin ({accuracy:.0%}); {int(bins_in_target)} landed in any bin."
        )
    else:
        accuracy = bins_in_target / dynamic
        score = accuracy * 70.0 + stability * 20.0
        success = accuracy >= 0.5
        summary = (
            f"{int(bins_in_target)}/{int(dynamic)} items landed in a bin "
            f"({accuracy:.0%} containment, stability {stability:.2f})."
        )
    return score, success, summary


def _reward_city_score(m: dict[str, float]) -> tuple[float, bool, str]:
    """Tiny City: more structures, well spread/spaced (livable), stable, and a
    real mix of city infrastructure — not just a row of identical buildings."""
    parts = m.get("parts_used", 0.0)
    building_count = m.get("building_count", 0.0)
    spread_area = m.get("spread_area", 0.0)
    avg_spacing = m.get("avg_spacing", 0.0)
    min_spacing = m.get("min_spacing", 0.0)
    stability = m.get("stability", 0.0)
    road_count = m.get("road_count", 0.0)
    park_count = m.get("park_count", 0.0)
    tree_count = m.get("tree_count", 0.0)
    height_variety = m.get("height_variety", 0.0)
    overlap_total = m.get("overlap_total", 0.0)
    infra_bonus = (
        min(road_count, 2.0) * 6.0
        + min(park_count, 2.0) * 6.0
        + min(tree_count, 4.0) * 2.0
        + min(height_variety, 6.0) * 2.0
    )
    overlap_penalty = overlap_total * 5.0
    # Cap the raw part-count term — a pile of identical boxes shouldn't be able
    # to out-score a smaller, well-composed mix of road/park/trees/buildings.
    score = (
        min(parts, 12.0) * 4.0
        + math.sqrt(max(0.0, spread_area)) * 2.0
        + avg_spacing * 4.0  # livability: well-spaced beats clumped
        + stability * 8.0
        + infra_bonus
        - overlap_penalty
    )
    # Success requires the actual mix the objective asks for (road + park +
    # trees + several buildings), not just "4+ things placed with some gap" —
    # a pile of boxes with no infrastructure used to pass this bar easily.
    success = (
        building_count >= 6
        and road_count >= 1
        and park_count >= 1
        and tree_count >= 2
        and min_spacing >= 1.0
    )
    summary = (
        f"City: {int(building_count)} buildings, {int(road_count)} road, "
        f"{int(park_count)} park, {int(tree_count)} tree "
        f"({int(parts)} parts total), {spread_area:.1f}u² spread, avg spacing "
        f"{avg_spacing:.2f} (min {min_spacing:.2f})"
        + (f", {overlap_total:.1f}u overlap" if overlap_total > 0 else "")
        + "."
    )
    return score, success, summary


def _zone_balance(m: dict[str, float]) -> float:
    """1.0 = perfectly even residential/commercial/industrial split, 0.0 = all one zone."""
    zoned = m.get("residential_count", 0.0) + m.get("commercial_count", 0.0) + m.get(
        "industrial_count", 0.0
    )
    if zoned <= 0.0:
        return 0.0
    shares = [
        m.get("residential_count", 0.0) / zoned,
        m.get("commercial_count", 0.0) / zoned,
        m.get("industrial_count", 0.0) / zoned,
    ]
    return max(0.0, 1.0 - (max(shares) - 1.0 / 3.0))


def _reward_city_planning(m: dict[str, float]) -> tuple[float, bool, str]:
    """Grid City: population + road connectivity + green space − overlap.

    The flagship isometric-city reward — rewards a REAL zoned layout (grown
    population, connected to roads) over a pile of disconnected buildings.
    """
    population = m.get("population", 0.0)
    connectivity = m.get("connectivity_fraction", 0.0)
    green = m.get("green_count", 0.0)
    zoned = m.get("zoned_count", 0.0)
    overlap = m.get("overlap_total", 0.0)
    score = population * 2.0 + connectivity * 40.0 + min(green, 6.0) * 5.0 - overlap * 8.0
    success = population >= 20.0 and connectivity >= 0.6 and zoned >= 4
    summary = (
        f"Population {population:.0f}, {connectivity:.0%} connected to roads, "
        f"{int(green)} green space(s)."
    )
    return score, success, summary


def _reward_boomtown(m: dict[str, float]) -> tuple[float, bool, str]:
    """Boomtown: maximize population growth — connectivity is what feeds it."""
    population = m.get("population", 0.0)
    connectivity = m.get("connectivity_fraction", 0.0)
    score = population * 5.0 + connectivity * 20.0
    success = population >= 40.0
    summary = f"Boomtown: population {population:.0f} ({connectivity:.0%} connected)."
    return score, success, summary


def _reward_budget_city(m: dict[str, float]) -> tuple[float, bool, str]:
    """Budget City: grow the treasury while still building a real zoned city."""
    budget = m.get("budget", 0.0)
    zoned = m.get("zoned_count", 0.0)
    score = budget * 0.1 + zoned * 3.0
    success = budget >= 1500.0 and zoned >= 4
    summary = f"Budget {budget:.0f} with {int(zoned)} zoned structures."
    return score, success, summary


def _reward_balanced_city(m: dict[str, float]) -> tuple[float, bool, str]:
    """Balanced City: even residential/commercial/industrial mix + happiness."""
    balance = _zone_balance(m)
    happiness = m.get("happiness", 0.0)
    green = m.get("green_count", 0.0)
    zoned = m.get("zoned_count", 0.0)
    score = balance * 50.0 + happiness * 30.0 + min(green, 4.0) * 5.0
    success = balance >= 0.7 and happiness >= 0.6 and zoned >= 6
    summary = f"Zone balance {balance:.0%}, happiness {happiness:.0%}."
    return score, success, summary


def _reward_green_capital(m: dict[str, float]) -> tuple[float, bool, str]:
    """Green Capital: grow population while keeping pollution low."""
    pollution = m.get("pollution", 0.0)
    population = m.get("population", 0.0)
    green = m.get("green_count", 0.0)
    score = population * 2.0 + green * 8.0 - pollution * 3.0
    success = pollution <= 5.0 and population >= 15.0
    summary = (
        f"Population {population:.0f}, pollution {pollution:.1f}, "
        f"{int(green)} green space(s)."
    )
    return score, success, summary


def _reward_default(m: dict[str, float]) -> tuple[float, bool, str]:
    distance = m.get("distance_m", 0.0)
    score = distance * 10.0
    success = distance >= 2.0
    summary = f"Default reward: travelled {distance:.2f}m."
    return score, success, summary


REWARDS: dict[str, Callable[[dict[str, float]], tuple[float, bool, str]]] = {
    "distance_plus_stability": _reward_distance_plus_stability,
    "bridge_transport": _reward_bridge_transport,
    "crawl_locomotion": _reward_crawl_locomotion,
    "sorting_accuracy": _reward_sorting_accuracy,
    "city_score": _reward_city_score,
    "city_planning": _reward_city_planning,
    "boomtown": _reward_boomtown,
    "budget_city": _reward_budget_city,
    "balanced_city": _reward_balanced_city,
    "green_capital": _reward_green_capital,
    "default": _reward_default,
}

# Rewards scored from a `citysim` (layout/economy) trace rather than a
# physics trace — compute_city_metrics reads zoning/connectivity + the
# final economy tick instead of distance/stability/falls.
_CITY_REWARDS = frozenset(
    {"city_planning", "boomtown", "budget_city", "balanced_city", "green_capital"}
)


# Reference distance below which a stable design is considered "short" for the
# improvement hint. Matches the distance success threshold used by the rewards.
_SHORT_DISTANCE_TARGET = 3.0


def _city_improvement_hint(metrics: dict[str, float]) -> str:
    """Improvement hint for a citysim (`population` present) metrics dict."""
    if metrics.get("parts_used", 0.0) == 0:
        return "Design was empty — place buildings before simulating."
    if metrics.get("zoned_count", 0.0) == 0:
        return "No zoned structures (house/shop/factory/…) — nothing to grow."
    if metrics.get("connectivity_fraction", 0.0) < 0.5:
        return "Most structures aren't near a road — add roads or move buildings closer."
    if metrics.get("overlap_total", 0.0) > 0:
        return "Buildings overlap — space structures further apart."
    return "Solid city — iterate on zoning mix and green space."


def _improvement_hint(metrics: dict[str, float]) -> str:
    """Short, deterministic "why it failed / how to improve" derived from metrics."""
    if "population" in metrics:
        return _city_improvement_hint(metrics)
    parts = metrics.get("parts_used", 0.0)
    falls = metrics.get("falls", 0.0)
    distance = metrics.get("distance_m", 0.0)
    if parts == 0:
        return "Design was empty — add bodies before simulating."
    if falls > 0:
        return (
            f"Structure fell {int(falls)}x — add support or lower the "
            "center of mass."
        )
    if distance < _SHORT_DISTANCE_TARGET:
        return "Stable but short — add propulsion or extend reach."
    return "Solid attempt — iterate on the best design."


def score_attempt(
    trace: EpisodeTrace | None, design: DesignSpec, reward: str
) -> ScoreCard:
    """Compute metrics and apply the named reward to produce a ScoreCard.

    Unknown reward names fall back to ``default`` (but the ScoreCard records
    ``reward="default"`` so callers can tell). A ``None`` trace yields a zero
    ScoreCard.
    """
    if trace is None:
        no_trace_metrics = {
            "parts_used": float(len(_agent_bodies(design))),
            "bins_count": float(len(design.metadata.get("bins", []))),
            "bins_in_target": 0.0,
            "spread_area": 0.0,
        }
        return ScoreCard(
            score_total=0.0,
            success=False,
            metrics=no_trace_metrics,
            failure_events=(
                [{"type": "empty_design"}] if not design.bodies else []
            ),
            summary="No simulation was run (empty design).",
            reward=reward if reward in REWARDS else "default",
            improvement_hint=_improvement_hint(no_trace_metrics),
        )

    reward_name = reward if reward in REWARDS else "default"
    metrics = (
        compute_city_metrics(trace, design)
        if reward_name in _CITY_REWARDS
        else compute_metrics(trace, design)
    )

    reward_fn = REWARDS[reward_name]
    score_total, success, summary = reward_fn(metrics)

    failure_events: list[dict] = []
    if metrics.get("falls", 0.0) > 0:
        failure_events.append({"type": "fall", "count": int(metrics["falls"])})
    if metrics.get("parts_used", 0.0) == 0:
        failure_events.append({"type": "empty_design"})

    return ScoreCard(
        score_total=score_total,
        success=success,
        metrics=metrics,
        failure_events=failure_events,
        summary=summary,
        reward=reward_name,
        improvement_hint=_improvement_hint(metrics),
    )
