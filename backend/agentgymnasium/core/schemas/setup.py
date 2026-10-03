from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class CollaborationMode(StrEnum):
    single = "single"
    competitive = "competitive"
    cooperative = "cooperative"
    relay = "relay"
    sandbox = "sandbox"


class BehaviorMode(StrEnum):
    engineer = "engineer"
    mad_scientist = "mad_scientist"
    evolution = "evolution"
    minimalist = "minimalist"
    speed_demon = "speed_demon"
    builder = "builder"
    critic = "critic"


class AgentRole(StrEnum):
    builder = "builder"
    crawler = "crawler"
    structural_engineer = "structural_engineer"
    controller_designer = "controller_designer"
    world_planner = "world_planner"
    critic = "critic"
    mutator = "mutator"


class MemoryMode(StrEnum):
    none = "none"
    episodic = "episodic"
    best_attempt_summary = "best_attempt_summary"


class MutationStrategy(StrEnum):
    balanced = "balanced"
    aggressive = "aggressive"
    conservative = "conservative"


class LLMProvider(StrEnum):
    localdeploy = "localdeploy"
    openai_compatible = "openai_compatible"
    mock = "mock"
    manual = "manual"


class PhysicsEngine(StrEnum):
    pymunk2d = "pymunk2d"
    pybullet3d = "pybullet3d"
    # Layout + economy simulation (no rigid-body physics) for isometric city
    # building — zoning/roads/population/budget over discrete ticks.
    citysim = "citysim"


class Terrain(StrEnum):
    grassland = "grassland"
    desert = "desert"
    factory = "factory"
    city = "city"
    cave = "cave"


class VisualStyle(StrEnum):
    realistic = "realistic"
    playful = "playful"
    blueprint = "blueprint"
    neon_lab = "neon_lab"


class CollisionSafety(StrEnum):
    strict = "strict"
    relaxed = "relaxed"


class WorldBounds(StrEnum):
    enforced = "enforced"
    soft = "soft"
    disabled = "disabled"


class LaunchState(StrEnum):
    ready = "READY"
    missing_required = "MISSING_REQUIRED"
    llm_offline = "LLM_OFFLINE"
    tool_challenge_mismatch = "TOOL_CHALLENGE_MISMATCH"
    constraints_too_loose = "CONSTRAINTS_TOO_LOOSE"
    unsupported_engine = "UNSUPPORTED_ENGINE"
    unsupported_mode = "UNSUPPORTED_MODE"


class AgentConfig(BaseModel):
    id: str
    name: str
    role: AgentRole = AgentRole.builder
    behavior_mode: BehaviorMode = BehaviorMode.engineer
    provider: LLMProvider = LLMProvider.mock
    model: str = "mock"
    endpoint_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.7
    max_attempts: int = 50
    context_window: str = "8k"
    memory_mode: MemoryMode = MemoryMode.none
    mutation_strategy: MutationStrategy = MutationStrategy.balanced
    system_prompt_override: str | None = None


class LLMConnectionConfig(BaseModel):
    endpoint_url: str = "http://127.0.0.1:8000/v1"
    api_key: str | None = None


class ScenarioConfig(BaseModel):
    preset: str  # required
    objective: str = ""
    reward: str = "distance_plus_stability"


class WorldConfig(BaseModel):
    template: str  # required
    terrain: Terrain = Terrain.grassland
    engine: PhysicsEngine = PhysicsEngine.pymunk2d
    gravity: float = -9.81
    map_size: list[int] = [32, 32]
    # Matches WorldTemplate's default so template- and hand-built worlds agree.
    active_physics_zones: int = 1
    visual_style: VisualStyle = VisualStyle.realistic
    seed: int | None = None


class AgentsConfig(BaseModel):
    mode: CollaborationMode = CollaborationMode.single
    participants: list[AgentConfig] = []


class ToolsConfig(BaseModel):
    enabled: list[str] = []


class ConstraintsConfig(BaseModel):
    max_parts: int = 300
    max_joints: int = 120
    max_motors: int = 40
    energy_budget: int = 1200
    max_attempts: int = 50
    simulation_duration_seconds: int = 180
    # Model↔environment turns inside one attempt. Mock demos deliberately use
    # one turn; real providers can observe a simulation and revise.
    agent_turns_per_attempt: int = 3
    material_budget: int = 2000
    collision_safety: CollisionSafety = CollisionSafety.strict
    world_bounds: WorldBounds = WorldBounds.enforced
    repair_loop_enabled: bool = True


class OutputsConfig(BaseModel):
    replay_json: bool = True
    scorecard_json: bool = True
    trace_jsonl: bool = True
    markdown_report: bool = False
    screenshot: bool = False
    video_capture: bool = False


class LaunchConfig(BaseModel):
    version: int = 1
    project_name: str = "AgentGymnasium Run"
    scenario: ScenarioConfig
    world: WorldConfig
    agents: AgentsConfig = AgentsConfig()
    llm_connection: LLMConnectionConfig = LLMConnectionConfig()
    tools: ToolsConfig = ToolsConfig()
    constraints: ConstraintsConfig = ConstraintsConfig()
    outputs: OutputsConfig = OutputsConfig()


class ValidationResult(BaseModel):
    state: LaunchState
    missing: list[str] = []
    warnings: list[str] = []
    estimated_runtime_min: tuple[int, int] | None = None
