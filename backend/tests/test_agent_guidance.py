"""What an agent is told about the world, and the payload a challenge moves."""

import pytest

from agentgymnasium.agents import runner
from agentgymnasium.agents.prompts import build_system_prompt
from agentgymnasium.core.schemas.design import DesignSpec, payload_ids
from agentgymnasium.core.schemas.setup import LaunchConfig
from agentgymnasium.tools.apply import apply_tool_call


def _seeded(preset_name: str, template: str) -> tuple[LaunchConfig, object, DesignSpec]:
    config = LaunchConfig.model_validate(
        {
            "scenario": {"preset": preset_name},
            "world": {"template": template, "seed": 7},
            "agents": {"mode": "single", "participants": [{"id": "a", "name": "A"}]},
        }
    )
    preset = runner.get_scenario_preset(preset_name)
    design = DesignSpec(name="d")
    runner._seed_world(design, config)
    runner._seed_scaffold(design, preset)
    return config, preset, design


def test_the_bridge_world_says_where_the_floor_stops_and_how_big_each_part_is():
    config, preset, design = _seeded("bridge_builder", "island_cliff_small")
    text = runner._world_context(config, preset, design)
    assert "There is NO floor for x -10.5 to 2" in text
    assert "flat solid floor" not in text
    assert "right_cliff (fixed box, 12 x 1.5 m, x 2.00 to 14.00, top at y=1.50)" in text
    assert "left_slope (fixed segment, from [-13.61, 5.95] to [-4.39, 2.05])" in text
    assert "crate (movable circle, radius 0.6 m, center [-12.0, 7.5]; the object to move" in text


def test_a_world_payload_replaces_the_rule_to_add_a_movable_body():
    _, _, design = _seeded("bridge_builder", "island_cliff_small")
    assert payload_ids(design) == ["crate"]
    prompt = build_system_prompt("obj", "world", [], payloads=payload_ids(design))
    assert "moving on their own: crate. Do NOT create another one" in prompt
    assert "MUST include at least one MOVABLE" not in prompt
    # Without a payload the old rule stands.
    assert "MUST include at least one MOVABLE" in build_system_prompt("obj", "world", [])


def test_joining_the_payload_is_refused_with_the_reason():
    _, _, design = _seeded("bridge_builder", "island_cliff_small")
    apply_tool_call(
        design,
        agent_id="a",
        tool="create_body",
        args={"id": "post", "shape": "box", "position": [4.0, 2.0], "width": 0.5, "height": 0.5},
        enabled_tools=["create_body", "add_joint"],
    )
    result = apply_tool_call(
        design,
        agent_id="a",
        tool="add_joint",
        args={"id": "j", "body_a": "crate", "body_b": "post", "type": "pivot"},
        enabled_tools=["create_body", "add_joint"],
    )
    assert not result.mutated
    assert "'crate' is what this challenge moves" in (result.record.error or "")


@pytest.mark.parametrize("preset_name", ["crawl_challenge"])
def test_a_movable_part_the_agent_extends_is_not_a_payload(preset_name):
    # The crawl challenge's torso is the agent's own creature to build on, not cargo.
    preset = runner.get_scenario_preset(preset_name)
    if preset is None:
        pytest.skip(f"no {preset_name} preset")
    design = DesignSpec(name="d")
    runner._seed_scaffold(design, preset)
    assert "torso" in {b.id for b in design.bodies}
    assert "torso" not in payload_ids(design)
