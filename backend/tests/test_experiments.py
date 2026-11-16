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


def test_recovery_blocks_queued_work_when_inflight_cell_may_still_run(tmp_path, monkeypatch):
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
    assert not interrupted.recovery_safe
    assert interrupted.cells[0].score == 7
    monkeypatch.setattr(routes_experiments, "experiment_manager", manager)

    async def scenario():
        with pytest.raises(ValueError, match="safely recorded"):
            await manager.resume(record.id, {"m": "temporary-secret"})
        with pytest.raises(HTTPException) as error:
            await routes_experiments.resume_experiment(record.id, ResumeExperimentRequest())
        assert error.value.status_code == 409

    asyncio.run(scenario())
    assert not ExperimentManager(root=tmp_path, runs=RunManager()).get(record.id).recovery_safe
    assert "temporary-secret" not in (tmp_path / "interrupted.json").read_text(encoding="utf-8")


def test_recovery_can_resume_queued_cells_without_an_inflight_cell(tmp_path):
    spec = ExperimentSpec(
        base_config=_base_config(),
        models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
        seeds=[1, 2, 3],
    )
    record = ExperimentRecord(
        id="safe-interrupted", spec=spec, created_at=time.time(), status=ExperimentStatus.running,
        recovery_safe=True,
        cells=[
            ExperimentCell(id="m:1:0", model_variant_id="m", model_label="M", seed=1,
                           repeat_index=0, status=CellStatus.completed, score=7),
            ExperimentCell(id="m:2:0", model_variant_id="m", model_label="M", seed=2,
                           repeat_index=0, status=CellStatus.failed, error="A known earlier failure"),
            ExperimentCell(id="m:3:0", model_variant_id="m", model_label="M", seed=3,
                           repeat_index=0),
        ],
    )
    (tmp_path / "safe-interrupted.json").write_text(record.model_dump_json(), encoding="utf-8")
    manager = ExperimentManager(root=tmp_path, runs=RunManager())
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
    assert finished.status == ExperimentStatus.completed
    assert finished.outcome == "partial"
    assert finished.coverage["completed"] == 2
    assert finished.coverage["failed"] == 1
    assert "temporary-secret" not in (tmp_path / "safe-interrupted.json").read_text(encoding="utf-8")


def test_legacy_interrupted_inflight_record_cannot_resume(tmp_path):
    spec = ExperimentSpec(
        base_config=_base_config(),
        models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
        seeds=[1, 2],
    )
    record = ExperimentRecord(
        id="legacy-interrupted", spec=spec, created_at=time.time(), status=ExperimentStatus.failed,
        interrupted=True, recovery_safe=True,
        cells=[
            ExperimentCell(id="m:1:0", model_variant_id="m", model_label="M", seed=1,
                           repeat_index=0, status=CellStatus.failed,
                           error="Interrupted in flight; this cell was not retried."),
            ExperimentCell(id="m:2:0", model_variant_id="m", model_label="M", seed=2,
                           repeat_index=0),
        ],
    )
    (tmp_path / "legacy-interrupted.json").write_text(record.model_dump_json(), encoding="utf-8")
    manager = ExperimentManager(root=tmp_path, runs=RunManager())
    assert not manager.get(record.id).recovery_safe
    with pytest.raises(ValueError, match="safely recorded"):
        asyncio.run(manager.resume(record.id, {}))
    assert not ExperimentManager(root=tmp_path, runs=RunManager()).get(record.id).recovery_safe


def test_interrupted_launch_stops_later_cells_without_retry(tmp_path):
    class InterruptedRuns:
        def __init__(self):
            self.launched = []

        async def create_run(self, config, provenance=None):
            self.launched.append(config.world.seed)
            return "interrupted-launch"

        async def subscribe(self, _launch_id):
            yield {"type": "error", "terminal": True,
                   "detail": "Run observation was interrupted; external work may still be running."}

    async def scenario():
        runs = InterruptedRuns()
        manager = ExperimentManager(root=tmp_path, runs=runs)
        spec = ExperimentSpec(
            base_config=_base_config(),
            models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
            seeds=[1, 2],
        )
        record = await manager.create(spec)
        finished = await manager.wait(record.id)
        assert runs.launched == [1]
        assert finished.status == ExperimentStatus.failed
        assert finished.interrupted and not finished.recovery_safe
        assert [cell.status for cell in finished.cells] == [CellStatus.failed, CellStatus.queued]
        assert "may still be running" in finished.cells[0].error
        recovered = ExperimentManager(root=tmp_path, runs=runs).get(record.id)
        assert recovered.interrupted and not recovered.recovery_safe
        with pytest.raises(ValueError, match="safely recorded"):
            await manager.resume(record.id, {})
        assert runs.launched == [1]

    asyncio.run(scenario())


def test_experiment_stops_when_its_real_run_manager_is_interrupted(tmp_path, monkeypatch):
    from agentgymnasium.services import orchestrator

    async def scenario():
        runs = RunManager()
        calls = []

        async def interrupted(_run_id, config):
            calls.append(config.world.seed)
            raise asyncio.CancelledError

        monkeypatch.setattr(orchestrator, "record_launch_config", lambda *_args: None)
        monkeypatch.setattr(runs, "_run_inner", interrupted)
        manager = ExperimentManager(root=tmp_path, runs=runs)
        spec = ExperimentSpec(
            base_config=_base_config(),
            models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
            seeds=[1, 2],
        )
        record = await manager.create(spec)
        finished = await asyncio.wait_for(manager.wait(record.id), timeout=2)
        assert calls == [1]
        assert finished.interrupted and not finished.recovery_safe
        assert [cell.status for cell in finished.cells] == [CellStatus.failed, CellStatus.queued]

    asyncio.run(scenario())


def test_scheduler_cancellation_marks_inflight_work_uncertain_without_starting_more(tmp_path):
    class RunningProvider:
        def __init__(self):
            self.subscribed = asyncio.Event()
            self.launched = []

        async def create_run(self, config, provenance=None):
            self.launched.append(config.world.seed)
            return "still-running"

        async def subscribe(self, _launch_id):
            self.subscribed.set()
            await asyncio.Event().wait()
            yield {}  # pragma: no cover - keeps this a blocking async iterator

    async def scenario():
        runs = RunningProvider()
        manager = ExperimentManager(root=tmp_path, runs=runs)
        spec = ExperimentSpec(
            base_config=_base_config(),
            models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
            seeds=[1, 2],
        )
        record = await manager.create(spec)
        task = manager.tasks[record.id]
        await asyncio.wait_for(runs.subscribed.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        interrupted = manager.get(record.id)
        assert interrupted.status == ExperimentStatus.failed
        assert interrupted.interrupted and not interrupted.recovery_safe
        assert [cell.status for cell in interrupted.cells] == [CellStatus.failed, CellStatus.queued]
        assert runs.launched == [1]
        restored = ExperimentManager(root=tmp_path, runs=runs).get(record.id)
        assert restored.interrupted and not restored.recovery_safe
        with pytest.raises(ValueError, match="safely recorded"):
            await manager.resume(record.id, {})
        assert runs.launched == [1]

    asyncio.run(scenario())


@pytest.mark.parametrize("accepted_cancel", [False, True])
def test_scheduler_cancellation_before_start_preserves_safe_queued_recovery(tmp_path, accepted_cancel):
    async def scenario():
        manager = ExperimentManager(root=tmp_path, runs=RunManager())
        spec = ExperimentSpec(
            base_config=_base_config(),
            models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
        )
        record = await manager.create(spec)
        task = manager.tasks[record.id]
        if accepted_cancel:
            manager.cancel(record.id)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        interrupted = manager.get(record.id)
        assert interrupted.status == (
            ExperimentStatus.cancelled if accepted_cancel else ExperimentStatus.failed
        )
        assert interrupted.interrupted and interrupted.recovery_safe
        assert interrupted.cells[0].status == (
            CellStatus.cancelled if accepted_cancel else CellStatus.queued
        )
        restored = ExperimentManager(root=tmp_path, runs=RunManager()).get(record.id)
        assert restored.interrupted and restored.recovery_safe

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_at", ["launch", "subscribe"])
def test_scheduler_exception_does_not_leave_an_inflight_cell_running(tmp_path, failure_at):
    class FailingRuns:
        def __init__(self):
            self.launched = []

        async def create_run(self, config, provenance=None):
            self.launched.append(config.world.seed)
            if failure_at == "launch":
                raise RuntimeError("launch outcome unavailable")
            return "launch-id"

        async def subscribe(self, _launch_id):
            raise RuntimeError("observation unavailable")
            yield {}  # pragma: no cover - makes the fake an async iterator

    async def scenario():
        runs = FailingRuns()
        manager = ExperimentManager(root=tmp_path, runs=runs)
        spec = ExperimentSpec(
            base_config=_base_config(),
            models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
            seeds=[1, 2],
        )
        record = await manager.create(spec)
        finished = await manager.wait(record.id)
        assert finished.status == ExperimentStatus.failed
        assert finished.interrupted and not finished.recovery_safe
        assert [cell.status for cell in finished.cells] == [CellStatus.failed, CellStatus.queued]
        assert "may still be running" in finished.cells[0].error
        assert runs.launched == [1]
        assert not ExperimentManager(root=tmp_path, runs=runs).get(record.id).recovery_safe
        with pytest.raises(ValueError, match="safely recorded"):
            await manager.resume(record.id, {})
        assert runs.launched == [1]

    asyncio.run(scenario())


def test_restart_preserves_an_accepted_cancel_without_replaying_queued_cells(tmp_path):
    spec = ExperimentSpec(
        base_config=_base_config(),
        models=[ModelVariant(id="m", label="M", provider=LLMProvider.mock, model="mock")],
        seeds=[1, 2],
    )
    record = ExperimentRecord(
        id="cancel-before-restart", spec=spec, created_at=time.time(), status=ExperimentStatus.running,
        recovery_safe=True,
        cells=[
            ExperimentCell(id="m:1:0", model_variant_id="m", model_label="M", seed=1,
                           repeat_index=0, status=CellStatus.running),
            ExperimentCell(id="m:2:0", model_variant_id="m", model_label="M", seed=2,
                           repeat_index=0),
        ],
    )
    manager = ExperimentManager(root=tmp_path, runs=RunManager())
    manager.records[record.id] = record
    assert manager.cancel(record.id).cancel_requested is True

    recovered = ExperimentManager(root=tmp_path, runs=RunManager()).get(record.id)
    assert recovered is not None
    assert recovered.status == ExperimentStatus.cancelled
    assert recovered.outcome == "cancelled"
    assert [cell.status for cell in recovered.cells] == [CellStatus.failed, CellStatus.cancelled]
    assert recovered.cancel_requested is False


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
