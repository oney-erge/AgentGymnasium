import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type {
  LaunchConfig,
  LaunchResponse,
  RunConfigResponse,
  ValidationResult,
  WorkspaceConfigResponse,
  WorkspaceConfigStatus,
} from '../api/types'
import { AgentLLMColumn } from '../components/setup/AgentLLMColumn'
import { ScenarioWorldColumn } from '../components/setup/ScenarioWorldColumn'
import { ToolsLaunchColumn } from '../components/setup/ToolsLaunchColumn'
import { TopBar } from '../components/shared/TopBar'
import { useMediaQuery } from '../hooks/useMediaQuery'

// Sensible defaults for the full config
const DEFAULT_CONFIG: Partial<LaunchConfig> = {
  scenario: { preset: 'bridge_builder', objective: '', reward: '' },
  world: { template: 'island_cliff_small', engine: 'pymunk2d' },
  agents: {
    mode: 'single',
    participants: [
      {
        id: 'agent_a',
        name: 'Agent A',
        role: 'builder',
        behavior_mode: 'engineer',
        provider: 'localdeploy',
        model: 'qwen3_8b_ollama',
        endpoint_url: 'http://127.0.0.1:8000/v1',
        temperature: 0.2,
        max_attempts: 50,
        context_window: '8k',
        memory_mode: 'none',
        mutation_strategy: 'balanced',
      },
    ],
  },
  llm_connection: { endpoint_url: 'http://127.0.0.1:8000/v1' },
  tools: { enabled: [] },
  constraints: {
    max_parts: 300,
    max_joints: 120,
    energy_budget: 1200,
    max_attempts: 50,
    simulation_duration_seconds: 180,
    agent_turns_per_attempt: 3,
    material_budget: 2000,
    collision_safety: 'strict',
    world_bounds: 'enforced',
    repair_loop_enabled: true,
  },
  outputs: {
    replay_json: true,
    scorecard_json: true,
    trace_jsonl: true,
    markdown_report: false,
    screenshot: false,
    video_capture: false,
  },
}

const WORKSPACE_SYNC_POLL_MS = 1200
const WORKSPACE_AUTOSAVE_MS = 650

/** Turn a launch failure into a human message, pulling the backend's 422
 *  validation detail (state + missing list) out of an ApiError when present. */
function describeLaunchError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: { missing?: string[]; state?: string } } | null
    const detail = body?.detail
    if (detail?.missing && detail.missing.length > 0) {
      return `Launch blocked: ${detail.missing.join('; ')}`
    }
    if (err.status === 0 || err.status >= 500) {
      return 'Launch failed — the server is unreachable. Is it running?'
    }
    return `Launch failed (${err.status}). Check your configuration and try again.`
  }
  return 'Launch failed — the server is unreachable. Is it running?'
}

export function SetupScreen() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const configRunId = searchParams.get('configRunId')
  const [config, setConfig] = useState<Partial<LaunchConfig>>(DEFAULT_CONFIG)
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null)
  const [launching, setLaunching] = useState(false)
  // null = unknown (not yet checked); true/false = last server call reachable.
  const [backendReachable, setBackendReachable] = useState<boolean | null>(null)
  const [launchError, setLaunchError] = useState<string | null>(null)
  const [savePresetOpen, setSavePresetOpen] = useState(false)
  const [presetName, setPresetName] = useState('')
  const [presetMsg, setPresetMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [savingPreset, setSavingPreset] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const workspaceSaveRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const workspaceLoadedRef = useRef(false)
  const workspaceSavingRef = useRef(false)
  const lastWorkspaceMtimeRef = useRef<number | null>(null)
  const lastWorkspaceJsonRef = useRef('')
  const [workspacePath, setWorkspacePath] = useState('runs/workspace_config.json')
  const [workspaceSyncMsg, setWorkspaceSyncMsg] = useState('Loading workspace config…')
  const [workspaceSyncState, setWorkspaceSyncState] = useState<
    'loading' | 'saved' | 'saving' | 'external' | 'error'
  >('loading')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // Responsive breakpoints: 3 cols → 2 cols (≤1080px) → 1 col (≤720px).
  const twoCol = useMediaQuery('(max-width: 1080px)')
  const oneCol = useMediaQuery('(max-width: 720px)')
  const stacked = twoCol || oneCol
  const workspaceSyncColor =
    workspaceSyncState === 'error'
      ? 'var(--danger)'
      : workspaceSyncState === 'saving'
        ? 'var(--warn)'
        : workspaceSyncState === 'external'
          ? 'var(--accent)'
          : 'var(--ok)'

  // Merged config change handler
  const handleConfigChange = useCallback((patch: Partial<LaunchConfig>) => {
    setConfig((prev) => ({
      ...prev,
      ...patch,
      // Deep-merge nested objects so partial patches don't clobber sibling keys
      ...(patch.scenario !== undefined
        ? { scenario: { ...prev.scenario, ...patch.scenario } }
        : {}),
      ...(patch.world !== undefined
        ? { world: { ...prev.world, ...patch.world } }
        : {}),
      ...(patch.tools !== undefined
        ? { tools: { ...prev.tools, ...patch.tools } }
        : {}),
      ...(patch.constraints !== undefined
        ? { constraints: { ...prev.constraints, ...patch.constraints } }
        : {}),
      ...(patch.outputs !== undefined
        ? { outputs: { ...prev.outputs, ...patch.outputs } }
        : {}),
      // agents arrives as a full object from AgentLLMColumn — shallow merge is fine
      ...(patch.agents !== undefined
        ? { agents: { ...prev.agents, ...patch.agents } }
        : {}),
      ...(patch.llm_connection !== undefined
        ? { llm_connection: { ...prev.llm_connection, ...patch.llm_connection } }
        : {}),
    }))
  }, [])

  // Load a duplicated run config when requested; otherwise load the workspace
  // JSON once, then keep the UI and file synced both ways.
  useEffect(() => {
    let cancelled = false

    async function loadInitialConfig() {
      try {
        if (configRunId) {
          const result = await api.get<RunConfigResponse>(`/runs/${configRunId}/config`)
          if (cancelled) return

          const signature = JSON.stringify(result.config)
          lastWorkspaceJsonRef.current = signature
          lastWorkspaceMtimeRef.current = null
          workspaceLoadedRef.current = true
          setWorkspaceSyncState('external')
          setWorkspaceSyncMsg('Loaded run config')
          setConfig(result.config)
          return
        }

        const result = await api.get<WorkspaceConfigResponse>('/setup/workspace-config')
        if (cancelled) return

        const signature = JSON.stringify(result.config)
        lastWorkspaceJsonRef.current = signature
        lastWorkspaceMtimeRef.current = result.mtime_ns ?? null
        workspaceLoadedRef.current = true
        setWorkspacePath(result.path)
        setWorkspaceSyncState('saved')
        setWorkspaceSyncMsg('Workspace config synced')
        setConfig(result.config)
      } catch (err) {
        if (cancelled) return
        workspaceLoadedRef.current = true
        setWorkspaceSyncState('error')
        setWorkspaceSyncMsg(
          err instanceof Error
            ? `Workspace config could not load: ${err.message}`
            : 'Workspace config could not load',
        )
      }
    }

    loadInitialConfig()
    return () => {
      cancelled = true
    }
  }, [configRunId])

  useEffect(() => {
    if (!workspaceLoadedRef.current) return

    const signature = JSON.stringify(config)
    if (signature === lastWorkspaceJsonRef.current) return

    if (workspaceSaveRef.current) clearTimeout(workspaceSaveRef.current)
    setWorkspaceSyncState('saving')
    setWorkspaceSyncMsg('Saving workspace config…')

    workspaceSaveRef.current = setTimeout(async () => {
      workspaceSaveRef.current = null
      workspaceSavingRef.current = true
      try {
        const result = await api.post<WorkspaceConfigResponse>('/setup/workspace-config', {
          config,
        })
        const savedSignature = JSON.stringify(result.config)
        lastWorkspaceJsonRef.current = savedSignature
        lastWorkspaceMtimeRef.current = result.mtime_ns ?? null
        setWorkspacePath(result.path)
        setWorkspaceSyncState('saved')
        setWorkspaceSyncMsg('Workspace config saved')
        if (savedSignature !== signature) {
          setConfig(result.config)
        }
      } catch (err) {
        setWorkspaceSyncState('error')
        setWorkspaceSyncMsg(
          err instanceof Error
            ? `Workspace config save failed: ${err.message}`
            : 'Workspace config save failed',
        )
      } finally {
        workspaceSavingRef.current = false
      }
    }, WORKSPACE_AUTOSAVE_MS)

    return () => {
      if (workspaceSaveRef.current) clearTimeout(workspaceSaveRef.current)
    }
  }, [config])

  useEffect(() => {
    const interval = window.setInterval(async () => {
      if (
        !workspaceLoadedRef.current ||
        workspaceSavingRef.current ||
        workspaceSaveRef.current
      ) {
        return
      }

      try {
        const status = await api.get<WorkspaceConfigStatus>('/setup/workspace-config/status')
        setWorkspacePath(status.path)
        const remoteMtime = status.mtime_ns ?? null
        if (remoteMtime === null || remoteMtime === lastWorkspaceMtimeRef.current) {
          return
        }

        const result = await api.get<WorkspaceConfigResponse>('/setup/workspace-config')
        const signature = JSON.stringify(result.config)
        lastWorkspaceJsonRef.current = signature
        lastWorkspaceMtimeRef.current = result.mtime_ns ?? null
        setWorkspacePath(result.path)
        setWorkspaceSyncState('external')
        setWorkspaceSyncMsg('Reloaded saved workspace config')
        setConfig(result.config)
      } catch (err) {
        setWorkspaceSyncState('error')
        setWorkspaceSyncMsg(
          err instanceof Error
            ? `Workspace config sync paused: ${err.message}`
            : 'Workspace config sync paused',
        )
      }
    }, WORKSPACE_SYNC_POLL_MS)

    return () => window.clearInterval(interval)
  }, [])

  // Debounced validation
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      runValidation(config)
    }, 400)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [config])

  async function runValidation(cfg: Partial<LaunchConfig>) {
    try {
      const result = await api.post<ValidationResult>('/setup/validate', cfg)
      setValidationResult(result)
      setBackendReachable(true)
    } catch {
      // Couldn't reach the validation endpoint — surface it instead of leaving
      // the banner stuck on an eternal "Validating…".
      setBackendReachable(false)
    }
  }

  function handleValidateNow() {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    runValidation(config)
  }

  async function handleLaunch() {
    if (launching) return
    setLaunching(true)
    setLaunchError(null)
    try {
      const { run_id } = await api.post<LaunchResponse>('/setup/launch', config)
      navigate(`/studio/${run_id}`)
    } catch (err) {
      setLaunchError(describeLaunchError(err))
      setLaunching(false)
    }
  }

  function handleSavePreset() {
    setPresetName('')
    setPresetMsg(null)
    setSavePresetOpen(true)
  }

  function handleExportConfig() {
    const blob = new Blob([JSON.stringify(config, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const project = (config.project_name || config.scenario?.preset || 'agentarium')
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, '-')
      .replace(/^-+|-+$/g, '')
    a.href = url
    a.download = `${project || 'agentarium'}-launch-config.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  async function handleImportConfig(file: File | null) {
    if (!file) return
    try {
      const text = await file.text()
      const parsed = JSON.parse(text) as LaunchConfig
      setConfig(parsed)
      setWorkspaceSyncState('external')
      setWorkspaceSyncMsg(`Imported ${file.name}`)
      setLaunchError(null)
    } catch {
      setWorkspaceSyncState('error')
      setWorkspaceSyncMsg('Config import failed')
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function submitSavePreset() {
    const name = presetName.trim()
    if (!name || savingPreset) return
    setSavingPreset(true)
    try {
      await api.post('/setup/save-preset', { name, config })
      setPresetMsg({ ok: true, text: `Saved preset “${name}”.` })
      setTimeout(() => setSavePresetOpen(false), 900)
    } catch {
      setPresetMsg({ ok: false, text: 'Save failed — is the server running?' })
    } finally {
      setSavingPreset(false)
    }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <TopBar
        projectName={config.project_name || 'AgentGymnasium'}
        status={
          backendReachable === null ? 'connecting' : backendReachable ? 'online' : 'offline'
        }
      />

      {/* Title block */}
      <div
        style={{
          padding: '20px 24px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--surface-1)',
        }}
      >
        <h1 style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-1)', marginBottom: 4 }}>
          Simulation Setup
        </h1>
        <p style={{ fontSize: 12, color: 'var(--text-2)' }}>
          Configure your world, agents, tools, and constraints before launch.
        </p>
        <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={() => fileInputRef.current?.click()} style={secondaryBtn()}>
            Import JSON
          </button>
          <button onClick={handleExportConfig} style={secondaryBtn()}>
            Export JSON
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            onChange={(e) => void handleImportConfig(e.target.files?.[0] ?? null)}
            style={{ display: 'none' }}
          />
          <span
            title={workspacePath}
            style={{ fontSize: 11, color: 'var(--text-2)', display: 'inline-flex', gap: 5, alignItems: 'center' }}
          >
            <span style={{ color: workspaceSyncColor }}>●</span>
            {workspaceSyncMsg}
          </span>
        </div>
        {launchError && (
          <div
            role="alert"
            style={{
              marginTop: 12,
              padding: '8px 12px',
              borderRadius: 6,
              border: '1px solid var(--danger)',
              background: 'color-mix(in srgb, var(--danger) 12%, transparent)',
              color: 'var(--danger)',
              fontSize: 12,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
            }}
          >
            <span>{launchError}</span>
            <button
              onClick={() => setLaunchError(null)}
              aria-label="Dismiss"
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--danger)',
                cursor: 'pointer',
                fontSize: 14,
                lineHeight: 1,
              }}
            >
              ✕
            </button>
          </div>
        )}
      </div>

      {/* Full setup — three columns (collapses to 2 then 1 on narrow widths) */}
      <div
        style={{
          flex: 1,
          display: 'grid',
          gridTemplateColumns: oneCol ? '1fr' : twoCol ? '1fr 1fr' : '1fr 1fr 1fr',
          gap: 0,
          // When stacked, the whole grid scrolls; on wide screens each column does.
          overflowY: stacked ? 'auto' : 'hidden',
          overflowX: 'hidden',
        }}
      >
        {/* Column 1 — Scenario & World */}
        <div
          style={{
            borderRight: oneCol ? 'none' : '1px solid var(--border)',
            borderBottom: stacked ? '1px solid var(--border)' : 'none',
            padding: 16,
            overflowY: stacked ? 'visible' : 'auto',
          }}
        >
          <ColumnHeader number={1} title="Scenario & World Setup" badge="Required" />
          <ScenarioWorldColumn config={config} onConfigChange={handleConfigChange} />
        </div>

        {/* Column 2 — Agent & LLM */}
        <div
          style={{
            borderRight: oneCol ? 'none' : '1px solid var(--border)',
            borderBottom: stacked ? '1px solid var(--border)' : 'none',
            padding: 16,
            overflowY: stacked ? 'visible' : 'auto',
          }}
        >
          <ColumnHeader number={2} title="Agent & LLM Setup" badge="Required" />
          <AgentLLMColumn config={config} onConfigChange={handleConfigChange} />
        </div>

        {/* Column 3 — Tools, Constraints & Launch */}
        <div style={{ padding: 16, overflowY: stacked ? 'visible' : 'auto' }}>
          <ColumnHeader number={3} title="Tools, Constraints & Launch" />
          <ToolsLaunchColumn
            config={config}
            onConfigChange={handleConfigChange}
            validationResult={validationResult}
            onValidateNow={handleValidateNow}
            onLaunch={handleLaunch}
            onSavePreset={handleSavePreset}
          />
        </div>
      </div>

      {savePresetOpen && (
        <SavePresetModal
          name={presetName}
          onNameChange={setPresetName}
          onSubmit={submitSavePreset}
          onClose={() => setSavePresetOpen(false)}
          saving={savingPreset}
          message={presetMsg}
        />
      )}
    </div>
  )
}

function SavePresetModal({
  name,
  onNameChange,
  onSubmit,
  onClose,
  saving,
  message,
}: {
  name: string
  onNameChange: (v: string) => void
  onSubmit: () => void
  onClose: () => void
  saving: boolean
  message: { ok: boolean; text: string } | null
}) {
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Save preset"
        style={{
          width: 360,
          maxWidth: '90vw',
          background: 'var(--surface-1)',
          border: '1px solid var(--border)',
          borderRadius: 10,
          padding: 20,
        }}
      >
        <h2 style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-1)', marginBottom: 4 }}>
          Save preset
        </h2>
        <p style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 12 }}>
          Save this configuration so you can reload it later.
        </p>
        <input
          autoFocus
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onSubmit()
            if (e.key === 'Escape') onClose()
          }}
          placeholder="Preset name"
          style={{
            width: '100%',
            padding: '8px 10px',
            borderRadius: 6,
            border: '1px solid var(--border)',
            background: 'var(--surface-2)',
            color: 'var(--text-1)',
            fontSize: 13,
            marginBottom: 12,
          }}
        />
        {message && (
          <div
            style={{
              fontSize: 12,
              marginBottom: 12,
              color: message.ok ? 'var(--ok)' : 'var(--danger)',
            }}
          >
            {message.text}
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button
            onClick={onClose}
            style={{
              padding: '7px 14px',
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'transparent',
              color: 'var(--text-2)',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={onSubmit}
            disabled={!name.trim() || saving}
            style={{
              padding: '7px 14px',
              borderRadius: 6,
              border: 'none',
              background: 'var(--accent)',
              color: 'var(--on-accent)',
              fontSize: 12,
              fontWeight: 600,
              cursor: !name.trim() || saving ? 'not-allowed' : 'pointer',
              opacity: !name.trim() || saving ? 0.5 : 1,
            }}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ColumnHeader({
  number,
  title,
  badge,
}: {
  number: number
  title: string
  badge?: string
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 16,
        paddingBottom: 12,
        borderBottom: '1px solid var(--border)',
      }}
    >
      <span
        style={{
          width: 20,
          height: 20,
          borderRadius: '50%',
          background: 'var(--accent)',
          color: '#fff',
          fontSize: 11,
          fontWeight: 700,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        {number}
      </span>
      <span
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: 'var(--text-1)',
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
        }}
      >
        {title}
      </span>
      {badge && (
        <span
          style={{
            marginLeft: 'auto',
            fontSize: 10,
            padding: '2px 6px',
            borderRadius: 4,
            background: 'var(--accent-soft)',
            color: 'var(--accent)',
            border: '1px solid var(--accent)',
            fontWeight: 600,
          }}
        >
          {badge}
        </span>
      )}
    </div>
  )
}

function secondaryBtn(): React.CSSProperties {
  return {
    padding: '6px 10px',
    borderRadius: 6,
    border: '1px solid var(--border)',
    background: 'var(--surface-2)',
    color: 'var(--text-1)',
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
  }
}

