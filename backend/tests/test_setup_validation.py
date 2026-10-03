"""Tests for the POST /api/setup/validate endpoint (Step 6 — real validation logic)."""

import copy
from typing import Any

import httpx
from fastapi.testclient import TestClient

from agentgymnasium.app import app

client = TestClient(app)

# Minimal valid config using mock provider (no HTTP probe fired)
VALID_CONFIG: dict = {
    "scenario": {"preset": "bridge_builder", "objective": "Test", "reward": "distance_plus_stability"},
    "world": {"template": "island_cliff_small", "terrain": "grassland", "engine": "pymunk2d"},
    "agents": {
        "mode": "single",
        "participants": [{"id": "a1", "name": "Agent A", "provider": "mock", "model": "mock"}],
    },
    "tools": {"enabled": ["create_body", "add_beam", "add_joint", "run_simulation"]},
    "constraints": {},
    "outputs": {},
}


def _post(config: dict) -> dict:
    r = client.post("/api/setup/validate", json=config)
    assert r.status_code == 200
    return r.json()


def test_missing_scenario_preset() -> None:
    config = copy.deepcopy(VALID_CONFIG)
    config["scenario"]["preset"] = ""
    body = _post(config)
    assert body["state"] == "MISSING_REQUIRED"
    assert "scenario.preset" in body["missing"]


def test_missing_world_template() -> None:
    config = copy.deepcopy(VALID_CONFIG)
    config["world"]["template"] = ""
    body = _post(config)
    assert body["state"] == "MISSING_REQUIRED"
    assert "world.template" in body["missing"]


def test_unsupported_engine() -> None:
    config = copy.deepcopy(VALID_CONFIG)
    config["world"]["engine"] = "pybullet3d"
    body = _post(config)
    assert body["state"] == "UNSUPPORTED_ENGINE"


def test_relay_and_sandbox_modes_are_supported() -> None:
    for mode in ("relay", "sandbox"):
        config = copy.deepcopy(VALID_CONFIG)
        config["agents"]["mode"] = mode
        config["agents"]["participants"].append(
            {"id": "a2", "name": "Agent B", "provider": "mock", "model": "mock"}
        )
        body = _post(config)
        assert body["state"] == "READY"


def test_mock_provider_ready() -> None:
    body = _post(copy.deepcopy(VALID_CONFIG))
    assert body["state"] == "READY"
    assert body["missing"] == []
    assert body["estimated_runtime_min"] == [2, 4]


def test_remote_provider_requires_selected_model() -> None:
    config = copy.deepcopy(VALID_CONFIG)
    participant = config["agents"]["participants"][0]
    participant.update(
        {
            "provider": "openai_compatible",
            "model": "",
            "endpoint_url": "https://api.openai.com/v1",
        }
    )
    config["llm_connection"] = {"endpoint_url": "https://api.openai.com/v1"}

    body = _post(config)

    assert body["state"] == "MISSING_REQUIRED"
    assert "agents.participants[0].model" in body["missing"]


def test_remote_provider_rejects_model_not_returned_by_endpoint(monkeypatch) -> None:
    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            del args
            pass

        async def get(
            self, url: str, headers: dict[str, str] | None = None
        ) -> httpx.Response:
            del url, headers
            return httpx.Response(
                200,
                json={"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4.1-mini"}]},
            )

    config = copy.deepcopy(VALID_CONFIG)
    participant = config["agents"]["participants"][0]
    participant.update(
        {
            "provider": "openai_compatible",
            "model": "gpt-4-turbo",
            "endpoint_url": "https://api.openai.com/v1",
        }
    )
    config["llm_connection"] = {"endpoint_url": "https://api.openai.com/v1"}
    monkeypatch.setattr("agentgymnasium.setup.validators.httpx.AsyncClient", _Client)

    body = _post(config)

    assert body["state"] == "LLM_OFFLINE"
    assert "Model not available" in body["missing"][0]
    assert "gpt-4-turbo" in body["missing"][0]


def test_empty_tools_warning() -> None:
    config = copy.deepcopy(VALID_CONFIG)
    config["tools"]["enabled"] = []
    body = _post(config)
    # Empty tools triggers the warning; for a preset with required tools it
    # also blocks with TOOL_CHALLENGE_MISMATCH, but the warning still fires.
    assert body["state"] == "TOOL_CHALLENGE_MISMATCH"
    assert len(body["warnings"]) > 0
    assert any("No tools enabled" in w for w in body["warnings"])
