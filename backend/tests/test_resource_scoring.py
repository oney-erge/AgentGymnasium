from agentgymnasium.agents.runner import _apply_score_constraints
from agentgymnasium.core.schemas.design import BodySpec, DesignSpec, JointSpec
from agentgymnasium.core.schemas.score import ScoreCard
from agentgymnasium.core.schemas.setup import (
    AgentConfig,
    AgentsConfig,
    ConstraintsConfig,
    LaunchConfig,
    ScenarioConfig,
    WorldBounds,
    WorldConfig,
)


def _config() -> LaunchConfig:
    return LaunchConfig(
        scenario=ScenarioConfig(preset="distance"),
        world=WorldConfig(template="flat_ground"),
        agents=AgentsConfig(participants=[AgentConfig(id="a", name="A")]),
        constraints=ConstraintsConfig(
            energy_budget=10,
            material_budget=2000,
            world_bounds=WorldBounds.soft,
        ),
    )


def test_energy_budget_is_measured_and_can_fail_an_attempt():
    design = DesignSpec(
        bodies=[
            BodySpec(id="a", created_by="a", position=[20, 2]),
            BodySpec(id="b", created_by="a", position=[0, 2]),
        ],
        joints=[
            JointSpec(
                id="motor",
                body_a="a",
                body_b="b",
                motor_rate=10,
                motor_max_force=1000,
            )
        ],
    )
    raw = ScoreCard(score_total=100, success=True, reward="distance")
    score = _apply_score_constraints(raw, design, _config(), duration_s=10)

    assert score.metrics["motor_energy_estimate"] == 500
    assert score.metrics["out_of_bounds_parts"] == 1
    assert score.success is False
    assert any(event["type"] == "energy_budget_exceeded" for event in score.failure_events)
    assert any(event["type"] == "world_bounds_soft_penalty" for event in score.failure_events)
