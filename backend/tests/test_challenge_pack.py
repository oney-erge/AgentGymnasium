"""Challenge pack: goal zones + meaningfully distinct rewards per challenge."""
from __future__ import annotations

from agentgymnasium.core.schemas.design import BodyShape, BodySpec, DesignSpec
from agentgymnasium.core.schemas.trace import EpisodeTrace, Frame, FrameBody
from agentgymnasium.services.preset_service import get_scenario_preset
from agentgymnasium.services.scoring_service import REWARDS, compute_metrics, score_attempt


def _trace_to(x_final: float) -> EpisodeTrace:
    return EpisodeTrace(
        run_id="r",
        dt=0.5,
        frames=[
            Frame(t=0.0, bodies={"crate": FrameBody(x=0.0, y=1.0, angle=0.0)}),
            Frame(t=0.5, bodies={"crate": FrameBody(x=x_final / 2, y=1.0, angle=0.0)}),
            Frame(t=1.0, bodies={"crate": FrameBody(x=x_final, y=1.0, angle=0.0)}),
        ],
    )


def _design(metadata: dict) -> DesignSpec:
    d = DesignSpec(
        name="t",
        bodies=[BodySpec(id="crate", shape=BodyShape.box, position=[0.0, 1.0])],
    )
    d.metadata.update(metadata)
    return d


# ── Presets carry distinct rewards + goals ──────────────────────────────────


def test_presets_have_distinct_rewards():
    rewards = {
        get_scenario_preset(p).reward
        for p in ("bridge_builder", "crawl_challenge", "sorter", "tiny_city_preview")
    }
    # Bridge and Crawl no longer share distance_plus_stability.
    assert rewards == {"bridge_transport", "crawl_locomotion", "sorting_accuracy", "city_score"}


def test_bridge_and_crawl_carry_goal_params():
    assert get_scenario_preset("bridge_builder").goal.get("goal_x") == 8.0
    assert get_scenario_preset("crawl_challenge").goal.get("threshold_x") == 6.0


# ── Goal-aware metrics ──────────────────────────────────────────────────────


def test_reached_goal_metric():
    d = _design({"challenge": {"goal_x": 8.0}})
    m = compute_metrics(_trace_to(9.0), d)
    assert m["reached_goal"] == 1.0
    assert m["goal_progress"] == 1.0  # clamped


def test_goal_progress_partial():
    d = _design({"challenge": {"goal_x": 8.0}})
    m = compute_metrics(_trace_to(4.0), d)
    assert m["reached_goal"] == 0.0
    assert 0.4 < m["goal_progress"] < 0.6


def test_crossed_threshold_metric():
    d = _design({"challenge": {"threshold_x": 6.0}})
    assert compute_metrics(_trace_to(7.0), d)["crossed_threshold"] == 1.0
    assert compute_metrics(_trace_to(3.0), d)["crossed_threshold"] == 0.0


def test_falls_uses_kill_y_when_world_has_a_real_gap():
    # A world with a real ravine (kill_y set) should flag a fall once the body
    # passes the world's own chasm floor, not the generic default-world depth.
    d = _design({})
    trace = EpisodeTrace(
        run_id="r",
        dt=0.5,
        kill_y=-2.0,
        frames=[
            Frame(t=0.0, bodies={"crate": FrameBody(x=0.0, y=1.0, angle=0.0)}),
            Frame(t=0.5, bodies={"crate": FrameBody(x=0.0, y=-1.0, angle=0.0)}),
        ],
    )
    # -1.0 is above kill_y=-2.0 — still mid-fall through the gap, not "fallen" yet.
    assert compute_metrics(trace, d)["falls"] == 0.0

    trace_deep = trace.model_copy(deep=True)
    trace_deep.frames[1].bodies["crate"].y = -3.0
    assert compute_metrics(trace_deep, d)["falls"] == 1.0


# ── Rewards are distinct and goal-driven ────────────────────────────────────


def test_bridge_transport_rewards_reaching_goal():
    reached, ok, _ = REWARDS["bridge_transport"](
        {"goal_progress": 1.0, "reached_goal": 1.0, "stability": 1.0, "falls": 0.0, "parts_used": 6.0}
    )
    short, ok_short, _ = REWARDS["bridge_transport"](
        {"goal_progress": 0.3, "reached_goal": 0.0, "stability": 1.0, "falls": 0.0, "parts_used": 6.0}
    )
    assert reached > short
    assert ok is True and ok_short is False


def test_bridge_penalizes_excess_parts():
    lean, _, _ = REWARDS["bridge_transport"](
        {"goal_progress": 1.0, "reached_goal": 1.0, "stability": 1.0, "falls": 0.0, "parts_used": 8.0}
    )
    bloated, _, _ = REWARDS["bridge_transport"](
        {"goal_progress": 1.0, "reached_goal": 1.0, "stability": 1.0, "falls": 0.0, "parts_used": 40.0}
    )
    assert lean > bloated


def test_crawl_locomotion_rewards_motion_not_bulk():
    moved, ok, _ = REWARDS["crawl_locomotion"](
        {"distance_m": 7.0, "crossed_threshold": 1.0, "falls": 0.0}
    )
    still, ok_still, _ = REWARDS["crawl_locomotion"](
        {"distance_m": 0.5, "crossed_threshold": 0.0, "falls": 0.0}
    )
    assert moved > still
    assert ok is True and ok_still is False


# ── Sorter: true class-to-bin matching ──────────────────────────────────────


def _sorter_design(*, accepts: str | None, ball_color: str) -> DesignSpec:
    # Mirror real add_ball + add_bin: the bin is a static body AND a metadata entry.
    d = DesignSpec(
        name="t",
        bodies=[
            BodySpec(id="ball", shape=BodyShape.circle, position=[0.0, 1.0], color=ball_color),
            BodySpec(id="bin1", shape=BodyShape.box, position=[5.0, 0.0], size=[2.0, 2.0], static=True),
        ],
    )
    d.metadata["bins"] = [
        {"id": "bin1", "x": 5.0, "y": 0.0, "width": 2.0, "height": 2.0, "accepts": accepts}
    ]
    return d


def _ball_lands_in_bin() -> EpisodeTrace:
    return EpisodeTrace(
        run_id="r",
        dt=0.5,
        frames=[
            Frame(t=0.0, bodies={"ball": FrameBody(x=0.0, y=3.0, angle=0.0)}),
            Frame(t=0.5, bodies={"ball": FrameBody(x=5.0, y=0.0, angle=0.0)}),
        ],
    )


def test_sorter_counts_correct_class_match():
    d = _sorter_design(accepts="red", ball_color="red")
    m = compute_metrics(_ball_lands_in_bin(), d)
    assert m["bins_in_target"] == 1.0
    assert m["bins_correct"] == 1.0
    assert m["bins_matchable"] == 1.0


def test_sorter_wrong_class_is_contained_but_not_correct():
    d = _sorter_design(accepts="blue", ball_color="red")
    m = compute_metrics(_ball_lands_in_bin(), d)
    assert m["bins_in_target"] == 1.0
    assert m["bins_correct"] == 0.0
    # A wrong-bin landing must not count as a successful sort.
    assert score_attempt(_ball_lands_in_bin(), d, "sorting_accuracy").success is False


def test_sorter_falls_back_to_containment_without_classes():
    d = _sorter_design(accepts=None, ball_color="red")
    m = compute_metrics(_ball_lands_in_bin(), d)
    assert m["bins_matchable"] == 0.0
    # Containment counts when no class is declared.
    assert score_attempt(_ball_lands_in_bin(), d, "sorting_accuracy").success is True


# ── Tiny City: livability spacing ───────────────────────────────────────────


def test_city_rewards_spacing():
    well_spaced, _, _ = REWARDS["city_score"](
        {"parts_used": 5.0, "spread_area": 20.0, "avg_spacing": 3.0, "min_spacing": 2.0, "stability": 1.0}
    )
    clumped, _, _ = REWARDS["city_score"](
        {"parts_used": 5.0, "spread_area": 20.0, "avg_spacing": 0.3, "min_spacing": 0.2, "stability": 1.0}
    )
    assert well_spaced > clumped


def test_sorting_denominator_ignores_static_support(_unused=None):
    # Static support beams must NOT count as items to sort (H2 regression).
    from agentgymnasium.services.scoring_service import compute_metrics

    d = DesignSpec(
        name="t",
        bodies=[
            BodySpec(id="ball", shape=BodyShape.circle, position=[0.0, 1.0], color="red"),
            BodySpec(id="beam", shape=BodyShape.segment, position=[2.0, 0.0], size=[3.0], static=True),
            BodySpec(id="bin1", shape=BodyShape.box, position=[5.0, 0.0], size=[2.0, 2.0], static=True),
        ],
    )
    d.metadata["bins"] = [{"id": "bin1", "x": 5.0, "y": 0.0, "width": 2.0, "height": 2.0, "accepts": "red"}]
    m = compute_metrics(_ball_lands_in_bin(), d)
    # Only the dynamic ball is sortable, even though a static beam is present.
    assert m["sortable_items"] == 1.0
    # Perfect sort scores 100% (1/1), not 1/2 from counting the beam.
    card = score_attempt(_ball_lands_in_bin(), d, "sorting_accuracy")
    assert card.success is True
    assert "1/1" in card.summary
