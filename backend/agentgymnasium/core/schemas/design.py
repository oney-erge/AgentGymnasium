from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

# ``created_by`` value for parts the challenge/world seeds (terrain, the crate,
# goal markers) rather than an agent. Excluded from agent-effort scoring.
WORLD_AUTHOR = "world"


class BodyShape(StrEnum):
    segment = "segment"
    box = "box"
    circle = "circle"
    polygon = "polygon"


class BodySpec(BaseModel):
    id: str
    shape: BodyShape = BodyShape.box
    position: list[float] = [0.0, 0.0]  # [x, y]
    size: list[float] = [0.5, 0.5]  # box: [w, h]; circle: [r]; segment: [len]
    angle: float = 0.0  # orientation in radians; lets ramps/beams slope
    mass: float = 1.0
    static: bool = False  # static bodies don't move (terrain, anchors)
    material: str = "metal"
    friction: float = 0.6
    elasticity: float = 0.1
    color: str | None = None
    # Semantic label (house/tower/tree/road/wall/crate/ball/bin/water/…) so the
    # renderer can draw a recognizable prop instead of a generic shape.
    kind: str | None = None
    created_by: str | None = None  # agent id
    # A sensor detects overlap without physically blocking anything — for a
    # goal/finish marker, which announces "reached here" and must not itself be
    # a solid obstacle standing in the way of whatever is meant to reach it.
    sensor: bool = False
    # Ground-plane depth coordinate. Only meaningful for the layout-based
    # `citysim` engine, where a structure's footprint sits at (position[0], z)
    # and extrudes upward by size[1] (height); pymunk2d ignores this and uses
    # position as [x, y_height] instead.
    z: float = 0.0
    # Footprint depth (z-axis) for `citysim` structures. None means a square
    # footprint (same as the x-axis width, size[0]). Unused by pymunk2d.
    depth: float | None = None


class JointType(StrEnum):
    pivot = "pivot"
    pin = "pin"
    slide = "slide"
    spring = "spring"


class JointSpec(BaseModel):
    id: str
    body_a: str
    body_b: str
    type: JointType = JointType.pivot
    anchor_a: list[float] = [0.0, 0.0]
    anchor_b: list[float] = [0.0, 0.0]
    motor_rate: float | None = None  # if set, attach a simple motor
    motor_max_force: float = 100000.0
    created_by: str | None = None


class DesignSpec(BaseModel):
    name: str = "untitled"
    bodies: list[BodySpec] = []
    joints: list[JointSpec] = []
    metadata: dict = {}
