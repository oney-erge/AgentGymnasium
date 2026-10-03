from __future__ import annotations

from agentgymnasium.agents.base import (
    AgentProvider,
    ProviderStatus,
    StructuredOutputResult,
)


class ManualProvider(AgentProvider):
    name = "manual"

    async def test_connection(
        self, endpoint_url: str | None, api_key: str | None
    ) -> ProviderStatus:
        return ProviderStatus(online=True, detail="Manual builder — no model")

    async def test_structured_output(
        self, model: str, endpoint_url: str | None, api_key: str | None
    ) -> StructuredOutputResult:
        return StructuredOutputResult(
            ok=True, detail="Manual mode does not use a model"
        )

    async def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        endpoint_url: str | None,
        api_key: str | None,
        temperature: float = 0.7,
    ) -> str:
        raise NotImplementedError("Manual mode is driven by the UI, not a model")
