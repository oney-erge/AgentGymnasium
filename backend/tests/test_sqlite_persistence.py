"""SQLite write-through and DB-fallback for evicted in-memory runs."""
from __future__ import annotations

import pytest

from agentgymnasium.core.schemas.setup import (
    AgentConfig,
    AgentsConfig,
    LaunchConfig,
    LLMConnectionConfig,
    ScenarioConfig,
    WorldConfig,
)
from agentgymnasium.services import run_service
from agentgymnasium.services.run_service import create_run_from_design, hardcoded_demo_design


def _make_run() -> str:
    design = hardcoded_demo_design()
    world = WorldConfig(template="island_cliff_small", engine="pymunk2d")
    return create_run_from_design(design, world, duration_seconds=0.05)  # noqa: E302


def test_run_written_to_db(tmp_path, monkeypatch):
    """After create_run_from_design the run_id is queryable from the DB."""
    monkeypatch.setattr(run_service, "_RUNS_DIR", tmp_path)
    monkeypatch.setattr(run_service, "_DB_PATH", tmp_path / "agentgymnasium.db")
    run_service._init_db()

    run_id = _make_run()
    # Evict from memory to force DB path.
    run_service.RUNS.pop(run_id, None)
    run_service.SCORES.pop(run_id, None)
    run_service.DESIGNS.pop(run_id, None)

    assert run_service.get_trace(run_id) is not None
    assert run_service.get_score(run_id) is not None
    assert run_service.get_design(run_id) is not None


def test_score_written_to_db(tmp_path, monkeypatch):
    """store_score persists to DB so it survives memory eviction."""
    from agentgymnasium.core.schemas.score import ScoreCard  # noqa: PLC0415
    monkeypatch.setattr(run_service, "_RUNS_DIR", tmp_path)
    monkeypatch.setattr(run_service, "_DB_PATH", tmp_path / "agentgymnasium.db")
    run_service._init_db()

    run_id = _make_run()
    new_score = ScoreCard(
        run_id=run_id, reward="distance_plus_stability",
        score_total=42.0, success=True, metrics={}, failure_events=[],
        summary="test", improvement_hint="none",
    )
    run_service.store_score(run_id, new_score)
    run_service.SCORES.pop(run_id, None)

    stored = run_service.get_score(run_id)
    assert stored is not None
    assert stored.score_total == pytest.approx(42.0)


def test_unknown_run_returns_none():
    assert run_service.get_trace("nonexistent_run_id_xyz") is None
    assert run_service.get_score("nonexistent_run_id_xyz") is None
    assert run_service.get_design("nonexistent_run_id_xyz") is None


def test_persisted_launch_config_redacts_api_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(run_service, "_RUNS_DIR", tmp_path)
    monkeypatch.setattr(run_service, "_DB_PATH", tmp_path / "agentgymnasium.db")
    run_service._init_db()
    config = LaunchConfig(
        scenario=ScenarioConfig(preset="bridge_builder"),
        world=WorldConfig(template="island_cliff_small"),
        agents=AgentsConfig(
            participants=[
                AgentConfig(
                    id="agent_a",
                    name="Agent A",
                    api_key="participant-secret",
                )
            ]
        ),
        llm_connection=LLMConnectionConfig(api_key="shared-secret"),
    )

    run_service.record_launch_config("secret-test", config)

    stored = run_service.get_launch_config("secret-test")
    assert stored is not None
    assert stored.llm_connection.api_key is None
    assert stored.agents.participants[0].api_key is None
    artifact = (tmp_path / "secret-test" / "launch_config.json").read_text()
    assert "participant-secret" not in artifact
    assert "shared-secret" not in artifact
    # Redaction must not mutate the in-flight runtime config.
    assert config.llm_connection.api_key == "shared-secret"
