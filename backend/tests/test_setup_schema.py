from fastapi.testclient import TestClient

from agentgymnasium.app import app
from agentgymnasium.core.schemas.setup import (
    AgentsConfig,
    ConstraintsConfig,
    LaunchConfig,
    LLMConnectionConfig,
    OutputsConfig,
    ScenarioConfig,
    ToolsConfig,
    WorldConfig,
)

client = TestClient(app)

MINIMAL_LAUNCH_CONFIG = {
    "scenario": {"preset": "walk_forward"},
    "world": {"template": "flat_plane"},
}


def test_validate_stub_returns_ready() -> None:
    r = client.post("/api/setup/validate", json=MINIMAL_LAUNCH_CONFIG)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "READY"
    assert body["missing"] == []


def test_launch_config_serializes() -> None:
    config = LaunchConfig(
        scenario=ScenarioConfig(preset="walk_forward"),
        world=WorldConfig(template="flat_plane"),
        agents=AgentsConfig(),
        llm_connection=LLMConnectionConfig(),
        tools=ToolsConfig(),
        constraints=ConstraintsConfig(),
        outputs=OutputsConfig(),
    )
    data = config.model_dump()
    assert data["scenario"]["preset"] == "walk_forward"
    assert data["world"]["template"] == "flat_plane"
    assert data["version"] == 1
