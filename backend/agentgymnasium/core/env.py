"""Environment variables for AgentGymnasium.

The project was called Agentarium until 2026-10, and its variables were named ``AGENTARIUM_*``.
Both spellings are read, so existing setups keep working: ``AGENTGYMNASIUM_<NAME>`` wins, and
``AGENTARIUM_<NAME>`` is used only when the new name is not set at all.
"""
from __future__ import annotations

import os

PREFIX = "AGENTGYMNASIUM_"
LEGACY_PREFIX = "AGENTARIUM_"


def env(name: str, default: str | None = None) -> str | None:
    """Return ``AGENTGYMNASIUM_<name>``, else the legacy ``AGENTARIUM_<name>``, else ``default``."""
    value = os.environ.get(PREFIX + name)
    if value is None:
        value = os.environ.get(LEGACY_PREFIX + name)
    return default if value is None else value
