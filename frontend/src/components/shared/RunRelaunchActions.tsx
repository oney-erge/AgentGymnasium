import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../../api/client'
import type {
  AgentConfig,
  LaunchConfig,
  RelaunchRunResponse,
  RunConfigResponse,
} from '../../api/types'

type RerunValues = {
  model: string
  temperature: string
  seed: string
  attempts: string
}

interface RunRelaunchActionsProps {
  runId?: string | null
  compact?: boolean
  align?: 'left' | 'right'
  disabled?: boolean
}

function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: unknown } | null
    if (typeof body?.detail === 'string') return body.detail
    if (
      body?.detail &&
      typeof body.detail === 'object' &&
      'missing' in body.detail &&
      Array.isArray((body.detail as { missing?: unknown }).missing)
    ) {
      return ((body.detail as { missing: string[] }).missing).join('; ')
    }
    return `Request failed (${err.status})`
  }
  return err instanceof Error ? err.message : 'Request failed'
}

function firstAgent(config: LaunchConfig): AgentConfig | null {
  return config.agents?.participants?.[0] ?? null
}

function valuesFromConfig(config: LaunchConfig): RerunValues {
  const agent = firstAgent(config)
  return {
    model: agent?.model ?? '',
    temperature: String(agent?.temperature ?? 0.2),
    seed: (agent?.provider_seed ?? config.world?.seed) == null
      ? ''
      : String(agent?.provider_seed ?? config.world.seed),
    attempts: String(config.constraints?.max_attempts ?? 50),
  }
}

function finiteNumber(value: string, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export function RunRelaunchActions({
  runId,
  compact = false,
  align = 'right',
  disabled = false,
}: RunRelaunchActionsProps) {
  const navigate = useNavigate()
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadingConfig, setLoadingConfig] = useState(false)
  const [open, setOpen] = useState(false)
  const [config, setConfig] = useState<LaunchConfig | null>(null)
  const [values, setValues] = useState<RerunValues>({
    model: '',
    temperature: '0.2',
    seed: '',
    attempts: '50',
  })
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      const node = rootRef.current
      if (node && !node.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('pointerdown', onPointerDown)
    return () => window.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  async function launchRerun(patch?: Record<string, unknown>) {
    if (!runId || busy) return
    setBusy(true)
    setError(null)
    try {
      const response = await api.post<RelaunchRunResponse>(
        `/runs/${runId}/relaunch`,
        patch ? { patch } : {},
      )
      navigate(`/studio/${response.run_id}`)
    } catch (err) {
      setError(describeApiError(err))
    } finally {
      setBusy(false)
    }
  }

  async function loadConfig(): Promise<LaunchConfig | null> {
    if (!runId) return null
    if (config) return config
    setLoadingConfig(true)
    setError(null)
    try {
      const response = await api.get<RunConfigResponse>(`/runs/${runId}/config`)
      setConfig(response.config)
      setValues(valuesFromConfig(response.config))
      return response.config
    } catch (err) {
      setError(describeApiError(err))
      return null
    } finally {
      setLoadingConfig(false)
    }
  }

  async function openChanges(event: React.MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    setOpen((current) => !current)
    if (!open) await loadConfig()
  }

  function duplicateEdit(event: React.MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    if (!runId) return
    navigate(`/setup?configRunId=${encodeURIComponent(runId)}`)
  }

  async function submitChanges(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    event.stopPropagation()
    const base = config ?? (await loadConfig())
    if (!base) return

    const seed = values.seed.trim() === '' ? null : Math.trunc(finiteNumber(values.seed, 0))
    const patch: Record<string, unknown> = {
      constraints: {
        max_attempts: Math.max(1, Math.trunc(finiteNumber(values.attempts, 1))),
      },
    }

    const participants = (base.agents?.participants ?? []).map((agent) => ({ ...agent }))
    // Clearing a seed also clears the legacy fallback. Preserve its existing
    // effect on other agents and on the appearance of older saved runs.
    if (seed === null && base.world.seed != null) {
      for (const agent of participants.slice(1)) {
        agent.provider_seed ??= base.world.seed
      }
      patch.world = {
        seed: null,
        visual_seed: base.world.visual_seed ?? base.world.seed,
      }
    }
    if (participants[0]) {
      participants[0] = {
        ...participants[0],
        model: values.model.trim() || participants[0].model,
        temperature: Math.max(0, Math.min(1, finiteNumber(values.temperature, 0.2))),
        provider_seed: seed,
      }
      patch.agents = { participants }
    }

    await launchRerun(patch)
  }

  const off = disabled || !runId || busy

  return (
    <div
      ref={rootRef}
      onClick={(e) => e.stopPropagation()}
      style={{ position: 'relative', display: 'inline-flex', gap: 6, alignItems: 'center' }}
    >
      <button
        onClick={(e) => {
          e.stopPropagation()
          void launchRerun()
        }}
        disabled={off}
        style={buttonStyle('primary', compact, off)}
      >
        {busy ? 'Starting…' : 'Run again'}
      </button>
      <button onClick={duplicateEdit} disabled={off} style={buttonStyle('secondary', compact, off)}>
        Duplicate & edit
      </button>
      <button onClick={openChanges} disabled={off} style={buttonStyle('secondary', compact, off)}>
        Re-run with changes
      </button>

      {open && (
        <form
          onSubmit={(e) => void submitChanges(e)}
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            left: align === 'left' ? 0 : undefined,
            right: align === 'right' ? 0 : undefined,
            width: 260,
            padding: 12,
            borderRadius: 8,
            border: '1px solid var(--border)',
            background: 'var(--surface-1)',
            boxShadow: '0 18px 42px rgba(0,0,0,0.42)',
            zIndex: 30,
            display: 'grid',
            gap: 8,
          }}
        >
          <Field label="Model">
            <input
              value={values.model}
              onChange={(e) => setValues((v) => ({ ...v, model: e.target.value }))}
              disabled={loadingConfig}
              style={inputStyle()}
            />
          </Field>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <Field label="Temperature">
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={values.temperature}
                onChange={(e) => setValues((v) => ({ ...v, temperature: e.target.value }))}
                disabled={loadingConfig}
                style={inputStyle()}
              />
            </Field>
            <Field label="Model seed (first agent)">
              <input
                type="number"
                value={values.seed}
                onChange={(e) => setValues((v) => ({ ...v, seed: e.target.value }))}
                disabled={loadingConfig}
                style={inputStyle()}
              />
            </Field>
          </div>
          <Field label="Attempts">
            <input
              type="number"
              min={1}
              max={500}
              value={values.attempts}
              onChange={(e) => setValues((v) => ({ ...v, attempts: e.target.value }))}
              disabled={loadingConfig}
              style={inputStyle()}
            />
          </Field>
          {error && <div style={{ fontSize: 11, color: 'var(--danger)' }}>{error}</div>}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button
              type="button"
              onClick={() => setOpen(false)}
              style={buttonStyle('secondary', false, false)}
            >
              Cancel
            </button>
            <button type="submit" disabled={busy || loadingConfig} style={buttonStyle('primary', false, busy)}>
              Launch
            </button>
          </div>
        </form>
      )}
      {!open && error && !compact && (
        <span style={{ fontSize: 11, color: 'var(--danger)', maxWidth: 220 }}>{error}</span>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'grid', gap: 3 }}>
      <span style={{ fontSize: 10, color: 'var(--text-2)' }}>{label}</span>
      {children}
    </label>
  )
}

function buttonStyle(
  tone: 'primary' | 'secondary',
  compact: boolean,
  disabled: boolean,
): React.CSSProperties {
  const primary = tone === 'primary'
  return {
    padding: compact ? '4px 8px' : '6px 10px',
    borderRadius: 6,
    border: primary ? 'none' : '1px solid var(--border)',
    background: primary ? 'var(--accent)' : 'var(--surface-2)',
    color: primary ? 'var(--on-accent)' : 'var(--text-1)',
    fontSize: compact ? 11 : 12,
    fontWeight: 700,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.55 : 1,
    whiteSpace: 'nowrap',
  }
}

function inputStyle(): React.CSSProperties {
  return {
    width: '100%',
    padding: '5px 7px',
    borderRadius: 5,
    border: '1px solid var(--border)',
    background: 'var(--surface-2)',
    color: 'var(--text-1)',
    fontSize: 12,
  }
}
