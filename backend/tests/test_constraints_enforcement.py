"""max_parts / max_joints budgets are enforced at the apply chokepoint."""
from __future__ import annotations

from agentgymnasium.core.schemas.design import DesignSpec
from agentgymnasium.tools.apply import apply_tool_call, material_units

_BUILD_TOOLS = ["create_body", "add_ball", "add_joint"]


def _add_body(design: DesignSpec, bid: str, max_parts: int | None = None):
    return apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"id": bid, "shape": "box", "position": [0.0, 5.0]},
        enabled_tools=_BUILD_TOOLS,
        max_parts=max_parts,
    )


def test_max_parts_rejects_over_budget():
    design = DesignSpec(name="t")
    # Budget of 2: first two succeed, third rejected.
    assert _add_body(design, "b1", max_parts=2).mutated
    assert _add_body(design, "b2", max_parts=2).mutated
    result = _add_body(design, "b3", max_parts=2)
    assert not result.mutated
    assert result.record.status.value.lower() == "rejected"
    assert "max_parts" in (result.record.error or "")
    assert len(design.bodies) == 2


def test_max_parts_none_is_unlimited():
    design = DesignSpec(name="t")
    for i in range(5):
        assert _add_body(design, f"b{i}", max_parts=None).mutated
    assert len(design.bodies) == 5


def test_max_joints_rejects_over_budget():
    design = DesignSpec(name="t")
    _add_body(design, "b1")
    _add_body(design, "b2")
    _add_body(design, "b3")

    def add_joint(jid: str, a: str, b: str):
        return apply_tool_call(
            design,
            agent_id="a",
            tool="add_joint",
            args={"id": jid, "body_a": a, "body_b": b, "type": "pivot"},
            enabled_tools=_BUILD_TOOLS,
            max_joints=1,
        )

    assert add_joint("j1", "b1", "b2").mutated
    result = add_joint("j2", "b2", "b3")
    assert not result.mutated
    assert "max_joints" in (result.record.error or "")
    assert len(design.joints) == 1


def test_material_budget_rejects_before_mutating():
    design = DesignSpec(name="t")
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={
            "id": "large",
            "shape": "box",
            "position": [0, 5],
            "width": 10,
            "height": 10,
        },
        enabled_tools=_BUILD_TOOLS,
        material_budget=100,
    )
    assert not result.mutated
    assert "material_budget" in (result.record.error or "")
    assert material_units(design) == 0


def test_world_bounds_and_strict_spawn_safety_are_real_constraints():
    design = DesignSpec(name="t")
    outside = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"id": "outside", "shape": "box", "position": [9, 5]},
        enabled_tools=_BUILD_TOOLS,
        world_bounds=(-2, 2, 0, 10),
    )
    assert not outside.mutated
    assert "world_bounds" in (outside.record.error or "")

    assert _add_body(design, "first").mutated
    collision = apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"id": "stacked", "shape": "box", "position": [0, 5]},
        enabled_tools=_BUILD_TOOLS,
        strict_collision=True,
    )
    assert not collision.mutated
    assert "strict collision safety" in (collision.record.error or "")
