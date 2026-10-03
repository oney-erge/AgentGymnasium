from agentgymnasium.agents.mock_provider import _calls_for_prompt
from agentgymnasium.agents.runner import _project_name
from agentgymnasium.core.schemas.design import DesignSpec
from agentgymnasium.core.schemas.setup import LaunchConfig, ScenarioConfig, WorldConfig
from agentgymnasium.tools.apply import apply_tool_call


def test_create_body_preserves_semantic_color() -> None:
    design = DesignSpec(name="city")

    result = apply_tool_call(
        design,
        "agent_a",
        "create_body",
        {
            "id": "corner_shop",
            "shape": "box",
            "kind": "shop",
            "color": "#38bdf8",
            "position": [0.0, 1.5],
            "width": 2.0,
            "height": 3.0,
            "static": True,
        },
        ["create_body"],
    )

    assert result.mutated
    assert design.bodies[0].kind == "shop"
    assert design.bodies[0].color == "#38bdf8"


def test_structural_tools_preserve_semantic_color() -> None:
    design = DesignSpec(name="bridge")

    apply_tool_call(
        design,
        "agent_a",
        "add_beam",
        {
            "id": "wood_span",
            "start": [-2.0, 1.0],
            "end": [2.0, 1.0],
            "kind": "beam",
            "color": "#8b5a2b",
        },
        ["add_beam"],
    )

    assert design.bodies[0].kind == "beam"
    assert design.bodies[0].color == "#8b5a2b"


def test_mock_city_prompt_builds_city_semantics() -> None:
    calls = _calls_for_prompt("", "Achieve: Build a small city block with a park.")
    kinds = {call["args"].get("kind") for call in calls if call["tool"] == "create_body"}

    assert {"road", "park", "house", "tower", "shop", "tree"}.issubset(kinds)


def test_mock_challenge_prompts_route_to_distinct_visual_grammars() -> None:
    bridge_tools = {
        call["tool"] for call in _calls_for_prompt("", "Achieve: Build a bridge for the crate.")
    }
    crawl_tools = {
        call["tool"] for call in _calls_for_prompt("", "Achieve: Build a crawling creature.")
    }
    sorter_tools = {
        call["tool"] for call in _calls_for_prompt("", "Achieve: Sort balls into matching bins.")
    }

    assert "add_beam" in bridge_tools
    assert {"add_joint", "add_motor"}.issubset(crawl_tools)
    assert {"add_bin", "add_ramp"}.issubset(sorter_tools)


def test_stale_bridge_project_name_uses_selected_preset_name() -> None:
    config = LaunchConfig(
        project_name="Bridge Builder Lab",
        scenario=ScenarioConfig(preset="tiny_city_preview"),
        world=WorldConfig(template="tiny_city_block"),
    )

    assert _project_name(config) == "Tiny City Builder"
