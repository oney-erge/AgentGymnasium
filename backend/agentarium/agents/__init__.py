from __future__ import annotations

from agentarium.agents.base import (
    AgentProvider,
    ProviderStatus,
    StructuredOutputResult,
)
from agentarium.agents.localdeploy import LocalDeployProvider
from agentarium.agents.manual_provider import ManualProvider
from agentarium.agents.mock_provider import MockProvider
from agentarium.agents.openai_compatible import (
    OpenAICompatibleProvider,
    mask_secret,
    openai_env_key,
)

_PROVIDERS: dict[str, AgentProvider] = {
    "mock": MockProvider(),
    "localdeploy": LocalDeployProvider(),
    "openai_compatible": OpenAICompatibleProvider(),
    "manual": ManualProvider(),
}

_PROVIDER_META: list[dict] = [
    {
        "id": "mock",
        "name": "Mock / No model",
        "requires_endpoint": False,
        "requires_api_key": False,
        "description": (
            "Offline demo provider. It does not call an LLM; it emits fixed "
            "sample tool calls so the app can launch without setup."
        ),
    },
    {
        "id": "localdeploy",
        "name": "LocalDeploy",
        "requires_endpoint": True,
        "requires_api_key": False,
        "description": (
            "LocalDeploy OpenAI-compatible server. Run the LocalDeploy GitHub "
            "repo locally, then point AgentGymnasium at its /v1 endpoint."
        ),
    },
    {
        "id": "openai_compatible",
        "name": "OpenAI-Compatible",
        "requires_endpoint": True,
        "requires_api_key": True,
        "description": "Any hosted OpenAI-compatible API.",
    },
    {
        "id": "manual",
        "name": "Manual Builder",
        "requires_endpoint": False,
        "requires_api_key": False,
        "description": "You build the design by hand using the same tools.",
    },
]


def get_provider(provider: str) -> AgentProvider | None:
    return _PROVIDERS.get(provider)


def list_providers() -> list[dict]:
    env_key = openai_env_key()
    providers: list[dict] = []
    for meta in _PROVIDER_META:
        item = dict(meta)
        if item["id"] == "openai_compatible":
            item["env_api_key_available"] = env_key is not None
            item["env_api_key_preview"] = mask_secret(env_key)
        else:
            item["env_api_key_available"] = False
            item["env_api_key_preview"] = None
        providers.append(item)
    return providers


__all__ = [
    "AgentProvider",
    "ProviderStatus",
    "StructuredOutputResult",
    "get_provider",
    "list_providers",
]
