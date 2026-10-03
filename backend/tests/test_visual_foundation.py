"""Visual foundation: semantic kind end-to-end (design -> trace -> summary)."""
from __future__ import annotations

from agentgymnasium.agents.prompts import build_system_prompt
from agentgymnasium.core.schemas.design import BodyShape, BodySpec, DesignSpec, JointSpec
from agentgymnasium.core.schemas.setup import WorldConfig
from agentgymnasium.engines.pymunk2d.engine import Pymunk2DEngine
from agentgymnasium.services.orchestrator import _design_summary
from agentgymnasium.tools.apply import apply_tool_call
from agentgymnasium.tools.registry import get_tool

_BUILD = ["create_body", "add_beam", "add_ramp", "add_ball", "add_bin"]


def test_create_body_records_kind():
    d = DesignSpec(name="t")
    apply_tool_call(
        d, agent_id="a", tool="create_body",
        args={"id": "h1", "shape": "box", "position": [0.0, 5.0], "kind": "house"},
        enabled_tools=_BUILD,
    )
    assert d.bodies[0].kind == "house"


def test_builder_tools_default_kind():
    d = DesignSpec(name="t")
    apply_tool_call(
        d, agent_id="a", tool="add_beam",
        args={"id": "beam1", "start": [0.0, 1.0], "end": [3.0, 1.0]},
        enabled_tools=_BUILD,
    )
    apply_tool_call(
        d, agent_id="a", tool="add_ball",
        args={"id": "ball1", "position": [0.0, 5.0]}, enabled_tools=_BUILD,
    )
    kinds = {b.id: b.kind for b in d.bodies}
    assert kinds["beam1"] == "beam"
    assert kinds["ball1"] == "ball"


def test_create_body_kind_arg_in_schema():
    assert "kind" in get_tool("create_body").input_schema["properties"]


def test_trace_carries_kind_in_body_meta():
    design = DesignSpec(
        name="t",
        bodies=[
            BodySpec(id="h1", shape=BodyShape.box, position=[0.0, 5.0], size=[2.0, 2.0], kind="house"),
            BodySpec(id="wall", shape=BodyShape.box, position=[3.0, 0.0], size=[1.0, 3.0], static=True, kind="wall"),
        ],
    )
    trace = Pymunk2DEngine().simulate(design, WorldConfig(template="tiny_city_block", terrain="city"), 0.1)
    # Dynamic body's BodyMeta carries its semantic kind + real size.
    assert trace.body_meta["h1"].kind == "house"
    assert trace.body_meta["h1"].size == [2.0, 2.0]
    # Static prop kind prefers the semantic label.
    wall_prop = next(p for p in trace.world_static if p.id == "wall")
    assert wall_prop.kind == "wall"
    # Terrain threaded through (PR #6 field).
    assert trace.terrain == "city"


def test_trace_carries_theme_material_seed_and_joint_metadata():
    design = DesignSpec(
        name="visual-contract",
        bodies=[
            BodySpec(
                id="torso",
                shape=BodyShape.box,
                position=[0.0, 2.0],
                material="rubber",
                kind="torso",
                created_by="agent_a",
            ),
            BodySpec(
                id="leg",
                shape=BodyShape.segment,
                position=[0.0, 1.0],
                material="wood",
                kind="leg",
            ),
        ],
        joints=[
            JointSpec(
                id="hip",
                body_a="torso",
                body_b="leg",
                anchor_a=[0.2, -0.2],
                anchor_b=[-0.3, 0.0],
                motor_rate=1.5,
            )
        ],
    )
    world = WorldConfig(
        template="flat_arena",
        visual_style="neon_lab",
        seed=73,
    )

    first = Pymunk2DEngine().simulate(design, world, 0.1)
    second = Pymunk2DEngine().simulate(design, world, 0.1)

    assert first.version == 3
    assert first.visual_style == "neon_lab"
    assert first.visual_seed == 73
    assert first.body_meta["torso"].visual.material == "rubber"
    assert first.body_meta["torso"].visual.seed == second.body_meta["torso"].visual.seed
    assert first.body_meta["torso"].created_by == "agent_a"
    assert first.joints[0].id == "hip"
    assert first.joints[0].anchor_a == [0.2, -0.2]
    assert first.joints[0].motor_rate == 1.5
    initial_types = {event["type"] for event in first.frames[0].events}
    assert {"body_created", "joint_attached", "motor_activated"} <= initial_types


def test_old_trace_payload_gets_backwards_compatible_visual_defaults():
    from agentgymnasium.core.schemas.trace import EpisodeTrace

    trace = EpisodeTrace.model_validate(
        {
            "version": 2,
            "run_id": "old",
            "dt": 0.1,
            "world_static": [],
            "frames": [],
        }
    )

    assert trace.visual_style == "realistic"
    assert trace.visual_seed == 0
    assert trace.joints == []


def test_old_design_without_kind_defaults_to_none():
    design = DesignSpec(
        name="t",
        bodies=[BodySpec(id="b1", shape=BodyShape.box, position=[0.0, 5.0])],
    )
    trace = Pymunk2DEngine().simulate(design, WorldConfig(template="flat_arena"), 0.05)
    assert trace.body_meta["b1"].kind is None


def test_prompt_includes_kind_guidance_when_buildable():
    prompt = build_system_prompt("Lay out a small city", "city terrain", [get_tool("create_body")])
    assert "kind" in prompt.lower()
    assert "house" in prompt.lower()  # city palette hint


def test_prompt_omits_kind_guidance_without_build_tools():
    prompt = build_system_prompt("Inspect only", "flat", [get_tool("run_simulation")])
    assert "recognizable prop" not in prompt


def test_design_summary_by_kind():
    design = DesignSpec(
        name="t",
        bodies=[
            BodySpec(id="h1", shape=BodyShape.box, kind="house", created_by="agent_a"),
            BodySpec(id="h2", shape=BodyShape.box, kind="house", created_by="agent_a"),
            BodySpec(id="t1", shape=BodyShape.box, kind="tower", created_by="agent_a"),
            BodySpec(id="b1", shape=BodyShape.segment, static=True, kind="beam", created_by="agent_a"),
        ],
    )
    summary = _design_summary(design)
    assert summary["by_kind"] == {"house": 2, "tower": 1, "beam": 1}
    assert summary["beams"] == 1  # derived from kind, not hardcoded 0
