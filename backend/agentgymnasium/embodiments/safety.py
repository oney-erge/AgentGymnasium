from __future__ import annotations

import asyncio
import math
import secrets
import time
import uuid
from collections.abc import Callable

from agentgymnasium.core.schemas.embodiment import (
    ActionKind,
    ActionReceipt,
    EmbodimentAction,
    EmbodimentObservation,
    SafetyLimits,
    SafetyState,
)
from agentgymnasium.embodiments.base import EmbodimentAdapter


class SafetyViolation(ValueError):
    pass


class SafetySupervisor:
    """Stateful interlock around one adapter.

    The token is short-lived in memory, the emergency stop is latched, and the
    watchdog stops motion when heartbeats cease. A real robot gateway must also
    enforce the same limits locally because a host process cannot be a hardware
    safety system.
    """

    def __init__(
        self,
        adapter: EmbodimentAdapter,
        limits: SafetyLimits | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.adapter = adapter
        self.limits = limits or SafetyLimits()
        self.state = SafetyState.disarmed
        self._clock = clock
        self._last_heartbeat: float | None = None
        self._control_token: str | None = None
        self._watchdog_task: asyncio.Task[None] | None = None

    @property
    def heartbeat_age_s(self) -> float | None:
        if self._last_heartbeat is None:
            return None
        return max(0.0, self._clock() - self._last_heartbeat)

    def _valid_token(self, token: str | None) -> bool:
        return bool(
            token
            and self._control_token
            and secrets.compare_digest(token, self._control_token)
        )

    async def arm(self) -> str:
        if self.state == SafetyState.emergency_stopped:
            raise SafetyViolation("Emergency stop is latched; reset it before arming.")
        if self.state == SafetyState.armed:
            raise SafetyViolation("Device is already armed.")
        self._control_token = secrets.token_urlsafe(24)
        self._last_heartbeat = self._clock()
        self.state = SafetyState.armed
        self._start_watchdog()
        return self._control_token

    async def disarm(self, token: str | None) -> None:
        if self.state == SafetyState.emergency_stopped:
            return
        if self.state == SafetyState.armed and not self._valid_token(token):
            raise SafetyViolation("A valid control token is required to disarm.")
        await self.adapter.emergency_stop()
        self.state = SafetyState.disarmed
        self._control_token = None
        self._last_heartbeat = None
        self._cancel_watchdog()

    async def heartbeat(self, token: str | None) -> None:
        self._require_armed(token)
        self._last_heartbeat = self._clock()

    async def emergency_stop(self, reason: str = "operator") -> None:
        del reason
        await self.adapter.emergency_stop()
        self.state = SafetyState.emergency_stopped
        self._control_token = None
        self._last_heartbeat = None
        self._cancel_watchdog()

    async def reset_emergency_stop(self) -> None:
        if self.state != SafetyState.emergency_stopped:
            raise SafetyViolation("Emergency stop is not latched.")
        self.state = SafetyState.disarmed

    async def execute(
        self,
        action: EmbodimentAction,
        token: str | None,
    ) -> ActionReceipt:
        self._require_armed(token)
        self._validate_action(action)
        self._last_heartbeat = self._clock()
        observation = await self.adapter.execute(action)
        observation.safety_state = self.state
        return ActionReceipt(
            action_id=str(uuid.uuid4()),
            accepted=True,
            observation=observation,
        )

    async def observe(self) -> EmbodimentObservation:
        await self._enforce_watchdog()
        observation = await self.adapter.observe()
        observation.safety_state = self.state
        return observation

    def _require_armed(self, token: str | None) -> None:
        if self.state != SafetyState.armed:
            raise SafetyViolation(f"Device is {self.state.value}; arm it before acting.")
        if not self._valid_token(token):
            raise SafetyViolation("A valid control token is required.")
        age = self.heartbeat_age_s
        if age is None or age > self.limits.heartbeat_timeout_s:
            raise SafetyViolation("Control heartbeat expired.")

    def _validate_action(self, action: EmbodimentAction) -> None:
        if not math.isfinite(action.max_speed_mps) or action.max_speed_mps <= 0:
            raise SafetyViolation("Action speed must be finite and positive.")
        if action.max_speed_mps > self.limits.max_linear_speed_mps:
            raise SafetyViolation("Action exceeds the configured speed limit.")
        if not math.isfinite(action.duration_s) or action.duration_s <= 0:
            raise SafetyViolation("Action duration must be finite and positive.")
        if action.duration_s > self.limits.max_action_duration_s:
            raise SafetyViolation("Action exceeds the configured duration limit.")
        if action.kind == ActionKind.drive_to:
            if action.target_x is None or action.target_y is None:
                raise SafetyViolation("drive_to requires target_x and target_y.")
            if not all(math.isfinite(v) for v in (action.target_x, action.target_y)):
                raise SafetyViolation("Action target must be finite.")
            if not self.limits.min_x <= action.target_x <= self.limits.max_x:
                raise SafetyViolation("Action target is outside the X geofence.")
            if not self.limits.min_y <= action.target_y <= self.limits.max_y:
                raise SafetyViolation("Action target is outside the Y geofence.")

    def _start_watchdog(self) -> None:
        self._cancel_watchdog()
        self._watchdog_task = asyncio.create_task(self._watchdog())

    def _cancel_watchdog(self) -> None:
        task = self._watchdog_task
        self._watchdog_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _watchdog(self) -> None:
        interval = max(0.01, min(0.25, self.limits.heartbeat_timeout_s / 4))
        try:
            while self.state == SafetyState.armed:
                await asyncio.sleep(interval)
                await self._enforce_watchdog()
        except asyncio.CancelledError:
            return

    async def _enforce_watchdog(self) -> None:
        age = self.heartbeat_age_s
        if (
            self.state == SafetyState.armed
            and age is not None
            and age > self.limits.heartbeat_timeout_s
        ):
            await self.emergency_stop("heartbeat_timeout")

