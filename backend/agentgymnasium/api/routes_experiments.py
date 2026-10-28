from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agentgymnasium.core.schemas.experiment import (
    ExperimentAggregate,
    ExperimentPairwise,
    ExperimentRecord,
    ExperimentSpec,
    ResumeExperimentRequest,
)
from agentgymnasium.core.schemas.setup import LaunchState
from agentgymnasium.services.experiment_service import experiment_manager
from agentgymnasium.setup.validators import validate_launch_config

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


async def _validate_spec(spec: ExperimentSpec) -> None:
    if not spec.base_config.agents.participants:
        raise HTTPException(status_code=422, detail="base_config requires one participant")
    for variant in spec.models:
        config = spec.base_config.model_copy(deep=True)
        participant = config.agents.participants[0]
        participant.provider = variant.provider
        participant.model = variant.model
        participant.endpoint_url = variant.endpoint_url
        participant.api_key = variant.api_key
        participant.temperature = variant.temperature
        result = await validate_launch_config(config)
        if result.state != LaunchState.ready:
            raise HTTPException(
                status_code=422,
                detail={
                    "model_variant_id": variant.id,
                    "state": result.state.value,
                    "missing": result.missing,
                    "warnings": result.warnings,
                },
            )


@router.post("", response_model=ExperimentRecord)
async def create_experiment(spec: ExperimentSpec) -> ExperimentRecord:
    await _validate_spec(spec)
    try:
        return await experiment_manager.create(spec)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[ExperimentRecord])
async def list_experiments() -> list[ExperimentRecord]:
    return experiment_manager.list()


@router.get("/{experiment_id}", response_model=ExperimentRecord)
async def get_experiment(experiment_id: str) -> ExperimentRecord:
    record = experiment_manager.get(experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return record


@router.get("/{experiment_id}/aggregates", response_model=list[ExperimentAggregate])
async def get_experiment_aggregates(
    experiment_id: str,
) -> list[ExperimentAggregate]:
    aggregates = experiment_manager.aggregates(experiment_id)
    if aggregates is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return aggregates


@router.get("/{experiment_id}/pairwise", response_model=list[ExperimentPairwise])
async def get_experiment_pairwise(experiment_id: str) -> list[ExperimentPairwise]:
    comparisons = experiment_manager.pairwise(experiment_id)
    if comparisons is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return comparisons


@router.post("/{experiment_id}/cancel", response_model=ExperimentRecord)
async def cancel_experiment(experiment_id: str) -> ExperimentRecord:
    record = experiment_manager.cancel(experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return record


@router.post("/{experiment_id}/resume", response_model=ExperimentRecord)
async def resume_experiment(
    experiment_id: str, request: ResumeExperimentRequest
) -> ExperimentRecord:
    record = experiment_manager.get(experiment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if not record.interrupted or not record.recovery_safe:
        raise HTTPException(status_code=409, detail="Experiment cannot be safely resumed")
    pending_ids = {cell.model_variant_id for cell in record.cells if cell.status == "queued"}
    if not pending_ids or set(request.api_keys) - pending_ids:
        raise HTTPException(status_code=409, detail="No queued cells or unknown credential variant")
    spec = record.spec.model_copy(deep=True)
    spec.models = [variant for variant in spec.models if variant.id in pending_ids]
    for variant in spec.models:
        variant.api_key = request.api_keys.get(variant.id)
    await _validate_spec(spec)
    try:
        return await experiment_manager.resume(experiment_id, request.api_keys)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
