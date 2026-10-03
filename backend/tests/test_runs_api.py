import asyncio
import uuid

from fastapi.testclient import TestClient

from agentgymnasium.agents.runner import run_single_attempt
from agentgymnasium.app import app
from agentgymnasium.core.schemas.setup import (
    AgentConfig,
    AgentsConfig,
    LaunchConfig,
    LLMProvider,
    ScenarioConfig,
    ToolsConfig,
    WorldConfig,
)

client = TestClient(app)


def test_create_run_returns_id():
    r = client.post("/api/runs")
    assert r.status_code == 200
    body = r.json()
    assert "run_id" in body
    assert isinstance(body["run_id"], str)
    assert body["run_id"]


def test_get_trace():
    create = client.post("/api/runs", json={"duration_seconds": 1.0})
    assert create.status_code == 200
    run_id = create.json()["run_id"]

    r = client.get(f"/api/runs/{run_id}/trace")
    assert r.status_code == 200
    trace = r.json()
    assert trace["run_id"] == run_id
    assert trace["dt"] > 0
    assert len(trace["frames"]) > 0


def test_get_trace_404():
    r = client.get("/api/runs/does-not-exist/trace")
    assert r.status_code == 404


def test_get_snapshots_old_run_empty_list():
    create = client.post("/api/runs", json={"duration_seconds": 1.0})
    assert create.status_code == 200
    run_id = create.json()["run_id"]

    r = client.get(f"/api/runs/{run_id}/snapshots")
    assert r.status_code == 200
    assert r.json() == []


def test_get_snapshots_404():
    r = client.get("/api/runs/does-not-exist/snapshots")
    assert r.status_code == 404


def test_get_snapshots_for_persisted_agent_attempt():
    config = LaunchConfig(
        scenario=ScenarioConfig(preset="tiny_city_preview"),
        world=WorldConfig(template="tiny_city_block"),
        agents=AgentsConfig(
            participants=[AgentConfig(id="a", name="Builder", provider=LLMProvider.mock)]
        ),
        tools=ToolsConfig(enabled=["create_body", "run_simulation"]),
    )
    result = asyncio.run(run_single_attempt(config))
    assert result.trace_run_id is not None

    r = client.get(f"/api/runs/{result.trace_run_id}/snapshots")
    assert r.status_code == 200
    steps = r.json()
    assert len(steps) == len(result.build_steps)
    assert steps[0]["tool"] == "create_body"
    assert steps[0]["trace_run_id"] == result.trace_run_id
    assert "trace" in steps[0]

    cfg = client.get(f"/api/runs/{result.trace_run_id}/config")
    assert cfg.status_code == 200
    assert cfg.json()["config"]["scenario"]["preset"] == "tiny_city_preview"
    assert cfg.json()["provenance"]["kind"] == "attempt"

    interactions = client.get(
        f"/api/runs/{result.trace_run_id}/model-interactions"
    )
    assert interactions.status_code == 200
    assert interactions.json()[0]["result"]["provider"] == "mock"


def test_run_attempts_grouped_by_parent():
    config = LaunchConfig(
        scenario=ScenarioConfig(preset="tiny_city_preview"),
        world=WorldConfig(template="tiny_city_block"),
        agents=AgentsConfig(
            participants=[AgentConfig(id="agent_a", name="Builder", provider=LLMProvider.mock)]
        ),
        tools=ToolsConfig(enabled=["create_body", "run_simulation"]),
    )
    parent = f"test-parent-{uuid.uuid4().hex}"
    a0 = asyncio.run(run_single_attempt(config, attempt_index=0, parent_run_id=parent))
    a1 = asyncio.run(run_single_attempt(config, attempt_index=1, parent_run_id=parent))
    assert a0.trace_run_id and a1.trace_run_id

    # Grouped by the parent launch id: both attempts, sorted by attempt index.
    r = client.get(f"/api/runs/{parent}/attempts")
    assert r.status_code == 200
    attempts = r.json()
    ids = [a["trace_run_id"] for a in attempts]
    assert a0.trace_run_id in ids
    assert a1.trace_run_id in ids
    assert [a["attempt_index"] for a in attempts] == [0, 1]
    assert attempts[0]["agent_id"] == "agent_a"

    # Querying by one attempt id returns the full sibling set, not just itself.
    r2 = client.get(f"/api/runs/{a0.trace_run_id}/attempts")
    assert r2.status_code == 200
    siblings = [a["trace_run_id"] for a in r2.json()]
    assert a1.trace_run_id in siblings

    # An unrelated run has no linked attempts.
    r3 = client.get("/api/runs/does-not-exist/attempts")
    assert r3.status_code == 200
    assert r3.json() == []


def test_launch_config_is_captured_and_relaunchable():
    config = {
        "scenario": {"preset": "tiny_city_preview", "objective": "", "reward": "city_score"},
        "world": {"template": "tiny_city_block", "engine": "pymunk2d", "seed": 7},
        "agents": {
            "mode": "single",
            "participants": [
                {
                    "id": "agent_a",
                    "name": "Agent A",
                    "provider": "mock",
                    "model": "mock",
                    "temperature": 0.2,
                }
            ],
        },
        "tools": {"enabled": ["create_body", "run_simulation"]},
        "constraints": {"max_attempts": 1, "simulation_duration_seconds": 10},
        "outputs": {},
    }
    launched = client.post("/api/setup/launch", json=config)
    assert launched.status_code == 200
    run_id = launched.json()["run_id"]

    captured = client.get(f"/api/runs/{run_id}/config")
    assert captured.status_code == 200
    body = captured.json()
    assert body["config"]["world"]["seed"] == 7
    assert body["provenance"]["kind"] == "launch"

    relaunched = client.post(
        f"/api/runs/{run_id}/relaunch",
        json={"patch": {"world": {"seed": 99}, "constraints": {"max_attempts": 1}}},
    )
    assert relaunched.status_code == 200
    next_body = relaunched.json()
    assert next_body["source_run_id"] == run_id
    assert next_body["config"]["world"]["seed"] == 99
    assert next_body["run_id"] != run_id
