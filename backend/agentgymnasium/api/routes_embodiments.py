from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from agentgymnasium.core.env import env
from agentgymnasium.core.schemas.embodiment import (
    ActionReceipt,
    EmbodimentAction,
    EmbodimentDevice,
    EmbodimentEpisodeRequest,
    EmbodimentEpisodeResult,
    EmbodimentEvent,
    EmbodimentObservation,
    EnvironmentMode,
)
from agentgymnasium.embodiments.safety import SafetyViolation
from agentgymnasium.services.embodiment_episode_service import run_embodiment_episode
from agentgymnasium.services.embodiment_service import embodiment_manager


def _control_token(
    x_agentgymnasium_control_token: str | None = Header(default=None),
    x_agentarium_control_token: str | None = Header(default=None),  # the project's former name
) -> str | None:
    return x_agentgymnasium_control_token or x_agentarium_control_token


def _operator_key(
    x_agentgymnasium_operator_key: str | None = Header(default=None),
    x_agentarium_operator_key: str | None = Header(default=None),  # the project's former name
) -> str | None:
    return x_agentgymnasium_operator_key or x_agentarium_operator_key


router = APIRouter(prefix="/api/embodiments", tags=["embodiments"])


class ConfirmationRequest(BaseModel):
    confirmation: str


class ArmResponse(BaseModel):
    device_id: str
    control_token: str
    heartbeat_timeout_s: float


def _device_or_404(device_id: str) -> EmbodimentDevice:
    devices = {device.id: device for device in embodiment_manager.list_devices()}
    if device_id not in devices:
        raise HTTPException(status_code=404, detail=f"Unknown device: {device_id}")
    return devices[device_id]


def _safety_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _authorize_real_device(
    device: EmbodimentDevice,
    operator_key: str | None,
) -> None:
    if device.mode not in (
        EnvironmentMode.real,
        EnvironmentMode.hardware_in_the_loop,
    ):
        return
    expected = env("OPERATOR_KEY")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Hardware-backed arming is disabled until AGENTGYMNASIUM_OPERATOR_KEY is set.",
        )
    if not operator_key or not secrets.compare_digest(operator_key, expected):
        raise HTTPException(status_code=403, detail="Invalid operator key.")


@router.get("", response_model=list[EmbodimentDevice])
async def list_embodiments() -> list[EmbodimentDevice]:
    return embodiment_manager.list_devices()


@router.get("/events", response_model=list[EmbodimentEvent])
async def embodiment_events(
    device_id: str | None = None,
    limit: int = 100,
) -> list[EmbodimentEvent]:
    if device_id is not None:
        _device_or_404(device_id)
    return embodiment_manager.events(device_id, limit)


@router.get("/{device_id}/observation", response_model=EmbodimentObservation)
async def observe_embodiment(device_id: str) -> EmbodimentObservation:
    _device_or_404(device_id)
    return await embodiment_manager.observe(device_id)


@router.post("/{device_id}/arm", response_model=ArmResponse)
async def arm_embodiment(
    device_id: str,
    request: ConfirmationRequest,
    x_agentgymnasium_operator_key: str | None = Depends(_operator_key),
) -> ArmResponse:
    device = _device_or_404(device_id)
    _authorize_real_device(device, x_agentgymnasium_operator_key)
    if request.confirmation != f"ARM {device_id}":
        raise HTTPException(
            status_code=400,
            detail=f"Confirmation must exactly match: ARM {device_id}",
        )
    try:
        token = await embodiment_manager.arm(device_id)
    except SafetyViolation as exc:
        raise _safety_error(exc) from exc
    return ArmResponse(
        device_id=device_id,
        control_token=token,
        heartbeat_timeout_s=device.limits.heartbeat_timeout_s,
    )


@router.post("/{device_id}/heartbeat", status_code=204)
async def embodiment_heartbeat(
    device_id: str,
    x_agentgymnasium_control_token: str | None = Depends(_control_token),
) -> None:
    _device_or_404(device_id)
    try:
        await embodiment_manager.heartbeat(device_id, x_agentgymnasium_control_token)
    except SafetyViolation as exc:
        raise _safety_error(exc) from exc


@router.post("/{device_id}/actions", response_model=ActionReceipt)
async def execute_embodiment_action(
    device_id: str,
    action: EmbodimentAction,
    x_agentgymnasium_control_token: str | None = Depends(_control_token),
) -> ActionReceipt:
    _device_or_404(device_id)
    try:
        return await embodiment_manager.execute(
            device_id,
            action,
            x_agentgymnasium_control_token,
        )
    except SafetyViolation as exc:
        raise _safety_error(exc) from exc


@router.post("/{device_id}/episodes", response_model=EmbodimentEpisodeResult)
async def execute_embodiment_episode(
    device_id: str,
    request: EmbodimentEpisodeRequest,
    x_agentgymnasium_control_token: str | None = Depends(_control_token),
) -> EmbodimentEpisodeResult:
    _device_or_404(device_id)
    try:
        return await run_embodiment_episode(
            device_id,
            request,
            x_agentgymnasium_control_token,
        )
    except (SafetyViolation, ValueError) as exc:
        raise _safety_error(exc) from exc


@router.post("/{device_id}/disarm", status_code=204)
async def disarm_embodiment(
    device_id: str,
    x_agentgymnasium_control_token: str | None = Depends(_control_token),
) -> None:
    _device_or_404(device_id)
    try:
        await embodiment_manager.disarm(device_id, x_agentgymnasium_control_token)
    except SafetyViolation as exc:
        raise _safety_error(exc) from exc


@router.post("/{device_id}/emergency-stop", status_code=204)
async def emergency_stop_embodiment(device_id: str) -> None:
    _device_or_404(device_id)
    await embodiment_manager.emergency_stop(device_id)


@router.post("/{device_id}/reset-emergency-stop", status_code=204)
async def reset_emergency_stop(
    device_id: str,
    request: ConfirmationRequest,
    x_agentgymnasium_operator_key: str | None = Depends(_operator_key),
) -> None:
    device = _device_or_404(device_id)
    _authorize_real_device(device, x_agentgymnasium_operator_key)
    if request.confirmation != f"RESET ESTOP {device_id}":
        raise HTTPException(
            status_code=400,
            detail=f"Confirmation must exactly match: RESET ESTOP {device_id}",
        )
    try:
        await embodiment_manager.reset_emergency_stop(device_id)
    except SafetyViolation as exc:
        raise _safety_error(exc) from exc
