from agentgymnasium.core.schemas.design import BodyShape, BodySpec, DesignSpec
from agentgymnasium.core.schemas.toolcall import ToolCallStatus
from agentgymnasium.tools.apply import apply_tool_call

_ENABLED = [
    "create_body",
    "add_joint",
    "add_motor",
    "set_material",
    "set_friction",
]


def test_create_body_mutates():
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"id": "b1", "shape": "box"},
        enabled_tools=_ENABLED,
    )
    assert result.mutated is True
    assert result.record.status == ToolCallStatus.success
    assert len(design.bodies) == 1
    assert design.bodies[0].id == "b1"
    assert design.bodies[0].created_by == "a"


def test_create_body_width_height_static():
    # A tall static building: width/height make a non-square box, static pins it.
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={
            "id": "tower",
            "shape": "box",
            "position": [4.0, 3.0],
            "width": 2.0,
            "height": 6.0,
            "static": True,
        },
        enabled_tools=["create_body"],
    )
    assert result.mutated is True
    body = design.bodies[0]
    assert body.size == [2.0, 6.0]
    assert body.static is True


def test_create_body_z_and_depth_for_citysim():
    # z/depth place a structure on a ground plane (x, z) for the citysim engine;
    # pymunk2d bodies simply carry them unused (z=0.0, depth=None by default).
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={
            "id": "shop1",
            "shape": "box",
            "position": [4.0, 2.0],
            "z": 5.0,
            "width": 2.0,
            "height": 4.0,
            "depth": 3.0,
            "static": True,
            "kind": "shop",
        },
        enabled_tools=["create_body"],
    )
    assert result.mutated is True
    body = design.bodies[0]
    assert body.z == 5.0
    assert body.depth == 3.0


def test_create_body_z_and_depth_default():
    design = DesignSpec()
    apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"id": "b1", "shape": "box", "static": True},
        enabled_tools=["create_body"],
    )
    body = design.bodies[0]
    assert body.z == 0.0
    assert body.depth is None


def test_create_body_kind_flows_through():
    # The cosmetic `kind` hint (renderer-only) must land on the BodySpec so the
    # engine/renderer can pick it up later.
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={
            "id": "house1",
            "shape": "box",
            "width": 2.0,
            "height": 3.0,
            "static": True,
            "kind": "house",
        },
        enabled_tools=["create_body"],
    )
    assert result.mutated is True
    assert design.bodies[0].kind == "house"


def test_create_body_clamps_embedded_dynamic_position():
    # A dynamic 1x1 box at the schema-default position [0, 0] is half-submerged
    # in the ground (y=0 line) and can tunnel through it forever (see E5 in
    # remaining_gaps.md). It must be clamped to rest at/above the surface.
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"id": "b1", "shape": "box"},
        enabled_tools=["create_body"],
    )
    assert result.mutated is True
    body = design.bodies[0]
    assert body.position[1] >= 0.25  # half of the default 1x1 box's height


def test_create_body_does_not_clamp_static_bodies():
    # Static terrain (e.g. a hill segment) is allowed to be embedded on purpose.
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"id": "hill", "shape": "box", "position": [0.0, 0.0], "static": True},
        enabled_tools=["create_body"],
    )
    assert result.mutated is True
    assert design.bodies[0].position == [0.0, 0.0]


def test_create_body_leaves_already_safe_position_untouched():
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"id": "b1", "shape": "box", "position": [2.0, 10.0]},
        enabled_tools=["create_body"],
    )
    assert result.mutated is True
    assert design.bodies[0].position == [2.0, 10.0]


def test_add_ball_clamps_embedded_dynamic_position():
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="add_ball",
        args={"id": "ball1", "position": [0.0, 0.0], "radius": 0.5},
        enabled_tools=["add_ball"],
    )
    assert result.mutated is True
    assert design.bodies[0].position[1] >= 0.5


def test_joint_between_two_static_bodies_rejected():
    # A joint between two static bodies is invalid (pymunk needs one dynamic) and
    # would otherwise crash the whole simulation — reject it with feedback.
    design = DesignSpec(
        bodies=[
            BodySpec(id="beam1", shape=BodyShape.segment, static=True),
            BodySpec(id="beam2", shape=BodyShape.segment, static=True),
        ]
    )
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="add_joint",
        args={"id": "j1", "body_a": "beam1", "body_b": "beam2", "type": "pivot"},
        enabled_tools=["add_joint"],
    )
    assert result.mutated is False
    assert result.record.status == ToolCallStatus.rejected
    assert "movable" in (result.record.error or "")
    assert len(design.joints) == 0


def test_add_ramp_keeps_slope_angle():
    # A ramp from a high start to a low end must be an angled segment, not a flat
    # horizontal bar at the midpoint — otherwise nothing can ever roll/slide.
    import math

    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="add_ramp",
        args={"id": "r1", "start": [0.0, 4.0], "end": [8.0, 0.0]},
        enabled_tools=["add_ramp"],
    )
    assert result.mutated is True
    ramp = design.bodies[0]
    assert ramp.static is True
    # Downhill to the right → negative angle, matching atan2(-4, 8).
    assert ramp.angle == math.atan2(-4.0, 8.0)
    assert ramp.angle < 0.0


def test_add_bin_builds_open_container_not_a_solid_box():
    # A bin must be an open-top container a ball can physically fall into, not
    # one solid box — a solid box would stop the ball's center from ever
    # entering the bin's bounding region, so containment scoring could never
    # trigger from real physics (only from a scripted/direct position).
    design = DesignSpec()
    result = apply_tool_call(
        design, agent_id="a", tool="add_bin",
        args={"id": "b1", "position": [0.0, 2.0], "width": 2.0, "height": 4.0, "accepts": "red"},
        enabled_tools=["add_bin"],
    )
    assert result.mutated is True
    ids = {b.id for b in design.bodies}
    assert {"b1", "b1_floor", "b1_wall_l", "b1_wall_r"} <= ids
    floor = next(b for b in design.bodies if b.id == "b1_floor")
    wall_l = next(b for b in design.bodies if b.id == "b1_wall_l")
    wall_r = next(b for b in design.bodies if b.id == "b1_wall_r")
    sensor_body = next(b for b in design.bodies if b.id == "b1")
    # Floor/walls are real (non-sensor) colliders that physically catch a ball;
    # only the full-size visual prop is a sensor (announces "this is the bin"
    # without blocking anything).
    assert floor.sensor is False and wall_l.sensor is False and wall_r.sensor is False
    assert sensor_body.sensor is True
    assert sensor_body.kind == "bin"
    # The walls must be narrower than the bin so there's an open interior gap
    # between them for something to fall through.
    assert wall_l.position[0] + wall_l.size[0] < wall_r.position[0] - wall_r.size[0]
    assert design.metadata["bins"] == [
        {"id": "b1", "x": 0.0, "y": 2.0, "width": 2.0, "height": 4.0, "accepts": "red"}
    ]


def test_add_bin_rejects_duplicate_id_including_sub_parts():
    design = DesignSpec(
        bodies=[BodySpec(id="b1_floor", shape=BodyShape.box, static=True)],
    )
    result = apply_tool_call(
        design, agent_id="a", tool="add_bin",
        args={"id": "b1", "position": [0.0, 2.0], "width": 2.0, "height": 4.0},
        enabled_tools=["add_bin"],
    )
    assert result.mutated is False
    assert result.record.status == ToolCallStatus.rejected


def test_add_bin_rejects_degenerate_width():
    # A tiny/negative width would produce a degenerate (or, pre-validation,
    # negative-position) floor/wall geometry — reject before it reaches physics.
    design = DesignSpec()
    result = apply_tool_call(
        design, agent_id="a", tool="add_bin",
        args={"id": "b1", "position": [0.0, 2.0], "width": -1.0, "height": 4.0},
        enabled_tools=["add_bin"],
    )
    assert result.mutated is False
    assert result.record.status == ToolCallStatus.rejected
    assert len(design.bodies) == 0


def test_disabled_tool_rejected():
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"id": "b1", "shape": "box"},
        enabled_tools=["add_joint"],  # create_body not enabled
    )
    assert result.mutated is False
    assert result.record.status == ToolCallStatus.rejected
    assert result.record.error == "tool not enabled"
    assert len(design.bodies) == 0


def test_invalid_args_rejected():
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"shape": "box"},  # missing required 'id'
        enabled_tools=_ENABLED,
    )
    assert result.mutated is False
    assert result.record.status == ToolCallStatus.rejected
    assert result.record.error is not None
    assert "invalid args" in result.record.error
    assert len(design.bodies) == 0


def test_add_joint_requires_bodies():
    design = DesignSpec()
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="add_joint",
        args={"id": "j1", "body_a": "x", "body_b": "y", "type": "pivot"},
        enabled_tools=_ENABLED,
    )
    assert result.mutated is False
    assert result.record.status == ToolCallStatus.rejected
    assert len(design.joints) == 0
