from __future__ import annotations

from agentgymnasium.core.schemas.tool import ToolDefinition


def _tool_line(tool: ToolDefinition) -> str:
    schema = tool.input_schema
    required = schema.get("required", [])
    req = ", ".join(required) if required else "(none)"
    # Surface enum constraints (e.g. shape must be box|circle|...) inline — weak
    # models otherwise guess invalid values ("rectangle") and get rejected.
    enums = [
        f"{name} must be one of {props['enum']}"
        for name, props in schema.get("properties", {}).items()
        if props.get("enum")
    ]
    enum_str = (" | " + "; ".join(enums)) if enums else ""
    return f"- {tool.name}: {tool.description} required args: {req}{enum_str}"


# Tools whose bodies accept a semantic ``kind`` label.
_KINDABLE_TOOLS = frozenset({"create_body", "add_beam", "add_ramp", "add_ball", "add_bin"})


def _kind_guidance(objective: str) -> str:
    """Tell the agent to label what it builds so it renders as a real prop.

    Includes concrete proportions (the renderer draws a recognizable house/tower/
    tree/road, not a generic block) plus a per-challenge palette hint.
    """
    lower = objective.lower()
    if "city" in lower:
        palette = (
            "For a city, vary the parts: 'house' (box ~2-4 wide x 2-3 tall), "
            "'tower' (box ~2 wide x 5-8 tall), 'tree' (small box/circle ~1 wide), "
            "'road' (long thin box, height ~0.3), 'plaza' (wide flat box). "
            "Aim for a readable layout: rows of buildings along roads, with gaps."
        )
    elif "bridge" in lower or "crate" in lower:
        palette = (
            "Label structural parts 'deck' (the walkway), 'pillar'/'support' "
            "(vertical), and the cargo 'crate'."
        )
    elif "creature" in lower or "crawl" in lower:
        palette = "Label parts 'body', 'leg', and 'foot' so the creature reads clearly."
    elif "sort" in lower or "bin" in lower:
        palette = "Label catchers 'bin' and the items 'ball' (give each a color)."
    else:
        palette = (
            "Use kinds like 'wall', 'platform', 'block', 'crate', 'ball' to make "
            "the design readable."
        )
    return (
        "Make the result LOOK like what it is: pass a `kind` label on every body "
        "you create (the renderer draws a recognizable prop per kind, scaled to "
        "the body's real size). " + palette
    )


def build_system_prompt(
    challenge_objective: str,
    world_summary: str,
    enabled_tools: list[ToolDefinition],
    constraints: str = "",
    movable_body_required: bool = True,
) -> str:
    """System prompt for a single builder agent in the physics sandbox.

    ``movable_body_required`` gates the "include a movable body" rule below —
    false for challenges (e.g. Tiny City) whose objective is a mostly-static
    scene, where forcing a movable body would fight the actual objective.
    """
    tool_lines = "\n".join(_tool_line(t) for t in enabled_tools)
    parts = [
        "You are a builder agent in a 2D physics sandbox. Your job is to "
        "construct a design that achieves the objective below.",
        f"Objective: {challenge_objective}",
        f"World: {world_summary}",
    ]
    if constraints:
        parts.append(f"Constraints: {constraints}")
    parts.append(
        "You may ONLY use the following tools:\n" + tool_lines
    )
    if any(t.name in _KINDABLE_TOOLS for t in enabled_tools):
        parts.append(_kind_guidance(challenge_objective))
    movable_rule = (
        "- Your design MUST include at least one MOVABLE (non-static) body, or "
        "nothing will move and you score zero. create_body and add_ball are "
        "movable; add_beam and add_ramp are fixed scaffolding.\n"
        if movable_body_required
        else "- This is a mostly-static scene — most or all bodies should be "
        "static:true (buildings, roads, parks). You do NOT need a moving body.\n"
    )
    parts.append(
        "Rules:\n"
        "- Build in world units (METERS), not pixels — coordinates are small "
        "numbers like 2.0 or -5.0, never 200 or 400.\n"
        f"{movable_rule}"
        "- To connect to an object already in the world, reference its id exactly.\n"
        "- Prefer a few well-placed parts over many."
    )
    parts.append(
        "Example of a VALID response — copy these exact field names and value "
        "formats (only use tools that appear in the list above):\n"
        '{"tool_calls": [\n'
        '  {"tool": "create_body", "args": {"id": "tower1", "shape": "box", '
        '"position": [-5.0, 3.0], "width": 2.0, "height": 6.0, "static": true}},\n'
        '  {"tool": "create_body", "args": {"id": "ball1", "shape": "circle", '
        '"position": [0.0, 5.0], "radius": 0.5, "mass": 1.0}},\n'
        '  {"tool": "add_ramp", "args": {"id": "ramp1", "start": [-4.0, 2.0], '
        '"end": [3.0, 1.0]}}\n'
        "]}\n"
        "Notes: shape is \"box\" (never \"rectangle\"). A box is sized with "
        "\"width\" and \"height\" in metres (tall height = a building/wall); a "
        "circle uses \"radius\". Positions are [x, y] arrays in metres, and a "
        "body of height h rests ON the ground when its y = h/2. Use "
        "\"static\": true for fixed structures like buildings, walls, and "
        "platforms; leave it off for things that should move."
    )
    parts.append(
        "Respond with a SINGLE JSON object and nothing else, of the form:\n"
        '{"tool_calls": [{"tool": "<name>", "args": {...}}, ...]}\n'
        "Each tool call must use one of the listed tool names and supply its "
        "required args. Do not wrap the JSON in code fences or prose."
    )
    return "\n\n".join(parts)


def build_user_prompt(
    challenge_objective: str, attempt_index: int = 0, memory: str = ""
) -> str:
    """Per-attempt task text for the builder agent.

    ``memory`` is an optional brief summary of previous attempts (score +
    improvement hint) appended so an agent with episodic memory can iterate.
    """
    text = (
        f"Attempt #{attempt_index}. Build a design to achieve: "
        f"{challenge_objective}. Emit your tool_calls now."
    )
    if memory:
        text += f"\n\nPrevious attempts:\n{memory}"
    return text


def build_cooperative_user_prompt(
    challenge_objective: str,
    attempt_index: int,
    *,
    body_count: int,
    joint_count: int,
    existing_body_ids: list[str],
) -> str:
    """Task text for a follow-up agent extending a shared cooperative design.

    The agent is told the current design summary and asked to extend/stabilize
    the existing partial design rather than start from scratch.
    """
    ids_preview = ", ".join(existing_body_ids[:12])
    if len(existing_body_ids) > 12:
        ids_preview += ", …"
    return (
        f"Attempt #{attempt_index}. You are collaborating on a SHARED design "
        f"to achieve: {challenge_objective}.\n"
        f"The design so far has {body_count} bodies and {joint_count} joints.\n"
        f"Existing body ids: [{ids_preview}].\n"
        "Extend and stabilize this existing design (add supports, joints, or "
        "missing parts). To connect to an existing part, reference its id "
        "EXACTLY as listed above (e.g. body_a/body_b on add_joint). Emit your "
        "tool_calls now."
    )
