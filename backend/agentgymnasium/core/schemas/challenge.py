from __future__ import annotations

from pydantic import BaseModel

from agentgymnasium.core.schemas.setup import PhysicsEngine


class RewardOption(BaseModel):
    """One selectable scoring goal for a challenge with more than one reward.

    ``ScenarioPreset.reward`` stays the ACTIVE reward (single source of truth
    for scoring); ``reward_options`` just lets the Setup screen offer several
    named goals over the same challenge/world instead of duplicating the whole
    challenge per goal (e.g. one "City Builder" challenge, several city goals).
    Empty on every challenge that has only one reward.
    """

    value: str
    label: str
    description: str = ""


class ScenarioPreset(BaseModel):
    id: str
    name: str
    tagline: str
    tags: list[str]
    objective: str
    reward: str
    default_world: str
    required_tools: list[str]
    recommended_tools: list[str] = []
    # Scoring parameters for this challenge (goal_x, threshold_x, min_spacing, …).
    # Injected into the design metadata at scoring time so rewards are goal-aware.
    goal: dict = {}
    # Starting objects seeded into the design before the agent acts: the crate to
    # move, platforms, goal markers, balls to sort, … Each entry is a BodySpec
    # mapping. This gives every challenge a concrete, non-empty world the agent
    # can reason about and reference, and guarantees something to simulate.
    scaffold: list[dict] = []
    # Alternate scoring goals for this same challenge/world (see RewardOption).
    # Empty for every challenge with only one reward.
    reward_options: list[RewardOption] = []


class WorldTemplate(BaseModel):
    id: str
    name: str
    terrain: str
    map_size: list[int]
    gravity: float = -9.81
    active_physics_zones: int = 1
    description: str = ""
    # Fixed terrain geometry for this world (cliffs, ledges, hills, tables). Each
    # entry is a static BodySpec mapping. Seeded into the design like challenge
    # scaffold so worlds physically differ and render distinctly.
    static_bodies: list[dict] = []
    # Ground floor spans, in world metres, as [x0, x1] pairs. A body positioned
    # between spans has no floor beneath it and falls through — a real gap/chasm
    # instead of the universal invisible floor. Empty means "one span across the
    # whole map" (today's behavior; fully backward compatible).
    ground_spans: list[list[float]] = []
    # World-y below which a body in a gap is considered to have fallen into the
    # chasm (used by scoring, not physics). Only meaningful when ground_spans is set.
    kill_y: float | None = None
    # Which engine simulates this world. Defaults to pymunk2d (physics) so every
    # existing template is unaffected; `citysim` templates use the layout+economy
    # engine instead (no rigid-body physics).
    engine: PhysicsEngine = PhysicsEngine.pymunk2d
    # Starting city budget (citysim only), seeded onto design.metadata the same
    # way ground_spans/kill_y are — read by CityEngine's economy tick loop.
    starting_budget: float | None = None
