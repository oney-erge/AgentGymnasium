import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type {
  AgentConfig,
  AgentRole,
  AgentsConfig,
  BehaviorMode,
  CollaborationMode,
  LaunchConfig,
  LLMProvider,
  MemoryMode,
  ProviderMeta,
  ProviderStatus,
} from '../../api/types'

interface AgentLLMColumnProps {
  config: Partial<LaunchConfig>
  onConfigChange: (patch: Partial<LaunchConfig>) => void
}

// ─── Endpoints / defaults ──────────────────────────────────────────────────────

const LOCALDEPLOY_ENDPOINT = 'http://127.0.0.1:8000/v1'
const OPENAI_ENDPOINT = 'https://api.openai.com/v1'
const GENERIC_ENDPOINT = 'http://localhost:1234/v1'
const LOCALDEPLOY_REPO = 'https://github.com/oney-erge/LocalDeploy'

function endpointForProvider(provider: LLMProvider): string {
  if (provider === 'localdeploy') return LOCALDEPLOY_ENDPOINT
  if (provider === 'openai_compatible') return OPENAI_ENDPOINT
  return ''
}

const AGENT_COLORS = ['var(--agent-a)', 'var(--agent-b)', '#f59e0b', '#10b981']
const MAX_AGENTS = 4

function makeAgent(index: number): AgentConfig {
  const provider: LLMProvider = 'localdeploy'
  return {
    id: `agent_${String.fromCharCode(97 + index)}`,
    name: `Agent ${String.fromCharCode(65 + index)}`,
    role: 'builder',
    behavior_mode: 'engineer',
    provider,
    model: index === 0 ? 'qwen3_8b_ollama' : '',
    endpoint_url: endpointForProvider(provider),
    api_key: null,
    temperature: 0.2,
    max_attempts: 50,
    context_window: '8k',
    memory_mode: 'episodic',
    mutation_strategy: 'balanced',
  }
}

const ROLE_OPTIONS: { value: AgentRole; label: string }[] = [
  { value: 'builder', label: 'Builder' },
  { value: 'crawler', label: 'Crawler' },
  { value: 'structural_engineer', label: 'Structural Engineer' },
  { value: 'controller_designer', label: 'Controller Designer' },
  { value: 'world_planner', label: 'World Planner' },
  { value: 'critic', label: 'Critic' },
  { value: 'mutator', label: 'Mutator' },
]

const BEHAVIOR_OPTIONS: { value: BehaviorMode; label: string }[] = [
  { value: 'engineer', label: 'Engineer' },
  { value: 'mad_scientist', label: 'Mad Scientist' },
  { value: 'evolution', label: 'Evolution' },
  { value: 'minimalist', label: 'Minimalist' },
  { value: 'speed_demon', label: 'Speed Demon' },
  { value: 'builder', label: 'Builder' },
  { value: 'critic', label: 'Critic' },
]

const MEMORY_OPTIONS: { value: MemoryMode; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'episodic', label: 'Episodic' },
  { value: 'best_attempt_summary', label: 'Best Attempt Summary' },
]

const MULTI_MODES: { value: CollaborationMode; title: string; subtitle: string }[] = [
  { value: 'cooperative', title: 'Cooperative', subtitle: 'Build one shared design' },
  { value: 'competitive', title: 'Competitive', subtitle: 'Each optimizes alone' },
  { value: 'relay', title: 'Relay', subtitle: 'Pass scored lessons forward' },
  { value: 'sandbox', title: 'Sandbox', subtitle: 'One independent trial each' },
]

const MODEL_HINT: Record<LLMProvider, string> = {
  mock: 'No model — offline mock',
  localdeploy: 'Click Check, then pick a model',
  openai_compatible: 'Detected models only',
  manual: 'No model — manual',
}

// ─── Styles ────────────────────────────────────────────────────────────────────

function selectStyle(): React.CSSProperties {
  return {
    background: 'var(--surface-2)',
    color: 'var(--text-1)',
    border: '1px solid var(--border)',
    borderRadius: 4,
    padding: '4px 6px',
    fontSize: 11,
    cursor: 'pointer',
    width: '100%',
    boxSizing: 'border-box',
  }
}

function inputStyle(): React.CSSProperties {
  return {
    background: 'var(--surface-2)',
    color: 'var(--text-1)',
    border: '1px solid var(--border)',
    borderRadius: 4,
    padding: '4px 6px',
    fontSize: 11,
    width: '100%',
    boxSizing: 'border-box',
  }
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
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
      {children}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'block', marginBottom: 7 }}>
      <span style={{ fontSize: 10, color: 'var(--text-2)', display: 'block', marginBottom: 2 }}>
        {label}
      </span>
      {children}
    </label>
  )
}

function ModeCard({
  title,
  subtitle,
  selected,
  onSelect,
}: {
  title: string
  subtitle: string
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      onClick={onSelect}
      style={{
        textAlign: 'left',
        padding: 8,
        borderRadius: 8,
        border: selected ? '1px solid var(--accent)' : '1px solid var(--border)',
        background: selected ? 'var(--accent-soft)' : 'var(--surface-1)',
        cursor: 'pointer',
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-1)' }}>{title}</div>
      <div style={{ fontSize: 10, color: 'var(--text-2)', marginTop: 2 }}>{subtitle}</div>
    </button>
  )
}

// ─── Per-agent card ─────────────────────────────────────────────────────────────

function AgentCard({
  agent,
  color,
  providers,
  onChange,
  onDelete,
}: {
  agent: AgentConfig
  color: string
  providers: ProviderMeta[]
  onChange: (patch: Partial<AgentConfig>) => void
  onDelete?: () => void
}) {
  const [checking, setChecking] = useState(false)
  const [status, setStatus] = useState<ProviderStatus | null>(null)
  const [advanced, setAdvanced] = useState(false)

  const provider = (agent.provider ?? 'mock') as LLMProvider
  const meta = providers.find((p) => p.id === provider)
  const usesModel = provider !== 'mock' && provider !== 'manual'
  const requiresKey = meta?.requires_api_key ?? false
  const envKeyAvailable =
    provider === 'openai_compatible' && Boolean(meta?.env_api_key_available)
  const envKeyPreview = meta?.env_api_key_preview ?? '********'
  const hasEffectiveKey = Boolean(agent.api_key) || envKeyAvailable
  const models = status?.online ? (status.models ?? []) : []

  function setProvider(next: LLMProvider) {
    const patch: Partial<AgentConfig> = { provider: next }
    // Auto-fill the right endpoint and clear a stale mock/manual model id.
    const ep = endpointForProvider(next)
    if (ep) patch.endpoint_url = ep
    if (next === 'mock') patch.model = 'mock'
    else if (next === 'manual') patch.model = 'manual'
    else patch.model = ''
    setStatus(null)
    onChange(patch)
  }

  async function check() {
    setChecking(true)
    try {
      const res = await api.post<ProviderStatus>('/agents/test-connection', {
        provider,
        endpoint_url: agent.endpoint_url,
        api_key: agent.api_key,
      })
      setStatus(res)
      // First reachable model becomes the default if none is chosen yet.
      if (res.online && res.models && res.models.length > 0) {
        if (!agent.model || !res.models.includes(agent.model)) {
          onChange({ model: res.models[0] })
        }
      } else if (usesModel && agent.model) {
        onChange({ model: '' })
      }
    } catch (e) {
      setStatus({ online: false, detail: e instanceof Error ? e.message : 'Connection failed' })
      if (usesModel && agent.model) onChange({ model: '' })
    } finally {
      setChecking(false)
    }
  }

  // Auto-detect models when the provider/endpoint changes — no need to click.
  useEffect(() => {
    if (!usesModel || !agent.endpoint_url) return
    const t = setTimeout(() => {
      setStatus(null)
      void check()
    }, 600)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, agent.endpoint_url, agent.api_key, usesModel])

  return (
    <div
      style={{
        borderRadius: 8,
        border: '1px solid var(--border)',
        background: 'var(--surface-1)',
        marginBottom: 10,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '6px 10px',
          background: `color-mix(in srgb, ${color} 20%, transparent)`,
          borderBottom: `1px solid ${color}`,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
        <input
          value={agent.name ?? ''}
          onChange={(e) => onChange({ name: e.target.value })}
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            color: 'var(--text-1)',
            fontSize: 12,
            fontWeight: 700,
            padding: 0,
          }}
        />
        {onDelete && (
          <button
            onClick={onDelete}
            title="Remove agent"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-2)',
              cursor: 'pointer',
              fontSize: 14,
              lineHeight: 1,
            }}
          >
            ✕
          </button>
        )}
      </div>

      <div style={{ padding: 10 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <Field label="Provider">
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value as LLMProvider)}
              style={selectStyle()}
            >
              {providers.length === 0 && <option value={provider}>{provider}</option>}
              {providers.filter((p) => p.id !== 'manual').map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.env_api_key_available ? ' (env key)' : ''}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Model">
            {usesModel && models.length > 0 ? (
              <select
                value={agent.model && models.includes(agent.model) ? agent.model : ''}
                onChange={(e) => onChange({ model: e.target.value })}
                style={selectStyle()}
              >
                <option value="" disabled>
                  Select detected model…
                </option>
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            ) : (
              <input
                value={
                  usesModel
                    ? status?.online
                      ? 'Endpoint reachable, but no models were listed'
                      : status
                        ? 'Endpoint unavailable - no models selectable'
                        : 'Detecting available models...'
                    : MODEL_HINT[provider]
                }
                onChange={(e) => onChange({ model: e.target.value })}
                disabled
                placeholder={MODEL_HINT[provider]}
                style={inputStyle()}
              />
            )}
          </Field>
        </div>

        {usesModel && (
          <>
            <Field label="Endpoint URL">
              <input
                value={agent.endpoint_url ?? ''}
                onChange={(e) => onChange({ endpoint_url: e.target.value, model: '' })}
                placeholder={endpointForProvider(provider) || GENERIC_ENDPOINT}
                style={inputStyle()}
              />
            </Field>
            <Field
              label={
                requiresKey
                  ? envKeyAvailable && !agent.api_key
                    ? 'API Key - from env'
                    : 'API Key - required'
                  : 'API Key (optional)'
              }
            >
              <input
                type="password"
                value={agent.api_key ?? ''}
                onChange={(e) => onChange({ api_key: e.target.value || null })}
                placeholder={
                  envKeyAvailable && !agent.api_key
                    ? envKeyPreview
                    : requiresKey
                      ? 'sk-... (required)'
                      : 'optional'
                }
                style={{
                  ...inputStyle(),
                  borderColor:
                    requiresKey && !hasEffectiveKey ? 'var(--warn)' : 'var(--border)',
                }}
              />
            </Field>
            {requiresKey && envKeyAvailable && !agent.api_key && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  marginTop: -3,
                  marginBottom: 7,
                  fontSize: 10,
                  color: 'var(--ok)',
                }}
              >
                <span>Server OPENAI_API_KEY</span>
                <code
                  style={{
                    color: 'var(--text-1)',
                    background: 'var(--surface-2)',
                    border: '1px solid var(--border)',
                    borderRadius: 4,
                    padding: '1px 5px',
                    fontSize: 10,
                  }}
                >
                  {envKeyPreview}
                </code>
              </div>
            )}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <button
                onClick={check}
                disabled={checking}
                style={{
                  padding: '5px 10px',
                  borderRadius: 5,
                  border: '1px solid var(--border)',
                  background: 'var(--surface-2)',
                  color: 'var(--text-1)',
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: checking ? 'wait' : 'pointer',
                }}
              >
                {checking ? 'Detecting…' : 'Re-check'}
              </button>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  color: checking
                    ? 'var(--text-2)'
                    : status?.online
                      ? 'var(--ok)'
                      : status
                        ? 'var(--danger)'
                        : 'var(--text-2)',
                }}
              >
                {checking
                  ? '● detecting models…'
                  : status?.online
                    ? (status.models?.length ?? 0) > 0
                      ? `● ${status.models?.length ?? 0} models detected`
                      : '● endpoint reachable, no models listed'
                    : status
                      ? `● ${status.detail ?? 'offline'}`
                      : '● auto-detecting…'}
              </span>
            </div>

            {/* LocalDeploy setup guidance when it isn't reachable. */}
            {provider === 'localdeploy' && status && !status.online && (
              <div
                style={{
                  fontSize: 10,
                  lineHeight: 1.5,
                  color: 'var(--text-2)',
                  background: 'color-mix(in srgb, var(--warn) 10%, transparent)',
                  border: '1px solid var(--warn)',
                  borderRadius: 5,
                  padding: '6px 8px',
                  marginBottom: 4,
                }}
              >
                LocalDeploy isn't running at this URL. It's a free local model
                server — install &amp; start it from{' '}
                <a
                  href={LOCALDEPLOY_REPO}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--accent)' }}
                >
                  github.com/oney-erge/LocalDeploy
                </a>
                , then its models appear here automatically. Or switch the
                provider to OpenAI-Compatible or Mock.
              </div>
            )}
          </>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 4 }}>
          <Field label="Role">
            <select
              value={agent.role ?? 'builder'}
              onChange={(e) => onChange({ role: e.target.value as AgentRole })}
              style={selectStyle()}
            >
              {ROLE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Behavior">
            <select
              value={agent.behavior_mode ?? 'engineer'}
              onChange={(e) => onChange({ behavior_mode: e.target.value as BehaviorMode })}
              style={selectStyle()}
            >
              {BEHAVIOR_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <button
          onClick={() => setAdvanced((o) => !o)}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-2)',
            fontSize: 10,
            cursor: 'pointer',
            padding: '4px 0 0',
          }}
        >
          {advanced ? '▾' : '▸'} Tuning
        </button>
        {advanced && (
          <div style={{ marginTop: 4 }}>
            <Field label={`Temperature — ${(agent.temperature ?? 0.2).toFixed(2)}`}>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={agent.temperature ?? 0.2}
                onChange={(e) => onChange({ temperature: Number(e.target.value) })}
                style={{ width: '100%', accentColor: 'var(--accent)' }}
              />
            </Field>
            <Field label="Provider seed (optional)">
              <input type="number" value={agent.provider_seed ?? ''}
                onChange={(e) => onChange({ provider_seed: e.target.value === '' ? null : Number(e.target.value) })}
                style={{ width: '100%' }} />
            </Field>
            <Field label="Memory">
              <select
                value={agent.memory_mode ?? 'episodic'}
                onChange={(e) => onChange({ memory_mode: e.target.value as MemoryMode })}
                style={selectStyle()}
              >
                {MEMORY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export function AgentLLMColumn({ config, onConfigChange }: AgentLLMColumnProps) {
  const [providers, setProviders] = useState<ProviderMeta[]>([])

  useEffect(() => {
    api
      .get<ProviderMeta[]>('/agents/providers')
      .then(setProviders)
      .catch(() => {})
  }, [])

  const agents: AgentsConfig = config.agents ?? { mode: 'single', participants: [] }
  const mode: CollaborationMode = agents.mode ?? 'single'
  const isMulti = mode !== 'single'
  const participants: AgentConfig[] =
    agents.participants && agents.participants.length > 0 ? agents.participants : [makeAgent(0)]

  function emit(nextMode: CollaborationMode, next: AgentConfig[]) {
    onConfigChange({ agents: { mode: nextMode, participants: next } } as Partial<LaunchConfig>)
    // Mirror agent A's connection into llm_connection for fallback/validation.
    const a = next[0]
    if (a) {
      onConfigChange({
        llm_connection: { endpoint_url: a.endpoint_url ?? '', api_key: a.api_key ?? null },
      } as Partial<LaunchConfig>)
    }
  }

  function setSingle() {
    emit('single', [participants[0] ?? makeAgent(0)])
  }
  function setMulti() {
    const next = [...participants]
    if (next.length < 2) next.push(makeAgent(1))
    emit(mode === 'single' ? 'cooperative' : mode, next)
  }
  function selectMode(m: CollaborationMode) {
    const next = [...participants]
    if (next.length < 2) next.push(makeAgent(1))
    emit(m, next)
  }
  function changeAgent(i: number, patch: Partial<AgentConfig>) {
    emit(mode, participants.map((p, idx) => (idx === i ? { ...p, ...patch } : p)))
  }
  function addAgent() {
    if (participants.length >= MAX_AGENTS) return
    emit(mode, [...participants, makeAgent(participants.length)])
  }
  function removeAgent(i: number) {
    const next = participants.filter((_, idx) => idx !== i)
    emit(next.length <= 1 ? 'single' : mode, next.length ? next : [makeAgent(0)])
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <SectionLabel>Collaboration Mode</SectionLabel>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          border: '1px solid var(--border)',
          borderRadius: 6,
          overflow: 'hidden',
          marginBottom: 10,
        }}
      >
        <button
          onClick={setSingle}
          style={{
            padding: '7px 10px',
            border: 'none',
            background: !isMulti ? 'var(--accent)' : 'var(--surface-2)',
            color: !isMulti ? '#fff' : 'var(--text-2)',
            fontSize: 11,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Single-Agent
        </button>
        <button
          onClick={setMulti}
          style={{
            padding: '7px 10px',
            border: 'none',
            borderLeft: '1px solid var(--border)',
            background: isMulti ? 'var(--accent)' : 'var(--surface-2)',
            color: isMulti ? '#fff' : 'var(--text-2)',
            fontSize: 11,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Multi-Agent
        </button>
      </div>

      {isMulti && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
          {MULTI_MODES.map((m) => (
            <ModeCard
              key={m.value}
              title={m.title}
              subtitle={m.subtitle}
              selected={mode === m.value}
              onSelect={() => selectMode(m.value)}
            />
          ))}
        </div>
      )}

      <SectionLabel>Agents ({isMulti ? participants.length : 1})</SectionLabel>
      {(isMulti ? participants : participants.slice(0, 1)).map((agent, i) => (
        <AgentCard
          key={i}
          agent={agent}
          color={AGENT_COLORS[i % AGENT_COLORS.length]}
          providers={providers}
          onChange={(patch) => changeAgent(i, patch)}
          onDelete={isMulti && participants.length > 1 ? () => removeAgent(i) : undefined}
        />
      ))}

      {isMulti && participants.length < MAX_AGENTS && (
        <button
          onClick={addAgent}
          style={{
            padding: '8px',
            borderRadius: 6,
            border: '1px dashed var(--border)',
            background: 'transparent',
            color: 'var(--text-2)',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          + Add Agent
        </button>
      )}
    </div>
  )
}

export type { AgentLLMColumnProps }
