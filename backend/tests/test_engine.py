import math

from agentgymnasium.core.schemas.design import BodyShape, BodySpec, DesignSpec, JointSpec, JointType
from agentgymnasium.core.schemas.setup import WorldConfig
from agentgymnasium.engines import get_engine
from agentgymnasium.engines.pymunk2d.builder import valid_ground_spans
from agentgymnasium.engines.pymunk2d.engine import Pymunk2DEngine
from agentgymnasium.services.run_service import hardcoded_demo_design


def _world() -> WorldConfig:
    return WorldConfig(template="flat_ground")


def test_get_engine():
    assert isinstance(get_engine("pymunk2d"), Pymunk2DEngine)
    assert get_engine("nonexistent") is None


def test_pymunk_simulate_steps():
    engine = Pymunk2DEngine()
    design = hardcoded_demo_design()
    trace = engine.simulate(design, _world(), duration_seconds=1.0)

    assert len(trace.frames) > 0
    assert trace.dt > 0
    # Every frame body must expose x/y/angle.
    for frame in trace.frames:
        for body in frame.bodies.values():
            assert hasattr(body, "x")
            assert hasattr(body, "y")
            assert hasattr(body, "angle")


def test_ball_rolls_down_angled_ramp():
    # A ball dropped onto an angled static segment must travel horizontally — i.e.
    # the segment's angle is honored by the physics, so ramps actually slope.
    import math

    design = DesignSpec(
        name="ramp",
        bodies=[
            BodySpec(
                id="ramp",
                shape=BodyShape.segment,
                position=[0.0, 3.0],
                size=[10.0],
                angle=-0.4,  # downhill to the right
                static=True,
            ),
            BodySpec(
                id="ball",
                shape=BodyShape.circle,
                position=[-3.0, 5.0],
                size=[0.4],
                mass=1.0,
            ),
        ],
    )
    trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=3.0)
    start_x = trace.frames[0].bodies["ball"].x
    end_x = trace.frames[-1].bodies["ball"].x
    assert end_x - start_x > 1.0  # rolled meaningfully to the right
    # The ramp's slope is preserved in the static props for rendering.
    ramp_prop = next(p for p in trace.world_static if p.id == "ramp")
    assert ramp_prop.angle == -0.4
    assert not math.isclose(ramp_prop.angle, 0.0)


def test_falling_body_moves():
    design = DesignSpec(
        name="faller",
        bodies=[
            BodySpec(
                id="box",
                shape=BodyShape.box,
                position=[0.0, 10.0],
                size=[1.0, 1.0],
                mass=1.0,
            )
        ],
    )
    engine = Pymunk2DEngine()
    trace = engine.simulate(design, _world(), duration_seconds=1.0)

    first_y = trace.frames[0].bodies["box"].y
    last_y = trace.frames[-1].bodies["box"].y
    assert last_y < first_y


def test_world_static_includes_ground():
    engine = Pymunk2DEngine()
    trace = engine.simulate(hardcoded_demo_design(), _world(), duration_seconds=0.5)
    kinds = {p.kind for p in trace.world_static}
    assert "ground" in kinds


def test_kind_flows_to_static_prop_and_body_meta():
    # A cosmetic `kind` (e.g. "house") must reach both the static-prop trace
    # (for static bodies) and body_meta (for dynamic bodies) so the renderer
    # can draw a recognizable shape instead of a plain rectangle.
    design = DesignSpec(
        name="scene",
        bodies=[
            BodySpec(
                id="house1", shape=BodyShape.box, position=[0.0, 1.5],
                size=[2.0, 3.0], static=True, kind="house",
            ),
            BodySpec(
                id="crate1", shape=BodyShape.box, position=[5.0, 5.0],
                size=[1.0, 1.0], static=False, kind="tree",
            ),
        ],
    )
    trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=0.2)
    house_prop = next(p for p in trace.world_static if p.id == "house1")
    assert house_prop.kind == "house"
    assert trace.body_meta["crate1"].kind == "tree"


def test_body_spawned_at_ground_default_does_not_tunnel_through():
    # Regression for E5: a dynamic body created via apply_tool_call with no
    # explicit position (schema default [0, 0]) must rest near the ground after
    # simulating, not fall through it forever (previously observed y -> -4412).
    from agentgymnasium.tools.apply import apply_tool_call

    design = DesignSpec(name="t")
    apply_tool_call(
        design, agent_id="a", tool="create_body",
        args={"id": "b1", "shape": "box"}, enabled_tools=["create_body"],
    )
    trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=5.0)
    final_y = trace.frames[-1].bodies["b1"].y
    assert final_y > -1.0  # resting on/near the ground, not tunneled through


def test_valid_ground_spans_drops_malformed_entries():
    # Shared by the physics floor and the trace's visual ground props, so both
    # must agree on which spans are real — malformed entries (wrong shape,
    # reversed, zero-width) are dropped, not raised, since this ultimately
    # comes from world-template YAML rather than untrusted agent input.
    design = DesignSpec(name="t")
    design.metadata["ground_spans"] = [
        [-10.0, -4.0],
        "not-a-span",
        [5.0],  # too short
        [8.0, 8.0],  # zero-width
        [12.0, 6.0],  # reversed
        [4.0, 10.0],
    ]
    assert valid_ground_spans(design, map_width=32.0) == [(-10.0, -4.0), (4.0, 10.0)]


def test_valid_ground_spans_defaults_to_full_width():
    design = DesignSpec(name="t")
    assert valid_ground_spans(design, map_width=32.0) == [(-32.0, 32.0)]


def test_ground_spans_carve_a_real_gap():
    # A body positioned over the gap between two ground_spans must keep falling
    # (no phantom floor); a body resting on a span must stay put. This is the
    # mechanism a Bridge-style challenge needs: without it, every world has one
    # continuous invisible floor and a chasm can never be physically real.
    design = DesignSpec(
        name="gap",
        bodies=[
            BodySpec(
                id="over_gap", shape=BodyShape.circle, position=[0.0, 1.0],
                size=[0.3], mass=1.0,
            ),
            BodySpec(
                id="over_span", shape=BodyShape.circle, position=[-10.0, 1.0],
                size=[0.3], mass=1.0,
            ),
        ],
    )
    # Ground only from x=-12..-4 and x=4..12 — the gap is -4..4, where "over_gap"
    # sits directly above.
    design.metadata["ground_spans"] = [[-12.0, -4.0], [4.0, 12.0]]
    trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=2.0)

    gap_final_y = trace.frames[-1].bodies["over_gap"].y
    span_final_y = trace.frames[-1].bodies["over_span"].y
    assert gap_final_y < -5.0  # fell through the gap, no phantom floor
    assert span_final_y > 0.0  # rested on its span


def test_ground_spans_default_to_full_width_when_absent():
    # Backward compat: a design/world with no ground_spans recorded behaves like
    # before — one continuous floor at y=0 across the whole map.
    design = DesignSpec(
        name="no-gap",
        bodies=[
            BodySpec(id="ball", shape=BodyShape.circle, position=[0.0, 1.0], size=[0.3], mass=1.0),
        ],
    )
    trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=2.0)
    assert trace.frames[-1].bodies["ball"].y > 0.0


def test_world_static_ground_props_reflect_spans():
    design = DesignSpec(name="gap")
    design.metadata["ground_spans"] = [[-12.0, -4.0], [4.0, 12.0]]
    trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=0.1)
    ground_props = [p for p in trace.world_static if p.kind == "ground"]
    assert len(ground_props) == 2
    xs = sorted(p.position[0] for p in ground_props)
    assert xs == [-8.0, 8.0]  # midpoints of [-12,-4] and [4,12]


def test_kill_y_flows_from_metadata_to_trace():
    design = DesignSpec(name="gap")
    design.metadata["ground_spans"] = [[-12.0, -4.0], [4.0, 12.0]]
    design.metadata["kill_y"] = -3.0
    trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=0.1)
    assert trace.kill_y == -3.0


def test_kill_y_defaults_to_none():
    trace = Pymunk2DEngine().simulate(DesignSpec(name="plain"), _world(), duration_seconds=0.1)
    assert trace.kill_y is None


def test_pivot_joint_honors_both_anchors():
    # A pivot must pin anchor_a (local to body_a) to anchor_b (local to
    # body_b), not just treat anchor_a as a single world point (which silently
    # ignored anchor_b entirely). Two falling boxes pinned at an off-center
    # point on each must keep those two points coincident in world space —
    # the defining behavior of a hinge, and what a hinged creature's limb
    # joints depend on to not "pop" at simulation start.
    design = DesignSpec(
        name="t",
        bodies=[
            BodySpec(id="a", shape=BodyShape.box, position=[0.0, 5.0], size=[1.0, 1.0], mass=1.0),
            BodySpec(id="b", shape=BodyShape.box, position=[2.0, 5.0], size=[1.0, 1.0], mass=1.0),
        ],
        joints=[
            JointSpec(
                id="j", body_a="a", body_b="b", type=JointType.pivot,
                anchor_a=[0.5, 0.0], anchor_b=[-0.5, 0.0],
            )
        ],
    )
    trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=3.0)
    last = trace.frames[-1].bodies
    a, b = last["a"], last["b"]

    def local_to_world(body, anchor: tuple[float, float]) -> tuple[float, float]:
        cos_a, sin_a = math.cos(body.angle), math.sin(body.angle)
        return (
            body.x + anchor[0] * cos_a - anchor[1] * sin_a,
            body.y + anchor[0] * sin_a + anchor[1] * cos_a,
        )

    world_a = local_to_world(a, (0.5, 0.0))
    world_b = local_to_world(b, (-0.5, 0.0))
    assert math.dist(world_a, world_b) < 0.05


def test_sensor_body_does_not_block_movement():
    # A "goal" marker announces "reached here" and must not itself be a solid
    # wall standing in the way of whatever is meant to reach it (regression for
    # the Bridge Builder crate getting physically stuck against its own goal
    # marker instead of ever registering as having arrived).
    def rolls_past(sensor: bool) -> float:
        design = DesignSpec(
            name="t",
            bodies=[
                BodySpec(
                    id="ramp", shape=BodyShape.segment, position=[0.0, 1.0],
                    size=[6.0], angle=-0.2, static=True,
                ),
                BodySpec(
                    id="wall", shape=BodyShape.box, position=[3.0, 0.5],
                    size=[0.5, 1.0], static=True, sensor=sensor,
                ),
                BodySpec(
                    id="ball", shape=BodyShape.circle, position=[-2.5, 1.6],
                    size=[0.3], mass=1.0,
                ),
            ],
        )
        trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=3.0)
        return trace.frames[-1].bodies["ball"].x

    blocked_x = rolls_past(sensor=False)
    passthrough_x = rolls_past(sensor=True)
    assert blocked_x < 3.0  # stopped before reaching the wall's center
    assert passthrough_x > 3.0  # sensor let it roll straight through


def test_kind_falls_back_to_shape_when_absent():
    # Bodies without a `kind` keep the old shape-name fallback (backward compat
    # with challenges that don't use the cosmetic kind hint, e.g. bridge/crawl).
    design = DesignSpec(
        name="scene",
        bodies=[
            BodySpec(id="beam1", shape=BodyShape.segment, position=[0.0, 1.0], size=[2.0], static=True),
        ],
    )
    trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=0.2)
    beam_prop = next(p for p in trace.world_static if p.id == "beam1")
    assert beam_prop.kind == "segment"


def test_static_prop_carries_real_shape_alongside_semantic_kind():
    # A beam/ramp/wall is semantically "beam" (kind) but geometrically a thin
    # segment — the renderer needs the real shape too, or it draws a segment's
    # length as both width AND height (a fat square instead of a thin plank).
    design = DesignSpec(
        name="scene",
        bodies=[
            BodySpec(
                id="deck", shape=BodyShape.segment, position=[0.0, 1.0],
                size=[6.9], static=True, kind="beam",
            ),
            BodySpec(
                id="house1", shape=BodyShape.box, position=[5.0, 1.5],
                size=[2.0, 3.0], static=True, kind="house",
            ),
        ],
    )
    trace = Pymunk2DEngine().simulate(design, _world(), duration_seconds=0.2)
    deck_prop = next(p for p in trace.world_static if p.id == "deck")
    house_prop = next(p for p in trace.world_static if p.id == "house1")
    assert deck_prop.kind == "beam"
    assert deck_prop.shape == "segment"
    assert house_prop.kind == "house"
    assert house_prop.shape == "box"
