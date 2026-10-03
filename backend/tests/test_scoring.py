import pytest
from fastapi.testclient import TestClient

from agentgymnasium.app import app
from agentgymnasium.core.schemas.design import BodyShape, BodySpec, DesignSpec
from agentgymnasium.core.schemas.score import ScoreCard
from agentgymnasium.core.schemas.trace import EpisodeTrace, Frame, FrameBody
from agentgymnasium.services.scoring_service import (
    REWARDS,
    compute_metrics,
    score_attempt,
)

client = TestClient(app)


def _design(n: int = 1) -> DesignSpec:
    return DesignSpec(
        name="t",
        bodies=[
            BodySpec(id=f"b{i}", shape=BodyShape.box, position=[0.0, 1.0])
            for i in range(n)
        ],
    )


def _moving_trace(distance: float, *, falls: int = 0) -> EpisodeTrace:
    """A trace where body ``b0`` moves ``distance`` units in x over 3 frames."""
    half = distance / 2.0
    frames = [
        Frame(t=0.0, bodies={"b0": FrameBody(x=0.0, y=1.0, angle=0.0)}),
        Frame(t=0.5, bodies={"b0": FrameBody(x=half, y=1.0, angle=0.0)}),
        Frame(t=1.0, bodies={"b0": FrameBody(x=distance, y=1.0, angle=0.0)}),
    ]
    if falls:
        # Add a frame where the body drops below the fall threshold.
        frames.append(
            Frame(t=1.5, bodies={"b0": FrameBody(x=distance, y=-5.0, angle=0.0)})
        )
        frames.append(
            Frame(t=2.0, bodies={"b0": FrameBody(x=distance, y=1.0, angle=0.0)})
        )
    return EpisodeTrace(run_id="r", dt=0.5, frames=frames)


def test_seeded_world_parts_excluded_and_city_layout_scored():
    # A city of agent-placed structures plus seeded world terrain. Part count and
    # layout spread/spacing must reflect only the agent's spread-out structures,
    # never the clustered terrain.
    design = DesignSpec(
        name="city",
        bodies=[
            BodySpec(id="ground_pad", shape=BodyShape.box, position=[0.0, 0.0], created_by="world"),
            BodySpec(id="bldg1", shape=BodyShape.box, position=[-6.0, 1.0], created_by="a"),
            BodySpec(id="bldg2", shape=BodyShape.box, position=[0.0, 1.0], created_by="a"),
            BodySpec(id="bldg3", shape=BodyShape.box, position=[6.0, 1.0], created_by="a"),
            BodySpec(id="bldg4", shape=BodyShape.box, position=[0.0, 5.0], created_by="a"),
        ],
    )
    trace = _moving_trace(0.0)  # positions are read from the design layout
    metrics = compute_metrics(trace, design)
    assert metrics["parts_used"] == 4.0  # excludes the seeded ground_pad
    assert metrics["spread_area"] > 0.0
    assert metrics["min_spacing"] >= 1.0
    score, success, _ = REWARDS["city_score"](metrics)
    # A pile of plain (unkinded) boxes is well-spread and spaced, but is not a
    # city — no road/park/trees and fewer than 6 buildings, so it must not pass.
    assert success is False


def test_metrics_from_trace():
    trace = _moving_trace(4.0)
    metrics = compute_metrics(trace, _design(2))
    for key in (
        "distance_m",
        "stability",
        "energy",
        "parts_used",
        "falls",
        "duration_s",
    ):
        assert key in metrics
        assert isinstance(metrics[key], float)
    assert metrics["parts_used"] == 2.0
    assert metrics["distance_m"] == 4.0
    assert metrics["duration_s"] == 1.0


def test_distance_reward_success():
    trace = _moving_trace(5.0)
    card = score_attempt(trace, _design(1), "distance_plus_stability")
    assert card.reward == "distance_plus_stability"
    assert card.success is True
    assert card.score_total > 0
    assert card.metrics["falls"] == 0.0


def test_distance_reward_falls_recorded():
    trace = _moving_trace(5.0, falls=1)
    card = score_attempt(trace, _design(1), "distance_plus_stability")
    assert card.metrics["falls"] == 1.0
    assert card.success is False
    assert any(e.get("type") == "fall" for e in card.failure_events)


def test_empty_design_zero_score():
    card = score_attempt(None, DesignSpec(name="empty"), "distance_plus_stability")
    assert card.score_total == 0.0
    assert card.success is False
    assert "empty" in card.summary.lower()
    assert any(e.get("type") == "empty_design" for e in card.failure_events)


def test_unknown_reward_uses_default():
    trace = _moving_trace(3.0)
    card = score_attempt(trace, _design(1), "nonexistent")
    assert card.reward == "default"
    assert isinstance(card, ScoreCard)


def test_all_named_rewards_registered():
    for name in ("distance_plus_stability", "sorting_accuracy", "city_score"):
        assert name in REWARDS


def test_get_score_endpoint():
    create = client.post("/api/runs", json={"duration_seconds": 1.0})
    assert create.status_code == 200
    run_id = create.json()["run_id"]

    r = client.get(f"/api/runs/{run_id}/score")
    assert r.status_code == 200
    body = r.json()
    assert "score_total" in body
    assert "metrics" in body
    assert isinstance(body["metrics"], dict)


def test_get_score_endpoint_404():
    r = client.get("/api/runs/does-not-exist/score")
    assert r.status_code == 404


# ── New metric keys ──────────────────────────────────────────────────────────

def test_new_metric_keys_always_present():
    trace = _moving_trace(2.0)
    metrics = compute_metrics(trace, _design(3))
    for key in ("spread_area", "bins_count", "bins_in_target"):
        assert key in metrics
        assert isinstance(metrics[key], float)


def test_spread_area_computed():
    """Spread_area reflects where the agent PLACED structures (design layout)."""
    trace = _moving_trace(0.0)  # any trace with frames; spread comes from layout
    design = DesignSpec(
        name="t",
        bodies=[
            BodySpec(id="b0", shape=BodyShape.box, position=[0.0, 0.0]),
            BodySpec(id="b1", shape=BodyShape.box, position=[10.0, 4.0]),
        ],
    )
    metrics = compute_metrics(trace, design)
    assert metrics["spread_area"] == pytest.approx(40.0)


# ── Sorting accuracy reward ──────────────────────────────────────────────────

def _sorter_design_in_bin():
    """One dynamic ball + one static bin; bin metadata stored in design.metadata."""
    return DesignSpec(
        name="sorter",
        bodies=[
            BodySpec(id="ball1", shape=BodyShape.circle, position=[0.0, 5.0]),
            BodySpec(id="bin1", shape=BodyShape.box, position=[3.0, 0.0],
                     size=[2.0, 2.0], static=True),
        ],
        metadata={"bins": [{"id": "bin1", "x": 3.0, "y": 0.0, "width": 2.0, "height": 2.0}]},
    )


def _sorter_trace_ball_in_bin():
    from agentgymnasium.core.schemas.trace import EpisodeTrace, Frame, FrameBody

    return EpisodeTrace(
        run_id="r",
        dt=0.5,
        frames=[
            Frame(t=0.0, bodies={
                "ball1": FrameBody(x=0.0, y=5.0, angle=0.0),
                "bin1": FrameBody(x=3.0, y=0.0, angle=0.0),
            }),
            Frame(t=1.0, bodies={
                "ball1": FrameBody(x=3.0, y=0.5, angle=0.0),  # inside bin ±1.0
                "bin1": FrameBody(x=3.0, y=0.0, angle=0.0),
            }),
        ],
    )


def test_sorting_accuracy_ball_in_bin():
    design = _sorter_design_in_bin()
    trace = _sorter_trace_ball_in_bin()
    card = score_attempt(trace, design, "sorting_accuracy")
    assert card.reward == "sorting_accuracy"
    assert card.metrics["bins_in_target"] == pytest.approx(1.0)
    assert card.success is True
    assert "1/1" in card.summary


def test_sorting_accuracy_no_bins():
    """Without bins placed, sorting accuracy falls back gracefully (not success)."""
    trace = _moving_trace(2.0)
    card = score_attempt(trace, _design(1), "sorting_accuracy")
    assert card.reward == "sorting_accuracy"
    assert card.success is False
    assert "No bins" in card.summary


# ── City score reward ────────────────────────────────────────────────────────

def _city_design_spread() -> DesignSpec:
    """Four structures placed across a 15×4 area → spread_area = 60."""
    return DesignSpec(
        name="city",
        bodies=[
            BodySpec(id="b0", shape=BodyShape.box, position=[0.0, 0.0]),
            BodySpec(id="b1", shape=BodyShape.box, position=[5.0, 2.0]),
            BodySpec(id="b2", shape=BodyShape.box, position=[10.0, 4.0]),
            BodySpec(id="b3", shape=BodyShape.box, position=[15.0, 1.0]),
        ],
    )


def test_city_score_spread_bodies():
    design = _city_design_spread()
    trace = _moving_trace(0.0)
    card = score_attempt(trace, design, "city_score")
    assert card.reward == "city_score"
    assert card.metrics["spread_area"] > 0
    # Four plain (unkinded) boxes are spread out but aren't a city — no
    # road/park/trees and fewer than 6 buildings, so this must not succeed.
    assert card.success is False
    assert card.score_total > 0


def test_city_score_success_requires_the_real_mix():
    # The bar a real Tiny City attempt must clear: 6+ buildings plus at least
    # one road, one park, and two trees — not just "4 things, spaced out".
    trace = _moving_trace(0.0)
    design = _city_design_with_kinds(
        ["road", "park", "tree", "tree", "house", "tower", "shop", "house", "tower", "shop"]
    )
    card = score_attempt(trace, design, "city_score")
    assert card.metrics["building_count"] == 6.0
    assert card.success is True


def test_city_score_single_body_not_success():
    trace = _moving_trace(0.0)
    card = score_attempt(trace, _design(1), "city_score")
    assert card.reward == "city_score"
    assert card.success is False


def _city_design_with_kinds(kinds: list[str | None]) -> DesignSpec:
    return DesignSpec(
        name="city",
        bodies=[
            BodySpec(
                id=f"b{i}", shape=BodyShape.box, position=[float(i * 3), 1.0],
                size=[2.0, 3.0], static=True, kind=k,
            )
            for i, k in enumerate(kinds)
        ],
    )


def test_city_score_rewards_infrastructure_variety():
    # A layout with a road, a park, and a tree (real city infra) must outscore
    # the same number of plain, kind-less boxes — this is what pushes agents to
    # build an actual city instead of a row of identical buildings.
    trace = _moving_trace(0.0)
    plain = _city_design_with_kinds([None] * 6)
    varied = _city_design_with_kinds(["road", "park", "tree", "house", "tower", "shop"])
    plain_score, _, _ = REWARDS["city_score"](compute_metrics(trace, plain))
    varied_score, _, _ = REWARDS["city_score"](compute_metrics(trace, varied))
    assert varied_score > plain_score


def test_city_score_kind_metrics_ignore_seeded_world_props():
    # The world template seeds its own road/trees (created_by="world") purely
    # for visual backdrop; they must not inflate the agent's infra-variety score.
    trace = _moving_trace(0.0)
    design = DesignSpec(
        name="city",
        bodies=[
            BodySpec(
                id="world_road", shape=BodyShape.box, position=[0.0, 0.1],
                size=[20.0, 0.3], static=True, kind="road", created_by="world",
            ),
            BodySpec(
                id="b0", shape=BodyShape.box, position=[-6.0, 1.5],
                size=[2.0, 3.0], static=True, kind="house", created_by="a",
            ),
        ],
    )
    metrics = compute_metrics(trace, design)
    assert metrics["road_count"] == 0.0  # world-seeded road excluded


def test_city_score_penalizes_overlapping_buildings():
    # Two buildings stacked at the same x-position visually intersect — a bad
    # city layout — and must score worse than the same buildings well-spaced.
    trace = _moving_trace(0.0)
    overlapping = DesignSpec(
        name="city",
        bodies=[
            BodySpec(id="b0", shape=BodyShape.box, position=[0.0, 1.5], size=[3.0, 3.0], static=True),
            BodySpec(id="b1", shape=BodyShape.box, position=[1.0, 1.5], size=[3.0, 3.0], static=True),
        ],
    )
    spaced = DesignSpec(
        name="city",
        bodies=[
            BodySpec(id="b0", shape=BodyShape.box, position=[0.0, 1.5], size=[3.0, 3.0], static=True),
            BodySpec(id="b1", shape=BodyShape.box, position=[6.0, 1.5], size=[3.0, 3.0], static=True),
        ],
    )
    overlap_metrics = compute_metrics(trace, overlapping)
    spaced_metrics = compute_metrics(trace, spaced)
    assert overlap_metrics["overlap_total"] > 0.0
    assert spaced_metrics["overlap_total"] == 0.0
    overlap_score, _, _ = REWARDS["city_score"](overlap_metrics)
    spaced_score, _, _ = REWARDS["city_score"](spaced_metrics)
    assert spaced_score > overlap_score
