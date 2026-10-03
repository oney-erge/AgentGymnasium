from agentgymnasium.core.schemas.tool import (
    RiskLevel,
    ToolCategory,
    ToolDefinition,
    ToolStatus,
)

_TOOLS: list[ToolDefinition] = [
    # -------------------------------------------------------------------------
    # building (enabled by default, except add_bin)
    # -------------------------------------------------------------------------
    ToolDefinition(
        name="create_body",
        category=ToolCategory.building,
        description="Create a rigid body with the given shape and optional physical properties.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        input_schema={
            "type": "object",
            "required": ["id", "shape"],
            "properties": {
                "id": {"type": "string", "description": "Unique identifier for the body"},
                "shape": {
                    "type": "string",
                    "enum": ["segment", "box", "circle", "polygon"],
                    "description": "Geometry type of the body",
                },
                "length": {"type": "number", "description": "Square box side (for box shapes)"},
                "width": {"type": "number", "description": "Box width in metres (overrides length)"},
                "height": {
                    "type": "number",
                    "description": "Box height in metres — use a tall height for buildings/walls",
                },
                "radius": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Radius (for circle shape)",
                },
                "mass": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Mass of the body in kg",
                },
                "static": {
                    "type": "boolean",
                    "description": "If true the body is fixed in place (e.g. a building or wall)",
                },
                "position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Centre [x, y] position; a body sits on the ground when y = height/2",
                },
                "z": {
                    "type": "number",
                    "description": (
                        "Ground-plane depth coordinate — ONLY for the citysim (isometric "
                        "city) engine, where a structure's footprint sits at [x, z]. Ignored "
                        "by physics worlds."
                    ),
                },
                "depth": {
                    "type": "number",
                    "minimum": 0.01,
                    "description": (
                        "Footprint depth along the z-axis (citysim only). Defaults to a "
                        "square footprint (same as width) when omitted."
                    ),
                },
                "kind": {
                    "type": "string",
                    "description": (
                        "Semantic label so it renders as a recognizable prop: "
                        "house/apartment/tower/shop/factory/school/hospital/power_plant/"
                        "road/tree/park/plaza/fountain/wall/crate/water/etc."
                    ),
                },
                "color": {
                    "type": "string",
                    "description": "Optional render color, e.g. '#60a5fa' or 'red'.",
                },
            },
        },
    ),
    ToolDefinition(
        name="add_joint",
        category=ToolCategory.building,
        description="Connect two bodies with a joint of the specified type.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        input_schema={
            "type": "object",
            "required": ["id", "body_a", "body_b", "type"],
            "properties": {
                "id": {"type": "string", "description": "Unique identifier for the joint"},
                "body_a": {"type": "string", "description": "ID of the first body"},
                "body_b": {"type": "string", "description": "ID of the second body"},
                "type": {
                    "type": "string",
                    "enum": ["pivot", "pin", "slide", "spring"],
                    "description": "Joint type",
                },
                "anchor_a": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": (
                        "Attachment point [x, y] in body_a's own local space, relative to "
                        "its center (default [0, 0] = body_a's center). For a hinge, use "
                        "the point where body_b actually touches body_a (e.g. a leg "
                        "attaching to a torso's edge), not the center — anchoring both "
                        "bodies at their centers snaps them together with a hard jolt."
                    ),
                },
                "anchor_b": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": (
                        "Attachment point [x, y] in body_b's own local space, relative to "
                        "its center (default [0, 0]). For a segment body_b (a leg/beam), "
                        "the ends are at [-length/2, 0] and [length/2, 0] before rotation — "
                        "use one of those as the hinge point, not the segment's middle."
                    ),
                },
            },
        },
    ),
    ToolDefinition(
        name="add_motor",
        category=ToolCategory.building,
        description="Attach a rotary motor to a joint to drive movement.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        input_schema={
            "type": "object",
            "required": ["id", "joint_id", "rate"],
            "properties": {
                "id": {"type": "string", "description": "Unique identifier for the motor"},
                "joint_id": {"type": "string", "description": "ID of the joint to motorise"},
                "rate": {"type": "number", "description": "Rotation rate in radians per second"},
                "max_force": {
                    "type": "number",
                    "description": "Maximum force the motor can exert",
                },
            },
        },
    ),
    ToolDefinition(
        name="add_beam",
        category=ToolCategory.building,
        description="Add a structural beam between two points in the world.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        input_schema={
            "type": "object",
            "required": ["id", "start", "end"],
            "properties": {
                "id": {"type": "string", "description": "Unique identifier for the beam"},
                "start": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Start [x, y] coordinate",
                },
                "end": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "End [x, y] coordinate",
                },
                "width": {"type": "number", "description": "Thickness of the beam"},
                "kind": {"type": "string", "description": "Semantic label (default 'beam')"},
                "color": {
                    "type": "string",
                    "description": "Optional render color, e.g. '#8b5a2b'.",
                },
            },
        },
    ),
    ToolDefinition(
        name="add_ramp",
        category=ToolCategory.building,
        description="Place an inclined ramp surface between two points.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        input_schema={
            "type": "object",
            "required": ["id", "start", "end"],
            "properties": {
                "id": {"type": "string", "description": "Unique identifier for the ramp"},
                "start": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Start [x, y] coordinate",
                },
                "end": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "End [x, y] coordinate",
                },
                "angle": {
                    "type": "number",
                    "description": "Override angle in degrees (optional)",
                },
                "kind": {"type": "string", "description": "Semantic label (default 'ramp')"},
                "color": {
                    "type": "string",
                    "description": "Optional render color, e.g. '#64748b'.",
                },
            },
        },
    ),
    ToolDefinition(
        name="add_ball",
        category=ToolCategory.building,
        description="Drop a spherical ball at the given position.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        input_schema={
            "type": "object",
            "required": ["id", "position"],
            "properties": {
                "id": {"type": "string", "description": "Unique identifier for the ball"},
                "position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Initial [x, y] position",
                },
                "radius": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Ball radius",
                },
                "mass": {
                    "type": "number",
                    "minimum": 0.001,
                    "description": "Mass of the ball in kg",
                },
                "color": {
                    "type": "string",
                    "description": "Ball class/color (e.g. 'red') for sorting challenges",
                },
                "kind": {"type": "string", "description": "Semantic label (default 'ball')"},
            },
        },
    ),
    ToolDefinition(
        name="add_bin",
        category=ToolCategory.building,
        description="Place a container bin that can catch objects.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        input_schema={
            "type": "object",
            "required": ["id", "position"],
            "properties": {
                "id": {"type": "string", "description": "Unique identifier for the bin"},
                "position": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Center [x, y] position",
                },
                "width": {
                    "type": "number",
                    "minimum": 0.4,
                    "description": "Width of the bin opening",
                },
                "height": {
                    "type": "number",
                    "minimum": 0.4,
                    "description": "Height of the bin walls",
                },
                "accepts": {
                    "type": "string",
                    "description": "Ball class/color this bin accepts (sorting challenges)",
                },
                "kind": {"type": "string", "description": "Semantic label (default 'bin')"},
                "color": {
                    "type": "string",
                    "description": "Optional render color, usually matching accepts.",
                },
            },
        },
    ),
    # -------------------------------------------------------------------------
    # sensors_control (all enabled by default)
    # -------------------------------------------------------------------------
    ToolDefinition(
        name="add_sensor",
        category=ToolCategory.sensors_control,
        description="Attach a sensor to a body to measure contact, distance, or velocity.",
        risk=RiskLevel.low,
        enabled_by_default=False,
        status=ToolStatus.experimental,
        input_schema={
            "type": "object",
            "required": ["id", "body_id", "type"],
            "properties": {
                "id": {"type": "string", "description": "Unique identifier for the sensor"},
                "body_id": {
                    "type": "string",
                    "description": "ID of the body to attach the sensor to",
                },
                "type": {
                    "type": "string",
                    "enum": ["contact", "distance", "velocity"],
                    "description": "Sensor measurement type",
                },
            },
        },
    ),
    ToolDefinition(
        name="set_controller",
        category=ToolCategory.sensors_control,
        description="Assign a motion controller to a body to drive its behaviour.",
        risk=RiskLevel.low,
        enabled_by_default=False,
        status=ToolStatus.experimental,
        input_schema={
            "type": "object",
            "required": ["body_id", "type"],
            "properties": {
                "body_id": {
                    "type": "string",
                    "description": "ID of the body to control",
                },
                "type": {
                    "type": "string",
                    "enum": ["oscillate", "pid", "sequence"],
                    "description": "Controller algorithm type",
                },
                "params": {
                    "type": "object",
                    "description": "Controller-specific parameters",
                },
            },
        },
    ),
    ToolDefinition(
        name="get_state",
        category=ToolCategory.sensors_control,
        description="Return a snapshot of the current world and design state.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        status=ToolStatus.inspection,
        input_schema={"type": "object", "properties": {}},
    ),
    # -------------------------------------------------------------------------
    # physics_materials (set_material, set_friction enabled; rest disabled)
    # -------------------------------------------------------------------------
    ToolDefinition(
        name="set_material",
        category=ToolCategory.physics_materials,
        description="Apply a named material preset (rubber/metal/wood/glass) to a body.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        input_schema={
            "type": "object",
            "required": ["body_id", "material"],
            "properties": {
                "body_id": {"type": "string", "description": "ID of the target body"},
                "material": {
                    "type": "string",
                    "enum": ["rubber", "metal", "wood", "glass"],
                    "description": "Material preset name",
                },
            },
        },
    ),
    ToolDefinition(
        name="set_friction",
        category=ToolCategory.physics_materials,
        description="Set the friction coefficient for a body surface.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        input_schema={
            "type": "object",
            "required": ["body_id", "friction"],
            "properties": {
                "body_id": {"type": "string", "description": "ID of the target body"},
                "friction": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Friction coefficient between 0.0 and 1.0",
                },
            },
        },
    ),
    ToolDefinition(
        name="set_density",
        category=ToolCategory.physics_materials,
        description="Override the density of a body to change its effective mass.",
        risk=RiskLevel.low,
        enabled_by_default=False,
        input_schema={
            "type": "object",
            "required": ["body_id", "density"],
            "properties": {
                "body_id": {"type": "string", "description": "ID of the target body"},
                "density": {"type": "number", "description": "Density value (kg/m²)"},
            },
        },
    ),
    ToolDefinition(
        name="set_collision_group",
        category=ToolCategory.physics_materials,
        description="Assign a body to a collision group so it ignores collisions within the group.",
        risk=RiskLevel.low,
        enabled_by_default=False,
        status=ToolStatus.experimental,
        input_schema={
            "type": "object",
            "required": ["body_id", "group"],
            "properties": {
                "body_id": {"type": "string", "description": "ID of the target body"},
                "group": {
                    "type": "integer",
                    "description": "Collision group integer identifier",
                },
            },
        },
    ),
    ToolDefinition(
        name="set_gravity",
        category=ToolCategory.physics_materials,
        description="Modify global gravity for the simulation world.",
        risk=RiskLevel.medium,
        enabled_by_default=False,
        input_schema={
            "type": "object",
            "required": ["gravity"],
            "properties": {
                "gravity": {
                    "type": "number",
                    "description": "Gravitational acceleration (negative = downward)",
                },
            },
        },
    ),
    # -------------------------------------------------------------------------
    # simulation_inspection (run/inspect enabled; compare_attempts disabled)
    # -------------------------------------------------------------------------
    ToolDefinition(
        name="run_simulation",
        category=ToolCategory.simulation_inspection,
        description="Execute the physics simulation and return the outcome.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        status=ToolStatus.inspection,
        input_schema={
            "type": "object",
            "properties": {
                "duration_seconds": {
                    "type": "number",
                    "description": "How long to run the simulation in seconds",
                },
            },
        },
    ),
    ToolDefinition(
        name="inspect_score",
        category=ToolCategory.simulation_inspection,
        description="Retrieve the current score for the active challenge attempt.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        status=ToolStatus.inspection,
        input_schema={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="inspect_failure_events",
        category=ToolCategory.simulation_inspection,
        description="List failure events from the last simulation run.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        status=ToolStatus.inspection,
        input_schema={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="compare_attempts",
        category=ToolCategory.simulation_inspection,
        description="Compare two past simulation attempts side-by-side.",
        risk=RiskLevel.low,
        enabled_by_default=False,
        status=ToolStatus.inspection,
        input_schema={
            "type": "object",
            "required": ["attempt_a", "attempt_b"],
            "properties": {
                "attempt_a": {
                    "type": "string",
                    "description": "ID or label of the first attempt",
                },
                "attempt_b": {
                    "type": "string",
                    "description": "ID or label of the second attempt",
                },
            },
        },
    ),
    # -------------------------------------------------------------------------
    # evolution_utilities (mutate/save/repair/name enabled; export disabled)
    # -------------------------------------------------------------------------
    ToolDefinition(
        name="mutate_design",
        category=ToolCategory.evolution_utilities,
        description="Apply a random or targeted mutation to the current design.",
        risk=RiskLevel.low,
        enabled_by_default=False,
        status=ToolStatus.experimental,
        input_schema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["random", "structural", "controller"],
                    "description": "Mutation strategy to apply",
                },
            },
        },
    ),
    ToolDefinition(
        name="save_best_design",
        category=ToolCategory.evolution_utilities,
        description="Persist the highest-scoring design seen so far to storage.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        status=ToolStatus.inspection,
        input_schema={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="repair_invalid_design",
        category=ToolCategory.evolution_utilities,
        description="Automatically fix constraint violations in the current design.",
        risk=RiskLevel.low,
        enabled_by_default=False,
        status=ToolStatus.experimental,
        input_schema={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="name_design",
        category=ToolCategory.evolution_utilities,
        description="Assign a human-readable name to the current design.",
        risk=RiskLevel.low,
        enabled_by_default=True,
        input_schema={
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Human-readable design name"},
            },
        },
    ),
    ToolDefinition(
        name="export_design",
        category=ToolCategory.evolution_utilities,
        description="Export the current design to a YAML or JSON file.",
        risk=RiskLevel.low,
        enabled_by_default=False,
        status=ToolStatus.inspection,
        input_schema={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["yaml", "json"],
                    "description": "Output file format",
                },
            },
        },
    ),
]

# Index by name for O(1) lookup
_TOOL_INDEX: dict[str, ToolDefinition] = {t.name: t for t in _TOOLS}


def get_all_tools() -> list[ToolDefinition]:
    """Return all registered tool definitions."""
    return list(_TOOLS)


def get_tools_by_category() -> dict[str, list[ToolDefinition]]:
    """Return tools grouped by category name."""
    result: dict[str, list[ToolDefinition]] = {}
    for tool in _TOOLS:
        result.setdefault(tool.category.value, []).append(tool)
    return result


def get_tool(name: str) -> ToolDefinition | None:
    """Return the tool with the given name, or None if not found."""
    return _TOOL_INDEX.get(name)
