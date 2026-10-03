from __future__ import annotations

import json
import math
import pathlib
import uuid

from agentgymnasium.agents import get_provider
from agentgymnasium.core.schemas.embodiment import (
    ActionKind,
    EmbodimentAction,
    EmbodimentEpisodeRequest,
    EmbodimentEpisodeResult,
)
from agentgymnasium.core.schemas.model import ModelInteraction, ModelRequest
from agentgymnasium.services.embodiment_service import embodiment_manager

_EPISODE_DIR = pathlib.Path("runs") / "embodiment-episodes"
_TOOLS = [
    {
        "name": "drive_to",
        "description": "Drive toward one geofenced planar target using bounded speed and time.",
        "parameters": {
            "type": "object",
            "required": ["target_x", "target_y", "max_speed_mps", "duration_s"],
            "properties": {
                "target_x": {"type": "number"},
                "target_y": {"type": "number"},
                "max_speed_mps": {"type": "number", "minimum": 0.01},
                "duration_s": {"type": "number", "minimum": 0.01},
            },
        },
    },
    {
        "name": "stop",
        "description": "Stop the device's commanded motion.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def _distance(observation, request: EmbodimentEpisodeRequest) -> float:
    return math.hypot(
        observation.pose.x - request.goal.x,
        observation.pose.y - request.goal.y,
    )


async def run_embodiment_episode(
    device_id: str,
    request: EmbodimentEpisodeRequest,
    control_token: str | None,
) -> EmbodimentEpisodeResult:
    provider = get_provider(request.agent.provider.value)
    if provider is None:
        raise ValueError(f"Unknown provider: {request.agent.provider.value}")
    if request.reset_before_run:
        await embodiment_manager.reset(device_id)

    episode_id = f"embodied-{uuid.uuid4().hex[:12]}"
    interactions: list[ModelInteraction] = []
    actions = []
    observations = [await embodiment_manager.observe(device_id)]
    initial_distance = _distance(observations[0], request)
    limits = next(
        device.limits
        for device in embodiment_manager.list_devices()
        if device.id == device_id
    )
    system = (
        "You control an embodied rover through high-level Embodiment control tools. "
        "Never invent raw motor, PWM, ROS topic, or shell commands. Choose at most "
        "one provided tool per turn. Remain inside the declared geofence and limits. "
        f"Goal: x={request.goal.x}, y={request.goal.y}; tolerance={request.tolerance_m}m. "
        f"Limits: x=[{limits.min_x},{limits.max_x}], y=[{limits.min_y},{limits.max_y}], "
        f"max_speed={limits.max_linear_speed_mps}m/s, "
        f"max_duration={limits.max_action_duration_s}s."
    )
    error: str | None = None

    for turn_index in range(request.max_turns):
        current = observations[-1]
        if _distance(current, request) <= request.tolerance_m:
            break
        user = (
            f"Objective: {request.objective}\n"
            f"Current normalized observation: "
            f"{json.dumps(current.model_dump(mode='json'), sort_keys=True)}\n"
            "Select the next safe action."
        )
        model_result = await provider.generate(
            ModelRequest(
                provider=request.agent.provider.value,
                model=request.agent.model,
                system=system,
                user=user,
                endpoint_url=request.agent.endpoint_url,
                api_key=request.agent.api_key,
                temperature=request.agent.temperature,
                seed=request.seed,
                tools=_TOOLS,
            )
        )
        interactions.append(
            ModelInteraction(
                turn_index=turn_index,
                agent_id=request.agent.id,
                system=system,
                user=user,
                seed=request.seed,
                result=model_result,
            )
        )
        call = next(
            (
                candidate
                for candidate in model_result.tool_calls
                if candidate.get("tool") in {"drive_to", "stop"}
            ),
            None,
        )
        if call is None:
            error = "Model returned no supported embodiment action."
            break
        try:
            action = EmbodimentAction.model_validate(
                {
                    **(call.get("args") or {}),
                    "kind": ActionKind(str(call["tool"])),
                }
            )
            receipt = await embodiment_manager.execute(
                device_id,
                action,
                control_token,
            )
        except Exception as exc:
            error = str(exc)
            break
        actions.append(receipt)
        observations.append(receipt.observation or await embodiment_manager.observe(device_id))

    final_distance = _distance(observations[-1], request)
    success = final_distance <= request.tolerance_m
    score = (
        100.0
        if success
        else max(
            0.0,
            100.0 * (initial_distance - final_distance) / max(0.001, initial_distance),
        )
    )
    result = EmbodimentEpisodeResult(
        id=episode_id,
        device_id=device_id,
        objective=request.objective,
        provider=request.agent.provider.value,
        model=request.agent.model,
        success=success,
        score=score,
        final_distance_m=final_distance,
        interactions=interactions,
        actions=actions,
        observations=observations,
        error=error,
    )
    _EPISODE_DIR.mkdir(parents=True, exist_ok=True)
    (_EPISODE_DIR / f"{episode_id}.json").write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return result
