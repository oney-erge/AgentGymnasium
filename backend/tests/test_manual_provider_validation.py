"""Validator rejects 'manual' provider with a clear message (H5 fix)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentgymnasium.app import app

client = TestClient(app)


def _base_config() -> dict:
    return {
        "scenario": {"preset": "bridge_builder", "objective": "", "reward": ""},
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
        "constraints": {
            "max_parts": 300,
            "max_joints": 120,
            "energy_budget": 1200,
            "max_attempts": 1,
            "simulation_duration_seconds": 5,
            "material_budget": 2000,
            "collision_safety": "strict",
            "world_bounds": "enforced",
            "repair_loop_enabled": False,
        },
        "outputs": {
            "replay_json": True,
            "scorecard_json": True,
            "trace_jsonl": True,
            "markdown_report": False,
            "screenshot": False,
            "video_capture": False,
        },
    }


def test_manual_provider_rejected():
    cfg = _base_config()
    cfg["agents"]["participants"][0]["provider"] = "manual"
    resp = client.post("/api/setup/validate", json=cfg)
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"].upper() == "MISSING_REQUIRED"
    assert any("manual" in m for m in data["missing"])


def test_mock_provider_passes_validation():
    cfg = _base_config()
    resp = client.post("/api/setup/validate", json=cfg)
    assert resp.status_code == 200
    data = resp.json()
    # Should reach 'ready' (mock provider, no LLM probe needed).
    assert data["state"].upper() == "READY"
