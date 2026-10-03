import asyncio

from fastapi.testclient import TestClient

from agentgymnasium.app import app
from agentgymnasium.core.schemas.setup import (
    AgentConfig,
    AgentsConfig,
    CollaborationMode,
    ConstraintsConfig,
    LaunchConfig,
    LLMProvider,
    ScenarioConfig,
    ToolsConfig,
    WorldConfig,
)
from agentgymnasium.services import orchestrator
from agentgymnasium.services.orchestrator import RunManager

# Keep streaming instant in tests.
orchestrator.STREAM_DELAY = 0.0


def _config() -> LaunchConfig:
    return LaunchConfig(
        scenario=ScenarioConfig(preset="distance", objective="Travel far"),
        world=WorldConfig(template="flat_ground"),
        agents=AgentsConfig(
            participants=[
                AgentConfig(id="a", name="Builder", provider=LLMProvider.mock),
            ]
        ),
        tools=ToolsConfig(enabled=["create_body", "run_simulation"]),
        constraints=ConstraintsConfig(max_attempts=2),
    )


async def _run_to_completion(manager: RunManager, config: LaunchConfig) -> str:
    run_id = await manager.create_run(config)
    # Poll until a run_finished event appears, with a timeout.
    for _ in range(500):
        events = manager.get_events(run_id)
        if events and events[-1].get("type") == "run_finished":
            return run_id
        await asyncio.sleep(0.01)
    raise AssertionError("run did not finish within timeout")


def test_launch_creates_run():
    async def scenario() -> None:
        manager = RunManager()
        run_id = await _run_to_completion(manager, _config())
        types = [e["type"] for e in manager.get_events(run_id)]
        assert "run_started" in types
        assert "attempt_started" in types
        assert types.count("tool_call") >= 1
        assert "score" in types
        assert "run_finished" in types

    asyncio.run(scenario())


def test_events_buffered():
    async def scenario() -> None:
        manager = RunManager()
        run_id = await _run_to_completion(manager, _config())
        events = manager.get_events(run_id)
        assert events[0]["type"] == "run_started"
        assert events[-1]["type"] == "run_finished"

    asyncio.run(scenario())


def test_subscribe_yields_full_history():
    async def scenario() -> None:
        manager = RunManager()
        run_id = await _run_to_completion(manager, _config())
        # Late subscriber should still receive the full buffered history.
        received = [event async for event in manager.subscribe(run_id)]
        assert received[0]["type"] == "run_started"
        assert received[-1]["type"] == "run_finished"

    asyncio.run(scenario())


def test_subscribe_unknown_run():
    async def scenario() -> None:
        manager = RunManager()
        received = [event async for event in manager.subscribe("does-not-exist")]
        assert received == [{"type": "error", "detail": "unknown run"}]

    asyncio.run(scenario())


def _competitive_config() -> LaunchConfig:
    return LaunchConfig(
        scenario=ScenarioConfig(preset="distance", objective="Travel far"),
        world=WorldConfig(template="flat_ground"),
        agents=AgentsConfig(
            mode=CollaborationMode.competitive,
            participants=[
                AgentConfig(id="agent_a", name="Agent A", provider=LLMProvider.mock),
                AgentConfig(id="agent_b", name="Agent B", provider=LLMProvider.mock),
            ],
        ),
        tools=ToolsConfig(enabled=["create_body", "run_simulation"]),
        constraints=ConstraintsConfig(max_attempts=2),
    )


def test_competitive_two_agents():
    async def scenario() -> None:
        manager = RunManager()
        run_id = await _run_to_completion(manager, _competitive_config())
        events = manager.get_events(run_id)

        # Both agents produced their own scored designs.
        score_agents = {
            e["agent_id"] for e in events if e["type"] == "score"
        }
        assert "agent_a" in score_agents
        assert "agent_b" in score_agents

        # A winner event exists naming one of the two agents.
        winners = [e for e in events if e["type"] == "winner"]
        assert len(winners) == 1
        assert winners[0]["agent_id"] in {"agent_a", "agent_b"}

        # run_finished carries the winner.
        finished = events[-1]
        assert finished["type"] == "run_finished"
        assert finished["winner_agent_id"] in {"agent_a", "agent_b"}
        assert finished["winner_agent_id"] == winners[0]["agent_id"]

        # run_started advertises both participants.
        started = events[0]
        assert started["type"] == "run_started"
        assert started["mode"] == "competitive"
        assert {a["id"] for a in started["agents"]} == {"agent_a", "agent_b"}

    asyncio.run(scenario())


def test_relay_alternates_agents_and_preserves_lineage():
    async def scenario() -> None:
        manager = RunManager()
        config = _competitive_config()
        config.agents.mode = CollaborationMode.relay
        config.constraints.max_attempts = 3
        run_id = await _run_to_completion(manager, config)
        events = manager.get_events(run_id)

        started = [event for event in events if event["type"] == "attempt_started"]
        assert [event["agent_id"] for event in started] == [
            "agent_a",
            "agent_b",
            "agent_a",
        ]
        assert started[0]["parent_attempt_id"] is None
        assert started[1]["parent_attempt_id"] is not None
        assert started[2]["parent_attempt_id"] is not None
        assert not any(event["type"] == "winner" for event in events)
        assert events[-1]["winner_agent_id"] is None

    asyncio.run(scenario())


def test_sandbox_gives_each_agent_one_trial_without_winner():
    async def scenario() -> None:
        manager = RunManager()
        config = _competitive_config()
        config.agents.mode = CollaborationMode.sandbox
        config.constraints.max_attempts = 7
        run_id = await _run_to_completion(manager, config)
        events = manager.get_events(run_id)

        scores = [event for event in events if event["type"] == "score"]
        assert [event["agent_id"] for event in scores] == ["agent_a", "agent_b"]
        assert not any(event["type"] == "winner" for event in events)
        assert events[-1]["winner_agent_id"] is None

    asyncio.run(scenario())


def test_ws_streams_events():
    orchestrator.STREAM_DELAY = 0.0
    client = TestClient(app)
    resp = client.post("/api/setup/launch", json=_config().model_dump(mode="json"))
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        types: list[str] = []
        for _ in range(200):
            event = ws.receive_json()
            types.append(event["type"])
            if event["type"] == "run_finished":
                break
        assert "run_started" in types
        assert "run_finished" in types


def test_design_snapshot_events_stream_in_lockstep_with_tool_calls():
    # The Build Timeline needs one design_snapshot per tool_call, same attempt,
    # same agent, in matching order — so the UI can pair them up 1:1.
    async def scenario() -> None:
        manager = RunManager()
        run_id = await _run_to_completion(manager, _config())
        events = manager.get_events(run_id)

        tool_calls = [e for e in events if e["type"] == "tool_call"]
        snapshots = [e for e in events if e["type"] == "design_snapshot"]
        assert len(snapshots) == len(tool_calls)
        for snap in snapshots:
            assert "trace" in snap
            assert "world_static" in snap["trace"]
            assert "body_meta" in snap["trace"]
            assert isinstance(snap["step_index"], int)
            assert isinstance(snap["tool"], str)
            assert snap["status"] in {"success", "repaired", "rejected"}
            assert isinstance(snap["label"], str)
            assert isinstance(snap["mutated"], bool)
            assert isinstance(snap["visual_change"], bool)
            assert isinstance(snap["new_body_ids"], list)
            assert isinstance(snap["new_joint_ids"], list)

    asyncio.run(scenario())


def test_run_started_reports_effective_caps():
    async def scenario() -> None:
        manager = RunManager()
        cfg = _config()
        cfg.constraints.max_attempts = 50
        cfg.constraints.simulation_duration_seconds = 180
        run_id = await _run_to_completion(manager, cfg)
        started = manager.get_events(run_id)[0]
        assert started["type"] == "run_started"
        # Effective single-agent cap is the ceiling; sim cap too; requests echoed.
        from agentgymnasium.agents.runner import _MAX_SIM_DURATION_SECONDS
        from agentgymnasium.services.orchestrator import MAX_ATTEMPTS_CAP

        assert started["max_attempts"] == MAX_ATTEMPTS_CAP
        assert started["requested_attempts"] == 50
        assert started["attempts_cap"] == MAX_ATTEMPTS_CAP
        assert started["simulation_cap_s"] == _MAX_SIM_DURATION_SECONDS
        assert started["requested_duration_s"] == 180

    asyncio.run(scenario())
