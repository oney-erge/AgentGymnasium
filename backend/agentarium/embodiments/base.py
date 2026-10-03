from __future__ import annotations

from abc import ABC, abstractmethod

from agentarium.core.schemas.embodiment import (
    EmbodimentAction,
    EmbodimentObservation,
    EnvironmentMode,
)


class EmbodimentAdapter(ABC):
    """Narrow high-level boundary between AgentGymnasium and an embodied system.

    Adapters intentionally do not expose raw motor/PWM commands. A robot-side
    controller remains responsible for its own low-level control and watchdog.
    """

    id: str
    label: str
    mode: EnvironmentMode
    adapter_name: str

    @abstractmethod
    async def reset(self) -> EmbodimentObservation:
        """Reset a simulated device or request a safe logical reset."""

    @abstractmethod
    async def observe(self) -> EmbodimentObservation:
        """Return the latest normalized observation."""

    @abstractmethod
    async def execute(self, action: EmbodimentAction) -> EmbodimentObservation:
        """Execute one already safety-validated, bounded action."""

    @abstractmethod
    async def emergency_stop(self) -> None:
        """Stop motion using the adapter's shortest available path."""

