// Auto-mirrored from backend/agentgymnasium/core/schemas/setup.py — keep in sync.

export type CollaborationMode =
  | 'single'
  | 'competitive'
  | 'cooperative'
  | 'relay'
  | 'sandbox'

export type BehaviorMode =
  | 'engineer'
  | 'mad_scientist'
  | 'evolution'
  | 'minimalist'
  | 'speed_demon'
  | 'builder'
  | 'critic'

export type AgentRole =
  | 'builder'
  | 'crawler'
  | 'structural_engineer'
  | 'controller_designer'
  | 'world_planner'
  | 'critic'
  | 'mutator'

export type MemoryMode = 'none' | 'episodic' | 'best_attempt_summary'

export type MutationStrategy = 'balanced' | 'aggressive' | 'conservative'

export type LLMProvider = 'localdeploy' | 'openai_compatible' | 'mock' | 'manual'

export type PhysicsEngine = 'pymunk2d' | 'pybullet3d' | 'citysim'

export type Terrain = 'grassland' | 'desert' | 'factory' | 'city' | 'cave'

export type VisualStyle = 'realistic' | 'playful' | 'blueprint' | 'neon_lab'

export type CollisionSafety = 'strict' | 'relaxed'

export type WorldBounds = 'enforced' | 'soft' | 'disabled'

export type LaunchState =
  | 'READY'
  | 'MISSING_REQUIRED'
  | 'LLM_OFFLINE'
  | 'TOOL_CHALLENGE_MISMATCH'
  | 'CONSTRAINTS_TOO_LOOSE'
  | 'UNSUPPORTED_ENGINE'
  | 'UNSUPPORTED_MODE'

export interface AgentConfig {
  id: string
  name: string
  role?: AgentRole
  behavior_mode?: BehaviorMode
  provider?: LLMProvider
  model?: string
  endpoint_url?: string | null
  api_key?: string | null
  temperature?: number
  max_attempts?: number
  context_window?: string
  memory_mode?: MemoryMode
  mutation_strategy?: MutationStrategy
  system_prompt_override?: string | null
}

export interface LLMConnectionConfig {
  endpoint_url?: string
  api_key?: string | null
}

export interface ProviderMeta {
  id: string
  name: string
  requires_endpoint: boolean
  requires_api_key: boolean
  description: string
  env_api_key_available?: boolean
  env_api_key_preview?: string | null
}

export interface ProviderStatus {
  online: boolean
  detail: string
  models?: string[]
}

export interface ScenarioConfig {
  preset: string
  objective?: string
  reward?: string
}

export interface WorldConfig {
  template: string
  terrain?: Terrain
  engine?: PhysicsEngine
  gravity?: number
  map_size?: number[]
  active_physics_zones?: number
  visual_style?: VisualStyle
  seed?: number | null
}

export interface AgentsConfig {
  mode?: CollaborationMode
  participants?: AgentConfig[]
}

export interface ToolsConfig {
  enabled?: string[]
}

export interface ConstraintsConfig {
  max_parts?: number
  max_joints?: number
  max_motors?: number
  energy_budget?: number
  max_attempts?: number
  simulation_duration_seconds?: number
  agent_turns_per_attempt?: number
  material_budget?: number
  collision_safety?: CollisionSafety
  world_bounds?: WorldBounds
  repair_loop_enabled?: boolean
}

export interface OutputsConfig {
  replay_json?: boolean
  scorecard_json?: boolean
  trace_jsonl?: boolean
  markdown_report?: boolean
  screenshot?: boolean
  video_capture?: boolean
}

export interface LaunchConfig {
  version?: number
  project_name?: string
  scenario: ScenarioConfig
  world: WorldConfig
  agents?: AgentsConfig
  llm_connection?: LLMConnectionConfig
  tools?: ToolsConfig
  constraints?: ConstraintsConfig
  outputs?: OutputsConfig
}

export interface RewardOption {
  value: string
  label: string
  description?: string
}

export interface ScenarioPreset {
  id: string
  name: string
  tagline: string
  tags: string[]
  objective: string
  reward: string
  default_world: string
  required_tools: string[]
  recommended_tools: string[]
  goal?: Record<string, number | string>
  // Alternate scoring goals for this same challenge/world (e.g. City
  // Builder's Boomtown/Budget/Balanced/Green goals). Empty for every
  // challenge that has only one reward.
  reward_options?: RewardOption[]
}

export interface WorldTemplate {
  id: string
  name: string
  terrain: Terrain
  map_size: number[]
  gravity: number
  active_physics_zones: number
  description: string
  // Which engine simulates this world (defaults to pymunk2d server-side).
  engine?: PhysicsEngine
  // Starting city treasury (citysim worlds only).
  starting_budget?: number | null
}

export interface ValidationResult {
  state: LaunchState
  missing?: string[]
  warnings?: string[]
  estimated_runtime_min?: [number, number] | null
}

export interface WorkspaceConfigResponse {
  config: LaunchConfig
  path: string
  mtime_ns?: number | null
}

export interface WorkspaceConfigStatus {
  path: string
  exists: boolean
  mtime_ns?: number | null
}

// ─── Episode trace (mirrors backend/agentgymnasium/core/schemas/trace.py) ──────────

export interface VisualSpec {
  variant?: string | null
  material?: string | null
  condition?: string
  theme?: string | null
  seed?: number
  emission?: number
  label?: string | null
  animation_state?: string | null
}

export interface StaticProp {
  id: string
  kind: string // "ground" | "goal" | "prop" | body shape
  position: number[]
  size?: number[]
  angle?: number // orientation in radians (sloped ramps/beams)
  color?: string | null
  // Actual geometry (box/circle/segment), independent of `kind` — a
  // beam/ramp/wall is semantically e.g. "beam" but geometrically a segment.
  shape?: string
  // Ground-plane depth coordinate (iso/`citysim` traces only); 0 for side view.
  z?: number
  created_by?: string | null
  visual?: VisualSpec
}

export interface FrameBody {
  x: number
  y: number
  angle: number
  // Ground-plane depth coordinate (iso traces only); 0 for side-view traces.
  z?: number
}

export interface BodyMeta {
  shape: string // box | circle | segment | polygon
  size?: number[]
  color?: string | null
  kind?: string | null // semantic label (house/tower/tree/road/…)
  created_by?: string | null
  visual?: VisualSpec
}

export interface JointMeta {
  id: string
  body_a: string
  body_b: string
  type: 'pivot' | 'pin' | 'slide' | 'spring' | string
  anchor_a: number[]
  anchor_b: number[]
  motor_rate?: number | null
  motor_max_force?: number
  created_by?: string | null
}

export type TraceVisualEvent =
  | { type: 'body_created'; body_id: string; kind?: string; created_by?: string | null }
  | { type: 'joint_attached'; joint_id: string; body_a: string; body_b: string }
  | { type: 'motor_activated'; joint_id: string; rate: number }
  | { type: 'contact_started'; body_a: string; body_b: string; impulse?: number }
  | { type: 'structure_stressed'; body_id?: string; joint_id?: string; level: number }
  | { type: 'goal_reached'; body_id?: string; goal_id?: string }
  | { type: 'object_sorted'; body_id: string; bin_id: string; accepted: boolean }
  | { type: 'body_destroyed'; body_id: string; reason?: string }
  | ({ type: 'city_tick' } & Record<string, unknown>)
  | ({ type: string } & Record<string, unknown>)

export interface Frame {
  t: number
  bodies: Record<string, FrameBody>
  events?: TraceVisualEvent[]
}

export interface EpisodeTrace {
  version: number
  run_id: string
  attempt_id: string
  engine: string
  camera: string
  terrain?: string
  visual_style?: VisualStyle
  visual_seed?: number
  dt: number
  // World-y below which a body in a ground gap has fallen into the chasm. Null
  // when this world has no gap (ground_spans not set).
  kill_y?: number | null
  world_static: StaticProp[]
  body_meta?: Record<string, BodyMeta>
  joints?: JointMeta[]
  frames: Frame[]
}

export interface CreateRunResponse {
  run_id: string
}

export interface LaunchResponse {
  run_id: string
}

export interface RunSummary {
  run_id: string
  created_at?: number | null
  project_name?: string | null
  challenge?: string | null
  mode?: string | null
  reward?: string | null
  score_total?: number | null
  success?: boolean | null
  artifact_dir?: string | null
  config_available?: boolean
  attempt_count?: number
  provider?: string | null
  model?: string | null
  seed?: number | null
  input_tokens?: number | null
  output_tokens?: number | null
  latency_ms?: number | null
  protocol?: string | null
  benchmark_hash?: string | null
}

export interface RunConfigResponse {
  run_id: string
  config: LaunchConfig
  provenance?: Record<string, unknown>
}

export interface RelaunchRunRequest {
  patch?: Record<string, unknown>
}

export interface RelaunchRunResponse {
  run_id: string
  source_run_id: string
  config: LaunchConfig
}

export interface RunAttemptSummary {
  trace_run_id: string
  attempt_index?: number | null
  agent_id?: string | null
  score_total?: number | null
  success?: boolean | null
}

export type ExperimentStatus = 'queued' | 'running' | 'completed' | 'cancelled' | 'failed'
export type ExperimentCellStatus = ExperimentStatus

export interface ModelVariant {
  id: string
  label: string
  provider: LLMProvider
  model: string
  endpoint_url?: string | null
  api_key?: string | null
  temperature?: number
}

export interface ExperimentSpec {
  name: string
  base_config: LaunchConfig
  models: ModelVariant[]
  seeds: number[]
  repeats: number
}

export interface ExperimentCell {
  id: string
  model_variant_id: string
  model_label: string
  seed: number
  repeat_index: number
  status: ExperimentCellStatus
  launch_run_id?: string | null
  trace_run_id?: string | null
  score?: number | null
  success?: boolean | null
  input_tokens: number
  output_tokens: number
  latency_ms: number
  error?: string | null
}

export interface ExperimentRecord {
  id: string
  spec: ExperimentSpec
  status: ExperimentStatus
  created_at: number
  started_at?: number | null
  finished_at?: number | null
  cells: ExperimentCell[]
  error?: string | null
}

export interface ExperimentAggregate {
  model_variant_id: string
  model_label: string
  n: number
  successes: number
  success_rate: number
  mean_score: number
  stddev_score: number
  ci95_low: number
  ci95_high: number
  mean_latency_ms: number
  mean_tokens: number
}

export interface ExperimentPairwise {
  model_a_id: string
  model_a_label: string
  model_b_id: string
  model_b_label: string
  n_pairs: number
  wins_a: number
  ties: number
  wins_b: number
  mean_score_delta: number
  ci95_low: number
  ci95_high: number
}

export interface TokenUsage {
  input_tokens: number
  output_tokens: number
  reasoning_tokens: number
  cached_input_tokens: number
}

export interface ModelResult {
  provider: string
  model: string
  raw_text: string
  tool_calls: Record<string, unknown>[]
  native_tool_calls: boolean
  finish_reason?: string | null
  request_id?: string | null
  latency_ms: number
  retries: number
  usage: TokenUsage
}

export interface ModelInteraction {
  turn_index: number
  agent_id: string
  system: string
  user: string
  seed?: number | null
  result: ModelResult
}

// ─── Score / tool-call (mirrors backend score.py / toolcall.py) ────────────────

export type ToolCallStatus = 'success' | 'repaired' | 'rejected'

export interface ToolCallRecord {
  ts: number
  agent_id: string
  tool: string
  args: Record<string, unknown>
  status: ToolCallStatus
  error?: string | null
  source?: string
  mutated?: boolean
  visual_change?: boolean
  new_body_ids?: string[]
  new_joint_ids?: string[]
  output?: Record<string, unknown>
}

export interface BuildStepRecord {
  attempt_index: number
  step_index: number
  trace_run_id?: string | null
  agent_id: string
  tool: string
  status: ToolCallStatus
  label: string
  mutated: boolean
  visual_change: boolean
  new_body_ids: string[]
  new_joint_ids: string[]
  error?: string | null
  trace: EpisodeTrace
}

export interface ScoreCard {
  score_total: number
  success: boolean
  metrics: Record<string, number>
  failure_events: Record<string, unknown>[]
  summary: string
  reward: string
  // Short deterministic "why it failed / how to improve" derived from metrics.
  improvement_hint?: string
}

export interface DesignSummary {
  bodies: number
  joints: number
  motors: number
  sensors: number
  beams: number
  ramps: number
  total_parts: number
  // Per-kind breakdown (house/tower/tree/road/…) of what was built.
  by_kind?: Record<string, number>
}

// ─── Live run events (mirrors backend orchestrator event protocol) ─────────────

export interface RunAgentInfo {
  id: string
  name: string
  role: string
}

export interface RunStartedEvent {
  type: 'run_started'
  run_id: string
  project_name: string
  mode: string
  objective: string
  reward?: string
  max_attempts: number
  // Effective MVP caps vs. what the user requested (for the "running 3 of 50" note).
  requested_attempts?: number
  attempts_cap?: number
  requested_duration_s?: number
  simulation_cap_s?: number
  constraints?: Partial<ConstraintsConfig>
  agents?: RunAgentInfo[]
}

export interface RunCaps {
  effectiveAttempts: number
  requestedAttempts?: number
  simCapS?: number
  requestedDurationS?: number
}

export interface AttemptStartedEvent {
  type: 'attempt_started'
  attempt_index: number
  agent_id?: string
  // Cooperative attempts are shared by several agents at once.
  agent_ids?: string[]
  // Lineage: id of the previous attempt this one iterates on (null for first).
  parent_attempt_id?: string | null
}

export interface ToolCallEvent {
  type: 'tool_call'
  attempt_index: number
  agent_id?: string
  record: ToolCallRecord
}

export interface DesignUpdateEvent {
  type: 'design_update'
  attempt_index: number
  // Single/competitive: the owning agent. Cooperative omits it in favour of
  // ``agent_ids`` + ``by_agent``.
  agent_id?: string
  agent_ids?: string[]
  summary: DesignSummary
  // Cooperative ownership breakdown: who built which parts of the shared design.
  by_agent?: Record<string, Partial<DesignSummary>>
}

export interface DesignSnapshotEvent {
  type: 'design_snapshot'
  attempt_index: number
  agent_id?: string
  // Index into the attempt's tool_calls, matching one-to-one with ToolCallEvent.
  step_index: number
  trace_run_id?: string | null
  tool: string
  status: ToolCallStatus
  label: string
  mutated: boolean
  visual_change: boolean
  new_body_ids: string[]
  new_joint_ids: string[]
  error?: string | null
  // Un-simulated, single-frame EpisodeTrace-shaped snapshot of the design as it
  // stood right after this tool call — lets the Studio replay the CONSTRUCTION
  // sequence (Build Timeline) with the same renderer used for physics replay.
  trace: EpisodeTrace
}

export interface TraceReadyEvent {
  type: 'trace_ready'
  attempt_index: number
  agent_id?: string
  agent_ids?: string[]
  trace_run_id: string
}

export interface AttemptDiff {
  prev_attempt_index: number
  parts_delta: number
  joints_delta: number
  added_parts: string[]
  removed_parts: string[]
  moved_parts: string[]
  prev_score: number
  score_delta: number
  failure_events: string[]
}

export interface ScoreEvent {
  type: 'score'
  attempt_index: number
  // Cooperative emits a single shared score with agent_id === "shared".
  agent_id?: string
  scorecard: ScoreCard
  diff?: AttemptDiff | null
}

export interface AttemptFinishedEvent {
  type: 'attempt_finished'
  attempt_index: number
  agent_id?: string
  agent_ids?: string[]
}

export interface WinnerEvent {
  type: 'winner'
  agent_id: string
  score: number
}

export interface RunFinishedEvent {
  type: 'run_finished'
  best_attempt_index: number
  best_score: number
  // trace_run_id of the best attempt, for one-click replay of the winner.
  best_trace_run_id?: string | null
  winner_agent_id?: string | null
}

export interface ErrorEvent {
  type: 'error'
  detail: string
  // Structured failure kind for LLM errors (auth/timeout/server/…).
  kind?: string
}

export interface ModelResultEvent {
  type: 'model_result'
  attempt_index: number
  agent_id: string
  turn_index: number
  provider: string
  model: string
  latency_ms: number
  retries: number
  finish_reason?: string | null
  native_tool_calls: boolean
  usage: TokenUsage
}

export type RunEvent =
  | RunStartedEvent
  | AttemptStartedEvent
  | ToolCallEvent
  | DesignSnapshotEvent
  | DesignUpdateEvent
  | TraceReadyEvent
  | ScoreEvent
  | AttemptFinishedEvent
  | ModelResultEvent
  | WinnerEvent
  | RunFinishedEvent
  | ErrorEvent

// ─── Embodiment gateway ─────────────────────────────────────────────────────

export type EnvironmentMode = 'simulation' | 'shadow' | 'hardware_in_the_loop' | 'real'
export type SafetyState = 'disarmed' | 'armed' | 'emergency_stopped'
export type EmbodimentActionKind = 'stop' | 'drive_to'

export interface SafetyLimits {
  min_x: number
  max_x: number
  min_y: number
  max_y: number
  max_linear_speed_mps: number
  max_action_duration_s: number
  heartbeat_timeout_s: number
}

export interface EmbodimentDevice {
  id: string
  label: string
  adapter: string
  mode: EnvironmentMode
  safety_state: SafetyState
  limits: SafetyLimits
  connected: boolean
  last_heartbeat_age_s: number | null
}

export interface EmbodimentObservation {
  device_id: string
  timestamp: number
  sequence: number
  pose: { x: number; y: number; heading_rad: number }
  velocity: { linear_mps: number; angular_rps: number }
  battery_fraction: number | null
  sensors: Record<string, unknown>
  safety_state: SafetyState
}

export interface EmbodimentAction {
  kind: EmbodimentActionKind
  target_x?: number | null
  target_y?: number | null
  max_speed_mps?: number
  duration_s?: number
}

export interface EmbodimentActionReceipt {
  action_id: string
  accepted: boolean
  reason: string | null
  observation: EmbodimentObservation | null
}

export interface EmbodimentEvent {
  timestamp: number
  device_id: string
  event: string
  detail: Record<string, unknown>
}

export interface EmbodimentEpisodeResult {
  id: string
  device_id: string
  objective: string
  provider: string
  model: string
  success: boolean
  score: number
  final_distance_m: number
  interactions: ModelInteraction[]
  actions: EmbodimentActionReceipt[]
  observations: EmbodimentObservation[]
  error?: string | null
}
