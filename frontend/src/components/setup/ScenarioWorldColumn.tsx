import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type {
  LaunchConfig,
  PhysicsEngine,
  ScenarioPreset,
  Terrain,
  VisualStyle,
  WorldTemplate,
} from '../../api/types'

// ─── Props ────────────────────────────────────────────────────────────────────

interface ScenarioWorldColumnProps {
  config: Partial<LaunchConfig>
  onConfigChange: (patch: Partial<LaunchConfig>) => void
}

// ─── Custom scenario card (not from API) ──────────────────────────────────────

const CUSTOM_PRESET: ScenarioPreset = {
  id: 'custom',
  name: 'Custom Scenario',
  tagline: 'Start from scratch.',
  tags: ['Custom'],
  objective: '',
  reward: '',
  default_world: '',
  required_tools: [],
  recommended_tools: [],
}

// Real in-engine screenshots (side-view renderer), not concept art — what you
// see here is what the Studio actually renders for a mock attempt at this
// challenge, so the preview never oversells the result.
const PRESET_IMAGES: Record<string, { src: string; alt: string }> = {
  bridge_builder: {
    src: '/presets/bridge-builder.png',
    alt: 'Side-view render: a crate on a ramp beside a gap, with a goal flag on the far platform',
  },
  crawl_challenge: {
    src: '/presets/crawl-challenge.png',
    alt: 'Side-view render: a creature seed body on a hill path with a goal flag ahead',
  },
  sorter: {
    src: '/presets/sorter.png',
    alt: 'Side-view render: colored balls beside a sorting table',
  },
  tiny_city_preview: {
    src: '/presets/tiny-city-preview.png',
    alt: 'Side-view render: a small city block with houses, towers, a road, and trees',
  },
  city_builder: {
    src: '/presets/city-builder.png',
    alt: 'Isometric render: houses, a tower, a shop, a road with sidewalks, and a park',
  },
  custom: {
    src: '/presets/custom-scenario.png',
    alt: 'Side-view render: an open flat arena for freeform building',
  },
}

// ─── Shared sub-components (match ToolsLaunchColumn styling) ───────────────────

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
  return <div style={{ borderTop: '1px solid var(--border)', margin: '12px 0' }} />
}

function SmallChip({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '1px 6px',
        borderRadius: 8,
        background: 'var(--surface-2)',
        border: '1px solid var(--border)',
        color: 'var(--text-2)',
        fontSize: 9,
        fontWeight: 600,
      }}
    >
      {children}
    </span>
  )
}

function selectStyle(): React.CSSProperties {
  return {
    background: 'var(--surface-2)',
    color: 'var(--text-1)',
    border: '1px solid var(--border)',
    borderRadius: 4,
    padding: '3px 6px',
    fontSize: 11,
    cursor: 'pointer',
  }
}

function inputStyle(): React.CSSProperties {
  return {
    background: 'var(--surface-2)',
    color: 'var(--text-1)',
    border: '1px solid var(--border)',
    borderRadius: 4,
    padding: '3px 6px',
    fontSize: 11,
    width: '100%',
    boxSizing: 'border-box',
  }
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
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
      {children}
    </div>
  )
}

// ─── Challenge card ───────────────────────────────────────────────────────────

function ChallengeCard({
  preset,
  selected,
  onSelect,
}: {
  preset: ScenarioPreset
  selected: boolean
  onSelect: () => void
}) {
  const image = PRESET_IMAGES[preset.id] ?? PRESET_IMAGES.custom

  return (
    <button
      onClick={onSelect}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        width: '100%',
        textAlign: 'left',
        padding: 10,
        marginBottom: 8,
        borderRadius: 8,
        border: selected ? '1px solid var(--accent)' : '1px solid var(--border)',
        background: selected ? 'var(--accent-soft)' : 'var(--surface-1)',
        boxShadow: selected ? '0 0 0 1px var(--accent)' : 'none',
        cursor: 'pointer',
      }}
    >
      <div
        style={{
          width: 76,
          height: 64,
          flexShrink: 0,
          borderRadius: 6,
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          overflow: 'hidden',
          boxShadow: '0 8px 18px rgba(0, 0, 0, 0.22)',
        }}
      >
        <img
          src={image.src}
          alt={image.alt}
          loading="lazy"
          style={{
            width: '100%',
            height: '100%',
            display: 'block',
            objectFit: 'cover',
          }}
        />
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-1)' }}>{preset.name}</div>
        <div style={{ fontSize: 10, color: 'var(--text-2)', marginTop: 2 }}>{preset.tagline}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
          {preset.tags.map((tag) => (
            <SmallChip key={tag}>{tag}</SmallChip>
          ))}
        </div>
      </div>
    </button>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ScenarioWorldColumn({ config, onConfigChange }: ScenarioWorldColumnProps) {
  const [presets, setPresets] = useState<ScenarioPreset[]>([])
  const [worlds, setWorlds] = useState<WorldTemplate[]>([])
  const [advancedOpen, setAdvancedOpen] = useState(false)

  // ── Fetch presets + worlds on mount ──
  useEffect(() => {
    api
      .get<ScenarioPreset[]>('/presets')
      .then(setPresets)
      .catch(() => {
        /* backend may be down in tests */
      })
    api
      .get<WorldTemplate[]>('/worlds')
      .then(setWorlds)
      .catch(() => {
        /* backend may be down in tests */
      })
  }, [])

  const scenario = config.scenario
  const world = config.world

  const selectedPresetId = scenario?.preset ?? ''
  const selectedWorldId = world?.template ?? ''
  const projectName = config.project_name ?? ''

  useEffect(() => {
    const selected = presets.find((preset) => preset.id === selectedPresetId)
    if (!selected) return
    if (
      !projectName ||
      projectName === 'AgentGymnasium Run' ||
      projectName === 'Agentarium Run' || // former default name, possibly saved in old configs
      projectName === 'Bridge Builder Lab'
    ) {
      onConfigChange({ project_name: selected.name } as Partial<LaunchConfig>)
    }
  }, [onConfigChange, presets, projectName, selectedPresetId])

  // Cards shown in the list: API presets minus the classic side-view city
  // (folded into City Building as the "City View" selector below, so there
  // aren't two confusing city cards) + the custom card.
  const allCards: ScenarioPreset[] = [
    ...presets.filter((p) => p.id !== 'tiny_city_preview'),
    CUSTOM_PRESET,
  ]

  // Every preset, INCLUDING ones without their own card — needed to resolve
  // the active selection (tiny_city_preview has no card but can still be
  // scenario.preset) for reward_options/description lookups below.
  const allPresets: ScenarioPreset[] = [...presets, CUSTOM_PRESET]
  const selectedPreset = allPresets.find((p) => p.id === selectedPresetId)
  const selectedPresetOptions = selectedPreset?.reward_options ?? []
  const selectedRewardOptionDescription = selectedPresetOptions.find(
    (o) => o.value === (scenario?.reward ?? selectedPresetOptions[0]?.value),
  )?.description

  // City View: the classic 2D side-view city is a SETTING within City
  // Building, not its own card — this toggles between the two real presets.
  const cityBuilderPreset = presets.find((p) => p.id === 'city_builder')
  const tinyCityPreset = presets.find((p) => p.id === 'tiny_city_preview')
  const isCityFamily = selectedPresetId === 'city_builder' || selectedPresetId === 'tiny_city_preview'

  // ── Apply a world template's dependent fields ──
  function worldFieldsFor(worldId: string): Partial<LaunchConfig['world']> {
    const w = worlds.find((x) => x.id === worldId)
    if (!w) return { template: worldId }
    return {
      template: w.id,
      terrain: w.terrain,
      map_size: w.map_size,
      gravity: w.gravity,
      active_physics_zones: w.active_physics_zones,
      // The template dictates its engine too (like terrain/map_size) — a
      // citysim (isometric city) template must not silently launch on the
      // physics engine, which is what would happen if this stayed pymunk2d.
      engine: w.engine ?? 'pymunk2d',
    }
  }

  // ── Selecting a challenge preset auto-fills scenario, world, and required tools ──
  function handleSelectPreset(preset: ScenarioPreset) {
    // Merge the preset's required tools into whatever is already enabled so the
    // challenge is launchable without wiping the user's (or default-on) tools.
    const enabled = Array.from(
      new Set([...(config.tools?.enabled ?? []), ...preset.required_tools]),
    )
    onConfigChange({
      project_name: preset.name,
      scenario: {
        preset: preset.id,
        objective: preset.objective,
        reward: preset.reward,
      },
      world: worldFieldsFor(preset.default_world),
      tools: { enabled },
    } as Partial<LaunchConfig>)
  }

  // ── Picking a City Goal (or any challenge with reward_options) just
  // changes scenario.reward — same challenge, same build, different scoring.
  function handleSelectRewardOption(reward: string) {
    onConfigChange({
      scenario: { preset: selectedPresetId, objective: scenario?.objective ?? '', reward },
    } as Partial<LaunchConfig>)
  }

  // ── City View swaps the whole preset (isometric city_builder <-> classic
  // side-view tiny_city_preview) — a different world/engine/reward, not just
  // a reward, so it reuses handleSelectPreset rather than patching one field.
  function handleSelectCityView(view: 'isometric' | 'classic') {
    const target = view === 'isometric' ? cityBuilderPreset : tinyCityPreset
    if (target) handleSelectPreset(target)
  }

  // ── Changing world template updates dependent fields ──
  function handleSelectWorld(worldId: string) {
    onConfigChange({ world: worldFieldsFor(worldId) } as Partial<LaunchConfig>)
  }

  function handleWorldField(patch: Partial<LaunchConfig['world']>) {
    onConfigChange({
      world: { template: selectedWorldId, ...patch },
    } as Partial<LaunchConfig>)
  }

  const selectedWorld = worlds.find((w) => w.id === selectedWorldId)
  const mapSize = world?.map_size ?? selectedWorld?.map_size

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {/* ── Section 1: Challenge Preset ── */}
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
        Challenge Preset
      </div>

      {/* Challenge cards */}
      <div>
        {allCards.map((preset) => (
          <ChallengeCard
            key={preset.id}
            preset={preset}
            selected={preset.id === selectedPresetId}
            onSelect={() => handleSelectPreset(preset)}
          />
        ))}
      </div>

      {/* City View — the classic 2D side-view city is a setting here, not a
          separate card. Only shown once City Building is selected either way. */}
      {isCityFamily && cityBuilderPreset && tinyCityPreset && (
        <div style={{ marginTop: 4, marginBottom: 4 }}>
          <FieldRow label="City View">
            <div style={{ display: 'flex', gap: 6 }}>
              {(['isometric', 'classic'] as const).map((view) => {
                const active =
                  view === 'isometric'
                    ? selectedPresetId === 'city_builder'
                    : selectedPresetId === 'tiny_city_preview'
                return (
                  <button
                    key={view}
                    onClick={() => handleSelectCityView(view)}
                    style={{
                      padding: '4px 10px',
                      borderRadius: 6,
                      fontSize: 11,
                      fontWeight: 600,
                      cursor: 'pointer',
                      border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
                      background: active ? 'var(--accent-soft)' : 'var(--surface-2)',
                      color: active ? 'var(--accent)' : 'var(--text-2)',
                    }}
                  >
                    {view === 'isometric' ? 'Isometric' : 'Classic Side View'}
                  </button>
                )
              })}
            </div>
          </FieldRow>
        </div>
      )}

      {/* City Goal — only shown for a challenge with alternate reward_options
          (today: City Builder's Balanced/Boomtown/Budget/Zoned/Green goals).
          Selecting one just changes scenario.reward; it's the same build. */}
      {selectedPresetOptions.length > 0 && (
        <div style={{ marginTop: 4, marginBottom: 4 }}>
          <FieldRow label="City Goal">
            <select
              value={scenario?.reward ?? selectedPresetOptions[0].value}
              onChange={(e) => handleSelectRewardOption(e.target.value)}
              style={selectStyle()}
            >
              {selectedPresetOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </FieldRow>
          {selectedRewardOptionDescription && (
            <div style={{ fontSize: 10, color: 'var(--text-2)', marginTop: -4, marginBottom: 4 }}>
              {selectedRewardOptionDescription}
            </div>
          )}
        </div>
      )}

      <Divider />

      {/* ── Section 2: World Settings ── */}
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '0.8px',
          textTransform: 'uppercase',
          color: 'var(--text-2)',
          marginBottom: 10,
        }}
      >
        World Settings
      </div>

      <FieldRow label="World Template">
        <select
          value={selectedWorldId}
          onChange={(e) => handleSelectWorld(e.target.value)}
          style={selectStyle()}
        >
          {worlds.length === 0 && selectedWorldId && (
            <option value={selectedWorldId}>{selectedWorldId}</option>
          )}
          {worlds.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow label="Terrain">
        <select
          value={world?.terrain ?? 'grassland'}
          onChange={(e) => handleWorldField({ terrain: e.target.value as Terrain })}
          style={selectStyle()}
        >
          <option value="grassland">Grassland</option>
          <option value="desert">Desert</option>
          <option value="factory">Factory</option>
          <option value="city">City</option>
          <option value="cave">Cave</option>
        </select>
      </FieldRow>

      {/* Physics Engine — radio-style */}
      <FieldRow label="Physics Engine">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
            <input
              type="radio"
              name="physics-engine"
              checked={(world?.engine ?? 'pymunk2d') === 'pymunk2d'}
              onChange={() => handleWorldField({ engine: 'pymunk2d' as PhysicsEngine })}
              style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
            />
            <span style={{ fontSize: 11, color: 'var(--text-1)' }}>Pymunk 2D (Stable)</span>
          </label>
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              cursor: 'not-allowed',
              opacity: 0.6,
            }}
          >
            <input
              type="radio"
              name="physics-engine"
              disabled
              checked={world?.engine === 'pybullet3d'}
              readOnly
              style={{ cursor: 'not-allowed' }}
            />
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>PyBullet 3D (Beta)</span>
            <span
              style={{
                fontSize: 9,
                fontWeight: 600,
                padding: '1px 6px',
                borderRadius: 8,
                background: 'color-mix(in srgb, var(--warn) 15%, transparent)',
                border: '1px solid var(--warn)',
                color: 'var(--warn)',
              }}
            >
              Coming Soon
            </span>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
            <input
              type="radio"
              name="physics-engine"
              checked={world?.engine === 'citysim'}
              onChange={() => handleWorldField({ engine: 'citysim' as PhysicsEngine })}
              style={{ accentColor: 'var(--accent)', cursor: 'pointer' }}
            />
            <span style={{ fontSize: 11, color: 'var(--text-1)' }}>
              City Sim (Isometric layout, no physics)
            </span>
          </label>
        </div>
      </FieldRow>

      <FieldRow label="Gravity (m/s²)">
        <input
          type="number"
          step={0.01}
          value={world?.gravity ?? -9.81}
          onChange={(e) => handleWorldField({ gravity: Number(e.target.value) })}
          style={inputStyle()}
        />
      </FieldRow>

      <FieldRow label="Map Size">
        <span style={{ fontSize: 11, color: 'var(--text-1)' }}>
          {mapSize ? `${mapSize[0]} x ${mapSize[1]} tiles` : '—'}
        </span>
      </FieldRow>

      <FieldRow label="Physics Zones">
        <input
          type="number"
          min={0}
          value={world?.active_physics_zones ?? 0}
          onChange={(e) => handleWorldField({ active_physics_zones: Number(e.target.value) })}
          style={inputStyle()}
        />
      </FieldRow>

      <FieldRow label="Visual Style">
        <select
          value={world?.visual_style ?? 'realistic'}
          onChange={(e) => handleWorldField({ visual_style: e.target.value as VisualStyle })}
          style={selectStyle()}
        >
          <option value="realistic">Realistic</option>
          <option value="playful">Playful</option>
          <option value="blueprint">Blueprint</option>
          <option value="neon_lab">Neon Lab</option>
        </select>
      </FieldRow>

      <Divider />

      {/* ── Section 3: Advanced Settings (collapsible) ── */}
      <SectionHeader
        title="Advanced Settings · Optional"
        open={advancedOpen}
        onToggle={() => setAdvancedOpen((o) => !o)}
      />

      {advancedOpen && (
        <div style={{ marginTop: 6 }}>
          <FieldRow label="Seed">
            <input
              type="number"
              value={world?.seed ?? ''}
              onChange={(e) =>
                handleWorldField({
                  seed: e.target.value === '' ? null : Number(e.target.value),
                })
              }
              style={inputStyle()}
            />
          </FieldRow>
          <div style={{ fontSize: 10, color: 'var(--text-2)', marginTop: 4, lineHeight: 1.4 }}>
            Seed varies LLM sampling only — the physics engine is already
            deterministic, so replays are exact regardless of seed.
          </div>
        </div>
      )}
    </div>
  )
}

export type { ScenarioWorldColumnProps }
