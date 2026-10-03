from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agentgymnasium.core.schemas.design import DesignSpec
from agentgymnasium.core.schemas.model import ModelInteraction
from agentgymnasium.core.schemas.score import ScoreCard
from agentgymnasium.core.schemas.setup import LaunchConfig, LaunchState, WorldConfig
from agentgymnasium.core.schemas.toolcall import BuildStepRecord
from agentgymnasium.core.schemas.trace import EpisodeTrace
from agentgymnasium.services.orchestrator import run_manager
from agentgymnasium.services.run_service import (
    create_run_from_design,
    get_build_snapshots,
    get_launch_config,
    get_launch_provenance,
    get_model_interactions,
    get_score,
    get_trace,
    hardcoded_demo_design,
    leaderboard,
    list_run_attempts,
    list_runs,
)
from agentgymnasium.setup.validators import validate_launch_config

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunSummary(BaseModel):
    run_id: str
    created_at: int | None = None
    project_name: str | None = None
    challenge: str | None = None
    mode: str | None = None
    reward: str | None = None
    score_total: float | None = None
    success: bool | None = None
    artifact_dir: str | None = None
    config_available: bool = False
    attempt_count: int = 1
    provider: str | None = None
    model: str | None = None
    seed: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    protocol: str | None = None
    benchmark_hash: str | None = None


class CreateRunRequest(BaseModel):
    design: DesignSpec | None = None
    world: WorldConfig | None = None
    duration_seconds: float = 5.0


class CreateRunResponse(BaseModel):
    run_id: str


class RunConfigResponse(BaseModel):
    run_id: str
    config: LaunchConfig
    provenance: dict[str, Any] = {}


class RelaunchRunRequest(BaseModel):
    patch: dict[str, Any] | None = None


class RelaunchRunResponse(BaseModel):
    run_id: str
    source_run_id: str
    config: LaunchConfig


class RunAttemptSummary(BaseModel):
    trace_run_id: str
    attempt_index: int | None = None
    agent_id: str | None = None
    score_total: float | None = None
    success: bool | None = None


def _default_world() -> WorldConfig:
    return WorldConfig(template="flat_ground")


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge mappings; lists/scalars are replaced as whole values."""
    merged = dict(base)
    for key, value in patch.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


@router.post("", response_model=CreateRunResponse)
async def create_run(request: CreateRunRequest | None = None) -> CreateRunResponse:
    req = request or CreateRunRequest()
    design = req.design or hardcoded_demo_design()
    world = req.world or _default_world()
    run_id = create_run_from_design(design, world, req.duration_seconds)
    return CreateRunResponse(run_id=run_id)


def _to_summary(row: dict) -> RunSummary:
    s = row.get("success")
    return RunSummary(**{**row, "success": None if s is None else bool(s)})


@router.get("/history", response_model=list[RunSummary])
async def run_history(limit: int = 50) -> list[RunSummary]:
    """Recent runs (newest first), persisted across restarts."""
    return [_to_summary(r) for r in list_runs(limit)]


@router.get("/leaderboard", response_model=list[RunSummary])
async def run_leaderboard(challenge: str | None = None, limit: int = 10) -> list[RunSummary]:
    """Top runs by score, optionally filtered to one challenge."""
    return [_to_summary(r) for r in leaderboard(challenge, limit)]


@router.get("/{run_id}/config", response_model=RunConfigResponse)
async def get_run_config(run_id: str) -> RunConfigResponse:
    config = get_launch_config(run_id)
    if config is None:
        raise HTTPException(
            status_code=404,
            detail=f"Launch config not found for run: {run_id}",
        )
    return RunConfigResponse(
        run_id=run_id,
        config=config,
        provenance=get_launch_provenance(run_id),
    )


@router.post("/{run_id}/relaunch", response_model=RelaunchRunResponse)
async def relaunch_run(
    run_id: str,
    request: RelaunchRunRequest | None = None,
) -> RelaunchRunResponse:
    original = get_launch_config(run_id)
    if original is None:
        raise HTTPException(
            status_code=404,
            detail=f"Launch config not found for run: {run_id}",
        )

    patch = (request.patch if request is not None else None) or {}
    try:
        config = LaunchConfig.model_validate(
            _deep_merge(original.model_dump(mode="json"), patch)
        )
    except Exception as exc:  # noqa: BLE001 - surface invalid patch as 422
        raise HTTPException(status_code=422, detail=f"Invalid launch patch: {exc}") from exc

    result = await validate_launch_config(config)
    if result.state != LaunchState.ready:
        raise HTTPException(
            status_code=422,
            detail={
                "state": result.state.value,
                "missing": result.missing,
                "warnings": result.warnings,
            },
        )

    new_run_id = await run_manager.create_run(
        config,
        provenance={
            "source": "relaunch",
            "source_run_id": run_id,
            "patch": patch,
        },
    )
    return RelaunchRunResponse(
        run_id=new_run_id,
        source_run_id=run_id,
        config=config,
    )


@router.get("/{run_id}/attempts", response_model=list[RunAttemptSummary])
async def get_run_attempts(run_id: str) -> list[RunAttemptSummary]:
    """Every attempt trace belonging to the same run as ``run_id`` (empty if none).

    Lets Studio show and replay each attempt of a finished/historical run, not
    only the single best trace it opened with.
    """
    return [RunAttemptSummary(**a) for a in list_run_attempts(run_id)]


@router.get("/{run_id}/trace", response_model=EpisodeTrace)
async def get_run_trace(run_id: str) -> EpisodeTrace:
    trace = get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return trace


@router.get("/{run_id}/score", response_model=ScoreCard)
async def get_run_score(run_id: str) -> ScoreCard:
    score = get_score(run_id)
    if score is None:
        raise HTTPException(status_code=404, detail=f"Score not found: {run_id}")
    return score


@router.get("/{run_id}/snapshots", response_model=list[BuildStepRecord])
async def get_run_snapshots(run_id: str) -> list[BuildStepRecord]:
    snapshots = get_build_snapshots(run_id)
    if snapshots is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return snapshots


@router.get("/{run_id}/model-interactions", response_model=list[ModelInteraction])
async def get_run_model_interactions(run_id: str) -> list[ModelInteraction]:
    interactions = get_model_interactions(run_id)
    if interactions is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return interactions
