from __future__ import annotations

import logging
import pathlib
import re

import yaml

from agentgymnasium.core.schemas.challenge import ScenarioPreset, WorldTemplate
from agentgymnasium.core.schemas.setup import LaunchConfig

logger = logging.getLogger(__name__)

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CHALLENGES_DIR = _PACKAGE_ROOT / "challenges"
_WORLD_TEMPLATES_DIR = _PACKAGE_ROOT / "worlds" / "templates"

# Saved custom presets live under the run-artifacts directory, relative to cwd.
_SAVED_PRESETS_DIR = pathlib.Path("runs") / "presets"


def _load_yaml(path: pathlib.Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    # An empty file parses to None; treat it as an empty mapping.
    return data or {}


def load_scenario_presets() -> list[ScenarioPreset]:
    """Load all built-in scenario presets from disk, sorted by id.

    A single malformed YAML file is skipped (and logged) rather than 500-ing the
    whole setup flow, since presets feed validation and the setup screen.
    """
    presets: list[ScenarioPreset] = []
    for path in sorted(_CHALLENGES_DIR.glob("*.yaml")):
        try:
            presets.append(ScenarioPreset(**_load_yaml(path)))
        except Exception:  # noqa: BLE001 - skip a bad file, keep the rest usable
            logger.warning("Skipping malformed scenario preset: %s", path, exc_info=True)
    return presets


def get_scenario_preset(preset_id: str) -> ScenarioPreset | None:
    """Return the scenario preset with the given id, or None if missing."""
    for preset in load_scenario_presets():
        if preset.id == preset_id:
            return preset
    return None


def load_world_templates() -> list[WorldTemplate]:
    """Load all world templates from disk, sorted by id.

    A malformed file is skipped (and logged) rather than breaking the setup flow.
    """
    templates: list[WorldTemplate] = []
    for path in sorted(_WORLD_TEMPLATES_DIR.glob("*.yaml")):
        try:
            templates.append(WorldTemplate(**_load_yaml(path)))
        except Exception:  # noqa: BLE001 - skip a bad file, keep the rest usable
            logger.warning("Skipping malformed world template: %s", path, exc_info=True)
    return templates


def get_world_template(template_id: str) -> WorldTemplate | None:
    """Return the world template with the given id, or None if missing."""
    for template in load_world_templates():
        if template.id == template_id:
            return template
    return None


def _safe_preset_name(name: str) -> str:
    """Reduce ``name`` to a filename-safe slug that can't escape the presets dir.

    Strips any path components and characters outside ``[A-Za-z0-9._-]`` so a
    crafted name (``../../etc/x``) can't traverse out of ``runs/presets/``.
    """
    base = pathlib.PurePath(name).name  # drop any directory components
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", base).strip("._")
    return slug


def save_preset(name: str, config: LaunchConfig) -> str:
    """Persist a custom LaunchConfig under runs/presets/{name}.json.

    Returns the path to the written file. Raises ValueError if ``name`` has no
    usable filename-safe characters.
    """
    safe = _safe_preset_name(name)
    if not safe:
        raise ValueError("invalid preset name")
    _SAVED_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    path = _SAVED_PRESETS_DIR / f"{safe}.json"
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    return str(path)


def load_preset(name: str) -> LaunchConfig | None:
    """Load a previously saved custom LaunchConfig, or None if missing."""
    safe = _safe_preset_name(name)
    if not safe:
        return None
    path = _SAVED_PRESETS_DIR / f"{safe}.json"
    if not path.is_file():
        return None
    return LaunchConfig.model_validate_json(path.read_text(encoding="utf-8"))


def list_saved_presets() -> list[str]:
    """Return the names of all saved custom presets, sorted."""
    if not _SAVED_PRESETS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _SAVED_PRESETS_DIR.glob("*.json"))
