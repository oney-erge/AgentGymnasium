"""Attempt diff: structured comparison fed into the prompt and surfaced to Studio."""
from __future__ import annotations

from agentgymnasium.agents.runner import AttemptResult, _attempt_diff, _build_memory
from agentgymnasium.core.schemas.design import BodyShape, BodySpec, DesignSpec
from agentgymnasium.core.schemas.score import ScoreCard


def _design(ids_positions: dict[str, list[float]]) -> DesignSpec:
    return DesignSpec(
        name="t",
        bodies=[
            BodySpec(id=bid, shape=BodyShape.box, position=pos)
            for bid, pos in ids_positions.items()
        ],
    )


def _score(total: float, failures: list[dict] | None = None) -> ScoreCard:
    return ScoreCard(
        run_id="r",
        reward="default",
        score_total=total,
        success=False,
        metrics={},
        failure_events=failures or [],
        summary="",
        improvement_hint="",
    )


def _attempt(idx: int, design: DesignSpec, score: ScoreCard) -> AttemptResult:
    return AttemptResult(
        attempt_id=f"a{idx}", design=design, trace_run_id=None,
        score=score, tool_calls=[], attempt_index=idx,
    )


def test_diff_is_none_for_first_attempt():
    assert _attempt_diff(None, _design({"b1": [0, 1]}), _score(5)) is None


def test_diff_tracks_added_removed_moved_and_score():
    prev = _attempt(0, _design({"b1": [0.0, 1.0], "b2": [1.0, 1.0]}), _score(10.0))
    cur_design = _design({"b1": [0.0, 1.0], "b3": [2.0, 1.0]})  # removed b2, added b3
    cur_design.bodies[0].position = [0.5, 1.0]  # moved b1
    diff = _attempt_diff(prev, cur_design, _score(14.0, [{"type": "fall"}]))
    assert diff is not None
    assert diff["prev_attempt_index"] == 0
    assert diff["added_parts"] == ["b3"]
    assert diff["removed_parts"] == ["b2"]
    assert diff["moved_parts"] == ["b1"]
    assert diff["parts_delta"] == 0  # 2 → 2
    assert diff["score_delta"] == 4.0
    assert diff["prev_score"] == 10.0
    assert diff["failure_events"] == ["fall"]


def test_memory_includes_diff_summary():
    prev = _attempt(0, _design({"b1": [0.0, 1.0]}), _score(5.0))
    # Build attempt 1 with a diff vs attempt 0.
    a1_design = _design({"b1": [0.0, 1.0], "b2": [1.0, 1.0]})
    a1 = _attempt(1, a1_design, _score(8.0))
    a1.diff = _attempt_diff(prev, a1_design, a1.score)

    memory = _build_memory(a1)
    assert "Attempt #1" in memory
    assert "added 1 part" in memory
    assert "score +3.0" in memory


def test_memory_empty_for_no_previous():
    assert _build_memory(None) == ""
