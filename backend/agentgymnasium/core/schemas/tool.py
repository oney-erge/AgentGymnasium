from enum import StrEnum

from pydantic import BaseModel


class ToolCategory(StrEnum):
    building = "building"
    sensors_control = "sensors_control"
    physics_materials = "physics_materials"
    simulation_inspection = "simulation_inspection"
    evolution_utilities = "evolution_utilities"


class RiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class ToolStatus(StrEnum):
    """Honest implementation state of a tool, surfaced to the UI and chokepoint.

    - ``implemented``: mutates the design and takes real effect.
    - ``inspection``: read-only / informational — legitimately does not mutate.
    - ``experimental``: not yet implemented; off by default and rejected with a
      clear message if called, so it never silently "succeeds" as a no-op.
    """

    implemented = "implemented"
    inspection = "inspection"
    experimental = "experimental"


class ToolDefinition(BaseModel):
    name: str
    category: ToolCategory
    description: str
    risk: RiskLevel = RiskLevel.low
    enabled_by_default: bool = True
    status: ToolStatus = ToolStatus.implemented
    compatible_challenges: list[str] = []  # empty = all
    input_schema: dict = {}  # JSON Schema object for the tool args

