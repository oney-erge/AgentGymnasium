"""Memory-retention bounds (gap H3).

The in-memory run stores must not grow without limit on a long-lived server.
``run_service`` evicts oldest runs across all three stores together; the
orchestrator evicts only oldest FINISHED runs (never in-flight ones).
"""

from __future__ import annotations

from agentgymnasium.core.schemas.design import BodyShape, BodySpec, DesignSpec
from agentgymnasium.core.schemas.score import ScoreCard
from agentgymnasium.core.schemas.trace import EpisodeTrace
from agentgymnasium.services import orchestrator, run_service
from agentgymnasium.services.orchestrator import RunManager, _RunState


def test_run_service_evicts_oldest_across_all_stores(monkeypatch):
    monkeypatch.setattr(run_service, "_MAX_RETAINED_RUNS", 3)
    run_service.RUNS.clear()
    run_service.SCORES.clear()
    run_service.DESIGNS.clear()

    for i in range(5):
        rid = f"run_{i}"
        run_service.RUNS[rid] = EpisodeTrace(run_id=rid, dt=0.1)
        run_service.SCORES[rid] = ScoreCard()
        run_service.DESIGNS[rid] = DesignSpec(
            bodies=[BodySpec(id="b", shape=BodyShape.box)]
        )
        run_service._evict_oldest_runs()

    # Only the 3 newest remain, and all three stores stayed in lock-step.
    assert set(run_service.RUNS) == {"run_2", "run_3", "run_4"}
    assert set(run_service.SCORES) == set(run_service.RUNS)
    assert set(run_service.DESIGNS) == set(run_service.RUNS)


def test_orchestrator_evicts_only_finished_runs(monkeypatch):
    monkeypatch.setattr(orchestrator, "MAX_RETAINED_RUNS", 2)
    manager = RunManager()

    # Two finished runs + one in-flight, all over the cap of 2.
    finished_a = _RunState()
    finished_a.finished = True
    finished_b = _RunState()
    finished_b.finished = True
    in_flight = _RunState()  # finished defaults to False

    manager._runs["finished_a"] = finished_a
    manager._runs["finished_b"] = finished_b
    manager._runs["in_flight"] = in_flight

    manager._evict_finished_runs()

    # Oldest finished run dropped; the in-flight run is never evicted.
    assert "in_flight" in manager._runs
    assert "finished_a" not in manager._runs
    assert len(manager._runs) == 2


def test_orchestrator_keeps_inflight_when_all_unfinished(monkeypatch):
    monkeypatch.setattr(orchestrator, "MAX_RETAINED_RUNS", 1)
    manager = RunManager()
    manager._runs["a"] = _RunState()
    manager._runs["b"] = _RunState()

    manager._evict_finished_runs()

    # Nothing finished → nothing evicted even though we're over the cap.
    assert set(manager._runs) == {"a", "b"}


def test_create_run_from_design_respects_cap(monkeypatch):
    monkeypatch.setattr(run_service, "_MAX_RETAINED_RUNS", 2)
    run_service.RUNS.clear()
    run_service.SCORES.clear()
    run_service.DESIGNS.clear()

    from agentgymnasium.core.schemas.setup import WorldConfig

    design = DesignSpec(
        bodies=[BodySpec(id="ball", shape=BodyShape.circle, position=[0.0, 5.0])]
    )
    for _ in range(4):
        run_service.create_run_from_design(design, WorldConfig(template="flat"), 0.2)

    assert len(run_service.RUNS) == 2
    assert set(run_service.SCORES) == set(run_service.RUNS)
    assert set(run_service.DESIGNS) == set(run_service.RUNS)
