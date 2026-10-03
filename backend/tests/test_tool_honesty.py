"""Honesty pass: tools mutate, inspect, or reject — never silently no-op."""
from __future__ import annotations

import pytest

from agentgymnasium.core.schemas.design import BodySpec, DesignSpec
from agentgymnasium.core.schemas.setup import WorldConfig
from agentgymnasium.engines.pymunk2d.builder import build_space
from agentgymnasium.tools.apply import apply_tool_call
from agentgymnasium.tools.registry import get_tool

_ALL = [
    "set_density", "set_gravity", "add_sensor", "set_controller",
    "mutate_design", "repair_invalid_design", "get_state", "create_body",
]


def _design_with_body() -> DesignSpec:
    return DesignSpec(
        name="t",
        bodies=[BodySpec(id="b1", shape="box", position=[0.0, 5.0], size=[2.0, 1.0], mass=1.0)],
    )


def test_set_density_changes_mass():
    d = _design_with_body()
    r = apply_tool_call(
        d, agent_id="a", tool="set_density",
        args={"body_id": "b1", "density": 5.0}, enabled_tools=_ALL,
    )
    assert r.record.status.value.lower() == "success"
    # box area = 2*1 = 2; mass = density(5) * area(2) = 10.
    assert d.bodies[0].mass == pytest.approx(10.0)


def test_set_density_rejects_unknown_body():
    d = _design_with_body()
    r = apply_tool_call(
        d, agent_id="a", tool="set_density",
        args={"body_id": "nope", "density": 5.0}, enabled_tools=_ALL,
    )
    assert r.record.status.value.lower() == "rejected"


def test_set_gravity_honored_by_engine():
    d = _design_with_body()
    apply_tool_call(
        d, agent_id="a", tool="set_gravity", args={"gravity": -20.0}, enabled_tools=_ALL,
    )
    assert d.metadata["gravity_override"] == -20.0
    space, _ = build_space(d, WorldConfig(template="flat_arena"))
    assert space.gravity.y == pytest.approx(-20.0)


def test_experimental_tools_rejected_not_silent_noop():
    d = _design_with_body()
    for tool in ("add_sensor", "set_controller", "mutate_design", "repair_invalid_design"):
        r = apply_tool_call(d, agent_id="a", tool=tool, args={}, enabled_tools=_ALL)
        assert r.record.status.value.lower() == "rejected", tool
        assert "experimental" in (r.record.error or ""), tool
        assert r.mutated is False


def test_experimental_tools_off_by_default():
    for tool in ("add_sensor", "set_controller", "set_collision_group",
                 "mutate_design", "repair_invalid_design"):
        d = get_tool(tool)
        assert d is not None
        assert d.status.value == "experimental", tool
        assert d.enabled_by_default is False, tool


def test_inspection_tools_marked_and_dont_mutate():
    d = _design_with_body()
    before = d.model_dump()
    r = apply_tool_call(d, agent_id="a", tool="get_state", args={}, enabled_tools=_ALL)
    # Inspection tools legitimately succeed without mutating the design.
    assert r.record.status.value.lower() == "success"
    assert r.mutated is False
    assert d.model_dump() == before
    assert get_tool("get_state").status.value == "inspection"
