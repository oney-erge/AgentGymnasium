"""Opt-in smoke checks against the real hosted OpenAI-compatible endpoint.

These are intentionally skipped by default so the normal suite stays offline,
deterministic, and free. To run locally:

    AGENTGYMNASIUM_LIVE_OPENAI_TESTS=1 OPENAI_API_KEY=... uv run pytest backend/tests/test_openai_live_smoke.py

Set AGENTGYMNASIUM_LIVE_OPENAI_MODEL as well to run the tiny completion smoke.
"""
from __future__ import annotations

import asyncio

import pytest

from agentgymnasium.agents.openai_compatible import OpenAICompatibleProvider, openai_env_key
from agentgymnasium.core.env import env

_ENDPOINT = "https://api.openai.com/v1"


pytestmark = pytest.mark.skipif(
    env("LIVE_OPENAI_TESTS") != "1",
    reason="set AGENTGYMNASIUM_LIVE_OPENAI_TESTS=1 to run live OpenAI smoke tests",
)


def test_live_openai_models_endpoint_uses_env_key():
    if not openai_env_key():
        pytest.skip("OPENAI_API_KEY is not set")

    status = asyncio.run(OpenAICompatibleProvider().test_connection(_ENDPOINT, None))
    assert status.online is True, status.detail
    assert status.models is not None
    assert len(status.models) > 0


def test_live_openai_tiny_completion_when_model_is_set(monkeypatch):
    if not openai_env_key():
        pytest.skip("OPENAI_API_KEY is not set")
    model = env("LIVE_OPENAI_MODEL")
    if not model:
        pytest.skip("set AGENTGYMNASIUM_LIVE_OPENAI_MODEL to run completion smoke")

    monkeypatch.setenv("AGENTGYMNASIUM_LLM_RETRIES", "0")
    out = asyncio.run(
        OpenAICompatibleProvider().complete(
            model=model,
            system="Reply with exactly: ok",
            user="ok",
            endpoint_url=_ENDPOINT,
            api_key=None,
            temperature=0,
        )
    )
    assert out.strip()
