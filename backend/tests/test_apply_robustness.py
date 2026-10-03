"""Adversarial tool-call validation at the apply chokepoint.

Untrusted agent args that could crash the physics engine (negative/zero mass,
malformed position, out-of-range friction) must be rejected here, leaving the
design unchanged.
"""

from __future__ import annotations

from agentgymnasium.core.schemas.design import DesignSpec
from agentgymnasium.tools.apply import apply_tool_call

_BUILD_TOOLS = ["create_body", "add_ball", "set_friction"]


def _apply(design: DesignSpec, tool: str, args: dict):
    return apply_tool_call(design, agent_id="a", tool=tool, args=args, enabled_tools=_BUILD_TOOLS)


def test_negative_mass_rejected():
    design = DesignSpec()
    res = _apply(design, "create_body", {"id": "b", "shape": "box", "mass": -1.0})
    assert res.record.status.value == "rejected"
    assert not design.bodies


def test_zero_mass_rejected():
    design = DesignSpec()
    res = _apply(design, "create_body", {"id": "b", "shape": "circle", "mass": 0.0})
    assert res.record.status.value == "rejected"
    assert not design.bodies


def test_short_position_rejected():
    design = DesignSpec()
    res = _apply(design, "add_ball", {"id": "b", "position": [1.0]})
    assert res.record.status.value == "rejected"
    assert not design.bodies


def test_non_numeric_position_rejected():
    design = DesignSpec()
    res = _apply(design, "create_body", {"id": "b", "shape": "box", "position": ["x", "y"]})
    assert res.record.status.value == "rejected"
    assert not design.bodies


def test_out_of_range_friction_rejected():
    design = DesignSpec()
    _apply(design, "create_body", {"id": "b", "shape": "box"})
    res = _apply(design, "set_friction", {"body_id": "b", "friction": 50.0})
    assert res.record.status.value == "rejected"
    # body still present, friction unchanged from its default
    assert design.bodies[0].friction != 50.0


def test_valid_body_still_accepted():
    design = DesignSpec()
    res = _apply(design, "create_body", {"id": "b", "shape": "box", "mass": 1.5, "position": [0.0, 2.0]})
    assert res.record.status.value == "success"
    assert len(design.bodies) == 1
