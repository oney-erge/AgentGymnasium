from __future__ import annotations

from agentgymnasium.core.schemas.design import BodyShape, DesignSpec
from agentgymnasium.core.schemas.setup import WorldConfig
from agentgymnasium.core.schemas.trace import (
    BodyMeta,
    EpisodeTrace,
    Frame,
    FrameBody,
    JointMeta,
    StaticProp,
    VisualSpec,
    stable_visual_seed,
)
from agentgymnasium.engines.base import EngineAdapter
from agentgymnasium.engines.pymunk2d.builder import GROUND_ID, build_space, valid_ground_spans

# Hard cap on physics steps to keep simulations (and tests) fast.
_MAX_STEPS = 6000
# Target output frame rate; we sub-sample physics steps down to ~this rate.
_TARGET_FPS = 30.0


class Pymunk2DEngine(EngineAdapter):
    name = "pymunk2d"

    def simulate(
        self,
        design: DesignSpec,
        world: WorldConfig,
        duration_seconds: float,
        dt: float = 1 / 60,
    ) -> EpisodeTrace:
        space, bodies = build_space(design, world)

        # Only dynamic (non-static) bodies are recorded per frame.
        dynamic_ids = [spec.id for spec in design.bodies if not spec.static]

        total_steps = int(duration_seconds / dt)
        total_steps = max(0, min(total_steps, _MAX_STEPS))

        # Record roughly every Nth step to hit ~_TARGET_FPS regardless of dt.
        sim_fps = 1.0 / dt if dt > 0 else _TARGET_FPS
        record_every = max(1, round(sim_fps / _TARGET_FPS))

        trace = EpisodeTrace(
            run_id="",  # filled in by caller / run service
            engine=self.name,
            terrain=getattr(world.terrain, "value", str(world.terrain)),
            visual_style=getattr(world.visual_style, "value", str(world.visual_style)),
            visual_seed=world.seed or 0,
            dt=dt,
            kill_y=design.metadata.get("kill_y"),
            world_static=self._build_static(design, world),
            body_meta={
                spec.id: BodyMeta(
                    shape=spec.shape.value
                    if isinstance(spec.shape, BodyShape)
                    else str(spec.shape),
                    size=list(spec.size),
                    color=spec.color,
                    kind=spec.kind,
                    created_by=spec.created_by,
                    visual=VisualSpec(
                        material=spec.material,
                        seed=stable_visual_seed(world.seed, spec.id),
                        variant=f"v{stable_visual_seed(world.seed, spec.id) % 4}",
                        label=spec.kind,
                    ),
                )
                for spec in design.bodies
                if not spec.static
            },
            joints=[
                JointMeta(
                    id=joint.id,
                    body_a=joint.body_a,
                    body_b=joint.body_b,
                    type=getattr(joint.type, "value", str(joint.type)),
                    anchor_a=list(joint.anchor_a),
                    anchor_b=list(joint.anchor_b),
                    motor_rate=joint.motor_rate,
                    motor_max_force=joint.motor_max_force,
                    created_by=joint.created_by,
                )
                for joint in design.joints
            ],
        )

        pending_events: list[dict] = []
        seen_contacts: set[tuple[str, str]] = set()
        stressed_pairs: set[tuple[str, str]] = set()
        body_id_by_object = {id(body): body_id for body_id, body in bodies.items()}
        body_id_by_object[id(space.static_body)] = GROUND_ID

        def collision_pair(arbiter) -> tuple[str, str]:
            names = [
                body_id_by_object.get(id(shape.body), GROUND_ID)
                for shape in arbiter.shapes
            ]
            return tuple(sorted((names[0], names[1])))

        def on_contact_started(arbiter, _space, _data) -> bool:
            pair = collision_pair(arbiter)
            if pair not in seen_contacts and total_steps > 0:
                seen_contacts.add(pair)
                pending_events.append(
                    {
                        "type": "contact_started",
                        "body_a": pair[0],
                        "body_b": pair[1],
                    }
                )
            return True

        def on_contact_solved(arbiter, _space, _data) -> None:
            pair = collision_pair(arbiter)
            impulse = float(arbiter.total_impulse.length)
            if impulse < 40 or pair in stressed_pairs or total_steps <= 0:
                return
            stressed_pairs.add(pair)
            body_id = next((name for name in pair if name != GROUND_ID), pair[0])
            pending_events.append(
                {
                    "type": "structure_stressed",
                    "body_id": body_id,
                    "level": min(1.0, impulse / 180.0),
                    "impulse": impulse,
                }
            )

        if hasattr(space, "on_collision"):
            space.on_collision(
                None,
                None,
                begin=on_contact_started,
                post_solve=on_contact_solved,
            )
        else:  # pragma: no cover - compatibility with the pymunk 6.9 minimum
            handler = space.add_default_collision_handler()
            handler.begin = on_contact_started
            handler.post_solve = on_contact_solved

        goal_specs = [spec for spec in design.bodies if spec.static and spec.kind == "goal"]
        bins = {
            str(item.get("id")): item
            for item in design.metadata.get("bins", [])
            if isinstance(item, dict) and item.get("id")
        }
        seen_goals: set[tuple[str, str]] = set()
        seen_sorted: set[tuple[str, str]] = set()
        seen_fallen: set[str] = set()

        def state_events() -> list[dict]:
            events: list[dict] = []
            for spec in design.bodies:
                if spec.static:
                    continue
                body = bodies[spec.id]
                x = float(body.position.x)
                y = float(body.position.y)
                for goal in goal_specs:
                    key = (spec.id, goal.id)
                    if key in seen_goals:
                        continue
                    width = goal.size[0] if goal.size else 1.0
                    height = goal.size[1] if len(goal.size) > 1 else width
                    if abs(x - goal.position[0]) <= width / 2 and abs(y - goal.position[1]) <= height / 2:
                        seen_goals.add(key)
                        events.append(
                            {
                                "type": "goal_reached",
                                "body_id": spec.id,
                                "goal_id": goal.id,
                            }
                        )
                if spec.kind == "ball":
                    for bin_id, bin_meta in bins.items():
                        key = (spec.id, bin_id)
                        if key in seen_sorted:
                            continue
                        bx = float(bin_meta.get("x", 0.0))
                        by = float(bin_meta.get("y", 0.0))
                        width = float(bin_meta.get("width", 1.0))
                        height = float(bin_meta.get("height", 1.0))
                        if abs(x - bx) <= width / 2 and abs(y - by) <= height / 2:
                            seen_sorted.add(key)
                            accepts = str(bin_meta.get("accepts", ""))
                            events.append(
                                {
                                    "type": "object_sorted",
                                    "body_id": spec.id,
                                    "bin_id": bin_id,
                                    "accepted": not accepts or accepts.lower() in (spec.color or "").lower(),
                                }
                            )
                kill_y = trace.kill_y
                if kill_y is not None and y < float(kill_y) and spec.id not in seen_fallen:
                    seen_fallen.add(spec.id)
                    events.append(
                        {
                            "type": "body_destroyed",
                            "body_id": spec.id,
                            "reason": "fell_below_world",
                        }
                    )
            return events

        initial_events: list[dict] = []
        if total_steps > 0:
            initial_events.extend(
                {
                    "type": "body_created",
                    "body_id": spec.id,
                    "kind": spec.kind or spec.shape.value,
                    "created_by": spec.created_by,
                }
                for spec in design.bodies
                if not spec.static
            )
            for joint in design.joints:
                initial_events.append(
                    {
                        "type": "joint_attached",
                        "joint_id": joint.id,
                        "body_a": joint.body_a,
                        "body_b": joint.body_b,
                    }
                )
                if joint.motor_rate is not None:
                    initial_events.append(
                        {
                            "type": "motor_activated",
                            "joint_id": joint.id,
                            "rate": joint.motor_rate,
                        }
                    )

        def record(step: int, events: list[dict] | None = None) -> None:
            frame_bodies: dict[str, FrameBody] = {}
            for bid in dynamic_ids:
                body = bodies[bid]
                frame_bodies[bid] = FrameBody(
                    x=float(body.position.x),
                    y=float(body.position.y),
                    angle=float(body.angle),
                )
            trace.frames.append(Frame(t=step * dt, bodies=frame_bodies, events=events or []))

        # Initial frame at t=0.
        record(0, initial_events)
        last_recorded = 0
        for step in range(1, total_steps + 1):
            space.step(dt)
            if step % record_every == 0:
                events = pending_events[:16] + state_events()
                pending_events.clear()
                record(step, events)
                last_recorded = step
        # Always record the final state so distance/duration/falls aren't read
        # from a frame up to (record_every - 1) steps stale.
        if total_steps > 0 and last_recorded != total_steps:
            events = pending_events[:16] + state_events()
            pending_events.clear()
            record(total_steps, events)

        return trace

    @staticmethod
    def _build_static(design: DesignSpec, world: WorldConfig) -> list[StaticProp]:
        props: list[StaticProp] = []
        map_width = float(world.map_size[0]) if world.map_size else 32.0
        spans = valid_ground_spans(design, map_width)
        for i, (x0, x1) in enumerate(spans):
            props.append(
                StaticProp(
                    id=f"{GROUND_ID}_{i}" if len(spans) > 1 else GROUND_ID,
                    kind="ground",
                    position=[(x0 + x1) / 2.0, 0.0],
                    size=[x1 - x0, 0.2],
                )
            )
        for spec in design.bodies:
            if spec.static:
                shape_name = (
                    spec.shape.value
                    if isinstance(spec.shape, BodyShape)
                    else str(spec.shape)
                )
                props.append(
                    StaticProp(
                        id=spec.id,
                        # Prefer the semantic label so static structures render as
                        # themselves (wall/bin/house) rather than a raw shape.
                        kind=spec.kind or shape_name,
                        position=list(spec.position),
                        size=list(spec.size),
                        angle=spec.angle,
                        color=spec.color,
                        shape=shape_name,
                        created_by=spec.created_by,
                        visual=VisualSpec(
                            material=spec.material,
                            seed=stable_visual_seed(world.seed, spec.id),
                            variant=f"v{stable_visual_seed(world.seed, spec.id) % 4}",
                            label=spec.kind,
                        ),
                    )
                )
        return props
