"""OPENAI_API_KEY env fallback: the hosted OpenAI provider reads the key from the
environment so it never has to be pasted into the UI or saved config — but
LocalDeploy (a subclass that needs no key) must not pick it up."""
from __future__ import annotations

from agentgymnasium.agents.localdeploy import LocalDeployProvider
from agentgymnasium.agents.openai_compatible import (
    OpenAICompatibleProvider,
    mask_secret,
    openai_env_key,
)


def test_openai_env_key_reads_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    assert openai_env_key() == "sk-test-123"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert openai_env_key() is None


def test_openai_provider_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    provider = OpenAICompatibleProvider()
    # An explicit key always wins; otherwise the env key is used.
    assert provider._resolve_api_key("sk-explicit") == "sk-explicit"
    assert provider._resolve_api_key(None) == "sk-env-key"


def test_mask_secret_never_returns_full_key():
    key = "sk-test-1234567890"
    masked = mask_secret(key)
    assert masked is not None
    assert masked != key
    assert masked.startswith("sk-")
    assert masked.endswith("7890")
    assert "test-123456" not in masked


def test_localdeploy_ignores_openai_env_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    # LocalDeploy needs no key and must not leak the OpenAI key to a local server.
    assert LocalDeployProvider()._resolve_api_key(None) is None
