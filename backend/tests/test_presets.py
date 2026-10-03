import uuid

import pytest
from fastapi.testclient import TestClient

from agentgymnasium.app import app
from agentgymnasium.core.schemas.setup import (
    LaunchConfig,
    LaunchState,
    ScenarioConfig,
    ToolsConfig,
    WorldConfig,
)
from agentgymnasium.setup.validators import validate_launch_config

client = TestClient(app)


def test_list_presets():
    r = client.get("/api/presets")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 5
    ids = {p["id"] for p in body}
    assert ids == {
        "bridge_builder",
        "crawl_challenge",
        "sorter",
        "tiny_city_preview",
        "city_builder",
    }


def test_city_builder_preset_has_reward_options():
    # One isometric city challenge; its 5 scoring goals are a selectable
    # setting (reward_options), not 5 separate presets.
    r = client.get("/api/presets/city_builder")
    assert r.status_code == 200
    body = r.json()
    assert body["reward"] == "city_planning"
    values = {o["value"] for o in body["reward_options"]}
    assert values == {
        "city_planning", "boomtown", "budget_city", "balanced_city", "green_capital",
    }


def test_get_preset():
    r = client.get("/api/presets/bridge_builder")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "bridge_builder"
    assert body["required_tools"]


def test_list_worlds():
    r = client.get("/api/worlds")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 7


def test_save_and_load_preset():
    name = f"test_preset_{uuid.uuid4().hex}"
    config = LaunchConfig(
        scenario=ScenarioConfig(preset="bridge_builder"),
        world=WorldConfig(template="island_cliff_small"),
        tools=ToolsConfig(enabled=["create_body", "add_beam", "add_joint", "run_simulation"]),
    )

    save_resp = client.post(
        "/api/setup/save-preset",
        json={"name": name, "config": config.model_dump(mode="json")},
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["name"] == name

    load_resp = client.get(f"/api/setup/presets/{name}")
    assert load_resp.status_code == 200
    loaded = LaunchConfig.model_validate(load_resp.json())
    assert loaded == config

    list_resp = client.get("/api/setup/presets")
    assert list_resp.status_code == 200
    assert name in list_resp.json()


@pytest.mark.asyncio
async def test_required_tools_validation():
    config = LaunchConfig(
        scenario=ScenarioConfig(preset="bridge_builder"),
        world=WorldConfig(template="island_cliff_small"),
        # Missing required "add_beam"
        tools=ToolsConfig(enabled=["create_body", "add_joint", "run_simulation"]),
    )
    result = await validate_launch_config(config)
    assert result.state == LaunchState.tool_challenge_mismatch
    assert any("add_beam" in m for m in result.missing)
