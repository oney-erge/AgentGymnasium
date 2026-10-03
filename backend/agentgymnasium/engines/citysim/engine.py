"""CityEngine: a layout + economy simulation, not a physics engine.

A city's structures don't fall over — they get placed, zoned, connected to
roads, and grown over time. So this engine never steps rigid-body physics:
every design body renders as a static `StaticProp` (extruded box in the iso
renderer), and "simulation" is a discrete economy tick loop (population,
budget, income, pollution/happiness) recorded as `city_tick` events on the
trace frames — the same engine-neutral `EpisodeTrace` contract every other
engine produces, so scoring and the renderer need no engine-specific code.
"""

from __future__ import annotations

from agentgymnasium.core.schemas.design import BodyShape, DesignSpec
from agentgymnasium.core.schemas.setup import WorldConfig
from agentgymnasium.core.schemas.trace import (
    EpisodeTrace,
    Frame,
    StaticProp,
    VisualSpec,
    stable_visual_seed,
)
from agentgymnasium.engines.base import EngineAdapter
from agentgymnasium.engines.citysim import layout

# One tick per second of configured "duration" — a full run of e.g. 30s of
# simulation time plays out as 30 economy ticks (population/budget updates).
_TICK_SECONDS = 1.0
_MAX_TICKS = 120
_DEFAULT_STARTING_BUDGET = 1000.0

# Economy tuning constants (documented magic numbers, matching the style of
# scoring_service's reward functions — tunable, not derived from real data).
_GROWTH_RATE = 0.15  # fraction of the gap to target population closed per tick
_INCOME_PER_COMMERCIAL = 8.0
_INCOME_PER_INDUSTRIAL = 12.0
_UPKEEP_PER_RESIDENTIAL = 1.0
_UPKEEP_PER_ROAD = 0.5
_POLLUTION_PER_INDUSTRIAL = 3.0
_POLLUTION_OFFSET_PER_GREEN = 1.0
_POLLUTION_HAPPINESS_SCALE = 50.0


class CityEngine(EngineAdapter):
    name = "citysim"

    def simulate(
        self,
        design: DesignSpec,
        world: WorldConfig,
        duration_seconds: float,
        dt: float = 1 / 60,
    ) -> EpisodeTrace:
        buildings = list(design.bodies)
        roads = [b for b in buildings if layout.zone_of(b.kind) == "road"]
        residential = [b for b in buildings if layout.zone_of(b.kind) == "residential"]
        commercial = [b for b in buildings if layout.zone_of(b.kind) == "commercial"]
        industrial = [b for b in buildings if layout.zone_of(b.kind) == "industrial"]
        green = [b for b in buildings if layout.zone_of(b.kind) == "green"]
        zoned = residential + commercial + industrial

        connected = {b.id: layout.is_connected(b, roads) for b in zoned}
        connectivity_fraction = (
            sum(connected.values()) / len(zoned) if zoned else 0.0
        )
        total_capacity = sum(
            layout.capacity_of(b) for b in residential if connected.get(b.id)
        )

        raw_budget = design.metadata.get("starting_budget", _DEFAULT_STARTING_BUDGET)
        try:
            budget = float(raw_budget)
        except (TypeError, ValueError):
            budget = _DEFAULT_STARTING_BUDGET

        total_ticks = 1
        if duration_seconds > 0:
            total_ticks = max(1, min(round(duration_seconds / _TICK_SECONDS), _MAX_TICKS))

        trace = EpisodeTrace(
            run_id="",
            engine=self.name,
            camera="iso",
            terrain=getattr(world.terrain, "value", str(world.terrain)),
            visual_style=getattr(world.visual_style, "value", str(world.visual_style)),
            visual_seed=world.seed or 0,
            dt=_TICK_SECONDS,
            kill_y=None,
            world_static=self._build_static(design, world),
            body_meta={},
        )

        population = 0.0
        for tick in range(total_ticks):
            income = (
                len(commercial) * _INCOME_PER_COMMERCIAL * connectivity_fraction
                + len(industrial) * _INCOME_PER_INDUSTRIAL * connectivity_fraction
            )
            upkeep = (
                len(residential) * _UPKEEP_PER_RESIDENTIAL
                + len(roads) * _UPKEEP_PER_ROAD
            )
            budget += income - upkeep
            pollution = max(
                0.0,
                len(industrial) * _POLLUTION_PER_INDUSTRIAL
                - len(green) * _POLLUTION_OFFSET_PER_GREEN,
            )
            happiness = layout.clamp01(1.0 - pollution / _POLLUTION_HAPPINESS_SCALE)
            target_population = total_capacity * connectivity_fraction * (0.5 + 0.5 * happiness)
            population += (target_population - population) * _GROWTH_RATE
            trace.frames.append(
                Frame(
                    t=float(tick),
                    bodies={},
                    events=[
                        {
                            "type": "city_tick",
                            "tick": tick,
                            "population": population,
                            "budget": budget,
                            "income": income,
                            "upkeep": upkeep,
                            "pollution": pollution,
                            "happiness": happiness,
                            "connectivity_fraction": connectivity_fraction,
                        }
                    ],
                )
            )

        if not trace.frames:
            trace.frames.append(Frame(t=0.0, bodies={}, events=[]))

        return trace

    @staticmethod
    def _build_static(design: DesignSpec, world: WorldConfig) -> list[StaticProp]:
        """Every body becomes a static prop: CityEngine has no rigid-body motion.

        Buildings sit at ground level (y=0) and extrude upward by size[1]
        (height) — unlike pymunk2d, where `position[1]` is the body's own
        height-anchor, a citysim body's vertical placement is implicit.
        """
        props: list[StaticProp] = []
        for spec in design.bodies:
            shape_name = (
                spec.shape.value if isinstance(spec.shape, BodyShape) else str(spec.shape)
            )
            width = layout.footprint_width(spec)
            height = layout.height_of(spec)
            depth = layout.footprint_depth(spec)
            props.append(
                StaticProp(
                    id=spec.id,
                    kind=spec.kind or shape_name,
                    position=[spec.position[0] if spec.position else 0.0, 0.0],
                    z=spec.z,
                    size=[width, height, depth],
                    angle=spec.angle,
                    color=spec.color,
                    shape=shape_name,
                    created_by=spec.created_by,
                    visual=VisualSpec(
                        # "metal" is the legacy BodySpec default. City façades
                        # keep their semantic palette unless the design chose a
                        # more meaningful material explicitly.
                        material=None if spec.material == "metal" else spec.material,
                        seed=stable_visual_seed(world.seed, spec.id),
                        variant=f"v{stable_visual_seed(world.seed, spec.id) % 4}",
                        label=spec.kind,
                    ),
                )
            )
        return props
