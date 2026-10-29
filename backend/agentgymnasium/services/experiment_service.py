from __future__ import annotations

import asyncio
import math
import pathlib
import statistics
import time
import uuid

from agentgymnasium.core.schemas.experiment import (
    CellStatus,
    ExperimentAggregate,
    ExperimentCell,
    ExperimentPairwise,
    ExperimentRecord,
    ExperimentSpec,
    ExperimentStatus,
    ModelVariant,
)
from agentgymnasium.services.orchestrator import RunManager, run_manager
from agentgymnasium.services.run_service import get_model_interactions, get_score

_EXPERIMENTS_DIR = pathlib.Path("runs") / "experiments"
_MAX_CELLS = 120

# Two-sided 95% Student-t critical values for 1..30 degrees of freedom.
# For larger samples the 30-df value is conservative; no statistics package is
# required and the same rule is used for scores and paired differences.
_T95 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)


def _mean_interval(values: list[float]) -> tuple[float | None, float | None]:
    """Student-t interval for independent observations; unavailable for n < 2."""
    if len(values) < 2:
        return None, None
    mean = statistics.fmean(values)
    critical = _T95[min(len(values) - 1, len(_T95)) - 1]
    margin = critical * statistics.stdev(values) / math.sqrt(len(values))
    return mean - margin, mean + margin


class ExperimentManager:
    """Sequential experiment scheduler with explicit interruption recovery.

    Each matrix cell is an ordinary AgentGymnasium launch, preserving all existing
    validation, traces, scores, artifacts, and replay behavior. Experiments are
    local-first JSON records. Only queued cells can be resumed after restart;
    an in-flight cell is marked failed because it may already have incurred work.
    """

    def __init__(
        self,
        root: pathlib.Path = _EXPERIMENTS_DIR,
        runs: RunManager = run_manager,
    ) -> None:
        self.root = root
        self.runs = runs
        self.records: dict[str, ExperimentRecord] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.cancel_requested: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.root.is_dir():
            return
        for path in self.root.glob("*.json"):
            try:
                record = ExperimentRecord.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception:
                continue
            # A record from disk must not choose an arbitrary persistence path.
            if record.id != path.stem:
                continue
            if record.status in (ExperimentStatus.queued, ExperimentStatus.running):
                record.status = ExperimentStatus.failed
                record.finished_at = time.time()
                record.interrupted = True
                record.error = "Server restarted before the experiment completed."
                for cell in record.cells:
                    if cell.status == CellStatus.running:
                        cell.status = CellStatus.failed
                        cell.error = "Interrupted in flight; this cell was not retried."
                self._persist(record)
            self.records[record.id] = record

    @staticmethod
    def _redact(record: ExperimentRecord) -> ExperimentRecord:
        safe = record.model_copy(deep=True)
        safe.spec.base_config.llm_connection.api_key = None
        for participant in safe.spec.base_config.agents.participants:
            participant.api_key = None
        for variant in safe.spec.models:
            variant.api_key = None
        return safe

    def _persist(self, record: ExperimentRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{record.id}.json"
        pending = self.root / f".{record.id}.tmp"
        pending.write_text(self._redact(record).model_dump_json(indent=2), encoding="utf-8")
        pending.replace(path)

    async def create(self, spec: ExperimentSpec) -> ExperimentRecord:
        cell_count = len(spec.models) * len(spec.seeds) * spec.repeats
        if cell_count > _MAX_CELLS:
            raise ValueError(
                f"Experiment has {cell_count} cells; maximum is {_MAX_CELLS}."
            )
        experiment_id = uuid.uuid4().hex
        cells = [
            ExperimentCell(
                id=f"{variant.id}:{seed}:{repeat}",
                model_variant_id=variant.id,
                model_label=variant.label,
                seed=seed,
                repeat_index=repeat,
            )
            for variant in spec.models
            for seed in spec.seeds
            for repeat in range(spec.repeats)
        ]
        record = ExperimentRecord(
            id=experiment_id,
            spec=spec,
            created_at=time.time(),
            cells=cells,
            recovery_safe=True,
        )
        self.records[experiment_id] = record
        self._persist(record)
        task = asyncio.create_task(self._execute(record))
        self.tasks[experiment_id] = task
        task.add_done_callback(lambda _task: self.tasks.pop(experiment_id, None))
        return self._redact(record)

    async def resume(self, experiment_id: str, api_keys: dict[str, str]) -> ExperimentRecord:
        record = self.records.get(experiment_id)
        if record is None:
            raise ValueError("Experiment not found.")
        if not record.interrupted or not record.recovery_safe:
            raise ValueError("Only safely recorded interrupted experiments can be resumed.")
        if experiment_id in self.tasks:
            raise ValueError("Experiment is already running.")
        pending_ids = {c.model_variant_id for c in record.cells if c.status == CellStatus.queued}
        if not pending_ids:
            raise ValueError("No queued cells remain to resume.")
        if set(api_keys) - pending_ids:
            raise ValueError("Credentials may only be supplied for queued model variants.")
        for variant in record.spec.models:
            variant.api_key = api_keys.get(variant.id)
        record.interrupted = False
        record.status = ExperimentStatus.queued
        record.error = None
        record.finished_at = None
        self._persist(record)
        task = asyncio.create_task(self._execute(record))
        self.tasks[experiment_id] = task
        task.add_done_callback(lambda _task: self.tasks.pop(experiment_id, None))
        return self._redact(record)

    def list(self) -> list[ExperimentRecord]:
        records = sorted(self.records.values(), key=lambda r: r.created_at, reverse=True)
        return [self._redact(record) for record in records]

    def get(self, experiment_id: str) -> ExperimentRecord | None:
        record = self.records.get(experiment_id)
        return self._redact(record) if record is not None else None

    def cancel(self, experiment_id: str) -> ExperimentRecord | None:
        record = self.records.get(experiment_id)
        if record is None:
            return None
        if record.status in (ExperimentStatus.queued, ExperimentStatus.running):
            self.cancel_requested.add(experiment_id)
        return self._redact(record)

    async def wait(self, experiment_id: str) -> ExperimentRecord | None:
        task = self.tasks.get(experiment_id)
        if task is not None:
            await task
        record = self.records.get(experiment_id)
        return self._redact(record) if record is not None else None

    @staticmethod
    def _variant(spec: ExperimentSpec, variant_id: str) -> ModelVariant:
        return next(v for v in spec.models if v.id == variant_id)

    async def _execute(self, record: ExperimentRecord) -> None:
        record.status = ExperimentStatus.running
        record.started_at = time.time()
        self._persist(record)
        try:
            for cell in record.cells:
                if cell.status != CellStatus.queued:
                    continue
                if record.id in self.cancel_requested:
                    cell.status = CellStatus.cancelled
                    continue
                await self._execute_cell(record, cell)
                self._persist(record)
            if record.id in self.cancel_requested:
                record.status = ExperimentStatus.cancelled
                for cell in record.cells:
                    if cell.status == CellStatus.queued:
                        cell.status = CellStatus.cancelled
            elif any(cell.status == CellStatus.completed for cell in record.cells):
                record.status = ExperimentStatus.completed
            else:
                record.status = ExperimentStatus.failed
                record.error = "Every experiment cell failed."
        except Exception as exc:  # noqa: BLE001 - persist scheduler failure
            record.status = ExperimentStatus.failed
            record.error = str(exc)
        finally:
            record.finished_at = time.time()
            self.cancel_requested.discard(record.id)
            self._persist(record)

    async def _execute_cell(
        self,
        record: ExperimentRecord,
        cell: ExperimentCell,
    ) -> None:
        variant = self._variant(record.spec, cell.model_variant_id)
        config = record.spec.base_config.model_copy(deep=True)
        if not config.agents.participants:
            cell.status = CellStatus.failed
            cell.error = "base_config has no participant"
            return
        agent = config.agents.participants[0]
        agent.provider = variant.provider
        agent.model = variant.model
        agent.endpoint_url = variant.endpoint_url
        agent.api_key = variant.api_key
        agent.temperature = variant.temperature
        agent.provider_seed = cell.seed
        config.world.seed = cell.seed
        if config.world.visual_seed is None:
            config.world.visual_seed = 0
        config.project_name = f"{record.spec.name} · {variant.label} · seed {cell.seed}"

        cell.status = CellStatus.running
        self._persist(record)
        launch_id = await self.runs.create_run(
            config,
            provenance={
                "source": "experiment",
                "experiment_id": record.id,
                "cell_id": cell.id,
            },
        )
        cell.launch_run_id = launch_id
        error_detail: str | None = None
        finished: dict | None = None
        async for event in self.runs.subscribe(launch_id):
            if event.get("type") == "error":
                error_detail = str(event.get("detail") or "run failed")
            elif event.get("type") == "run_finished":
                finished = event

        trace_id = finished.get("best_trace_run_id") if finished else None
        if error_detail or not trace_id:
            cell.status = CellStatus.failed
            cell.error = error_detail or "Run produced no scored trace."
            return

        score = get_score(trace_id)
        interactions = get_model_interactions(trace_id) or []
        cell.trace_run_id = trace_id
        cell.score = score.score_total if score is not None else None
        cell.success = score.success if score is not None else False
        cell.input_tokens = sum(i.result.usage.input_tokens for i in interactions)
        cell.output_tokens = sum(i.result.usage.output_tokens for i in interactions)
        cell.latency_ms = sum(i.result.latency_ms for i in interactions)
        cell.status = CellStatus.completed

    def aggregates(self, experiment_id: str) -> list[ExperimentAggregate] | None:
        record = self.records.get(experiment_id)
        if record is None:
            return None
        result: list[ExperimentAggregate] = []
        for variant in record.spec.models:
            cells = [
                c
                for c in record.cells
                if c.model_variant_id == variant.id
                and c.status == CellStatus.completed
                and c.score is not None
            ]
            if not cells:
                continue
            scores = [float(c.score) for c in cells if c.score is not None]
            mean = statistics.fmean(scores)
            stddev = statistics.stdev(scores) if len(scores) > 1 else 0.0
            ci_low, ci_high = _mean_interval(scores)
            result.append(
                ExperimentAggregate(
                    model_variant_id=variant.id,
                    model_label=variant.label,
                    n=len(cells),
                    successes=sum(1 for c in cells if c.success),
                    success_rate=sum(1 for c in cells if c.success) / len(cells),
                    mean_score=mean,
                    stddev_score=stddev,
                    ci95_low=ci_low,
                    ci95_high=ci_high,
                    mean_latency_ms=statistics.fmean(c.latency_ms for c in cells),
                    mean_tokens=statistics.fmean(
                        c.input_tokens + c.output_tokens for c in cells
                    ),
                )
            )
        return result

    def pairwise(self, experiment_id: str) -> list[ExperimentPairwise] | None:
        record = self.records.get(experiment_id)
        if record is None:
            return None
        by_model: dict[str, dict[tuple[int, int], ExperimentCell]] = {}
        labels: dict[str, str] = {}
        for cell in record.cells:
            labels[cell.model_variant_id] = cell.model_label
            if cell.status == CellStatus.completed and cell.score is not None:
                by_model.setdefault(cell.model_variant_id, {})[
                    (cell.seed, cell.repeat_index)
                ] = cell

        model_ids = [variant.id for variant in record.spec.models]
        comparisons: list[ExperimentPairwise] = []
        for index, model_a in enumerate(model_ids):
            for model_b in model_ids[index + 1 :]:
                cells_a = by_model.get(model_a, {})
                cells_b = by_model.get(model_b, {})
                paired_keys = sorted(set(cells_a) & set(cells_b))
                deltas = [
                    float(cells_a[key].score) - float(cells_b[key].score)
                    for key in paired_keys
                ]
                n_pairs = len(deltas)
                mean_delta = statistics.fmean(deltas) if deltas else 0.0
                ci_low, ci_high = _mean_interval(deltas)
                comparisons.append(
                    ExperimentPairwise(
                        model_a_id=model_a,
                        model_a_label=labels.get(model_a, model_a),
                        model_b_id=model_b,
                        model_b_label=labels.get(model_b, model_b),
                        n_pairs=n_pairs,
                        wins_a=sum(delta > 1e-9 for delta in deltas),
                        ties=sum(abs(delta) <= 1e-9 for delta in deltas),
                        wins_b=sum(delta < -1e-9 for delta in deltas),
                        mean_score_delta=mean_delta,
                        ci95_low=ci_low,
                        ci95_high=ci_high,
                    )
                )
        return comparisons


experiment_manager = ExperimentManager()
