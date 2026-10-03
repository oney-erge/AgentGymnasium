from __future__ import annotations

from agentgymnasium.agents.openai_compatible import OpenAICompatibleProvider


class LocalDeployProvider(OpenAICompatibleProvider):
    name = "localdeploy"
    default_endpoint = "http://127.0.0.1:8000/v1"
