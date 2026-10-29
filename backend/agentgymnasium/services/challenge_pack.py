"""Small, explicitly parameterized physics cases for repeatable experiments.

These are starter cases, not a validated general-purpose benchmark. A case
selects a fixed physical instance; sampling and cosmetic seeds are separate.
"""

from __future__ import annotations

from agentgymnasium.core.schemas.setup import LaunchConfig, ScenarioConfig, WorldConfig
from agentgymnasium.services.preset_service import get_scenario_preset, get_world_template
from agentgymnasium.services.workspace_config_service import default_workspace_config

PACK_ID = "starter-physics-v1"
_GRAVITY = (("light", -7.0), ("standard", -9.81), ("strong", -12.0))


def list_cases() -> dict:
    return {
        "pack_id": PACK_ID,
        "status": "experimental; cases are not yet validated reference solutions",
        "cases": [
            {
                "id": f"{preset}-{label}",
                "preset": preset,
                "gravity": gravity,
                "label": f"{label.title()} gravity ({gravity:g} m/s²)",
            }
            for preset in ("bridge_builder", "sorter")
            for label, gravity in _GRAVITY
        ],
    }


def case_config(case_id: str) -> LaunchConfig | None:
    case = next((item for item in list_cases()["cases"] if item["id"] == case_id), None)
    if case is None:
        return None
    preset = get_scenario_preset(case["preset"])
    template = get_world_template(preset.default_world) if preset else None
    if preset is None or template is None:
        raise ValueError(f"challenge pack references a missing preset or world: {case_id}")

    config = default_workspace_config()
    config.project_name = f"{PACK_ID} / {case_id}"
    config.scenario = ScenarioConfig(
        preset=preset.id, objective=preset.objective, reward=preset.reward
    )
    config.world = WorldConfig(
        template=template.id,
        terrain=template.terrain,
        engine=template.engine,
        gravity=case["gravity"],
        map_size=template.map_size,
        active_physics_zones=template.active_physics_zones,
        visual_seed=0,
    )
    # Keep gravity part of the task, rather than a tool-controlled escape hatch.
    config.tools.enabled = [name for name in config.tools.enabled if name != "set_gravity"]
    config.constraints.max_attempts = 1
    config.constraints.simulation_duration_seconds = 60
    return config
