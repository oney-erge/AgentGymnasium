from __future__ import annotations

import asyncio

from agentgymnasium.core.schemas.experiment import (
    ExperimentSpec,
    ExperimentStatus,
    ModelVariant,
)
from agentgymnasium.core.schemas.setup import (
    AgentConfig,
    AgentsConfig,
    ConstraintsConfig,
    LaunchConfig,
    LLMProvider,
    ScenarioConfig,
    ToolsConfig,
    WorldConfig,
)
from agentgymnasium.services.experiment_service import ExperimentManager
from agentgymnasium.services.orchestrator import RunManager


def _base_config() -> LaunchConfig:
    return LaunchConfig(
        scenario=ScenarioConfig(
            preset="tiny_city_preview",
            objective="Build a small city",
            reward="city_score",
        ),
        world=WorldConfig(template="tiny_city_block"),
        agents=AgentsConfig(
            participants=[
                AgentConfig(
                    id="agent_a",
                    name="Agent A",
                    provider=LLMProvider.mock,
                    model="mock",
                )
            ]
        ),
        tools=ToolsConfig(enabled=["create_body", "run_simulation"]),
        constraints=ConstraintsConfig(
            max_attempts=1,
            simulation_duration_seconds=1,
            agent_turns_per_attempt=1,
        ),
    )


def test_experiment_matrix_runs_and_aggregates(tmp_path):
    async def scenario():
        manager = ExperimentManager(root=tmp_path, runs=RunManager())
        record = await manager.create(
            ExperimentSpec(
                name="comparison",
                base_config=_base_config(),
                models=[
                    ModelVariant(
                        id="model-a",
                        label="Model A",
                        provider=LLMProvider.mock,
                        model="mock-a",
                    ),
                    ModelVariant(
                        id="model-b",
                        label="Model B",
                        provider=LLMProvider.mock,
                        model="mock-b",
                    ),
                ],
                seeds=[7, 11],
                repeats=1,
            )
        )
        finished = await manager.wait(record.id)
        assert finished is not None
        return manager, finished

    manager, finished = asyncio.run(scenario())

    assert finished.status == ExperimentStatus.completed
    assert len(finished.cells) == 4
    assert all(cell.trace_run_id for cell in finished.cells)
    aggregates = manager.aggregates(finished.id)
    assert aggregates is not None
    assert {a.model_variant_id for a in aggregates} == {"model-a", "model-b"}
    assert all(a.n == 2 for a in aggregates)
    assert all(0.0 <= a.success_rate <= 1.0 for a in aggregates)
    pairwise = manager.pairwise(finished.id)
    assert pairwise is not None
    assert len(pairwise) == 1
    assert pairwise[0].n_pairs == 2
    assert pairwise[0].wins_a + pairwise[0].ties + pairwise[0].wins_b == 2
    assert (tmp_path / f"{finished.id}.json").is_file()


def test_experiment_persistence_redacts_all_keys(tmp_path):
    async def scenario():
        manager = ExperimentManager(root=tmp_path, runs=RunManager())
        config = _base_config()
        config.llm_connection.api_key = "shared-secret"
        config.agents.participants[0].api_key = "agent-secret"
        record = await manager.create(
            ExperimentSpec(
                base_config=config,
                models=[
                    ModelVariant(
                        id="m",
                        label="M",
                        provider=LLMProvider.mock,
                        model="mock",
                        api_key="variant-secret",
                    )
                ],
            )
        )
        await manager.wait(record.id)
        return record.id

    experiment_id = asyncio.run(scenario())
    raw = (tmp_path / f"{experiment_id}.json").read_text(encoding="utf-8")
    assert "shared-secret" not in raw
    assert "agent-secret" not in raw
    assert "variant-secret" not in raw
