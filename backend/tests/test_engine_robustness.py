"""Engine robustness: a pathological agent design must not crash the simulation.

Agent tool args are untrusted, so a dynamic body with zero/negative mass or a
zero-size shape (which pymunk would otherwise assert on when stepped) must be
clamped to safe minimums rather than aborting the whole run.
"""

from __future__ import annotations

import math

from agentgymnasium.core.schemas.design import BodyShape, BodySpec, DesignSpec
from agentgymnasium.core.schemas.setup import WorldConfig
from agentgymnasium.engines.pymunk2d.engine import Pymunk2DEngine


def _simulate(design: DesignSpec):
    return Pymunk2DEngine().simulate(design, WorldConfig(template="flat_arena"), 1.0)


def test_zero_mass_dynamic_body_does_not_crash():
    design = DesignSpec(
        bodies=[BodySpec(id="b", shape=BodyShape.box, position=[0.0, 5.0], mass=0.0)]
    )
    trace = _simulate(design)
    assert trace.frames
    last = trace.frames[-1].bodies["b"]
    assert math.isfinite(last.x) and math.isfinite(last.y)


def test_zero_size_shapes_do_not_crash():
    design = DesignSpec(
        bodies=[
            BodySpec(id="c", shape=BodyShape.circle, position=[0.0, 5.0], size=[0.0]),
            BodySpec(id="bx", shape=BodyShape.box, position=[2.0, 5.0], size=[0.0, 0.0]),
        ]
    )
    trace = _simulate(design)
    assert trace.frames
    for bid in ("c", "bx"):
        body = trace.frames[-1].bodies[bid]
        assert math.isfinite(body.x) and math.isfinite(body.y)


def test_negative_mass_clamped():
    design = DesignSpec(
        bodies=[BodySpec(id="n", shape=BodyShape.box, position=[0.0, 5.0], mass=-3.0)]
    )
    trace = _simulate(design)
    assert trace.frames
    assert math.isfinite(trace.frames[-1].bodies["n"].y)
