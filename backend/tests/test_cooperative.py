from __future__ import annotations

import asyncio

from agentgymnasium.agents.runner import _remap_ids, run_cooperative_attempt
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


def _cooperative_config() -> LaunchConfig:
    return LaunchConfig(
        scenario=ScenarioConfig(preset="distance", objective="Travel far"),
        world=WorldConfig(template="flat_ground"),
        agents=AgentsConfig(
            mode=CollaborationMode.cooperative,
            participants=[
                AgentConfig(id="agent_a", name="Agent A", provider=LLMProvider.mock),
                AgentConfig(id="agent_b", name="Agent B", provider=LLMProvider.mock),
            ],
        ),
        tools=ToolsConfig(enabled=["create_body", "run_simulation"]),
        constraints=ConstraintsConfig(max_attempts=2),
    )


async def _run_to_completion(manager: RunManager, config: LaunchConfig) -> str:
    run_id = await manager.create_run(config)
    for _ in range(500):
        events = manager.get_events(run_id)
        if events and events[-1].get("type") == "run_finished":
            return run_id
        await asyncio.sleep(0.01)
    raise AssertionError("run did not finish within timeout")


def test_cooperative_shared_design():
    async def scenario() -> None:
        manager = RunManager()
        run_id = await _run_to_completion(manager, _cooperative_config())
        events = manager.get_events(run_id)

        # Exactly one trace_ready and one score per attempt (shared, not
        # one-per-agent).
        attempts = {
            e["attempt_index"] for e in events if e["type"] == "attempt_finished"
        }
        assert attempts, "expected at least one cooperative attempt"
        for attempt_index in attempts:
            traces = [
                e
                for e in events
                if e["type"] == "trace_ready"
                and e["attempt_index"] == attempt_index
            ]
            scores = [
                e
                for e in events
                if e["type"] == "score" and e["attempt_index"] == attempt_index
            ]
            assert len(traces) == 1, "exactly one shared trace per attempt"
            assert len(scores) == 1, "exactly one shared score per attempt"
            assert scores[0]["agent_id"] == "shared"

        # No winner event in cooperative mode.
        assert not [e for e in events if e["type"] == "winner"]

        finished = events[-1]
        assert finished["type"] == "run_finished"
        assert finished.get("winner_agent_id") is None

        # run_started advertises both participants in cooperative mode.
        started = events[0]
        assert started["type"] == "run_started"
        assert started["mode"] == "cooperative"
        assert {a["id"] for a in started["agents"]} == {"agent_a", "agent_b"}

        # tool_call events are attributed to BOTH agents.
        tool_agents = {
            e["agent_id"] for e in events if e["type"] == "tool_call"
        }
        assert "agent_a" in tool_agents
        assert "agent_b" in tool_agents

        # design_update carries a by_agent ownership breakdown.
        updates = [e for e in events if e["type"] == "design_update"]
        assert updates
        for update in updates:
            assert "by_agent" in update
            assert set(update["by_agent"]) >= {"agent_a", "agent_b"}

    asyncio.run(scenario())


def test_cooperative_attempt_ownership():
    async def scenario() -> None:
        result = await run_cooperative_attempt(_cooperative_config())
        owners = {b.created_by for b in result.design.bodies}
        assert "agent_a" in owners, "agent A must own at least one body"
        assert "agent_b" in owners, "agent B must own at least one body"

        # Ids are namespaced per agent so they don't collide in the shared
        # design.
        ids = {b.id for b in result.design.bodies}
        assert any(i.startswith("agent_a_") for i in ids)
        assert any(i.startswith("agent_b_") for i in ids)

        # One shared trace and one shared score for the whole design.
        assert result.trace_run_id is not None
        assert result.score is not None

    asyncio.run(scenario())


def test_remap_namespaces_own_created_ids():
    """An agent's own created body id is namespaced; its own self-reference too."""
    created: dict[str, str] = {}
    a = _remap_ids("agent_b", "create_body", {"id": "b1", "shape": "box"}, created)
    assert a["id"] == "agent_b_b1"
    assert created == {"b1": "agent_b_b1"}

    # A joint that references the agent's OWN freshly-created body remaps it.
    j = _remap_ids(
        "agent_b",
        "add_joint",
        {"id": "j1", "body_a": "b1", "body_b": "b2", "type": "pivot"},
        created,
    )
    assert j["id"] == "agent_b_j1"
    assert j["body_a"] == "agent_b_b1"  # own body → namespaced
    assert j["body_b"] == "b2"  # not created by this agent → left intact


def test_remap_preserves_cross_agent_reference():
    """A reference to another agent's already-live id is left untouched.

    This is the H6 fix: cross-agent joints must resolve against the live design
    rather than being rewritten into a non-existent namespaced id.
    """
    created: dict[str, str] = {}
    # agent_b references agent_a's already-namespaced body in a joint.
    j = _remap_ids(
        "agent_b",
        "add_joint",
        {"id": "j1", "body_a": "agent_a_base", "body_b": "agent_b_arm", "type": "pin"},
        created,
    )
    assert j["id"] == "agent_b_j1"
    # Neither ref was created by agent_b this turn, so both stay as written.
    assert j["body_a"] == "agent_a_base"
    assert j["body_b"] == "agent_b_arm"
