from __future__ import annotations

import time
from collections import deque

from agentgymnasium.core.env import env
from agentgymnasium.core.schemas.embodiment import (
    ActionReceipt,
    EmbodimentAction,
    EmbodimentDevice,
    EmbodimentEvent,
    EnvironmentMode,
    SafetyLimits,
)
from agentgymnasium.embodiments.base import EmbodimentAdapter
from agentgymnasium.embodiments.mock import MockRoverAdapter
from agentgymnasium.embodiments.ros2_gateway import ROS2GatewayAdapter
from agentgymnasium.embodiments.safety import SafetySupervisor


class EmbodimentManager:
    def __init__(self) -> None:
        self._supervisors: dict[str, SafetySupervisor] = {}
        self._events: deque[EmbodimentEvent] = deque(maxlen=500)

    def register(
        self,
        adapter: EmbodimentAdapter,
        limits: SafetyLimits | None = None,
    ) -> None:
        if adapter.id in self._supervisors:
            raise ValueError(f"Embodiment device already registered: {adapter.id}")
        self._supervisors[adapter.id] = SafetySupervisor(adapter, limits)
        self._record(adapter.id, "registered", {"adapter": adapter.adapter_name})

    def _get(self, device_id: str) -> SafetySupervisor:
        try:
            return self._supervisors[device_id]
        except KeyError as exc:
            raise KeyError(f"Unknown embodiment device: {device_id}") from exc

    def _record(self, device_id: str, event: str, detail: dict | None = None) -> None:
        self._events.append(
            EmbodimentEvent(
                timestamp=time.time(),
                device_id=device_id,
                event=event,
                detail=detail or {},
            )
        )

    def list_devices(self) -> list[EmbodimentDevice]:
        return [
            EmbodimentDevice(
                id=device_id,
                label=supervisor.adapter.label,
                adapter=supervisor.adapter.adapter_name,
                mode=supervisor.adapter.mode,
                safety_state=supervisor.state,
                limits=supervisor.limits,
                last_heartbeat_age_s=supervisor.heartbeat_age_s,
            )
            for device_id, supervisor in sorted(self._supervisors.items())
        ]

    async def reset(self, device_id: str):
        supervisor = self._get(device_id)
        if supervisor.adapter.mode in (
            EnvironmentMode.real,
            EnvironmentMode.hardware_in_the_loop,
        ):
            raise ValueError("Software reset is disabled for hardware-backed devices.")
        observation = await supervisor.adapter.reset()
        observation.safety_state = supervisor.state
        self._record(device_id, "reset", {"sequence": observation.sequence})
        return observation

    async def observe(self, device_id: str):
        observation = await self._get(device_id).observe()
        self._record(device_id, "observation", {"sequence": observation.sequence})
        return observation

    async def arm(self, device_id: str) -> str:
        token = await self._get(device_id).arm()
        self._record(device_id, "armed")
        return token

    async def heartbeat(self, device_id: str, token: str | None) -> None:
        await self._get(device_id).heartbeat(token)
        self._record(device_id, "heartbeat")

    async def disarm(self, device_id: str, token: str | None) -> None:
        await self._get(device_id).disarm(token)
        self._record(device_id, "disarmed")

    async def emergency_stop(self, device_id: str, reason: str = "operator") -> None:
        await self._get(device_id).emergency_stop(reason)
        self._record(device_id, "emergency_stop", {"reason": reason})

    async def reset_emergency_stop(self, device_id: str) -> None:
        await self._get(device_id).reset_emergency_stop()
        self._record(device_id, "emergency_stop_reset")

    async def execute(
        self,
        device_id: str,
        action: EmbodimentAction,
        token: str | None,
    ) -> ActionReceipt:
        try:
            receipt = await self._get(device_id).execute(action, token)
        except Exception as exc:
            self._record(
                device_id,
                "action_rejected",
                {"kind": action.kind.value, "reason": str(exc)},
            )
            raise
        self._record(
            device_id,
            "action_accepted",
            {"kind": action.kind.value, "action_id": receipt.action_id},
        )
        return receipt

    def events(self, device_id: str | None = None, limit: int = 100) -> list[EmbodimentEvent]:
        matching = [
            event for event in self._events if device_id is None or event.device_id == device_id
        ]
        return matching[-max(1, min(limit, 500)) :]


embodiment_manager = EmbodimentManager()
embodiment_manager.register(
    MockRoverAdapter(),
    SafetyLimits(
        min_x=-2.0,
        max_x=2.0,
        min_y=-2.0,
        max_y=2.0,
        max_linear_speed_mps=0.5,
        max_action_duration_s=5.0,
        heartbeat_timeout_s=2.0,
    ),
)

_ros2_url = env("ROS2_GATEWAY_URL")
_ros2_token = env("ROS2_GATEWAY_TOKEN")
if _ros2_url and _ros2_token:
    try:
        _ros2_mode = EnvironmentMode(
            env("ROS2_MODE", EnvironmentMode.real.value)
        )
    except ValueError:
        _ros2_mode = EnvironmentMode.real
    embodiment_manager.register(
        ROS2GatewayAdapter(
            device_id=env("ROS2_DEVICE_ID", "ros2-rover"),
            label=env("ROS2_DEVICE_LABEL", "ROS 2 Rover"),
            base_url=_ros2_url,
            control_token=_ros2_token,
            mode=_ros2_mode,
        )
    )
