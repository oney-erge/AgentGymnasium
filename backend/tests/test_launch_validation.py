"""POST /api/setup/launch re-validates server-side and rejects bad configs."""
from fastapi.testclient import TestClient

from agentgymnasium.app import app

client = TestClient(app)


def _ready_config() -> dict:
    return {
        "scenario": {"preset": "bridge_builder", "objective": "go", "reward": ""},
        "world": {"template": "island_cliff_small", "engine": "pymunk2d"},
        "agents": {
            "mode": "single",
            "participants": [
                {
                    "id": "agent_a",
                    "name": "Agent A",
                    "role": "builder",
                    "behavior_mode": "engineer",
                    "provider": "mock",
                    "model": "mock",
                    "temperature": 0.7,
                    "max_attempts": 1,
                    "context_window": "8k",
                    "memory_mode": "none",
                    "mutation_strategy": "balanced",
                }
            ],
        },
        "llm_connection": {"endpoint_url": "http://localhost:1234/v1"},
        "tools": {"enabled": ["create_body", "add_beam", "add_joint", "run_simulation"]},
        "constraints": {"max_attempts": 1},
        "outputs": {},
    }


def test_launch_ready_config_succeeds():
    r = client.post("/api/setup/launch", json=_ready_config())
    assert r.status_code == 200
    assert "run_id" in r.json()


def test_launch_rejects_manual_provider():
    cfg = _ready_config()
    cfg["agents"]["participants"][0]["provider"] = "manual"
    r = client.post("/api/setup/launch", json=cfg)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any("manual" in m for m in detail["missing"])


def test_launch_rejects_missing_tools():
    cfg = _ready_config()
    cfg["tools"]["enabled"] = []  # Bridge Builder requires tools
    r = client.post("/api/setup/launch", json=cfg)
    assert r.status_code == 422
