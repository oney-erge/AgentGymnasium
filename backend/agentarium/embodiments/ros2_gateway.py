from __future__ import annotations

from typing import Any

import httpx

from agentarium.core.schemas.embodiment import (
    EmbodimentAction,
    EmbodimentObservation,
    EnvironmentMode,
)
from agentarium.embodiments.base import EmbodimentAdapter


class ROS2GatewayAdapter(EmbodimentAdapter):
    """HTTP client for a robot-side ROS 2 gateway.

    The gateway is expected to translate these high-level messages into ROS 2
    interfaces and independently enforce a hardware watchdog and actuator
    limits. AgentGymnasium deliberately has no direct ROS or motor dependency.
    """

    adapter_name = "ros2_gateway"

    def __init__(
        self,
        *,
        device_id: str,
        label: str,
        base_url: str,
        control_token: str,
        mode: EnvironmentMode = EnvironmentMode.real,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.id = device_id
        self.label = label
        self.mode = mode
        self._base_url = base_url.rstrip("/")
        self._control_token = control_token
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._control_token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._client is not None:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers(),
                **kwargs,
            )
        else:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=self._headers(),
                    **kwargs,
                )
        response.raise_for_status()
        return response

    async def reset(self) -> EmbodimentObservation:
        response = await self._request("POST", "/v1/reset")
        return EmbodimentObservation.model_validate(response.json())

    async def observe(self) -> EmbodimentObservation:
        response = await self._request("GET", "/v1/observation")
        return EmbodimentObservation.model_validate(response.json())

    async def execute(self, action: EmbodimentAction) -> EmbodimentObservation:
        response = await self._request(
            "POST",
            "/v1/actions",
            json=action.model_dump(mode="json"),
        )
        return EmbodimentObservation.model_validate(response.json())

    async def emergency_stop(self) -> None:
        await self._request("POST", "/v1/emergency-stop")

