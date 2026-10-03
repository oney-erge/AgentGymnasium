from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agentgymnasium.agents import (
    ProviderStatus,
    StructuredOutputResult,
    get_provider,
    list_providers,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


class ProviderMeta(BaseModel):
    id: str
    name: str
    requires_endpoint: bool
    requires_api_key: bool
    description: str
    env_api_key_available: bool = False
    env_api_key_preview: str | None = None


class TestConnectionRequest(BaseModel):
    provider: str
    endpoint_url: str | None = None
    api_key: str | None = None


class TestStructuredRequest(BaseModel):
    provider: str
    model: str = "mock"
    endpoint_url: str | None = None
    api_key: str | None = None


@router.get("/providers", response_model=list[ProviderMeta])
async def get_providers() -> list[ProviderMeta]:
    return [ProviderMeta(**meta) for meta in list_providers()]


@router.post("/test-connection", response_model=ProviderStatus)
async def test_connection(req: TestConnectionRequest) -> ProviderStatus:
    provider = get_provider(req.provider)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider}")
    return await provider.test_connection(req.endpoint_url, req.api_key)


@router.post("/test-structured-output", response_model=StructuredOutputResult)
async def test_structured_output(
    req: TestStructuredRequest,
) -> StructuredOutputResult:
    provider = get_provider(req.provider)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider}")
    return await provider.test_structured_output(
        req.model, req.endpoint_url, req.api_key
    )
