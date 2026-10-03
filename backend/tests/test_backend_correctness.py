"""Backend correctness fixes: max_motors budget, scoring/engine, prune, path-safety."""
from __future__ import annotations

import sqlite3

import pytest

from agentgymnasium.core.schemas.design import DesignSpec
from agentgymnasium.core.schemas.setup import WorldConfig
from agentgymnasium.services import preset_service, run_service
from agentgymnasium.services.run_service import (
    create_run_from_design,
    hardcoded_demo_design,
)
from agentgymnasium.tools.apply import apply_tool_call

_TOOLS = ["create_body", "add_joint", "add_motor"]


def _two_bodies_one_joint() -> DesignSpec:
    d = DesignSpec(name="t")
    for bid in ("b1", "b2"):
        apply_tool_call(
            d, agent_id="a", tool="create_body",
            args={"id": bid, "shape": "box", "position": [0.0, 5.0]},
            enabled_tools=_TOOLS,
        )
    apply_tool_call(
        d, agent_id="a", tool="add_joint",
        args={"id": "j1", "body_a": "b1", "body_b": "b2", "type": "pivot"},
        enabled_tools=_TOOLS,
    )
    return d


def test_max_motors_enforced():
    d = _two_bodies_one_joint()
    # First motor under budget 1 succeeds; a second motor is rejected.
    ok = apply_tool_call(
        d, agent_id="a", tool="add_motor",
        args={"id": "m1", "joint_id": "j1", "rate": 1.0},
        enabled_tools=_TOOLS, max_motors=1,
    )
    assert ok.record.status.value.lower() == "success"
    # Add another joint so a second motor target exists.
    apply_tool_call(
        d, agent_id="a", tool="add_joint",
        args={"id": "j2", "body_a": "b1", "body_b": "b2", "type": "pin"},
        enabled_tools=_TOOLS,
    )
    rejected = apply_tool_call(
        d, agent_id="a", tool="add_motor",
        args={"id": "m2", "joint_id": "j2", "rate": 1.0},
        enabled_tools=_TOOLS, max_motors=1,
    )
    assert rejected.record.status.value.lower() == "rejected"
    assert "max_motors" in (rejected.record.error or "")


def test_name_design_sets_name():
    d = DesignSpec(name="t")
    r = apply_tool_call(
        d, agent_id="a", tool="name_design",
        args={"name": "My Bridge"}, enabled_tools=["name_design"],
    )
    assert r.record.status.value.lower() == "success"
    assert r.mutated is True
    assert d.name == "My Bridge"


def test_name_design_rejects_missing_name():
    d = DesignSpec(name="t")
    r = apply_tool_call(
        d, agent_id="a", tool="name_design", args={}, enabled_tools=["name_design"],
    )
    assert r.record.status.value.lower() == "rejected"
    assert d.name == "t"


def test_max_motors_none_unlimited():
    d = _two_bodies_one_joint()
    r = apply_tool_call(
        d, agent_id="a", tool="add_motor",
        args={"id": "m1", "joint_id": "j1", "rate": 1.0},
        enabled_tools=_TOOLS, max_motors=None,
    )
    assert r.record.status.value.lower() == "success"


def test_engine_records_final_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(run_service, "_RUNS_DIR", tmp_path)
    monkeypatch.setattr(run_service, "_DB_PATH", tmp_path / "db.sqlite")
    run_service._init_db()
    design = hardcoded_demo_design()
    world = WorldConfig(template="flat_arena", engine="pymunk2d")
    run_id = create_run_from_design(design, world, duration_seconds=0.3)
    trace = run_service.get_trace(run_id)
    assert trace is not None and trace.frames
    # The last recorded frame time should match the simulated duration (final
    # frame is always recorded), not stop short of it.
    assert trace.frames[-1].t == pytest.approx(0.3, abs=1 / 60 + 1e-6)


def test_save_preset_rejects_path_traversal(tmp_path, monkeypatch):
    import pathlib

    from agentgymnasium.core.schemas.setup import LaunchConfig, ScenarioConfig
    from agentgymnasium.core.schemas.setup import WorldConfig as WC

    monkeypatch.setattr(preset_service, "_SAVED_PRESETS_DIR", tmp_path / "presets")
    cfg = LaunchConfig(
        scenario=ScenarioConfig(preset="bridge_builder"),
        world=WC(template="island_cliff_small"),
    )
    path = preset_service.save_preset("../../evil", cfg)
    # The written file must stay inside the presets dir, with no traversal.
    written = pathlib.Path(path).resolve()
    assert (tmp_path / "presets").resolve() in written.parents
    assert ".." not in written.name


def test_db_prune_drops_orphan_scores_and_designs(tmp_path, monkeypatch):
    monkeypatch.setattr(run_service, "_RUNS_DIR", tmp_path)
    monkeypatch.setattr(run_service, "_DB_PATH", tmp_path / "db.sqlite")
    monkeypatch.setattr(run_service, "_DB_MAX_ROWS", 2)
    run_service._init_db()
    world = WorldConfig(template="flat_arena", engine="pymunk2d")
    for _ in range(4):
        create_run_from_design(hardcoded_demo_design(), world, duration_seconds=0.05)
    with sqlite3.connect(run_service._DB_PATH) as conn:
        runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        scores = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
        designs = conn.execute("SELECT COUNT(*) FROM designs").fetchone()[0]
    assert runs <= 2
    # scores/designs must not exceed the runs they belong to (no orphan leak).
    assert scores <= 2
    assert designs <= 2
