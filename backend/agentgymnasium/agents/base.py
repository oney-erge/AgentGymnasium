from __future__ import annotations

import time
from abc import ABC, abstractmethod

from pydantic import BaseModel

from agentgymnasium.agents.parsing import parse_tool_calls
from agentgymnasium.core.schemas.model import ModelRequest, ModelResult


class ProviderStatus(BaseModel):
    online: bool
    detail: str = ""
    models: list[str] = []


class StructuredOutputResult(BaseModel):
    ok: bool
    detail: str = ""
    sample: list[dict] = []  # parsed tool calls, if any


class AgentProvider(ABC):
    name: str  # matches LLMProvider value

    @abstractmethod
    async def test_connection(
        self, endpoint_url: str | None, api_key: str | None
    ) -> ProviderStatus: ...

    @abstractmethod
    async def test_structured_output(
        self, model: str, endpoint_url: str | None, api_key: str | None
    ) -> StructuredOutputResult: ...

    @abstractmethod
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
        """Return the raw text completion. Used later by the build loop."""
        ...

    async def generate(self, request: ModelRequest) -> ModelResult:
        """Return a normalized model result.

        Providers with native tool calling or token telemetry should override
        this method. The compatibility implementation keeps custom providers
        working by wrapping their existing ``complete`` method.
        """
        started = time.perf_counter()
        raw = await self.complete(
            model=request.model,
            system=request.system,
            user=request.user,
            endpoint_url=request.endpoint_url,
            api_key=request.api_key,
            temperature=request.temperature,
        )
        return ModelResult(
            provider=request.provider,
            model=request.model,
            raw_text=raw,
            tool_calls=parse_tool_calls(raw),
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
