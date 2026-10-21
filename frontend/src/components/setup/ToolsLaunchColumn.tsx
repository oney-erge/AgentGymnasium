import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import type {
  ConstraintsConfig,
  LaunchConfig,
  LaunchState,
  OutputsConfig,
  ToolsConfig,
  ValidationResult,
} from '../../api/types'

// ─── API shape mirrors backend ToolsResponse / ToolCategoryResponse ──────────

interface ToolDefinition {
  name: string
  category: string
  description: string
  risk: string
  enabled_by_default: boolean
  status?: 'implemented' | 'inspection' | 'experimental'
}

interface ToolCategoryResponse {
  category: string
  tools: ToolDefinition[]
  total: number
  enabled_count: number
}

interface ToolsResponse {
  categories: ToolCategoryResponse[]
  total: number
  enabled_total: number
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface ToolsLaunchColumnProps {
  config: Partial<LaunchConfig>
  onConfigChange: (patch: Partial<LaunchConfig>) => void
  validationResult: ValidationResult | null
  onValidateNow: () => void
  onLaunch: () => void
  onSavePreset: () => void
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatCategoryLabel(raw: string): string {
  return raw
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionHeader({
  title,
  open,
  onToggle,
}: {
  title: string
  open: boolean
  onToggle: () => void
}) {
  return (
    <button
      onClick={onToggle}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        width: '100%',
        background: 'none',
        border: 'none',
        padding: '8px 0 4px',
        cursor: 'pointer',
        color: 'var(--text-1)',
      }}
    >
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '0.8px',
          textTransform: 'uppercase',
          color: 'var(--text-2)',
        }}
      >
        {title}
      </span>
      <span style={{ fontSize: 10, color: 'var(--text-2)' }}>{open ? '▾' : '▸'}</span>
    </button>
  )
}

function Divider() {
  return (
    <div
      style={{
        borderTop: '1px solid var(--border)',
        margin: '12px 0',
      }}
    />
  )
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 10,
        background: 'var(--accent-soft)',
        border: '1px solid var(--accent)',
        color: 'var(--accent)',
        fontSize: 11,
        fontWeight: 600,
      }}
    >
      {children}
    </span>
  )
}

// ─── Slider row ───────────────────────────────────────────────────────────────

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (v: number) => void
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '120px 1fr 48px',
        alignItems: 'center',
        gap: 8,
        marginBottom: 8,
      }}
    >
      <span style={{ fontSize: 11, color: 'var(--text-2)' }}>
        {label}
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
      />
      <span
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: 'var(--text-1)',
          textAlign: 'right',
        }}
      >
        {value}
      </span>
    </div>
  )
}

// ─── Select row ───────────────────────────────────────────────────────────────

function SelectRow<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '120px 1fr',
        alignItems: 'center',
        gap: 8,
        marginBottom: 8,
      }}
    >
      <span style={{ fontSize: 11, color: 'var(--text-2)' }}>
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        style={{
          background: 'var(--surface-2)',
          color: 'var(--text-1)',
          border: '1px solid var(--border)',
          borderRadius: 4,
          padding: '3px 6px',
          fontSize: 11,
          cursor: 'pointer',
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}

// ─── Toggle row ───────────────────────────────────────────────────────────────

function ToggleRow({
  label,
  value,
  onChange,
}: {
  label: string
  value: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '120px 1fr',
        alignItems: 'center',
        gap: 8,
        marginBottom: 8,
      }}
    >
      <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{label}</span>
      <button
        onClick={() => onChange(!value)}
        style={{
          justifySelf: 'start',
          background: value ? 'var(--accent)' : 'var(--surface-2)',
          color: value ? '#fff' : 'var(--text-2)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          padding: '3px 10px',
          fontSize: 11,
          fontWeight: 600,
          cursor: 'pointer',
        }}
      >
        {value ? '● ON' : '○ OFF'}
      </button>
    </div>
  )
}

// ─── Validation banner ────────────────────────────────────────────────────────


/** The backend names missing fields by path; say what to do in words for the common first-run one. */
function describeMissingField(field: string): string {
  const model = /^agents\.participants\[(\d+)\]\.model$/.exec(field)
  if (model) {
    return `Agent ${String.fromCharCode(65 + Number(model[1]))} has no model. Pick one, or choose Mock / No model for an offline run`
  }
  return field
}

function ValidationBanner({ result }: { result: ValidationResult | null }) {
  if (!result) {
    return (
      <div
        style={{
          padding: '8px 12px',
          borderRadius: 6,
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          fontSize: 11,
          color: 'var(--text-2)',
        }}
      >
        Validating…
      </div>
    )
  }

  const { state, missing } = result

  type BannerStyle = { bg: string; border: string; color: string }

  const styles: Record<LaunchState, BannerStyle> = {
    READY: {
      bg: 'color-mix(in srgb, var(--ok) 15%, transparent)',
      border: 'var(--ok)',
      color: 'var(--ok)',
    },
    MISSING_REQUIRED: {
      bg: 'color-mix(in srgb, var(--danger) 15%, transparent)',
      border: 'var(--danger)',
      color: 'var(--danger)',
    },
    LLM_OFFLINE: {
      bg: 'color-mix(in srgb, var(--danger) 15%, transparent)',
      border: 'var(--danger)',
      color: 'var(--danger)',
    },
    TOOL_CHALLENGE_MISMATCH: {
      bg: 'color-mix(in srgb, var(--warn) 15%, transparent)',
      border: 'var(--warn)',
      color: 'var(--warn)',
    },
    CONSTRAINTS_TOO_LOOSE: {
      bg: 'color-mix(in srgb, var(--warn) 15%, transparent)',
      border: 'var(--warn)',
      color: 'var(--warn)',
    },
    UNSUPPORTED_ENGINE: {
      bg: 'color-mix(in srgb, var(--warn) 15%, transparent)',
      border: 'var(--warn)',
      color: 'var(--warn)',
    },
    UNSUPPORTED_MODE: {
      bg: 'color-mix(in srgb, var(--warn) 15%, transparent)',
      border: 'var(--warn)',
      color: 'var(--warn)',
    },
  }

  const s = styles[state] ?? styles['MISSING_REQUIRED']

  const messages: Record<LaunchState, string> = {
    READY: '✓ Ready to Launch — Your setup is valid.',
    MISSING_REQUIRED: `Can't launch yet: ${(missing ?? []).map(describeMissingField).join(' · ')}`,
    LLM_OFFLINE: (missing ?? []).length
      ? (missing ?? []).join(' · ')
      : 'LLM endpoint offline — check connection',
    TOOL_CHALLENGE_MISMATCH: (missing ?? []).length
      ? (missing ?? []).join(' · ')
      : 'Tool / challenge mismatch — adjust tools',
    CONSTRAINTS_TOO_LOOSE: 'Constraints too loose — tighten limits',
    UNSUPPORTED_ENGINE: 'Engine not available yet',
    UNSUPPORTED_MODE: (missing ?? []).length
      ? (missing ?? []).join(' · ')
      : 'Collaboration mode not available yet',
  }

  const msg = messages[state] ?? state

  return (
    <div
      style={{
        padding: '8px 12px',
        borderRadius: 6,
        background: s.bg,
        border: `1px solid ${s.border}`,
        fontSize: 11,
        fontWeight: 600,
        color: s.color,
      }}
    >
      {msg}
    </div>
  )
}

// ─── Summary row ──────────────────────────────────────────────────────────────

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
      <span style={{ fontSize: 11, color: 'var(--text-2)' }}>{label}</span>
      <span style={{ fontSize: 11, color: 'var(--text-1)', fontWeight: 500 }}>{value}</span>
    </div>
  )
}

// ─── Default constraint values ────────────────────────────────────────────────

const DEFAULT_CONSTRAINTS: Required<ConstraintsConfig> = {
  max_parts: 300,
  max_joints: 120,
  max_motors: 20,
  energy_budget: 1200,
  max_attempts: 50,
  simulation_duration_seconds: 180,
  agent_turns_per_attempt: 3,
  material_budget: 2000,
  collision_safety: 'strict',
  world_bounds: 'enforced',
  repair_loop_enabled: true,
}

const DEFAULT_OUTPUTS: Required<OutputsConfig> = {
  replay_json: true,
  scorecard_json: true,
  trace_jsonl: true,
  markdown_report: false,
  screenshot: false,
  video_capture: false,
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ToolsLaunchColumn({
  config,
  onConfigChange,
  validationResult,
  onValidateNow,
  onLaunch,
  onSavePreset,
}: ToolsLaunchColumnProps) {
  // ── Tools state ──
  const [toolsData, setToolsData] = useState<ToolsResponse | null>(null)
  // Checked tools are DERIVED from config.tools.enabled (the single source of
  // truth), so a preset that seeds required_tools and the per-tool checkboxes
  // can't diverge or clobber each other.
  const checkedTools = useMemo(
    () => new Set(config.tools?.enabled ?? []),
    [config.tools?.enabled],
  )
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set())
  const [toolsSectionOpen, setToolsSectionOpen] = useState(true)
  const [constraintsSectionOpen, setConstraintsSectionOpen] = useState(true)

  // ── Constraint state ──
  const constraints: Required<ConstraintsConfig> = {
    ...DEFAULT_CONSTRAINTS,
    ...config.constraints,
  }

  // ── Outputs state ──
  const outputs: Required<OutputsConfig> = {
    ...DEFAULT_OUTPUTS,
    ...config.outputs,
  }

  // ── Fetch tools on mount ──
  useEffect(() => {
    api
      .get<ToolsResponse>('/tools')
      .then((data) => {
        setToolsData(data)
        // Seed default-on tools, UNIONED with anything already enabled (e.g. a
        // preset's required_tools selected before this fetch resolved) so the
        // async seed can't clobber the preset's required tools.
        const initial = new Set<string>(config.tools?.enabled ?? [])
        data.categories.forEach((cat) => {
          cat.tools.forEach((t) => {
            if (t.enabled_by_default) initial.add(t.name)
          })
        })
        onConfigChange({ tools: { enabled: Array.from(initial) } } as Partial<LaunchConfig>)
      })
      .catch(() => {
        // silently ignore fetch errors (backend may be down in tests)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Helpers ──

  // Selectable = everything except experimental tools (which are disabled and
  // would be rejected at the chokepoint anyway).
  const selectableToolNames = (): string[] =>
    toolsData?.categories.flatMap((c) =>
      c.tools.filter((t) => t.status !== 'experimental').map((t) => t.name),
    ) ?? []

  const totalCount = toolsData?.total ?? 0
  const enabledCount = checkedTools.size

  function handleToggleTool(name: string, checked: boolean) {
    const next = new Set(checkedTools)
    if (checked) next.add(name)
    else next.delete(name)
    const toolsCfg: ToolsConfig = { enabled: Array.from(next) }
    onConfigChange({ tools: toolsCfg } as Partial<LaunchConfig>)
  }

  function handleSelectAll() {
    onConfigChange(
      { tools: { enabled: selectableToolNames() } } as Partial<LaunchConfig>,
    )
  }

  function handleClearAll() {
    onConfigChange({ tools: { enabled: [] } } as Partial<LaunchConfig>)
  }

  function handleConstraintChange(patch: Partial<ConstraintsConfig>) {
    onConfigChange({ constraints: { ...constraints, ...patch } } as Partial<LaunchConfig>)
  }

  function handleOutputChange(patch: Partial<OutputsConfig>) {
    onConfigChange({ outputs: { ...outputs, ...patch } } as Partial<LaunchConfig>)
  }

  function toggleCategoryCollapse(cat: string) {
    setCollapsedCategories((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  const isReady = validationResult?.state === 'READY'

  // ── Estimated runtime from validation ──
  const estRuntime = validationResult?.estimated_runtime_min
  const estRuntimeStr = estRuntime ? `~${estRuntime[0]}–${estRuntime[1]} min` : '~2–4 min'

  // ── Constraint summary string ──
  const constraintSummary = `${constraints.collision_safety === 'strict' ? 'Strict' : 'Relaxed'} · ${constraints.max_attempts} attempts · ${constraints.simulation_duration_seconds}s`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {/* ── Section 1: Available Tools ── */}
      <SectionHeader
        title="Available Tools"
        open={toolsSectionOpen}
        onToggle={() => setToolsSectionOpen((o) => !o)}
      />

      {toolsSectionOpen && (
        <>
          {/* Header row with Select All / Clear All */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 6,
            }}
          >
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>
              Tools define what agents are allowed to use.
            </span>
            <div style={{ display: 'flex', gap: 4 }}>
              <button
                onClick={handleSelectAll}
                style={{
                  fontSize: 10,
                  padding: '2px 7px',
                  borderRadius: 4,
                  border: '1px solid var(--border)',
                  background: 'var(--surface-2)',
                  color: 'var(--text-2)',
                  cursor: 'pointer',
                }}
              >
                Select All
              </button>
              <button
                onClick={handleClearAll}
                style={{
                  fontSize: 10,
                  padding: '2px 7px',
                  borderRadius: 4,
                  border: '1px solid var(--border)',
                  background: 'var(--surface-2)',
                  color: 'var(--text-2)',
                  cursor: 'pointer',
                }}
              >
                Clear All
              </button>
            </div>
          </div>

          {/* Categories */}
          {toolsData ? (
            toolsData.categories.map((cat) => {
              const catOpen = !collapsedCategories.has(cat.category)
              const catEnabled = cat.tools.filter((t) => checkedTools.has(t.name)).length
              return (
                <div key={cat.category} style={{ marginBottom: 8 }}>
                  {/* Category header */}
                  <button
                    onClick={() => toggleCategoryCollapse(cat.category)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      width: '100%',
                      background: 'none',
                      border: 'none',
                      borderTop: '1px solid var(--border)',
                      padding: '5px 0 3px',
                      cursor: 'pointer',
                    }}
                  >
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: '0.6px',
                        textTransform: 'uppercase',
                        color: 'var(--text-2)',
                      }}
                    >
                      {catOpen ? '▾' : '▸'} {formatCategoryLabel(cat.category)} ({catEnabled}/
                      {cat.total})
                    </span>
                  </button>

                  {/* Tool pills — name only; full description on hover. */}
                  {catOpen && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, padding: '4px 0 2px' }}>
                      {cat.tools.map((tool) => {
                        const experimental = tool.status === 'experimental'
                        const on = checkedTools.has(tool.name)
                        const desc =
                          tool.description +
                          (experimental
                            ? '  (experimental — not yet implemented)'
                            : tool.status === 'inspection'
                              ? '  (read-only)'
                              : '')
                        return (
                          <button
                            key={tool.name}
                            title={desc}
                            disabled={experimental}
                            onClick={() => handleToggleTool(tool.name, !on)}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              padding: '3px 8px',
                              borderRadius: 12,
                              fontSize: 10.5,
                              fontWeight: 600,
                              cursor: experimental ? 'not-allowed' : 'pointer',
                              opacity: experimental ? 0.5 : 1,
                              border: `1px solid ${on ? 'var(--accent)' : 'var(--border)'}`,
                              background: on ? 'var(--accent-soft)' : 'var(--surface-2)',
                              color: on ? 'var(--accent)' : 'var(--text-2)',
                            }}
                          >
                            <span style={{ fontSize: 9 }}>{on ? '✓' : '+'}</span>
                            {tool.name}
                            {tool.status === 'inspection' && (
                              <span style={{ fontSize: 8, opacity: 0.7 }}>·ro</span>
                            )}
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })
          ) : (
            <div
              style={{
                padding: 12,
                borderRadius: 6,
                border: '1px dashed var(--border)',
                color: 'var(--text-2)',
                fontSize: 11,
                textAlign: 'center',
              }}
            >
              Loading tools…
            </div>
          )}

          {/* Enabled count chip */}
          <div style={{ marginTop: 8, marginBottom: 4 }}>
            <Chip>
              {enabledCount} / {totalCount} tools enabled
            </Chip>
          </div>
        </>
      )}

      <Divider />

      {/* ── Section 2: Simulation Constraints ── */}
      <SectionHeader
        title="Simulation Constraints"
        open={constraintsSectionOpen}
        onToggle={() => setConstraintsSectionOpen((o) => !o)}
      />

      {constraintsSectionOpen && (
        <div style={{ marginTop: 6 }}>
          <SliderRow
            label="Max Parts"
            value={constraints.max_parts}
            min={10}
            max={1000}
            step={10}
            onChange={(v) => handleConstraintChange({ max_parts: v })}
          />
          <SliderRow
            label="Max Joints"
            value={constraints.max_joints}
            min={5}
            max={500}
            step={5}
            onChange={(v) => handleConstraintChange({ max_joints: v })}
          />
          <SliderRow
            label="Energy Budget"
            value={constraints.energy_budget}
            min={100}
            max={5000}
            step={100}
            onChange={(v) => handleConstraintChange({ energy_budget: v })}
          />
          <SliderRow
            label="Max Attempts"
            value={constraints.max_attempts}
            min={1}
            max={200}
            step={1}
            onChange={(v) => handleConstraintChange({ max_attempts: v })}
          />
          <SliderRow
            label="Simulation (s)"
            value={constraints.simulation_duration_seconds}
            min={10}
            max={600}
            step={10}
            onChange={(v) => handleConstraintChange({ simulation_duration_seconds: v })}
          />
          <SliderRow
            label="Agent Turns / Attempt"
            value={constraints.agent_turns_per_attempt}
            min={1}
            max={8}
            step={1}
            onChange={(v) => handleConstraintChange({ agent_turns_per_attempt: v })}
          />
          <SliderRow
            label="Material Budget"
            value={constraints.material_budget}
            min={100}
            max={5000}
            step={100}
            onChange={(v) => handleConstraintChange({ material_budget: v })}
          />

          <SelectRow
            label="Collision Safety"
            value={constraints.collision_safety}
            options={[
              { value: 'strict', label: 'Strict' },
              { value: 'relaxed', label: 'Relaxed' },
            ]}
            onChange={(v) => handleConstraintChange({ collision_safety: v })}
          />
          <SelectRow
            label="World Bounds"
            value={constraints.world_bounds}
            options={[
              { value: 'enforced', label: 'Enforced' },
              { value: 'soft', label: 'Soft' },
              { value: 'disabled', label: 'Disabled' },
            ]}
            onChange={(v) => handleConstraintChange({ world_bounds: v })}
          />
          <ToggleRow
            label="Agent Repair Loop"
            value={constraints.repair_loop_enabled}
            onChange={(v) => handleConstraintChange({ repair_loop_enabled: v })}
          />
        </div>
      )}

      <Divider />

      {/* ── Section 3: Launch Summary + Launch ── */}
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '0.8px',
          textTransform: 'uppercase',
          color: 'var(--text-2)',
          marginBottom: 8,
        }}
      >
        Launch Summary
      </div>

      {/* Challenge preview image */}
      <WorldThumbnail preset={config.scenario?.preset} />

      {/* Summary rows */}
      <div
        style={{
          background: 'var(--surface-2)',
          borderRadius: 6,
          border: '1px solid var(--border)',
          padding: '10px 12px',
          marginBottom: 10,
        }}
      >
        <SummaryRow
          label="Challenge"
          value={config.project_name || config.scenario?.preset || '—'}
        />
        <SummaryRow
          label="World"
          value={config.world?.template ?? '—'}
        />
        <SummaryRow
          label="Agents"
          value={
            config.agents?.participants
              ? `${config.agents.participants.length} (${config.agents.mode ?? 'single'})`
              : '1 (Single)'
          }
        />
        <SummaryRow label="Engine" value={config.world?.engine ?? 'pymunk2d'} />
        <SummaryRow
          label="Tools Enabled"
          value={`${enabledCount} / ${totalCount}`}
        />
        <SummaryRow label="Constraints" value={constraintSummary} />
        <SummaryRow label="Est. Run Time" value={estRuntimeStr} />
      </div>

      {/* Outputs */}
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '0.8px',
          textTransform: 'uppercase',
          color: 'var(--text-2)',
          marginBottom: 6,
        }}
      >
        Outputs
      </div>
      <OutputsGrid outputs={outputs} onChange={handleOutputChange} />

      {/* Validation banner */}
      <div style={{ marginTop: 10 }}>
        <ValidationBanner result={validationResult} />
      </div>

      {/* Action buttons */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          marginTop: 10,
          flexWrap: 'wrap',
        }}
      >
        <button
          onClick={onValidateNow}
          style={{
            flex: 1,
            padding: '7px 12px',
            borderRadius: 5,
            border: '1px solid var(--border)',
            background: 'var(--surface-2)',
            color: 'var(--text-1)',
            fontSize: 11,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Validate Setup
        </button>
        <button
          onClick={onSavePreset}
          style={{
            flex: 1,
            padding: '7px 12px',
            borderRadius: 5,
            border: '1px solid var(--border)',
            background: 'var(--surface-2)',
            color: 'var(--text-1)',
            fontSize: 11,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Save Preset
        </button>
      </div>

      <button
        disabled={!isReady}
        onClick={() => {
          if (isReady) onLaunch()
        }}
        style={{
          marginTop: 8,
          width: '100%',
          padding: '10px 16px',
          borderRadius: 6,
          border: 'none',
          background: isReady ? 'var(--accent)' : 'var(--surface-2)',
          color: isReady ? '#fff' : 'var(--text-2)',
          fontSize: 13,
          fontWeight: 700,
          cursor: isReady ? 'pointer' : 'not-allowed',
          opacity: isReady ? 1 : 0.5,
          letterSpacing: '0.3px',
        }}
      >
        Launch Simulation ▶
      </button>
    </div>
  )
}

// ─── World thumbnail ──────────────────────────────────────────────────────────

const PRESET_IMG: Record<string, string> = {
  bridge_builder: '/presets/bridge-builder.png',
  crawl_challenge: '/presets/crawl-challenge.png',
  sorter: '/presets/sorter.png',
  tiny_city_preview: '/presets/tiny-city-preview.png',
  custom: '/presets/custom-scenario.png',
}

function WorldThumbnail({ preset }: { preset?: string }) {
  const src = (preset && PRESET_IMG[preset]) || PRESET_IMG.custom
  return (
    <div
      style={{
        height: 96,
        borderRadius: 8,
        background: 'var(--surface-2)',
        border: '1px solid var(--border)',
        marginBottom: 10,
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <img
        src={src}
        alt={preset ?? 'challenge'}
        loading="lazy"
        style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
      />
    </div>
  )
}

// ─── Outputs grid ─────────────────────────────────────────────────────────────

function OutputsGrid({
  outputs,
  onChange,
}: {
  outputs: Required<OutputsConfig>
  onChange: (patch: Partial<OutputsConfig>) => void
}) {
  const items: { key: keyof OutputsConfig; label: string; optional?: boolean }[] = [
    { key: 'replay_json', label: 'Replay (JSON)' },
    { key: 'scorecard_json', label: 'Scorecard (JSON)' },
    { key: 'trace_jsonl', label: 'Trace (JSONL)' },
    { key: 'markdown_report', label: 'Report (MD)', optional: true },
  ]

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '4px 8px',
        marginBottom: 10,
      }}
    >
      {items.map(({ key, label, optional }) => (
        <label
          key={key}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            cursor: 'pointer',
            fontSize: 11,
            color: optional ? 'var(--text-2)' : 'var(--text-1)',
          }}
        >
          <input
            type="checkbox"
            checked={!!outputs[key]}
            onChange={(e) => onChange({ [key]: e.target.checked } as Partial<OutputsConfig>)}
            style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
          />
          {label}
          {optional && (
            <span style={{ fontSize: 9, color: 'var(--text-2)', marginLeft: 2 }}>Optional</span>
          )}
        </label>
      ))}
      <span style={{ gridColumn: '1 / -1', fontSize: 9, color: 'var(--text-2)' }}>
        Screenshots and WebM capture are available from Studio after the run.
      </span>
    </div>
  )
}

export type { ToolsLaunchColumnProps }
