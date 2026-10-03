from __future__ import annotations

from fastapi.testclient import TestClient

from agentgymnasium.app import app
from agentgymnasium.services import workspace_config_service

client = TestClient(app)


def test_workspace_config_creates_default_and_round_trips(tmp_path, monkeypatch):
    path = tmp_path / "workspace_config.json"
    monkeypatch.setattr(workspace_config_service, "_WORKSPACE_CONFIG_PATH", path)

    first = client.get("/api/setup/workspace-config")
    assert first.status_code == 200
    body = first.json()
    assert body["path"] == str(path)
    assert body["mtime_ns"] is not None
    assert body["config"]["scenario"]["preset"] == "bridge_builder"
    assert path.is_file()

    config = body["config"]
    config["project_name"] = "Synced Workspace"
    config["constraints"]["max_parts"] = 123

    saved = client.post("/api/setup/workspace-config", json={"config": config})
    assert saved.status_code == 200
    assert saved.json()["config"]["project_name"] == "Synced Workspace"

    loaded = client.get("/api/setup/workspace-config")
    assert loaded.status_code == 200
    assert loaded.json()["config"]["constraints"]["max_parts"] == 123

    status = client.get("/api/setup/workspace-config/status")
    assert status.status_code == 200
    assert status.json()["exists"] is True
    assert status.json()["mtime_ns"] == loaded.json()["mtime_ns"]


def test_workspace_config_reports_invalid_json(tmp_path, monkeypatch):
    path = tmp_path / "workspace_config.json"
    path.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(workspace_config_service, "_WORKSPACE_CONFIG_PATH", path)

    response = client.get("/api/setup/workspace-config")

    assert response.status_code == 422
    assert "Workspace config JSON is invalid" in response.json()["detail"]
