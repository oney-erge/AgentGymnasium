from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import HTTPException

from agentgymnasium.api import routes_experiments
from agentgymnasium.core.schemas.experiment import (
    CellStatus,
    ExperimentCell,
    ExperimentRecord,
    ExperimentSpec,
    ExperimentStatus,
    ModelVariant,
    ResumeExperimentRequest,
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
from agentgymnasium.services.experiment_service import ExperimentManager, _mean_interval
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


def test_student_t_interval_requires_two_observations_and_uses_small_sample_critical_value():
    assert _mean_interval([]) == (None, None)
    assert _mean_interval([2.0]) == (None, None)
    low, high = _mean_interval([1.0, 3.0])
    assert low == pytest.approx(2.0 - 12.706)
    assert high == pytest.approx(2.0 + 12.706)


def test_recovery_preserves_completed_and_does_not_replay_inflight_cells(tmp_path):
    spec = ExperimentSpec(
        base_config=_base_config(),
        models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
        seeds=[1, 2, 3],
    )
    record = ExperimentRecord(
        id="interrupted", spec=spec, created_at=time.time(), status=ExperimentStatus.running,
        recovery_safe=True,
        cells=[
            ExperimentCell(id="m:1:0", model_variant_id="m", model_label="M", seed=1,
                           repeat_index=0, status=CellStatus.completed, score=7),
            ExperimentCell(id="m:2:0", model_variant_id="m", model_label="M", seed=2,
                           repeat_index=0, status=CellStatus.running),
            ExperimentCell(id="m:3:0", model_variant_id="m", model_label="M", seed=3,
                           repeat_index=0),
        ],
    )
    (tmp_path / "interrupted.json").write_text(record.model_dump_json(), encoding="utf-8")
    manager = ExperimentManager(root=tmp_path, runs=RunManager())
    interrupted = manager.get(record.id)
    assert interrupted is not None and interrupted.interrupted
    assert [cell.status for cell in interrupted.cells] == [
        CellStatus.completed, CellStatus.failed, CellStatus.queued,
    ]
    visited = []

    async def fake_execute(_record, cell):
        visited.append(cell.seed)
        cell.status = CellStatus.completed
        cell.score = 9

    manager._execute_cell = fake_execute

    async def scenario():
        await manager.resume(record.id, {"m": "temporary-secret"})
        return await manager.wait(record.id)

    finished = asyncio.run(scenario())
    assert visited == [3]
    assert finished is not None and finished.cells[0].score == 7
    assert finished.cells[1].status == CellStatus.failed
    assert "temporary-secret" not in (tmp_path / "interrupted.json").read_text(encoding="utf-8")


def test_old_interrupted_record_cannot_resume(tmp_path):
    spec = ExperimentSpec(
        base_config=_base_config(),
        models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
    )
    record = ExperimentRecord(id="old", spec=spec, created_at=time.time(),
                              status=ExperimentStatus.running)
    (tmp_path / "old.json").write_text(record.model_dump_json(), encoding="utf-8")
    manager = ExperimentManager(root=tmp_path, runs=RunManager())
    with pytest.raises(ValueError, match="safely recorded"):
        asyncio.run(manager.resume("old", {}))


def test_resume_route_validates_pending_variants_and_redacts_keys(tmp_path, monkeypatch):
    spec = ExperimentSpec(
        base_config=_base_config(),
        models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
    )
    record = ExperimentRecord(
        id="resume-route", spec=spec, created_at=time.time(), status=ExperimentStatus.running,
        recovery_safe=True,
        cells=[ExperimentCell(id="m:1:0", model_variant_id="m", model_label="M", seed=1,
                              repeat_index=0)],
    )
    (tmp_path / "resume-route.json").write_text(record.model_dump_json(), encoding="utf-8")
    manager = ExperimentManager(root=tmp_path, runs=RunManager())
    monkeypatch.setattr(routes_experiments, "experiment_manager", manager)
    validated = []

    async def validate(specification):
        validated.append([(model.id, model.api_key) for model in specification.models])

    async def execute(_record, cell):
        cell.status = CellStatus.completed
        cell.score = 1

    monkeypatch.setattr(routes_experiments, "_validate_spec", validate)
    monkeypatch.setattr(manager, "_execute_cell", execute)

    async def scenario():
        with pytest.raises(HTTPException) as error:
            await routes_experiments.resume_experiment(
                record.id, ResumeExperimentRequest(api_keys={"wrong": "secret"})
            )
        assert error.value.status_code == 409
        resumed = await routes_experiments.resume_experiment(
            record.id, ResumeExperimentRequest(api_keys={"m": "secret"})
        )
        assert resumed.spec.models[0].api_key is None
        await manager.wait(record.id)

    asyncio.run(scenario())
    assert validated == [[("m", "secret")]]
    assert "secret" not in (tmp_path / "resume-route.json").read_text(encoding="utf-8")


def test_loading_record_with_mismatched_filename_cannot_write_elsewhere(tmp_path):
    spec = ExperimentSpec(
        base_config=_base_config(),
        models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
    )
    record = ExperimentRecord(id="../outside", spec=spec, created_at=time.time(),
                              status=ExperimentStatus.running)
    (tmp_path / "record.json").write_text(record.model_dump_json(), encoding="utf-8")
    manager = ExperimentManager(root=tmp_path, runs=RunManager())
    assert manager.get("../outside") is None
    assert not (tmp_path.parent / "outside.json").exists()


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
