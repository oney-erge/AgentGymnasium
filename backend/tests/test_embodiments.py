import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agentgymnasium.api.routes_embodiments import _authorize_real_device
from agentgymnasium.app import app
from agentgymnasium.core.schemas.embodiment import (
    ActionKind,
    EmbodimentAction,
    EmbodimentDevice,
    EnvironmentMode,
    SafetyLimits,
    SafetyState,
)
from agentgymnasium.embodiments.mock import MockRoverAdapter
from agentgymnasium.embodiments.safety import SafetySupervisor, SafetyViolation

client = TestClient(app)


@pytest.mark.asyncio
async def test_mock_rover_requires_arming_and_enforces_geofence():
    supervisor = SafetySupervisor(
        MockRoverAdapter("test-rover"),
        SafetyLimits(
            min_x=-1,
            max_x=1,
            min_y=-1,
            max_y=1,
            max_linear_speed_mps=0.4,
            max_action_duration_s=2,
            heartbeat_timeout_s=1,
        ),
    )
    action = EmbodimentAction(
        kind=ActionKind.drive_to,
        target_x=0.5,
        target_y=0,
        max_speed_mps=0.25,
        duration_s=1,
    )

    with pytest.raises(SafetyViolation, match="arm"):
        await supervisor.execute(action, None)

    token = await supervisor.arm()
    receipt = await supervisor.execute(action, token)
    assert receipt.accepted is True
    assert receipt.observation is not None
    assert receipt.observation.pose.x == pytest.approx(0.25)
    assert receipt.observation.safety_state == SafetyState.armed

    outside = action.model_copy(update={"target_x": 1.5})
    with pytest.raises(SafetyViolation, match="geofence"):
        await supervisor.execute(outside, token)

    too_fast = action.model_copy(update={"max_speed_mps": 0.8})
    with pytest.raises(SafetyViolation, match="speed limit"):
        await supervisor.execute(too_fast, token)

    await supervisor.disarm(token)
    assert supervisor.state == SafetyState.disarmed


@pytest.mark.asyncio
async def test_watchdog_latches_emergency_stop():
    supervisor = SafetySupervisor(
        MockRoverAdapter("watchdog-rover"),
        SafetyLimits(heartbeat_timeout_s=0.03),
    )
    await supervisor.arm()
    await asyncio.sleep(0.08)
    assert supervisor.state == SafetyState.emergency_stopped

    with pytest.raises(SafetyViolation, match="latched"):
        await supervisor.arm()
    await supervisor.reset_emergency_stop()
    assert supervisor.state == SafetyState.disarmed


def test_embodiment_api_control_flow():
    device_id = "mock-rover"
    # Normalize state so this test is independent of a previous interrupted run.
    client.post(f"/api/embodiments/{device_id}/emergency-stop")
    client.post(
        f"/api/embodiments/{device_id}/reset-emergency-stop",
        json={"confirmation": f"RESET ESTOP {device_id}"},
    )

    devices = client.get("/api/embodiments")
    assert devices.status_code == 200
    assert any(device["id"] == device_id for device in devices.json())

    refused = client.post(
        f"/api/embodiments/{device_id}/arm",
        json={"confirmation": "yes"},
    )
    assert refused.status_code == 400

    armed = client.post(
        f"/api/embodiments/{device_id}/arm",
        json={"confirmation": f"ARM {device_id}"},
    )
    assert armed.status_code == 200
    token = armed.json()["control_token"]
    headers = {"X-AgentGymnasium-Control-Token": token}

    moved = client.post(
        f"/api/embodiments/{device_id}/actions",
        headers=headers,
        json={
            "kind": "drive_to",
            "target_x": 0.5,
            "target_y": 0.25,
            "max_speed_mps": 0.25,
            "duration_s": 1,
        },
    )
    assert moved.status_code == 200
    assert moved.json()["accepted"] is True

    estop = client.post(f"/api/embodiments/{device_id}/emergency-stop")
    assert estop.status_code == 204
    blocked = client.post(
        f"/api/embodiments/{device_id}/actions",
        headers=headers,
        json={"kind": "stop"},
    )
    assert blocked.status_code == 409

    reset = client.post(
        f"/api/embodiments/{device_id}/reset-emergency-stop",
        json={"confirmation": f"RESET ESTOP {device_id}"},
    )
    assert reset.status_code == 204


def test_control_token_is_not_exposed_in_device_or_event_reads():
    payload = client.get("/api/embodiments").text + client.get("/api/embodiments/events").text
    assert "control_token" not in payload


def test_mock_llm_runs_a_scored_embodied_episode():
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
    token = armed.json()["control_token"]
    headers = {"X-AgentGymnasium-Control-Token": token}

    response = client.post(
        f"/api/embodiments/{device_id}/episodes",
        headers=headers,
        json={
            "objective": "Reach the paired benchmark target.",
            "goal": {"x": 1.0, "y": 1.0},
            "max_turns": 3,
            "reset_before_run": True,
            "seed": 7,
            "agent": {
                "id": "pilot",
                "name": "Pilot",
                "provider": "mock",
                "model": "mock",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["final_distance_m"] <= 0.15
    assert body["interactions"][0]["result"]["tool_calls"][0]["tool"] == "drive_to"
    assert body["actions"][0]["accepted"] is True

    client.post(
        f"/api/embodiments/{device_id}/disarm",
        headers=headers,
        json={},
    )


def test_real_device_arming_requires_operator_key(monkeypatch):
    device = EmbodimentDevice(
        id="real-rover",
        label="Real Rover",
        adapter="ros2_gateway",
        mode=EnvironmentMode.real,
        safety_state=SafetyState.disarmed,
        limits=SafetyLimits(),
    )
    monkeypatch.setenv("AGENTGYMNASIUM_OPERATOR_KEY", "operator-secret")
    with pytest.raises(HTTPException) as denied:
        _authorize_real_device(device, "wrong")
    assert denied.value.status_code == 403
    _authorize_real_device(device, "operator-secret")
