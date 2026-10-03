from __future__ import annotations

import pathlib

from agentgymnasium.core.schemas.setup import (
    AgentConfig,
    AgentsConfig,
    ConstraintsConfig,
    LaunchConfig,
    LLMConnectionConfig,
    ScenarioConfig,
    ToolsConfig,
    WorldConfig,
)

_WORKSPACE_CONFIG_PATH = pathlib.Path("runs") / "workspace_config.json"


def default_workspace_config() -> LaunchConfig:
    """Return the setup screen's persisted workspace baseline."""
    return LaunchConfig(
        project_name="Bridge Builder Lab",
        scenario=ScenarioConfig(
            preset="bridge_builder",
            objective="",
            reward="",
        ),
        world=WorldConfig(template="island_cliff_small"),
        agents=AgentsConfig(
            mode="single",
            participants=[
                AgentConfig(
                    id="agent_a",
                    name="Agent A",
                    provider="localdeploy",
                    model="qwen3_8b_ollama",
                    endpoint_url="http://127.0.0.1:8000/v1",
                    temperature=0.2,
                )
            ],
        ),
        llm_connection=LLMConnectionConfig(endpoint_url="http://127.0.0.1:8000/v1"),
        tools=ToolsConfig(enabled=[]),
        constraints=ConstraintsConfig(
            max_parts=300,
            max_joints=120,
            energy_budget=1200,
            max_attempts=50,
            simulation_duration_seconds=180,
            material_budget=2000,
        ),
    )


def workspace_config_path() -> pathlib.Path:
    return _WORKSPACE_CONFIG_PATH


def workspace_config_status() -> dict:
    path = workspace_config_path()
    exists = path.is_file()
    return {
        "path": str(path),
        "exists": exists,
        "mtime_ns": path.stat().st_mtime_ns if exists else None,
    }


def save_workspace_config(config: LaunchConfig) -> dict:
    path = workspace_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)
    return workspace_config_status()


def load_workspace_config() -> tuple[LaunchConfig, dict]:
    path = workspace_config_path()
    if not path.is_file():
        config = default_workspace_config()
        status = save_workspace_config(config)
        return config, status

    config = LaunchConfig.model_validate_json(path.read_text(encoding="utf-8"))
    return config, workspace_config_status()
