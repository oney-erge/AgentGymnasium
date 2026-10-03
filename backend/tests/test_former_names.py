"""The project was renamed from Agentarium. Its former names keep working.

New names win; the old ones are accepted so existing environments, scripts, headers, and saved
data are not broken by the rename.
"""
import pathlib
import tomllib

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agentgymnasium.api.routes_embodiments import _authorize_real_device
from agentgymnasium.app import app
from agentgymnasium.core.env import env
from agentgymnasium.core.schemas.embodiment import (
    EmbodimentDevice,
    EnvironmentMode,
    SafetyLimits,
    SafetyState,
)
from agentgymnasium.services import run_service

client = TestClient(app)


def test_env_prefers_the_new_name_and_falls_back_to_the_old_one(monkeypatch):
    monkeypatch.delenv("AGENTGYMNASIUM_LLM_RETRIES", raising=False)
    monkeypatch.delenv("AGENTARIUM_LLM_RETRIES", raising=False)
    assert env("LLM_RETRIES", "2") == "2"
    assert env("LLM_RETRIES") is None

    monkeypatch.setenv("AGENTARIUM_LLM_RETRIES", "5")
    assert env("LLM_RETRIES", "2") == "5"

    monkeypatch.setenv("AGENTGYMNASIUM_LLM_RETRIES", "7")
    assert env("LLM_RETRIES", "2") == "7"

    # A new name that is set but empty still wins over the old name.
    monkeypatch.setenv("AGENTGYMNASIUM_LLM_RETRIES", "")
    assert env("LLM_RETRIES", "2") == ""


def test_operator_key_is_read_from_the_former_variable(monkeypatch):
    device = EmbodimentDevice(
        id="real-rover",
        label="Real Rover",
        adapter="ros2_gateway",
        mode=EnvironmentMode.real,
        safety_state=SafetyState.disarmed,
        limits=SafetyLimits(),
    )
    monkeypatch.delenv("AGENTGYMNASIUM_OPERATOR_KEY", raising=False)
    monkeypatch.setenv("AGENTARIUM_OPERATOR_KEY", "legacy-secret")
    with pytest.raises(HTTPException) as denied:
        _authorize_real_device(device, "wrong")
    assert denied.value.status_code == 403
    _authorize_real_device(device, "legacy-secret")


@pytest.mark.parametrize(
    "header", ["X-AgentGymnasium-Control-Token", "X-Agentarium-Control-Token"]
)
def test_control_token_header_accepts_the_new_and_the_former_name(header):
    device_id = "mock-rover"
    client.post(f"/api/embodiments/{device_id}/emergency-stop")
    client.post(
        f"/api/embodiments/{device_id}/reset-emergency-stop",
        json={"confirmation": f"RESET ESTOP {device_id}"},
    )
    armed = client.post(
        f"/api/embodiments/{device_id}/arm",
        json={"confirmation": f"ARM {device_id}"},
    )
    assert armed.status_code == 200
    token = armed.json()["control_token"]

    accepted = client.post(
        f"/api/embodiments/{device_id}/actions",
        headers={header: token},
        json={"kind": "stop"},
    )
    assert accepted.status_code == 200, accepted.text

    missing = client.post(f"/api/embodiments/{device_id}/actions", json={"kind": "stop"})
    assert missing.status_code != 200
    client.post(f"/api/embodiments/{device_id}/disarm", headers={header: token})


def test_database_keeps_a_file_created_under_the_old_name(tmp_path):
    assert run_service._default_db_path(tmp_path) == tmp_path / "agentgymnasium.db"

    (tmp_path / "agentarium.db").write_bytes(b"")
    assert run_service._default_db_path(tmp_path) == tmp_path / "agentarium.db"

    (tmp_path / "agentgymnasium.db").write_bytes(b"")
    assert run_service._default_db_path(tmp_path) == tmp_path / "agentgymnasium.db"


def test_the_old_command_name_is_still_installed():
    root = pathlib.Path(__file__).resolve().parents[2]
    scripts = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "scripts"
    ]
    assert scripts["agentgymnasium"] == "agentgymnasium.cli:main"
    assert scripts["agentarium"] == scripts["agentgymnasium"]
