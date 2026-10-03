from __future__ import annotations

from pydantic import BaseModel, Field


class ModelRequest(BaseModel):
    """Provider-neutral request used by the agent runtime.

    Credentials are runtime-only and are excluded from every serialization path.
    Tool definitions use the common function shape
    ``{name, description, parameters}``.
    """

    provider: str
    model: str
    system: str
    user: str
    endpoint_url: str | None = None
    api_key: str | None = Field(default=None, exclude=True, repr=False)
    temperature: float = 0.7
    seed: int | None = None
    tools: list[dict] = Field(default_factory=list)


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelResult(BaseModel):
    """Normalized result so providers can be compared on the same telemetry."""

    provider: str
    model: str
    raw_text: str = ""
    tool_calls: list[dict] = Field(default_factory=list)
    native_tool_calls: bool = False
    finish_reason: str | None = None
    request_id: str | None = None
    latency_ms: float = 0.0
    retries: int = 0
    usage: TokenUsage = Field(default_factory=TokenUsage)


class ModelInteraction(BaseModel):
    """Persistable, credential-free record of one model turn."""

    turn_index: int
    agent_id: str
    system: str
    user: str
    seed: int | None = None
    result: ModelResult
