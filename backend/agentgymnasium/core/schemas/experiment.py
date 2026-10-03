from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from agentgymnasium.core.schemas.setup import LaunchConfig, LLMProvider


class ExperimentStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    cancelled = "cancelled"
    failed = "failed"


class CellStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ModelVariant(BaseModel):
    id: str
    label: str
    provider: LLMProvider
    model: str
    endpoint_url: str | None = None
    api_key: str | None = Field(default=None, exclude=True, repr=False)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class ExperimentSpec(BaseModel):
    name: str = "Model comparison"
    base_config: LaunchConfig
    models: list[ModelVariant] = Field(min_length=1, max_length=12)
    seeds: list[int] = Field(default_factory=lambda: [0], min_length=1, max_length=25)
    repeats: int = Field(default=1, ge=1, le=10)


class ExperimentCell(BaseModel):
    id: str
    model_variant_id: str
    model_label: str
    seed: int
    repeat_index: int
    status: CellStatus = CellStatus.queued
    launch_run_id: str | None = None
    trace_run_id: str | None = None
    score: float | None = None
    success: bool | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    error: str | None = None


class ExperimentAggregate(BaseModel):
    model_variant_id: str
    model_label: str
    n: int
    successes: int
    success_rate: float
    mean_score: float
    stddev_score: float
    ci95_low: float
    ci95_high: float
    mean_latency_ms: float
    mean_tokens: float


class ExperimentPairwise(BaseModel):
    model_a_id: str
    model_a_label: str
    model_b_id: str
    model_b_label: str
    n_pairs: int
    wins_a: int
    ties: int
    wins_b: int
    mean_score_delta: float
    ci95_low: float
    ci95_high: float


class ExperimentRecord(BaseModel):
    id: str
    spec: ExperimentSpec
    status: ExperimentStatus = ExperimentStatus.queued
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    cells: list[ExperimentCell] = Field(default_factory=list)
    error: str | None = None
