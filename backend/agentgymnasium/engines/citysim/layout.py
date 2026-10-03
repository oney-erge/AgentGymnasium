"""Pure zoning/connectivity/footprint helpers shared by CityEngine and scoring.

No physics: a city's structures are placed, zoned, and connected rather than
simulated as rigid bodies. Kept dependency-free (only `core.schemas.design`) so
`scoring_service` can reuse the same zone/connectivity logic the engine used to
produce the trace, instead of re-deriving it differently in two places.
"""

from __future__ import annotations

import math

from agentgymnasium.core.schemas.design import BodySpec

RESIDENTIAL_KINDS = frozenset({"house", "apartment", "tower"})
COMMERCIAL_KINDS = frozenset({"shop"})
INDUSTRIAL_KINDS = frozenset({"factory", "power_plant"})
CIVIC_KINDS = frozenset({"school", "hospital"})
GREEN_KINDS = frozenset({"park", "plaza", "tree", "water"})
ROAD_KINDS = frozenset({"road"})
DECORATION_KINDS = frozenset({"fountain"})

# Population capacity per residential structure at its baseline height.
_CAPACITY_PER_KIND = {"house": 4.0, "apartment": 10.0, "tower": 16.0}
_HEIGHT_BASELINE = {"house": 3.0, "apartment": 6.0, "tower": 8.0}

# How close (metres) a structure's center must be to a road's footprint edge
# to count as road-connected. A proxy for real road-graph reachability — good
# enough for "is this building near a street" without pathfinding.
_CONNECT_RADIUS = 4.0


def zone_of(kind: str | None) -> str:
    """Classify a body's semantic `kind` into a zoning category."""
    if kind in RESIDENTIAL_KINDS:
        return "residential"
    if kind in COMMERCIAL_KINDS:
        return "commercial"
    if kind in INDUSTRIAL_KINDS:
        return "industrial"
    if kind in CIVIC_KINDS:
        return "civic"
    if kind in GREEN_KINDS:
        return "green"
    if kind in ROAD_KINDS:
        return "road"
    return "other"


def footprint_depth(body: BodySpec) -> float:
    """Footprint depth (z-axis) in metres: explicit `depth`, else square (width)."""
    if body.depth is not None:
        return max(body.depth, 0.01)
    width = body.size[0] if body.size else 1.0
    return max(width, 0.01)


def footprint_width(body: BodySpec) -> float:
    return max(body.size[0] if body.size else 1.0, 0.01)


def height_of(body: BodySpec) -> float:
    return max(body.size[1] if len(body.size) > 1 else 1.0, 0.01)


def capacity_of(body: BodySpec) -> float:
    """Population capacity a residential structure contributes when connected.

    Taller-than-baseline structures of the same kind house more people —
    height/baseline scales capacity, so a tall tower is worth more than a
    short one instead of every tower counting identically.
    """
    base = _CAPACITY_PER_KIND.get(body.kind or "", 0.0)
    if base <= 0.0:
        return 0.0
    baseline = _HEIGHT_BASELINE.get(body.kind or "", 3.0)
    return base * max(1.0, height_of(body) / baseline)


def _point_to_rect_distance(
    px: float, pz: float, rx: float, rz: float, half_w: float, half_d: float
) -> float:
    """Distance from point (px, pz) to an axis-aligned rectangle centered at
    (rx, rz) with half-extents (half_w, half_d); 0 if the point is inside."""
    dx = max(abs(px - rx) - half_w, 0.0)
    dz = max(abs(pz - rz) - half_d, 0.0)
    return math.hypot(dx, dz)


def is_connected(body: BodySpec, roads: list[BodySpec], radius: float = _CONNECT_RADIUS) -> bool:
    """Whether `body`'s center sits within `radius` of any road's footprint.

    Roads are treated as axis-aligned rectangles (their `angle` is ignored) —
    consistent with `footprint_overlap_2d`'s simplification for the same reason.
    """
    for road in roads:
        distance = _point_to_rect_distance(
            body.position[0],
            body.z,
            road.position[0],
            road.z,
            footprint_width(road) / 2.0,
            footprint_depth(road) / 2.0,
        )
        if distance <= radius:
            return True
    return False


def footprint_overlap_2d(a: BodySpec, b: BodySpec) -> float:
    """Overlap area (m^2) of two structures' (x, z) footprints; 0 if none."""
    aw, ad = footprint_width(a) / 2.0, footprint_depth(a) / 2.0
    bw, bd = footprint_width(b) / 2.0, footprint_depth(b) / 2.0
    ox = min(a.position[0] + aw, b.position[0] + bw) - max(a.position[0] - aw, b.position[0] - bw)
    oz = min(a.z + ad, b.z + bd) - max(a.z - ad, b.z - bd)
    if ox <= 0.0 or oz <= 0.0:
        return 0.0
    return ox * oz


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
