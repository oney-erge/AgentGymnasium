from __future__ import annotations

import math
import time

from agentgymnasium.core.schemas.embodiment import (
    ActionKind,
    EmbodimentAction,
    EmbodimentObservation,
    EnvironmentMode,
    Pose2D,
    SafetyState,
    Velocity2D,
)
from agentgymnasium.embodiments.base import EmbodimentAdapter


class MockRoverAdapter(EmbodimentAdapter):
    """Deterministic rover used for contract tests and hardware-free demos."""

    adapter_name = "mock_rover"

    def __init__(self, device_id: str = "mock-rover", label: str = "Mock Lab Rover") -> None:
        self.id = device_id
        self.label = label
        self.mode = EnvironmentMode.simulation
        self._pose = Pose2D()
        self._velocity = Velocity2D()
        self._sequence = 0

    def _observation(self) -> EmbodimentObservation:
        return EmbodimentObservation(
            device_id=self.id,
            timestamp=time.time(),
            sequence=self._sequence,
            pose=self._pose.model_copy(deep=True),
            velocity=self._velocity.model_copy(deep=True),
            battery_fraction=1.0,
            sensors={"front_range_m": 10.0, "adapter": self.adapter_name},
            safety_state=SafetyState.disarmed,
        )

    async def reset(self) -> EmbodimentObservation:
        self._pose = Pose2D()
        self._velocity = Velocity2D()
        self._sequence += 1
        return self._observation()

    async def observe(self) -> EmbodimentObservation:
        return self._observation()

    async def execute(self, action: EmbodimentAction) -> EmbodimentObservation:
        self._sequence += 1
        if action.kind == ActionKind.stop:
            self._velocity = Velocity2D()
            return self._observation()

        target_x = action.target_x if action.target_x is not None else self._pose.x
        target_y = action.target_y if action.target_y is not None else self._pose.y
        dx = target_x - self._pose.x
        dy = target_y - self._pose.y
        distance = math.hypot(dx, dy)
        if distance <= 1e-9:
            self._velocity = Velocity2D()
            return self._observation()

        travel = min(distance, action.max_speed_mps * action.duration_s)
        ux, uy = dx / distance, dy / distance
        self._pose = Pose2D(
            x=self._pose.x + ux * travel,
            y=self._pose.y + uy * travel,
            heading_rad=math.atan2(dy, dx),
        )
        self._velocity = Velocity2D(
            linear_mps=travel / action.duration_s,
            angular_rps=0.0,
        )
        return self._observation()

    async def emergency_stop(self) -> None:
        self._velocity = Velocity2D()
        self._sequence += 1

