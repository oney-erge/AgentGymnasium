"""CityEngine (layout + economy, no physics): engine, layout helpers, scoring,
and the end-to-end mock pipeline for the new isometric city challenges."""

import asyncio

from agentgymnasium.agents.runner import run_single_attempt
from agentgymnasium.core.schemas.design import BodyShape, BodySpec, DesignSpec
from agentgymnasium.core.schemas.setup import (
    AgentConfig,
    AgentsConfig,
    LaunchConfig,
    LLMProvider,
    ScenarioConfig,
    ToolsConfig,
    WorldConfig,
)
from agentgymnasium.engines import get_engine
from agentgymnasium.engines.citysim import layout
from agentgymnasium.engines.citysim.engine import CityEngine
from agentgymnasium.services.preset_service import get_scenario_preset, get_world_template
from agentgymnasium.services.run_service import get_trace
from agentgymnasium.services.scoring_service import REWARDS, compute_city_metrics, score_attempt


def _world() -> WorldConfig:
    return WorldConfig(template="city_grid", engine="citysim", terrain="city", map_size=[40, 40])


def _road(x: float = 0.0, z: float = 0.0, width: float = 10.0, depth: float = 3.0) -> BodySpec:
    return BodySpec(
        id="road1", shape=BodyShape.box, kind="road", position=[x, 0.0], z=z,
        size=[width, 0.2], depth=depth, static=True, created_by="a",
    )


def _house(bid: str, x: float, z: float, height: float = 3.0) -> BodySpec:
    return BodySpec(
        id=bid, shape=BodyShape.box, kind="house", position=[x, height / 2.0], z=z,
        size=[2.0, height], static=True, created_by="a",
    )


# ── layout helpers ───────────────────────────────────────────────────────────


def test_zone_of_classifies_known_kinds():
    assert layout.zone_of("house") == "residential"
    assert layout.zone_of("apartment") == "residential"
    assert layout.zone_of("tower") == "residential"
    assert layout.zone_of("shop") == "commercial"
    assert layout.zone_of("factory") == "industrial"
    assert layout.zone_of("power_plant") == "industrial"
    assert layout.zone_of("school") == "civic"
    assert layout.zone_of("hospital") == "civic"
    assert layout.zone_of("park") == "green"
    assert layout.zone_of("tree") == "green"
    assert layout.zone_of("road") == "road"
    assert layout.zone_of(None) == "other"
    assert layout.zone_of("crate") == "other"


def test_capacity_scales_with_height():
    short = _house("h1", 0.0, 0.0, height=3.0)
    tall = _house("h2", 0.0, 0.0, height=6.0)
    assert layout.capacity_of(tall) > layout.capacity_of(short)


def test_is_connected_near_vs_far_from_road():
    road = _road()  # width=10 (half=5), depth=3 (half=1.5), centered at (0,0)
    near = _house("near", 2.0, 2.0)  # dz edge distance = 0.5 -> connected
    far = _house("far", 2.0, 20.0)  # dz edge distance = 18.5 -> not connected
    assert layout.is_connected(near, [road]) is True
    assert layout.is_connected(far, [road]) is False


def test_footprint_overlap_2d():
    a = _house("a", 0.0, 0.0)  # 2x2 footprint (depth defaults to width)
    b = _house("b", 1.0, 0.0)  # overlaps a by 1m in x, full depth in z
    c = _house("c", 10.0, 0.0)  # far away, no overlap
    assert layout.footprint_overlap_2d(a, b) > 0.0
    assert layout.footprint_overlap_2d(a, c) == 0.0


# ── CityEngine ────────────────────────────────────────────────────────────────


def test_get_engine_citysim():
    assert isinstance(get_engine("citysim"), CityEngine)


def test_city_engine_produces_iso_trace_with_ticks():
    design = DesignSpec(
        name="t",
        bodies=[_road(), _house("h1", 2.0, 2.0), _house("h2", 2.0, 20.0)],
    )
    trace = CityEngine().simulate(design, _world(), duration_seconds=5.0)
    assert trace.engine == "citysim"
    assert trace.camera == "iso"
    assert len(trace.frames) == 5
    for frame in trace.frames:
        assert frame.bodies == {}  # citysim has no rigid-body motion
        tick = frame.events[0]
        assert tick["type"] == "city_tick"
    # Every body (agent-built here) becomes a static prop, keeping its z/depth.
    prop_ids = {p.id for p in trace.world_static}
    assert prop_ids == {"road1", "h1", "h2"}
    h2_prop = next(p for p in trace.world_static if p.id == "h2")
    assert h2_prop.z == 20.0


def test_city_engine_population_grows_only_when_connected():
    design = DesignSpec(name="t", bodies=[_road(), _house("h1", 2.0, 2.0)])
    trace = CityEngine().simulate(design, _world(), duration_seconds=10.0)
    ticks = [f.events[0] for f in trace.frames]
    populations = [t["population"] for t in ticks]
    # Population should rise monotonically toward (but not exceed) capacity.
    assert all(b >= a - 1e-9 for a, b in zip(populations, populations[1:], strict=False))
    assert populations[-1] > 0.0
    assert populations[-1] < layout.capacity_of(design.bodies[1])
    assert all(t["connectivity_fraction"] == 1.0 for t in ticks)

    disconnected = DesignSpec(name="t", bodies=[_road(), _house("h1", 2.0, 20.0)])
    trace2 = CityEngine().simulate(disconnected, _world(), duration_seconds=10.0)
    ticks2 = [f.events[0] for f in trace2.frames]
    assert all(t["population"] == 0.0 for t in ticks2)
    assert all(t["connectivity_fraction"] == 0.0 for t in ticks2)


def test_city_engine_budget_tracks_upkeep_with_no_income():
    design = DesignSpec(name="t", bodies=[_road(), _house("h1", 2.0, 2.0)])
    trace = CityEngine().simulate(design, _world(), duration_seconds=4.0)
    # No commercial/industrial -> no income; upkeep = 1 residential*1.0 + 1 road*0.5.
    final_budget = trace.frames[-1].events[0]["budget"]
    assert final_budget == 1000.0 - 4 * 1.5


def test_city_engine_respects_starting_budget_metadata():
    design = DesignSpec(name="t", bodies=[_road()], metadata={"starting_budget": 50.0})
    trace = CityEngine().simulate(design, _world(), duration_seconds=1.0)
    # One road, no residential -> upkeep = 0.5, no income.
    assert trace.frames[0].events[0]["budget"] == 49.5


# ── scoring ───────────────────────────────────────────────────────────────────


def test_compute_city_metrics_from_trace():
    design = DesignSpec(name="t", bodies=[_road(), _house("h1", 2.0, 2.0)])
    trace = CityEngine().simulate(design, _world(), duration_seconds=3.0)
    metrics = compute_city_metrics(trace, design)
    assert metrics["road_count"] == 1.0
    assert metrics["residential_count"] == 1.0
    assert metrics["zoned_count"] == 1.0
    assert metrics["connectivity_fraction"] == 1.0
    assert metrics["population"] > 0.0
    assert metrics["budget"] == 1000.0 - 3 * 1.5


def test_score_attempt_routes_city_reward_through_city_metrics():
    design = DesignSpec(name="t", bodies=[_road(), _house("h1", 2.0, 2.0)])
    trace = CityEngine().simulate(design, _world(), duration_seconds=3.0)
    card = score_attempt(trace, design, "city_planning")
    assert card.reward == "city_planning"
    assert "population" in card.metrics
    assert "distance_m" not in card.metrics


def test_reward_city_planning_success():
    m = {
        "population": 25.0, "connectivity_fraction": 0.8, "green_count": 2.0,
        "zoned_count": 6.0, "overlap_total": 0.0,
    }
    score, success, _ = REWARDS["city_planning"](m)
    assert success is True
    assert score > 0.0


def test_reward_boomtown_threshold():
    below = REWARDS["boomtown"]({"population": 39.9, "connectivity_fraction": 1.0})
    above = REWARDS["boomtown"]({"population": 40.0, "connectivity_fraction": 1.0})
    assert below[1] is False
    assert above[1] is True


def test_reward_budget_city_success():
    m = {"budget": 1500.0, "zoned_count": 4.0}
    score, success, _ = REWARDS["budget_city"](m)
    assert success is True
    assert score > 0.0


def test_reward_balanced_city_even_split_succeeds():
    m = {
        "residential_count": 2.0, "commercial_count": 2.0, "industrial_count": 2.0,
        "happiness": 0.8, "green_count": 1.0, "zoned_count": 6.0,
    }
    score, success, _ = REWARDS["balanced_city"](m)
    assert success is True


def test_reward_balanced_city_lopsided_fails():
    m = {
        "residential_count": 6.0, "commercial_count": 0.0, "industrial_count": 0.0,
        "happiness": 0.8, "green_count": 1.0, "zoned_count": 6.0,
    }
    score, success, _ = REWARDS["balanced_city"](m)
    assert success is False


def test_reward_green_capital_success():
    m = {"pollution": 3.0, "population": 20.0, "green_count": 2.0}
    score, success, _ = REWARDS["green_capital"](m)
    assert success is True


# ── presets / world templates ────────────────────────────────────────────────


def test_city_grid_world_template_uses_citysim_engine():
    template = get_world_template("city_grid")
    assert template is not None
    assert template.engine.value == "citysim"
    assert template.starting_budget == 1200.0


def test_city_builder_preset_offers_reward_options():
    # One city challenge; its 5 scoring goals are a UI choice (reward_options),
    # not 5 separate challenges — the Setup screen's "City Goal" dropdown reads
    # this list and sets scenario.reward.
    preset = get_scenario_preset("city_builder")
    assert preset is not None
    assert preset.default_world == "city_grid"
    assert preset.reward == "city_planning"  # default/active reward
    option_values = {o.value for o in preset.reward_options}
    assert option_values == {
        "city_planning", "boomtown", "budget_city", "balanced_city", "green_capital",
    }
    assert option_values <= REWARDS.keys()


# ── end-to-end mock pipeline ──────────────────────────────────────────────────


def _city_builder_config(reward: str = "city_planning") -> LaunchConfig:
    return LaunchConfig(
        scenario=ScenarioConfig(preset="city_builder", reward=reward),
        world=WorldConfig(template="city_grid"),  # engine defaults pymunk2d here...
        agents=AgentsConfig(
            participants=[AgentConfig(id="a", name="Builder", provider=LLMProvider.mock)]
        ),
        tools=ToolsConfig(enabled=["create_body", "run_simulation"]),
    )


def test_city_builder_mock_end_to_end_uses_citysim_engine():
    # ...but _seed_world corrects it from the city_grid template, so the mock's
    # city build actually simulates through CityEngine (iso), not pymunk2d.
    result = asyncio.run(run_single_attempt(_city_builder_config()))
    assert result.trace_run_id is not None
    trace = get_trace(result.trace_run_id)
    assert trace.engine == "citysim"
    assert trace.camera == "iso"

    agent_bodies = [b for b in result.design.bodies if b.created_by == "a"]
    kinds = {b.kind for b in agent_bodies if b.kind}
    # Distinguishing kinds beyond the old single-row city demo (apartment/
    # factory/school) prove this routed to the tailored city-builder build.
    assert {"road", "house", "apartment", "shop", "factory", "school"} <= kinds
    # Real depth variety (not everything at z=0), proving the grid isn't a
    # degenerate single row like the old side-view city mock.
    z_values = {b.z for b in agent_bodies}
    assert len(z_values) > 1

    assert result.score.reward == "city_planning"
    assert "population" in result.score.metrics


def test_city_builder_reward_option_selects_a_different_scoring_goal():
    # Switching the reward_options selection (e.g. to "boomtown") must actually
    # change which reward scores the SAME build — proving the goal is a
    # scoring-time choice, not a separate challenge/build.
    result = asyncio.run(run_single_attempt(_city_builder_config(reward="boomtown")))
    assert result.score.reward == "boomtown"
    assert "population" in result.score.metrics
