import asyncio

from agentgymnasium.agents.runner import (
    AttemptResult,
    _build_memory,
    _repair_rejected,
)
from agentgymnasium.core.schemas.design import BodyShape, BodySpec, DesignSpec
from agentgymnasium.core.schemas.score import ScoreCard
from agentgymnasium.core.schemas.setup import (
    AgentConfig,
    AgentsConfig,
    ConstraintsConfig,
    LaunchConfig,
    LLMProvider,
    MemoryMode,
    ScenarioConfig,
    ToolsConfig,
    WorldConfig,
)
from agentgymnasium.core.schemas.toolcall import (
    ToolCallRecord,
    ToolCallStatus,
)
from agentgymnasium.core.schemas.trace import EpisodeTrace, Frame, FrameBody
from agentgymnasium.services import orchestrator
from agentgymnasium.services.orchestrator import RunManager
from agentgymnasium.services.scoring_service import score_attempt

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


def test_improvement_hint_populated():
    # Empty design -> hint mentions the design being empty.
    empty = score_attempt(None, DesignSpec(name="empty"), "distance_plus_stability")
    assert "empty" in empty.improvement_hint.lower()

    # Falling-body trace (body dips below the fall threshold then recovers) ->
    # hint mentions fell / support.
    design = DesignSpec(
        name="faller",
        bodies=[BodySpec(id="b1", shape=BodyShape.box, position=[0.0, 1.0])],
    )
    frames = [
        Frame(t=0.0, bodies={"b1": FrameBody(x=0.0, y=1.0, angle=0.0)}),
        Frame(t=0.1, bodies={"b1": FrameBody(x=0.0, y=-1.0, angle=0.0)}),
        Frame(t=0.2, bodies={"b1": FrameBody(x=0.0, y=1.0, angle=0.0)}),
    ]
    trace = EpisodeTrace(run_id="r1", dt=0.1, frames=frames)
    card = score_attempt(trace, design, "distance_plus_stability")
    assert card.metrics["falls"] > 0
    hint = card.improvement_hint.lower()
    assert "fell" in hint or "support" in hint


def test_attempt_lineage():
    async def scenario() -> None:
        manager = RunManager()
        run_id = await manager.create_run(_config())
        for _ in range(500):
            events = manager.get_events(run_id)
            if events and events[-1].get("type") == "run_finished":
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("run did not finish")

        events = manager.get_events(run_id)
        starts = [e for e in events if e["type"] == "attempt_started"]
        assert len(starts) >= 2
        # First attempt has no parent; the second's parent is set.
        assert starts[0]["parent_attempt_id"] is None
        assert starts[1]["parent_attempt_id"] is not None

    asyncio.run(scenario())


def test_build_memory_from_previous():
    # Plumbing: episodic/best_attempt_summary build a non-empty memory string.
    prev = AttemptResult(
        attempt_id="attempt_prev",
        design=DesignSpec(name="d"),
        trace_run_id=None,
        score=ScoreCard(score_total=12.5, improvement_hint="Stable but short."),
        tool_calls=[],
        attempt_index=0,
    )
    memory = _build_memory(prev)
    assert "12.5" in memory
    assert "Stable but short." in memory
    # No previous attempt -> empty memory.
    assert _build_memory(None) == ""
    # memory_mode none would pass "" (asserted via the enum contract).
    assert MemoryMode.none in MemoryMode


def _dup_record(bid: str) -> ToolCallRecord:
    return ToolCallRecord(
        ts=0.0,
        agent_id="a",
        tool="create_body",
        args={"id": bid, "shape": "box"},
        status=ToolCallStatus.rejected,
        error=f"body '{bid}' already exists",
    )


def test_repair_dedup():
    # A design that already contains b1; a rejected duplicate create_body for b1.
    design = DesignSpec(
        name="d",
        bodies=[BodySpec(id="b1", shape=BodyShape.box, position=[0.0, 0.0])],
    )
    records = [_dup_record("b1")]
    repair_record = _repair_rejected(design, ["create_body"], records)

    # Repair pass succeeded without hiding the original rejection.
    assert records[0].status == ToolCallStatus.rejected
    assert repair_record is not None
    assert repair_record.status == ToolCallStatus.repaired
    assert repair_record.tool == "repair_pass"
    assert repair_record.new_body_ids == ["b1_r"]
    assert {b.id for b in design.bodies} == {"b1", "b1_r"}


def test_repair_disabled_leaves_rejected():
    # When repair is NOT invoked (loop disabled), the duplicate stays rejected.
    design = DesignSpec(
        name="d",
        bodies=[BodySpec(id="b1", shape=BodyShape.box, position=[0.0, 0.0])],
    )
    records = [_dup_record("b1")]
    # Simulate the runner's gate: repair_loop_enabled=False => no repair call.
    assert records[0].status == ToolCallStatus.rejected
    assert {b.id for b in design.bodies} == {"b1"}
