from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agentgymnasium.core.schemas.model import ModelInteraction
from agentgymnasium.core.schemas.setup import AgentConfig


class EnvironmentMode(StrEnum):
    simulation = "simulation"
    shadow = "shadow"
    hardware_in_the_loop = "hardware_in_the_loop"
    real = "real"


class SafetyState(StrEnum):
    disarmed = "disarmed"
    armed = "armed"
    emergency_stopped = "emergency_stopped"


class ActionKind(StrEnum):
    stop = "stop"
    drive_to = "drive_to"


class Pose2D(BaseModel):
    x: float = 0.0
    y: float = 0.0
    heading_rad: float = 0.0


class Velocity2D(BaseModel):
    linear_mps: float = 0.0
    angular_rps: float = 0.0


class EmbodimentObservation(BaseModel):
    device_id: str
    timestamp: float
    sequence: int = 0
    pose: Pose2D = Field(default_factory=Pose2D)
    velocity: Velocity2D = Field(default_factory=Velocity2D)
    battery_fraction: float | None = None
    sensors: dict[str, Any] = Field(default_factory=dict)
    safety_state: SafetyState = SafetyState.disarmed


class EmbodimentAction(BaseModel):
    kind: ActionKind
    target_x: float | None = None
    target_y: float | None = None
    max_speed_mps: float = 0.25
    duration_s: float = 1.0
    metadata: dict[str, str] = Field(default_factory=dict)


class ActionReceipt(BaseModel):
    action_id: str
    accepted: bool
    reason: str | None = None
    observation: EmbodimentObservation | None = None


class SafetyLimits(BaseModel):
    min_x: float = -2.0
    max_x: float = 2.0
    min_y: float = -2.0
    max_y: float = 2.0
    max_linear_speed_mps: float = 0.5
    max_action_duration_s: float = 5.0
    heartbeat_timeout_s: float = 2.0


class EmbodimentDevice(BaseModel):
    id: str
    label: str
    adapter: str
    mode: EnvironmentMode
    safety_state: SafetyState
    limits: SafetyLimits
    connected: bool = True
    last_heartbeat_age_s: float | None = None


class EmbodimentEvent(BaseModel):
    timestamp: float
    device_id: str
    event: str
    detail: dict[str, Any] = Field(default_factory=dict)


class EmbodimentEpisodeRequest(BaseModel):
    objective: str = "Reach the target safely."
    goal: Pose2D
    tolerance_m: float = Field(default=0.15, gt=0.0, le=2.0)
    max_turns: int = Field(default=4, ge=1, le=8)
    reset_before_run: bool = True
    seed: int | None = None
    agent: AgentConfig


class EmbodimentEpisodeResult(BaseModel):
    id: str
    device_id: str
    objective: str
    provider: str
    model: str
    success: bool
    score: float
    final_distance_m: float
    interactions: list[ModelInteraction] = Field(default_factory=list)
    actions: list[ActionReceipt] = Field(default_factory=list)
    observations: list[EmbodimentObservation] = Field(default_factory=list)
    error: str | None = None
