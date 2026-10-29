from agentgymnasium.agents.runner import _benchmark_hash
from agentgymnasium.services.challenge_pack import case_config, list_cases
from agentgymnasium.services.preset_service import get_scenario_preset
from agentgymnasium.tools.registry import get_tool


def test_cases_resolve_fixed_gravity_and_do_not_allow_gravity_tool():
    pack = list_cases()
    assert len(pack["cases"]) == 6
    for case in pack["cases"]:
        config = case_config(case["id"])
        assert config is not None
        assert config.world.gravity == case["gravity"]
        assert config.world.visual_seed == 0
        assert config.agents.participants[0].provider.value == "mock"
        assert "set_gravity" not in config.tools.enabled
        assert config.constraints.max_attempts == 1


def test_benchmark_fingerprint_tracks_budget_but_not_visual_or_sampling_seed():
    config = case_config("bridge_builder-standard")
    assert config is not None
    preset = get_scenario_preset(config.scenario.preset)
    tools = [tool for name in config.tools.enabled if (tool := get_tool(name)) is not None]
    original = _benchmark_hash(config, preset, tools)
    config.world.seed = 42
    config.world.visual_seed = 99
    assert _benchmark_hash(config, preset, tools) == original
    config.constraints.max_attempts += 1
    assert _benchmark_hash(config, preset, tools) != original


def test_unknown_case_does_not_produce_a_configuration():
    assert case_config("not-a-case") is None
