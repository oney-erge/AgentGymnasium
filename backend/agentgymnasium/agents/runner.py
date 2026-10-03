from __future__ import annotations

import hashlib
import json
import pathlib
import time
import uuid

import yaml
from pydantic import BaseModel, Field

from agentgymnasium.agents import get_provider
from agentgymnasium.agents.prompts import (
    build_cooperative_user_prompt,
    build_system_prompt,
    build_user_prompt,
)
from agentgymnasium.core.schemas.challenge import ScenarioPreset
from agentgymnasium.core.schemas.design import WORLD_AUTHOR, BodySpec, DesignSpec
from agentgymnasium.core.schemas.model import ModelInteraction, ModelRequest
from agentgymnasium.core.schemas.score import ScoreCard
from agentgymnasium.core.schemas.setup import (
    AgentConfig,
    CollisionSafety,
    LaunchConfig,
    MemoryMode,
    PhysicsEngine,
    WorldBounds,
    WorldConfig,
)
from agentgymnasium.core.schemas.toolcall import BuildStepRecord, ToolCallRecord, ToolCallStatus
from agentgymnasium.engines import get_engine
from agentgymnasium.services.preset_service import get_scenario_preset, get_world_template
from agentgymnasium.services.run_service import (
    create_run_from_design,
    get_trace,
    record_run_meta,
    store_score,
)
from agentgymnasium.services.scoring_service import score_attempt
from agentgymnasium.tools.apply import apply_tool_call, material_units
from agentgymnasium.tools.registry import get_tool

_RUNS_DIR = pathlib.Path("runs")
# "Agentarium Run" is the project's former default name. Saved configs may still carry it,
# so it stays recognised as a stale default and is replaced by the challenge name.
_DEFAULT_PROJECT_NAMES = {"", "AgentGymnasium Run", "Agentarium Run", "Bridge Builder Lab"}

# Rewards scored from an all-static design (a city needs no movable body to
# "work") — the system prompt's "at least one MOVABLE body or score zero"
# rule would otherwise fight these challenges.
_STATIC_OK_REWARDS = frozenset(
    {"city_score", "city_planning", "boomtown", "budget_city", "balanced_city", "green_capital"}
)


def _project_name(config: LaunchConfig, preset: ScenarioPreset | None = None) -> str:
    """Human run name, correcting stale default setup names when possible."""
    preset = preset or get_scenario_preset(config.scenario.preset)
    if preset is not None and config.project_name in _DEFAULT_PROJECT_NAMES:
        return preset.name
    return config.project_name or (preset.name if preset is not None else "AgentGymnasium Run")


def _inject_challenge_goal(config: LaunchConfig, design: DesignSpec) -> None:
    """Record the challenge's scoring params on the design so rewards are goal-aware.

    The reward functions only see ``compute_metrics`` output, which reads
    ``design.metadata["challenge"]``; this is where goal_x / threshold_x /
    min_spacing from the chosen preset get surfaced to scoring.
    """
    preset = get_scenario_preset(config.scenario.preset)
    if preset is not None and preset.goal:
        design.metadata["challenge"] = dict(preset.goal)


def _seed_bodies(design: DesignSpec, raw_bodies: list[dict], force_static: bool) -> None:
    """Append ``raw_bodies`` (BodySpec mappings) into ``design`` (in place).

    Skips duplicate ids and malformed entries. Tags untagged bodies as world
    parts. ``force_static`` pins terrain geometry static regardless of the entry.
    """
    existing = {b.id for b in design.bodies}
    for raw in raw_bodies:
        try:
            spec = BodySpec(**raw)
        except Exception:  # noqa: BLE001 - skip a bad entry, keep the rest usable
            continue
        if spec.id in existing:
            continue
        if force_static:
            spec.static = True
        if spec.created_by is None:
            spec.created_by = WORLD_AUTHOR
        design.bodies.append(spec)
        existing.add(spec.id)


def _seed_world(design: DesignSpec, config: LaunchConfig) -> None:
    """Seed the chosen world template's fixed terrain (cliffs, ledges, hills)."""
    template = get_world_template(config.world.template)
    if template is None:
        return
    if template.static_bodies:
        _seed_bodies(design, template.static_bodies, force_static=True)
    # Ground spans/kill_y carve a real gap into the physics floor (see
    # builder.build_space); recorded on the design like the challenge goal so the
    # engine and scoring can read them without threading a new parameter through.
    if template.ground_spans:
        design.metadata["ground_spans"] = template.ground_spans
    if template.kill_y is not None:
        design.metadata["kill_y"] = template.kill_y
    # Starting city treasury (citysim only), read by CityEngine's economy tick
    # loop the same way ground_spans/kill_y are read by the physics builder.
    if template.starting_budget is not None:
        design.metadata["starting_budget"] = template.starting_budget
    # The template is authoritative for which engine simulates it, same as
    # terrain/map_size/gravity — guards a stale/hand-built LaunchConfig (whose
    # world.engine still defaults to pymunk2d) from running a citysim template
    # through the physics engine. A no-op for every existing template, whose
    # WorldTemplate.engine also defaults to pymunk2d.
    config.world.engine = template.engine


def _seed_scaffold(design: DesignSpec, preset: ScenarioPreset | None) -> None:
    """Seed the challenge's starting objects into ``design`` (in place).

    Gives every challenge a concrete, non-empty world the agent can reason about
    and reference, and guarantees at least one dynamic body so something always
    simulates. A malformed scaffold entry is skipped rather than failing the run.
    """
    if preset is None or not preset.scaffold:
        return
    _seed_bodies(design, preset.scaffold, force_static=False)


def _world_context(config: LaunchConfig, preset: ScenarioPreset | None, design: DesignSpec) -> str:
    """A grounded world description for the system prompt.

    Without this, models build at pixel-scale coordinates off the visible world
    and never place a movable body. This states the unit (meters), the bounds,
    the objects already present, and the concrete goal.
    """
    w = config.world
    half_x = int(w.map_size[0] // 2) if w.map_size else 16
    max_y = int(w.map_size[1]) if w.map_size and len(w.map_size) > 1 else 16
    max_y = max(10, max_y)
    if w.engine.value == "citysim":
        lines = [
            f"{w.terrain.value} terrain, engine citysim (isometric city — NOT physics: "
            "structures don't fall over, they get zoned and connected to roads).",
            "Coordinates are in METERS on a GROUND PLANE: x is create_body's `position[0]`, "
            f"z is the separate `z` arg (depth). Keep both within [-{half_x}, {half_x}]. "
            "`height` (size[1]) is how tall a structure is, not a y-position.",
            "Zoning: kind house/apartment/tower = residential; shop = commercial; "
            "factory/power_plant = industrial; school/hospital = civic; "
            "park/plaza/tree/water = green; road = infrastructure. Every zoned "
            "(non-road, non-green) structure needs a road within ~3m to grow population.",
        ]
    else:
        lines = [
            f"{w.terrain.value} terrain, engine {w.engine.value}, gravity {w.gravity} m/s^2.",
            "Coordinates are in METERS, not pixels. The ground is a flat solid floor at "
            f"y=0 and up is +y. Keep parts within x in [-{half_x}, {half_x}] and y in "
            f"[0, {max_y}].",
        ]
    if design.bodies:
        objs = "; ".join(
            f"{b.id} ({'fixed' if b.static else 'movable'} {b.shape.value}) at "
            f"[{b.position[0]:.1f}, {b.position[1]:.1f}]"
            for b in design.bodies[:10]
        )
        lines.append(f"Objects already in the world (build on / connect to these): {objs}.")
    goal = preset.goal if preset else {}
    if isinstance(goal.get("goal_x"), (int, float)):
        lines.append(
            f"Goal: get the movable object to x = {goal['goal_x']} (the green marker)."
        )
    if isinstance(goal.get("threshold_x"), (int, float)):
        lines.append(
            f"Goal: drive the movable object past x = {goal['threshold_x']} (the green marker)."
        )
    if isinstance(goal.get("target_structures"), (int, float)):
        spacing = goal.get("min_spacing", 1.0)
        lines.append(
            f"Goal: place at least {int(goal['target_structures'])} separate structures, "
            f"spread across the map and spaced at least {spacing} apart."
        )
    return "\n".join(lines)

# Ceiling on simulated time per attempt. The user's
# ``simulation_duration_seconds`` is honored up to this cap; the engine also caps
# total steps, so longer designs can settle while runs stay bounded.
_MAX_SIM_DURATION_SECONDS = 60


def _simulate_design(
    design: DesignSpec,
    config: LaunchConfig,
    duration: float,
    *,
    parent_run_id: str | None = None,
    attempt_index: int | None = None,
    agent_id: str | None = None,
) -> str | None:
    """Simulate ``design``, returning its trace run id, or None if it can't run.

    Any engine/physics failure (a degenerate body or constraint that trips
    pymunk) is contained here so one bad attempt scores zero and the run keeps
    going, instead of an exception aborting the entire run.
    """
    try:
        provenance = {
            "kind": "attempt",
            "parent_run_id": parent_run_id,
            "attempt_index": attempt_index,
            "agent_id": agent_id,
        }
        return create_run_from_design(
            design,
            config.world,
            duration_seconds=duration,
            launch_config=config,
            provenance={k: v for k, v in provenance.items() if v is not None},
            parent_run_id=parent_run_id,
        )
    except Exception:  # noqa: BLE001 - a bad design must not abort the whole run
        return None


class AttemptResult(BaseModel):
    attempt_id: str
    design: DesignSpec
    trace_run_id: str | None
    score: ScoreCard
    tool_calls: list[ToolCallRecord]
    parent_attempt_id: str | None = None
    attempt_index: int = 0
    # Structured diff vs. the previous attempt (None for the first attempt).
    diff: dict | None = None
    # Durable, labelled Build Timeline steps. ``snapshots`` remains as a
    # compatibility convenience for older tests/callers that only need traces.
    build_steps: list[BuildStepRecord] = Field(default_factory=list)
    snapshots: list[dict] = Field(default_factory=list)
    model_interactions: list[ModelInteraction] = Field(default_factory=list)


def _design_snapshot(design: DesignSpec, world: WorldConfig) -> dict:
    """A single-frame, un-simulated snapshot of ``design`` as it stands right now.

    Reuses the real engine's ``simulate`` with ``duration_seconds=0`` — this
    takes exactly zero physics steps, so the one frame it produces has every
    dynamic body at its as-placed position. That gives the Build Timeline the
    SAME EpisodeTrace shape (world_static/body_meta/frames) the physics replay
    uses, through the engine-neutral interface, with no new rendering code.
    """
    engine = get_engine(world.engine.value)
    if engine is None:
        return {}
    trace = engine.simulate(design, world, duration_seconds=0.0)
    return trace.model_dump(mode="json")


def _step_label(record: ToolCallRecord) -> str:
    """Short human label for one Build Timeline step."""
    if record.tool == "repair_pass":
        return "Auto-repair"
    if record.status == ToolCallStatus.rejected:
        detail = f": {record.error}" if record.error else ""
        return f"{record.tool} - rejected{detail}"
    added = [*record.new_body_ids, *record.new_joint_ids]
    if added:
        return f"{record.tool} - added {', '.join(added)}"
    if record.mutated:
        return f"{record.tool} - changed design"
    return f"{record.tool} - no visible build change"


def _build_step(
    record: ToolCallRecord,
    trace: dict,
    *,
    attempt_index: int,
    step_index: int,
    trace_run_id: str | None = None,
) -> BuildStepRecord:
    return BuildStepRecord(
        attempt_index=attempt_index,
        step_index=step_index,
        trace_run_id=trace_run_id,
        agent_id=record.agent_id,
        tool=record.tool,
        status=record.status,
        label=_step_label(record),
        mutated=record.mutated,
        visual_change=record.visual_change,
        new_body_ids=record.new_body_ids,
        new_joint_ids=record.new_joint_ids,
        error=record.error,
        trace=trace,
    )


def _body_ids(design: DesignSpec) -> set[str]:
    return {b.id for b in design.bodies}


def _joint_ids(design: DesignSpec) -> set[str]:
    return {j.id for j in design.joints}


def _persist_attempt_artifacts(
    out_dir: pathlib.Path,
    design: DesignSpec,
    records: list[ToolCallRecord],
    score: ScoreCard,
    build_steps: list[BuildStepRecord],
    model_interactions: list[ModelInteraction],
    config: LaunchConfig,
    trace_run_id: str | None,
) -> None:
    """Persist human-inspectable artifacts for one simulated attempt."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "design.yaml").write_text(
        yaml.safe_dump(design.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    with (out_dir / "toolcalls.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(record.model_dump_json() + "\n")
    if config.outputs.scorecard_json:
        (out_dir / "score.json").write_text(
            score.model_dump_json(indent=2), encoding="utf-8"
        )
    (out_dir / "build_snapshots.json").write_text(
        json.dumps([s.model_dump(mode="json") for s in build_steps], indent=2),
        encoding="utf-8",
    )
    (out_dir / "model_interactions.json").write_text(
        json.dumps([i.model_dump(mode="json") for i in model_interactions], indent=2),
        encoding="utf-8",
    )
    if trace_run_id is not None:
        from agentgymnasium.services.export_service import export_report, export_trace

        if config.outputs.replay_json:
            replay = export_trace(trace_run_id, "json")
            if replay is not None:
                (out_dir / "replay.json").write_text(replay, encoding="utf-8")
        if config.outputs.trace_jsonl:
            trace_jsonl = export_trace(trace_run_id, "jsonl")
            if trace_jsonl is not None:
                (out_dir / "trace.jsonl").write_text(trace_jsonl, encoding="utf-8")
        if config.outputs.markdown_report:
            report = export_report(trace_run_id)
            if report is not None:
                (out_dir / "report.md").write_text(report, encoding="utf-8")


def _provider_tools(enabled_defs: list) -> list[dict]:
    """Provider-neutral function definitions from the canonical tool registry."""
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.input_schema,
        }
        for definition in enabled_defs
    ]


def _benchmark_hash(
    config: LaunchConfig,
    preset: ScenarioPreset | None,
    enabled_defs: list,
) -> str:
    """Fingerprint the task/world/tool contract used for a comparable trial."""
    world_template = get_world_template(config.world.template)
    payload = {
        "scenario": config.scenario.model_dump(mode="json"),
        "preset": preset.model_dump(mode="json") if preset is not None else None,
        "world": config.world.model_dump(mode="json"),
        "world_template": (
            world_template.model_dump(mode="json")
            if world_template is not None
            else None
        ),
        "tools": _provider_tools(enabled_defs),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _world_limits(config: LaunchConfig) -> tuple[float, float, float, float]:
    size = config.world.map_size
    width = float(size[0]) if size else 32.0
    height = float(size[1]) if len(size) > 1 else width
    half_x = width / 2.0
    if config.world.engine == PhysicsEngine.citysim:
        return (-half_x, half_x, -height / 2.0, height / 2.0)
    # Static floors, bins, and chasm geometry legitimately sit slightly below
    # y=0; the lower half-map remains bounded without rejecting those designs.
    return (-half_x, half_x, -height / 2.0, height)


def _tool_constraint_kwargs(config: LaunchConfig) -> dict:
    return {
        "max_parts": config.constraints.max_parts,
        "max_joints": config.constraints.max_joints,
        "max_motors": config.constraints.max_motors,
        "material_budget": config.constraints.material_budget,
        "world_bounds": (
            _world_limits(config)
            if config.constraints.world_bounds == WorldBounds.enforced
            else None
        ),
        "use_z_bounds": config.world.engine == PhysicsEngine.citysim,
        "strict_collision": (
            config.constraints.collision_safety == CollisionSafety.strict
        ),
    }


def _estimated_motor_energy(design: DesignSpec, duration_s: float) -> float:
    """Comparable actuator effort estimate, not a hardware power measurement."""
    return sum(
        abs(joint.motor_rate or 0.0)
        * min(abs(joint.motor_max_force), 1000.0)
        / 200.0
        * duration_s
        for joint in design.joints
        if joint.motor_rate is not None
    )


def _out_of_bounds_count(design: DesignSpec, config: LaunchConfig) -> int:
    min_x, max_x, min_secondary, max_secondary = _world_limits(config)
    use_z = config.world.engine == PhysicsEngine.citysim
    count = 0
    for body in design.bodies:
        if body.created_by in (None, WORLD_AUTHOR):
            continue
        x = body.position[0] if body.position else 0.0
        secondary = body.z if use_z else (
            body.position[1] if len(body.position) > 1 else 0.0
        )
        if not (min_x <= x <= max_x and min_secondary <= secondary <= max_secondary):
            count += 1
    return count


def _apply_score_constraints(
    score: ScoreCard,
    design: DesignSpec,
    config: LaunchConfig,
    *,
    duration_s: float,
) -> ScoreCard:
    """Attach resource telemetry and apply hard/soft launch constraints."""
    constrained = score.model_copy(deep=True)
    used_material = material_units(design)
    energy = _estimated_motor_energy(design, duration_s)
    outside = _out_of_bounds_count(design, config)
    constrained.metrics["material_units"] = used_material
    constrained.metrics["motor_energy_estimate"] = energy
    constrained.metrics["out_of_bounds_parts"] = float(outside)

    hard_failures: list[dict] = []
    if used_material > config.constraints.material_budget:
        hard_failures.append(
            {
                "type": "material_budget_exceeded",
                "used": round(used_material, 3),
                "budget": config.constraints.material_budget,
            }
        )
    if energy > config.constraints.energy_budget:
        hard_failures.append(
            {
                "type": "energy_budget_exceeded",
                "used": round(energy, 3),
                "budget": config.constraints.energy_budget,
            }
        )
        constrained.score_total *= max(0.0, config.constraints.energy_budget / energy)
    if outside and config.constraints.world_bounds == WorldBounds.enforced:
        hard_failures.append(
            {"type": "world_bounds_exceeded", "parts": outside, "mode": "enforced"}
        )
    elif outside and config.constraints.world_bounds == WorldBounds.soft:
        constrained.failure_events.append(
            {"type": "world_bounds_soft_penalty", "parts": outside}
        )
        constrained.score_total = max(0.0, constrained.score_total - 5.0 * outside)

    if hard_failures:
        constrained.failure_events.extend(hard_failures)
        constrained.success = False
        constrained.summary = (
            f"{constrained.summary} Constraint failure: "
            + ", ".join(event["type"] for event in hard_failures)
        ).strip()
        constrained.improvement_hint = (
            "Reduce material or actuator effort and keep every agent-built part "
            "inside the configured world bounds."
        )
    return constrained


def _agent_system_prompt(agent: AgentConfig, generated: str) -> str:
    """Apply the user override or make the configured agent profile effective."""
    if agent.system_prompt_override and agent.system_prompt_override.strip():
        return agent.system_prompt_override.strip()
    return (
        f"{generated}\n\nAgent profile: role={agent.role.value}; "
        f"behavior={agent.behavior_mode.value}; "
        f"mutation_strategy={agent.mutation_strategy.value}. "
        "Follow this profile while remaining within the tool and safety rules."
    )


_OBSERVATION_TOOLS = frozenset(
    {
        "get_state",
        "run_simulation",
        "inspect_score",
        "inspect_failure_events",
        "compare_attempts",
    }
)


def _observe_design(design: DesignSpec, config: LaunchConfig) -> dict:
    """Run a bounded preview and return provider-neutral state + score feedback."""
    trace = None
    duration = min(
        float(config.constraints.simulation_duration_seconds),
        10.0,
    )
    if design.bodies:
        engine = get_engine(config.world.engine.value)
        if engine is not None:
            try:
                trace = engine.simulate(design, config.world, duration_seconds=duration)
            except Exception:  # noqa: BLE001 - feedback failure must stay contained
                trace = None
    score = _apply_score_constraints(
        score_attempt(trace, design, config.scenario.reward),
        design,
        config,
        duration_s=duration,
    )
    final_bodies: dict[str, dict] = {}
    if trace is not None and trace.frames:
        final_bodies = {
            body_id: body.model_dump(mode="json")
            for body_id, body in trace.frames[-1].bodies.items()
        }
    return {
        "score": score.model_dump(mode="json"),
        "state": {
            "body_count": len(design.bodies),
            "joint_count": len(design.joints),
            "final_bodies": final_bodies,
        },
    }


def _observation_prompt(objective: str, turn_index: int, observation: dict) -> str:
    compact = json.dumps(observation, separators=(",", ":"), sort_keys=True)
    return (
        f"Observation after model turn #{turn_index}: {compact}\n"
        f"Continue working toward: {objective}. Revise the design using enabled "
        "tools. You may call run_simulation/inspect_score again. If the design "
        'is satisfactory, return {"tool_calls": []}.'
    )


def _attempt_diff(prev: AttemptResult | None, design: DesignSpec, score: ScoreCard) -> dict | None:
    """Structured diff of this attempt vs. the previous one (parts, score, failures).

    Used both to feed the agent's prompt ("what you changed and how it scored")
    and to surface "what changed" in Studio. Returns None for the first attempt.
    """
    if prev is None:
        return None
    prev_ids = {b.id for b in prev.design.bodies}
    cur_ids = {b.id for b in design.bodies}
    prev_pos = {b.id: tuple(b.position) for b in prev.design.bodies}
    moved = [
        bid
        for b in design.bodies
        if (bid := b.id) in prev_pos and tuple(b.position) != prev_pos[bid]
    ]
    return {
        "prev_attempt_index": prev.attempt_index,
        "parts_delta": len(design.bodies) - len(prev.design.bodies),
        "joints_delta": len(design.joints) - len(prev.design.joints),
        "added_parts": sorted(cur_ids - prev_ids),
        "removed_parts": sorted(prev_ids - cur_ids),
        "moved_parts": sorted(moved),
        "prev_score": prev.score.score_total,
        "score_delta": score.score_total - prev.score.score_total,
        "failure_events": [str(e.get("type", e)) for e in score.failure_events],
    }


def _build_memory(prev: AttemptResult | None) -> str:
    """Previous-attempt summary for the prompt: score, hint, and what changed."""
    if prev is None:
        return ""
    line = (
        f"- Attempt #{prev.attempt_index}: score "
        f"{prev.score.score_total:.1f}. {prev.score.improvement_hint}".strip()
    )
    diff = prev.diff
    if diff:
        parts = []
        if diff["added_parts"]:
            parts.append(f"added {len(diff['added_parts'])} part(s)")
        if diff["removed_parts"]:
            parts.append(f"removed {len(diff['removed_parts'])} part(s)")
        if diff["moved_parts"]:
            parts.append(f"moved {len(diff['moved_parts'])} part(s)")
        delta = diff["score_delta"]
        trend = f"score {'+' if delta >= 0 else ''}{delta:.1f} vs the attempt before"
        change = "; ".join(parts) if parts else "no structural change"
        line += f"\n  (last change: {change}; {trend})"
    return line


def _repair_rejected(
    design: DesignSpec,
    enabled_names: list[str],
    records: list[ToolCallRecord],
    config: LaunchConfig | None = None,
) -> ToolCallRecord | None:
    """One conservative repair pass over rejected records (in place).

    Handles the most common ``apply_tool_call`` rejection: a duplicate id on a
    body-creating call (``... already exists``). Retries with a ``_r`` suffix and,
    on success, returns one synthetic ``repair_pass`` record. The original
    rejected records are preserved for explainability.
    """
    before_bodies = _body_ids(design)
    before_joints = _joint_ids(design)
    repairs: list[dict[str, str]] = []
    for record in records:
        if record.status != ToolCallStatus.rejected or not record.error:
            continue
        if "already exists" not in record.error:
            continue
        new_id = f"{record.args.get('id', '')}_r"
        if not new_id or new_id == "_r":
            continue
        repaired_args = {**record.args, "id": new_id}
        result = apply_tool_call(
            design,
            agent_id=record.agent_id,
            tool=record.tool,
            args=repaired_args,
            enabled_tools=enabled_names,
            **(_tool_constraint_kwargs(config) if config is not None else {}),
        )
        if result.mutated:
            repairs.append(
                {
                    "tool": record.tool,
                    "old_id": str(record.args.get("id", "")),
                    "new_id": new_id,
                }
            )
    if not repairs:
        return None
    new_body_ids = sorted(_body_ids(design) - before_bodies)
    new_joint_ids = sorted(_joint_ids(design) - before_joints)
    return ToolCallRecord(
        ts=time.time(),
        agent_id="system",
        tool="repair_pass",
        args={"repairs": repairs},
        status=ToolCallStatus.repaired,
        source="system",
        mutated=True,
        visual_change=bool(new_body_ids),
        new_body_ids=new_body_ids,
        new_joint_ids=new_joint_ids,
    )


async def run_single_attempt(
    config: LaunchConfig,
    *,
    attempt_index: int = 0,
    previous: AttemptResult | None = None,
    parent_run_id: str | None = None,
) -> AttemptResult:
    """Run one single-agent build attempt end-to-end with the mock/real provider.

    Defaults to ``participants[0]`` so the single-agent path is unchanged.
    """
    participants = config.agents.participants
    if not participants:
        raise ValueError("config.agents.participants is empty")
    return await run_agent_attempt(
        config,
        participants[0],
        attempt_index=attempt_index,
        previous=previous,
        parent_run_id=parent_run_id,
    )


async def run_agent_attempt(
    config: LaunchConfig,
    agent: AgentConfig,
    *,
    attempt_index: int = 0,
    previous: AttemptResult | None = None,
    parent_run_id: str | None = None,
    force_memory: bool = False,
) -> AttemptResult:
    """Run one build attempt end-to-end for a SPECIFIC participant.

    Builds that agent's own DesignSpec, applies its own tool calls (tagged with
    ``agent.id``), simulates, scores, and persists under ``runs/{trace_run_id}/``.
    """
    attempt_id = f"attempt_{uuid.uuid4().hex[:8]}"

    provider = get_provider(agent.provider.value)
    if provider is None:
        raise ValueError(f"unknown provider: {agent.provider.value}")

    enabled_names = config.tools.enabled
    enabled_defs = [d for n in enabled_names if (d := get_tool(n)) is not None]

    objective = config.scenario.objective or config.scenario.preset

    # Build the starting world first so the prompt can describe it and the agent
    # has a concrete, non-empty design to extend.
    preset = get_scenario_preset(config.scenario.preset)
    display_name = _project_name(config, preset)
    design = DesignSpec(name=display_name)
    _seed_world(design, config)
    _seed_scaffold(design, preset)

    world_summary = _world_context(config, preset, design)
    system_prompt = _agent_system_prompt(
        agent,
        build_system_prompt(
            objective,
            world_summary,
            enabled_defs,
            movable_body_required=preset is None or preset.reward not in _STATIC_OK_REWARDS,
        ),
    )
    memory = (
        _build_memory(previous)
        if force_memory
        or agent.memory_mode in (MemoryMode.episodic, MemoryMode.best_attempt_summary)
        else ""
    )
    user_prompt = build_user_prompt(objective, attempt_index, memory)

    records: list[ToolCallRecord] = []
    build_steps: list[BuildStepRecord] = []
    model_interactions: list[ModelInteraction] = []
    _inject_challenge_goal(config, design)

    # Offline mock demonstrations remain one deterministic response. Real
    # providers get a bounded observe→revise loop inside each attempt.
    configured_turns = max(1, min(config.constraints.agent_turns_per_attempt, 8))
    turn_limit = 1 if agent.provider.value == "mock" else configured_turns
    turn_user = user_prompt
    for turn_index in range(turn_limit):
        model_result = await provider.generate(
            ModelRequest(
                provider=agent.provider.value,
                model=agent.model,
                system=system_prompt,
                user=turn_user,
                endpoint_url=agent.endpoint_url or config.llm_connection.endpoint_url,
                api_key=agent.api_key or config.llm_connection.api_key,
                temperature=agent.temperature,
                seed=config.world.seed,
                tools=_provider_tools(enabled_defs),
            )
        )
        model_interactions.append(
            ModelInteraction(
                turn_index=turn_index,
                agent_id=agent.id,
                system=system_prompt,
                user=turn_user,
                seed=config.world.seed,
                result=model_result,
            )
        )
        if not model_result.tool_calls:
            break

        observation_records: list[ToolCallRecord] = []
        for call in model_result.tool_calls:
            tool = call.get("tool", "")
            args = call.get("args", {}) or {}
            result = apply_tool_call(
                design,
                agent_id=agent.id,
                tool=tool,
                args=args,
                enabled_tools=enabled_names,
                **_tool_constraint_kwargs(config),
            )
            records.append(result.record)
            if tool in _OBSERVATION_TOOLS and result.record.status != ToolCallStatus.rejected:
                observation_records.append(result.record)
            build_steps.append(
                _build_step(
                    result.record,
                    _design_snapshot(design, config.world),
                    attempt_index=attempt_index,
                    step_index=len(build_steps),
                )
            )

        # Only begin another model turn when the model explicitly requested an
        # observation. Mutation-only batches proceed directly to final scoring.
        if not observation_records:
            break
        observation = _observe_design(design, config)
        for record in observation_records:
            if record.tool == "get_state":
                record.output = observation["state"]
            elif record.tool == "inspect_score":
                record.output = observation["score"]
            elif record.tool == "inspect_failure_events":
                record.output = {
                    "failure_events": observation["score"]["failure_events"]
                }
            else:
                record.output = observation
        if turn_index + 1 >= turn_limit:
            break
        turn_user = _observation_prompt(objective, turn_index, observation)

    # Optional conservative repair pass over rejected calls (e.g. duplicate ids).
    if config.constraints.repair_loop_enabled and any(
        r.status == ToolCallStatus.rejected for r in records
    ):
        repair_record = _repair_rejected(design, enabled_names, records, config)
        if repair_record is not None:
            records.append(repair_record)
            build_steps.append(
                _build_step(
                    repair_record,
                    _design_snapshot(design, config.world),
                    attempt_index=attempt_index,
                    step_index=len(build_steps),
                )
            )

    # Simulate whenever the design has any body. All-static designs (e.g. a city
    # of fixed structures) still produce a trace + score; only a truly empty
    # design is skipped.
    trace_run_id: str | None = None
    if design.bodies:
        duration = min(
            config.constraints.simulation_duration_seconds, _MAX_SIM_DURATION_SECONDS
        )
        trace_run_id = _simulate_design(
            design,
            config,
            duration,
            parent_run_id=parent_run_id,
            attempt_index=attempt_index,
            agent_id=agent.id,
        )

    trace = get_trace(trace_run_id) if trace_run_id is not None else None
    score = _apply_score_constraints(
        score_attempt(trace, design, config.scenario.reward),
        design,
        config,
        duration_s=float(
            min(config.constraints.simulation_duration_seconds, _MAX_SIM_DURATION_SECONDS)
        ),
    )
    if trace_run_id is not None:
        store_score(trace_run_id, score)
        record_run_meta(
            trace_run_id,
            project_name=display_name,
            challenge=config.scenario.preset,
            mode=config.agents.mode.value,
            provider=agent.provider.value,
            model=agent.model,
            seed=config.world.seed,
            input_tokens=sum(
                item.result.usage.input_tokens for item in model_interactions
            ),
            output_tokens=sum(
                item.result.usage.output_tokens for item in model_interactions
            ),
            latency_ms=sum(item.result.latency_ms for item in model_interactions),
            protocol=(
                "native_tools"
                if any(item.result.native_tool_calls for item in model_interactions)
                else "prompt_json"
            ),
            benchmark_hash=_benchmark_hash(config, preset, enabled_defs),
        )
        for step in build_steps:
            step.trace_run_id = trace_run_id

    # Persist artifacts under runs/{trace_run_id or attempt_id}/.
    out_dir = _RUNS_DIR / (trace_run_id or attempt_id)
    _persist_attempt_artifacts(
        out_dir,
        design,
        records,
        score,
        build_steps,
        model_interactions,
        config,
        trace_run_id,
    )

    return AttemptResult(
        attempt_id=attempt_id,
        design=design,
        trace_run_id=trace_run_id,
        score=score,
        tool_calls=records,
        parent_attempt_id=previous.attempt_id if previous is not None else None,
        attempt_index=attempt_index,
        diff=_attempt_diff(previous, design, score),
        build_steps=build_steps,
        snapshots=[s.trace for s in build_steps],
        model_interactions=model_interactions,
    )


# Tools whose ``id`` arg names a NEW body/joint that becomes referenceable.
_OWN_ID_TOOLS = frozenset(
    {"create_body", "add_ball", "add_beam", "add_ramp", "add_bin", "add_joint"}
)
# Arg keys that REFERENCE an existing body/joint id.
_REF_ID_ARGS = ("body_a", "body_b", "body_id", "joint_id")


def _remap_ids(agent_id: str, tool: str, args: dict, created: dict[str, str]) -> dict:
    """Namespace an agent's OWN newly-created ids; leave cross-agent refs intact.

    The mock provider (and any naive agent) returns identical ids for every
    agent (e.g. ``create_body id="b1"``). In cooperative mode all agents write
    into ONE shared design, so without namespacing the second agent's parts
    would collide and be rejected. We prefix each agent's *own* created ids with
    ``{agent_id}_`` and record them in ``created`` (original → namespaced).

    References are only remapped when they point at an id THIS agent just
    created. A reference to anything else is left untouched so a genuine
    cross-agent joint (referencing a prior agent's already-live, namespaced id)
    resolves instead of being rewritten into a non-existent id.
    """
    new_args = dict(args)
    if tool in _OWN_ID_TOOLS:
        orig = new_args.get("id")
        if isinstance(orig, str):
            namespaced = f"{agent_id}_{orig}"
            new_args["id"] = namespaced
            created[orig] = namespaced
    for key in _REF_ID_ARGS:
        value = new_args.get(key)
        if isinstance(value, str) and value in created:
            new_args[key] = created[value]
    return new_args


async def run_cooperative_attempt(
    config: LaunchConfig,
    *,
    attempt_index: int = 0,
    parent_run_id: str | None = None,
) -> AttemptResult:
    """Run one COOPERATIVE attempt: all participants build ONE shared design.

    Turn order: participants in declared order. Agent A builds the base
    structure; each subsequent agent is shown a short summary of the design so
    far and asked to extend/stabilize it. Every agent's parts are tagged
    ``created_by=agent.id`` via :func:`apply_tool_call`. The shared design is
    simulated ONCE and scored ONCE into a single shared ScoreCard.

    Per-agent ids are namespaced (``{agent.id}_{id}``) so naive/identical tool
    calls from multiple agents don't collide in the shared design; references
    within an agent's own calls remap consistently.
    """
    participants = config.agents.participants
    if not participants:
        raise ValueError("config.agents.participants is empty")

    attempt_id = f"attempt_{uuid.uuid4().hex[:8]}"

    enabled_names = config.tools.enabled
    enabled_defs = [d for n in enabled_names if (d := get_tool(n)) is not None]

    objective = config.scenario.objective or config.scenario.preset

    preset = get_scenario_preset(config.scenario.preset)
    display_name = _project_name(config, preset)
    design = DesignSpec(name=display_name)
    _seed_world(design, config)
    _seed_scaffold(design, preset)

    world_summary = _world_context(config, preset, design)
    records: list[ToolCallRecord] = []
    build_steps: list[BuildStepRecord] = []
    model_interactions: list[ModelInteraction] = []

    for turn_index, agent in enumerate(participants):
        provider = get_provider(agent.provider.value)
        if provider is None:
            raise ValueError(f"unknown provider: {agent.provider.value}")
        system_prompt = _agent_system_prompt(
            agent,
            build_system_prompt(
                objective,
                world_summary,
                enabled_defs,
                movable_body_required=(
                    preset is None or preset.reward not in _STATIC_OK_REWARDS
                ),
            ),
        )

        if turn_index == 0:
            user_prompt = build_user_prompt(objective, attempt_index)
        else:
            existing_ids = [b.id for b in design.bodies]
            user_prompt = build_cooperative_user_prompt(
                objective,
                attempt_index,
                body_count=len(design.bodies),
                joint_count=len(design.joints),
                existing_body_ids=existing_ids,
            )

        model_result = await provider.generate(
            ModelRequest(
                provider=agent.provider.value,
                model=agent.model,
                system=system_prompt,
                user=user_prompt,
                endpoint_url=agent.endpoint_url or config.llm_connection.endpoint_url,
                api_key=agent.api_key or config.llm_connection.api_key,
                temperature=agent.temperature,
                seed=config.world.seed,
                tools=_provider_tools(enabled_defs),
            )
        )
        model_interactions.append(
            ModelInteraction(
                turn_index=turn_index,
                agent_id=agent.id,
                system=system_prompt,
                user=user_prompt,
                seed=config.world.seed,
                result=model_result,
            )
        )

        # Per-turn map of this agent's original id → namespaced id, so its own
        # references remap while cross-agent references stay intact.
        created: dict[str, str] = {}
        for call in model_result.tool_calls:
            tool = call.get("tool", "")
            args = _remap_ids(agent.id, tool, call.get("args", {}) or {}, created)
            result = apply_tool_call(
                design,
                agent_id=agent.id,
                tool=tool,
                args=args,
                enabled_tools=enabled_names,
                **_tool_constraint_kwargs(config),
            )
            records.append(result.record)
            build_steps.append(
                _build_step(
                    result.record,
                    _design_snapshot(design, config.world),
                    attempt_index=attempt_index,
                    step_index=len(build_steps),
                )
            )

    if config.constraints.repair_loop_enabled and any(
        r.status == ToolCallStatus.rejected for r in records
    ):
        repair_record = _repair_rejected(design, enabled_names, records, config)
        if repair_record is not None:
            records.append(repair_record)
            build_steps.append(
                _build_step(
                    repair_record,
                    _design_snapshot(design, config.world),
                    attempt_index=attempt_index,
                    step_index=len(build_steps),
                )
            )

    _inject_challenge_goal(config, design)

    # Simulate the SHARED design once when it has any body (all-static included).
    trace_run_id: str | None = None
    if design.bodies:
        duration = min(
            config.constraints.simulation_duration_seconds, _MAX_SIM_DURATION_SECONDS
        )
        trace_run_id = _simulate_design(
            design,
            config,
            duration,
            parent_run_id=parent_run_id,
            attempt_index=attempt_index,
            agent_id="shared",
        )

    trace = get_trace(trace_run_id) if trace_run_id is not None else None
    score = _apply_score_constraints(
        score_attempt(trace, design, config.scenario.reward),
        design,
        config,
        duration_s=float(
            min(config.constraints.simulation_duration_seconds, _MAX_SIM_DURATION_SECONDS)
        ),
    )
    if trace_run_id is not None:
        store_score(trace_run_id, score)
        record_run_meta(
            trace_run_id,
            project_name=display_name,
            challenge=config.scenario.preset,
            mode=config.agents.mode.value,
            provider=",".join(sorted({a.provider.value for a in participants})),
            model=",".join(sorted({a.model for a in participants})),
            seed=config.world.seed,
            input_tokens=sum(
                item.result.usage.input_tokens for item in model_interactions
            ),
            output_tokens=sum(
                item.result.usage.output_tokens for item in model_interactions
            ),
            latency_ms=sum(item.result.latency_ms for item in model_interactions),
            protocol=(
                "native_tools"
                if any(item.result.native_tool_calls for item in model_interactions)
                else "prompt_json"
            ),
            benchmark_hash=_benchmark_hash(config, preset, enabled_defs),
        )
        for step in build_steps:
            step.trace_run_id = trace_run_id

    out_dir = _RUNS_DIR / (trace_run_id or attempt_id)
    _persist_attempt_artifacts(
        out_dir,
        design,
        records,
        score,
        build_steps,
        model_interactions,
        config,
        trace_run_id,
    )

    return AttemptResult(
        attempt_id=attempt_id,
        design=design,
        trace_run_id=trace_run_id,
        score=score,
        tool_calls=records,
        attempt_index=attempt_index,
        build_steps=build_steps,
        snapshots=[s.trace for s in build_steps],
        model_interactions=model_interactions,
    )
