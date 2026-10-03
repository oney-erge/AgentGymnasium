import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { TopBar } from '../components/shared/TopBar'
import { WorldView, type WorldViewHandle } from '../components/studio/WorldView'
import { PlaybackToolbar } from '../components/studio/PlaybackToolbar'
import { ReplayTimeline } from '../components/studio/ReplayTimeline'
import { ChallengeBriefing } from '../components/studio/ChallengeBriefing'
import { AgentStatusPanel, type AgentInfo } from '../components/studio/AgentStatusPanel'
import { ScoreCardTable } from '../components/studio/ScoreCardTable'
import { ToolCallLog } from '../components/studio/ToolCallLog'
import { DesignSummaryPanel } from '../components/studio/DesignSummaryPanel'
import { TelemetryPanel, type AttemptScore } from '../components/studio/TelemetryPanel'
import { AttemptHistory } from '../components/studio/AttemptHistory'
import { AttemptDiffPanel } from '../components/studio/AttemptDiffPanel'
import { ModelInspector } from '../components/studio/ModelInspector'
import { api, downloadUrl, wsUrl } from '../api/client'
import { RunRelaunchActions } from '../components/shared/RunRelaunchActions'
import { useMediaQuery } from '../hooks/useMediaQuery'
import type {
  AttemptDiff,
  BuildStepRecord,
  ConstraintsConfig,
  CreateRunResponse,
  DesignSummary,
  EpisodeTrace,
  ModelInteraction,
  RunAttemptSummary,
  RunCaps,
  RunEvent,
  ScoreCard,
  ToolCallRecord,
} from '../api/types'

export function StudioScreen() {
  const { runId } = useParams<{ runId: string }>()

  // ── Playback state (drives the Phaser replay) ──────────────────────────────
  const [trace, setTrace] = useState<EpisodeTrace | null>(null)
  const [frameIndex, setFrameIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [videoExporting, setVideoExporting] = useState(false)
  const [videoMessage, setVideoMessage] = useState<string | null>(null)

  // ── Build Timeline (labelled per-tool-call design snapshots) ───────────────
  // Stored per trace run id on the backend, and streamed live as each attempt
  // finishes, so historical replay can show construction as well as physics.
  const [buildSteps, setBuildSteps] = useState<BuildStepRecord[]>([])
  const [buildStepIndex, setBuildStepIndex] = useState(0)
  const [viewMode, setViewMode] = useState<'physics' | 'build'>('physics')

  // ── Live run state (fed by the WebSocket) ──────────────────────────────────
  const [runStatus, setRunStatus] = useState<
    'connecting' | 'running' | 'finished' | 'disconnected'
  >('connecting')
  const [mode, setMode] = useState<string>('single')
  const [challengeName, setChallengeName] = useState('')
  const [objective, setObjective] = useState('')
  const [reward, setReward] = useState('')
  const [briefingConstraints, setBriefingConstraints] = useState<
    Partial<ConstraintsConfig> | undefined
  >(undefined)
  const [caps, setCaps] = useState<RunCaps | null>(null)
  const [latestDiff, setLatestDiff] = useState<AttemptDiff | null>(null)
  const [toolLog, setToolLog] = useState<ToolCallRecord[]>([])
  const [modelInteractions, setModelInteractions] = useState<ModelInteraction[]>([])
  // The agent whose score/metrics/design last updated — drives the "latest"
  // displays. Falls back to the first agent.
  const [latestAgentId, setLatestAgentId] = useState<string | null>(null)
  const [latestAttemptIndex, setLatestAttemptIndex] = useState<number | null>(null)
  const [winnerAgentId, setWinnerAgentId] = useState<string | null>(null)
  // Per-agent live state, keyed by agent_id. Single-agent runs use one key.
  const [designByAgent, setDesignByAgent] = useState<Record<string, DesignSummary>>({})
  // Cooperative ownership: per-agent contribution to the single shared design.
  const [ownershipByAgent, setOwnershipByAgent] = useState<
    Record<string, Partial<DesignSummary>>
  >({})
  const [latestScoreByAgent, setLatestScoreByAgent] = useState<Record<string, ScoreCard>>({})
  const [bestScoreByAgent, setBestScoreByAgent] = useState<Record<string, number>>({})
  const [attemptsByAgent, setAttemptsByAgent] = useState<Record<string, AttemptScore[]>>({})
  // trace_run_id per attempt, keyed `${agentId}:${attemptIndex}`, for replay.
  const [traceByAttempt, setTraceByAttempt] = useState<Record<string, string>>({})
  // best_attempt_index reported by run_finished (marks the ★ row).
  const [bestAttemptIndex, setBestAttemptIndex] = useState<number | null>(null)
  const DEFAULT_AGENTS: AgentInfo[] = [{ id: 'agent_a', name: 'Agent A', role: 'builder' }]
  const [agents, setAgents] = useState<AgentInfo[]>(DEFAULT_AGENTS)
  // Mirror of `agents` for the WS handlers, which close over the effect's initial
  // render (deps [runId]); reading the ref avoids a stale empty-agents fallback.
  const agentsRef = useRef<AgentInfo[]>(DEFAULT_AGENTS)
  useEffect(() => {
    agentsRef.current = agents
  }, [agents])

  const cooperative = mode === 'cooperative'

  // Resolve the "latest" agent (last to update), then its derived displays.
  // Cooperative runs have ONE shared design + ONE shared score (keyed "shared").
  const activeAgentId = cooperative
    ? 'shared'
    : (latestAgentId ?? agents[0]?.id ?? null)
  const designSummary = activeAgentId ? (designByAgent[activeAgentId] ?? null) : null
  const latestScore = activeAgentId ? (latestScoreByAgent[activeAgentId] ?? null) : null
  const latestAgentName = cooperative
    ? 'Shared'
    : (agents.find((a) => a.id === activeAgentId)?.name ?? activeAgentId ?? '')

  // Attempt history for the active agent + its per-attempt trace ids.
  const activeAttempts = activeAgentId ? (attemptsByAgent[activeAgentId] ?? []) : []
  const activeTraceByIndex: Record<number, string> = {}
  if (activeAgentId) {
    for (const [key, value] of Object.entries(traceByAttempt)) {
      const [aid, idx] = key.split(':')
      if (aid === activeAgentId) activeTraceByIndex[Number(idx)] = value
    }
  }

  const totalFrames = trace?.frames.length ?? 0

  // When viewing the Build Timeline, feed the current step's un-simulated
  // snapshot into the SAME renderer instead of the physics trace.
  const clampedBuildStep = Math.min(buildStepIndex, Math.max(0, buildSteps.length - 1))
  const currentBuildStep = buildSteps[clampedBuildStep]
  const displayedTrace =
    viewMode === 'build' && currentBuildStep ? currentBuildStep.trace : trace

  // Reverse-lookup the displayed trace's attempt index (for the replay label).
  let currentAttemptLabel: string | undefined
  if (trace?.run_id) {
    for (const [key, value] of Object.entries(traceByAttempt)) {
      if (value === trace.run_id) {
        const idx = Number(key.split(':')[1])
        if (Number.isFinite(idx)) {
          currentAttemptLabel = `Attempt ${String(idx + 1).padStart(3, '0')}`
        }
        break
      }
    }
  }

  const loadBuildStepsForTrace = useCallback(async (
    traceRunId: string,
    isStale: () => boolean = () => false,
  ) => {
    try {
      const steps = await api.get<BuildStepRecord[]>(`/runs/${traceRunId}/snapshots`)
      if (isStale()) return
      setBuildSteps(steps)
      setBuildStepIndex(Math.max(0, steps.length - 1))
      if (steps.length === 0) setViewMode('physics')
    } catch {
      if (isStale()) return
      setBuildSteps([])
      setBuildStepIndex(0)
      setViewMode('physics')
    }
  }, [])

  const loadModelInteractionsForTrace = useCallback(async (
    traceRunId: string,
    isStale: () => boolean = () => false,
  ) => {
    try {
      const interactions = await api.get<ModelInteraction[]>(
        `/runs/${traceRunId}/model-interactions`,
      )
      if (!isStale()) setModelInteractions(interactions)
    } catch {
      if (!isStale()) setModelInteractions([])
    }
  }, [])

  // Load + replay a specific attempt's trace by run id (Attempt History clicks).
  // Picking an attempt is a manual action, so it stops live-follow and reflects
  // the chosen attempt in the score/telemetry panels.
  const replayTraceRunId = async (traceRunId: string) => {
    followLiveRef.current = false
    try {
      const fetched = await api.get<EpisodeTrace>(`/runs/${traceRunId}/trace`)
      setTrace(fetched)
      setFrameIndex(0)
      setPlaying(true)
      setStatus('ready')
      setViewMode('physics')
      void loadBuildStepsForTrace(traceRunId)
      void loadModelInteractionsForTrace(traceRunId)
      // Reflect the picked attempt in the telemetry/score panels.
      const match = Object.entries(traceByAttempt).find(([, v]) => v === traceRunId)
      if (match) {
        const [aid, idxStr] = match[0].split(':')
        const idx = Number(idxStr)
        setLatestAgentId(aid)
        if (Number.isFinite(idx)) setLatestAttemptIndex(idx)
        try {
          const sc = await api.get<ScoreCard>(`/runs/${traceRunId}/score`)
          setLatestScoreByAgent((prev) => ({ ...prev, [aid]: sc }))
        } catch {
          /* score is best-effort */
        }
      }
    } catch {
      setStatus('error')
    }
  }

  // ── WebSocket subscription (live runs) ─────────────────────────────────────
  // Open exactly once per runId; tolerate StrictMode double-mount + close.
  const wsRef = useRef<WebSocket | null>(null)
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const worldViewRef = useRef<WorldViewHandle | null>(null)
  // While true, newly-produced attempt traces auto-load and play (live follow).
  // Any manual playback action (pause/stop/seek/pick an attempt) turns this off
  // so the user's controls stay authoritative and a live run can't yank the
  // viewport away or un-pause them.
  const followLiveRef = useRef(true)

  const handleTogglePlay = () => {
    followLiveRef.current = false
    setPlaying((p) => !p)
  }
  const handleStop = () => {
    followLiveRef.current = false
    setPlaying(false)
    setFrameIndex(0)
  }
  const handleSeek = (index: number) => {
    followLiveRef.current = false
    setFrameIndex(index)
  }

  useEffect(() => {
    if (!runId) return
    let cancelled = false

    // Fetch a trace by run id and auto-play it in the Phaser replay.
    const loadTrace = async (traceRunId: string) => {
      try {
        const fetched = await api.get<EpisodeTrace>(`/runs/${traceRunId}/trace`)
        if (cancelled) return
        setTrace(fetched)
        setFrameIndex(0)
        setPlaying(true)
        setStatus('ready')
        void loadBuildStepsForTrace(traceRunId, () => cancelled)
        void loadModelInteractionsForTrace(traceRunId, () => cancelled)
      } catch {
        if (!cancelled) setStatus('error')
      }
    }

    // A finished/historical run isn't in the live orchestrator (evicted, or after
    // a restart). Replay its persisted trace + score read-only instead of a dead
    // "unknown run" error. Returns whether the historical trace loaded.
    const loadHistorical = async (rid: string): Promise<boolean> => {
      try {
        const fetched = await api.get<EpisodeTrace>(`/runs/${rid}/trace`)
        if (cancelled) return true
        setTrace(fetched)
        setFrameIndex(0)
        setPlaying(true)
        setStatus('ready')
        setRunStatus('finished')
        setViewMode('physics')
        void loadBuildStepsForTrace(rid, () => cancelled)
        void loadModelInteractionsForTrace(rid, () => cancelled)
        let openedScore: ScoreCard | null = null
        try {
          const sc = await api.get<ScoreCard>(`/runs/${rid}/score`)
          if (!cancelled) {
            openedScore = sc
            setLatestScoreByAgent({ agent_a: sc })
            if (sc.reward) setReward(sc.reward)
          }
        } catch {
          /* score is best-effort */
        }
        // Populate the full attempt list so every attempt of this finished run
        // is browsable/replayable — not just the single trace we opened with.
        try {
          const attempts = await api.get<RunAttemptSummary[]>(`/runs/${rid}/attempts`)
          if (!cancelled && attempts.length > 0) {
            const traceMap: Record<string, string> = {}
            const byAgent: Record<string, AttemptScore[]> = {}
            const discovered = new Set<string>()
            for (const a of attempts) {
              const aid = a.agent_id ?? 'agent_a'
              const idx = a.attempt_index ?? 0
              traceMap[`${aid}:${idx}`] = a.trace_run_id
              discovered.add(aid)
              ;(byAgent[aid] ??= []).push({
                index: idx,
                scorecard: {
                  score_total: a.score_total ?? 0,
                  success: a.success ?? false,
                  metrics: {},
                  failure_events: [],
                  summary: '',
                  reward: '',
                },
              })
            }
            for (const list of Object.values(byAgent)) list.sort((x, y) => x.index - y.index)
            setTraceByAttempt((prev) => ({ ...traceMap, ...prev }))
            setAttemptsByAgent((prev) => ({ ...byAgent, ...prev }))
            setAgents((prev) => {
              const have = new Set(prev.map((p) => p.id))
              const additions = [...discovered]
                .filter((id) => !have.has(id))
                .map((id) => ({ id, name: id === 'agent_a' ? 'Agent A' : id, role: 'builder' }))
              return additions.length > 0 ? [...prev, ...additions] : prev
            })
            const opened = attempts.find((a) => a.trace_run_id === rid)
            const openedAgent = opened?.agent_id ?? 'agent_a'
            setLatestAgentId(openedAgent)
            setLatestAttemptIndex(opened?.attempt_index ?? 0)
            // Key the opened attempt's full score under its real agent, so a
            // multi-agent run's telemetry isn't misattributed to agent_a.
            if (openedScore && openedAgent !== 'agent_a') {
              setLatestScoreByAgent({ [openedAgent]: openedScore })
            }
            const series = byAgent[openedAgent] ?? []
            if (series.length > 0) {
              const best = series.reduce((b, a) =>
                a.scorecard.score_total > b.scorecard.score_total ? a : b,
              )
              setBestAttemptIndex(best.index)
            }
          }
        } catch {
          /* attempt list is best-effort */
        }
        return true
      } catch {
        return false
      }
    }

    const handleEvent = (event: RunEvent) => {
      switch (event.type) {
        case 'run_started':
          setChallengeName(event.project_name)
          setObjective(event.objective)
          setMode(event.mode)
          if (event.reward) setReward(event.reward)
          if (event.constraints) setBriefingConstraints(event.constraints)
          setCaps({
            effectiveAttempts: event.max_attempts,
            requestedAttempts: event.requested_attempts,
            simCapS: event.simulation_cap_s,
            requestedDurationS: event.requested_duration_s,
          })
          setRunStatus('running')
          if (event.agents && event.agents.length > 0) {
            setAgents(event.agents.map((a) => ({ id: a.id, name: a.name, role: a.role })))
          }
          break
        case 'attempt_started': {
          // Surface the in-flight attempt as soon as it begins, rather than only
          // when its score lands, so the "current attempt" reads as live.
          const id = event.agent_id ?? (event.agent_ids ? 'shared' : agentsRef.current[0]?.id ?? 'agent_a')
          setLatestAgentId(id)
          setLatestAttemptIndex(event.attempt_index)
          // A new attempt starts a fresh build sequence.
          setBuildSteps([])
          setBuildStepIndex(0)
          break
        }
        case 'attempt_finished':
          // The score/design events already drove the panels for this attempt.
          break
        case 'tool_call':
          setToolLog((prev) => [...prev, event.record])
          break
        case 'design_snapshot':
          setBuildSteps((prev) => [
            ...prev,
            {
              attempt_index: event.attempt_index,
              step_index: event.step_index,
              trace_run_id: event.trace_run_id,
              agent_id: event.agent_id ?? 'unknown',
              tool: event.tool,
              status: event.status,
              label: event.label,
              mutated: event.mutated,
              visual_change: event.visual_change,
              new_body_ids: event.new_body_ids,
              new_joint_ids: event.new_joint_ids,
              error: event.error,
              trace: event.trace,
            },
          ])
          setBuildStepIndex((i) => i + 1)
          break
        case 'design_update': {
          // Cooperative: one shared design (no agent_id) + a by_agent breakdown.
          if (event.by_agent) {
            setOwnershipByAgent(event.by_agent)
            setDesignByAgent((prev) => ({ ...prev, shared: event.summary }))
            setLatestAgentId('shared')
            break
          }
          const id = event.agent_id ?? agentsRef.current[0]?.id ?? 'agent_a'
          setDesignByAgent((prev) => ({ ...prev, [id]: event.summary }))
          setLatestAgentId(id)
          break
        }
        case 'trace_ready': {
          const id = event.agent_id ?? (event.agent_ids ? 'shared' : agentsRef.current[0]?.id ?? 'agent_a')
          setTraceByAttempt((prev) => ({
            ...prev,
            [`${id}:${event.attempt_index}`]: event.trace_run_id,
          }))
          // Only follow the newest attempt if the user hasn't taken manual
          // control of playback; otherwise keep them where they are.
          if (followLiveRef.current) void loadTrace(event.trace_run_id)
          break
        }
        case 'score': {
          const id = event.agent_id ?? agentsRef.current[0]?.id ?? 'agent_a'
          setLatestScoreByAgent((prev) => ({ ...prev, [id]: event.scorecard }))
          setBestScoreByAgent((prev) => ({
            ...prev,
            [id]: Math.max(prev[id] ?? -Infinity, event.scorecard.score_total),
          }))
          setLatestAgentId(id)
          setLatestAttemptIndex(event.attempt_index)
          if (event.diff !== undefined) setLatestDiff(event.diff)
          setAttemptsByAgent((prev) => {
            const series = (prev[id] ?? []).filter((a) => a.index !== event.attempt_index)
            series.push({ index: event.attempt_index, scorecard: event.scorecard })
            series.sort((a, b) => a.index - b.index)
            return { ...prev, [id]: series }
          })
          break
        }
        case 'winner':
          setWinnerAgentId(event.agent_id)
          break
        case 'run_finished':
          if (event.winner_agent_id) setWinnerAgentId(event.winner_agent_id)
          if (event.best_attempt_index >= 0) setBestAttemptIndex(event.best_attempt_index)
          // One-click winner replay: surface the best attempt's trace at run end,
          // unless the user is manually reviewing a specific attempt.
          if (event.best_trace_run_id && followLiveRef.current) {
            void loadTrace(event.best_trace_run_id)
          }
          setRunStatus('finished')
          break
        case 'error':
          // "unknown run" means it's not live — try replaying it from history.
          if (runId && event.detail?.includes('unknown run')) {
            void loadHistorical(runId).then((ok) => {
              if (!ok && !cancelled) {
                setStatus('error')
                setErrorDetail('Run not found.')
              }
            })
          } else {
            setStatus('error')
            setErrorDetail(event.detail || 'The run failed.')
          }
          break
        default:
          break
      }
    }

    const ws = new WebSocket(wsUrl(`/runs/${runId}`))
    wsRef.current = ws

    ws.onopen = () => {
      if (!cancelled) setRunStatus('running')
    }

    ws.onmessage = (msg) => {
      if (cancelled) return
      let event: RunEvent
      try {
        event = JSON.parse(msg.data) as RunEvent
      } catch {
        return
      }
      handleEvent(event)
    }

    ws.onerror = () => {
      if (!cancelled) setStatus('error')
    }

    ws.onclose = () => {
      // If the socket drops while still running (server crash, proxy timeout),
      // mark it 'disconnected' — distinct from a clean 'finished' so a failure
      // isn't misreported as success, and the UI doesn't hang on "Building…".
      if (!cancelled) setRunStatus((s) => (s === 'running' || s === 'connecting' ? 'disconnected' : s))
    }

    return () => {
      cancelled = true
      wsRef.current = null
      // 1000 = normal closure; tolerate sockets already closed after run_finished.
      try {
        ws.close(1000)
      } catch {
        /* already closed */
      }
    }
  }, [runId, loadBuildStepsForTrace, loadModelInteractionsForTrace])

  // ── Dev fallback: no runId → spin up a demo run so the world still moves. ───
  useEffect(() => {
    if (runId) return
    let cancelled = false
    async function loadDemo() {
      setStatus('loading')
      try {
        const created = await api.post<CreateRunResponse>('/runs', {})
        const fetched = await api.get<EpisodeTrace>(`/runs/${created.run_id}/trace`)
        if (cancelled) return
        setTrace(fetched)
        setFrameIndex(0)
        setPlaying(true)
        setStatus('ready')
        setRunStatus('finished')
      } catch {
        if (!cancelled) setStatus('error')
      }
    }
    loadDemo()
    return () => {
      cancelled = true
    }
  }, [runId])

  // ── Playback loop: advance frameIndex while playing, looping at the end. ────
  const rafRef = useRef<number | null>(null)
  const lastTsRef = useRef<number | null>(null)
  const accRef = useRef(0)

  useEffect(() => {
    if (!playing || !trace || trace.frames.length <= 1) return

    const dt = trace.dt > 0 ? trace.dt : 1 / 60

    const tick = (ts: number) => {
      if (lastTsRef.current == null) lastTsRef.current = ts
      const elapsed = (ts - lastTsRef.current) / 1000
      lastTsRef.current = ts
      accRef.current += elapsed * speed

      let advance = 0
      while (accRef.current >= dt) {
        accRef.current -= dt
        advance++
      }
      if (advance > 0) {
        setFrameIndex((prev) => (prev + advance) % trace.frames.length)
      }
      rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
      lastTsRef.current = null
      accRef.current = 0
    }
  }, [playing, trace, speed])

  const handleFullscreen = () => {
    const el = viewportRef.current
    if (!el) return
    if (document.fullscreenElement) void document.exitFullscreen()
    else void el.requestFullscreen?.()
  }

  const handleExportVideo = async () => {
    if (!trace || videoExporting) return
    const worldView = worldViewRef.current
    if (!worldView) return

    const totalTime = trace.frames.at(-1)?.t ?? trace.frames.length * (trace.dt || 1 / 60)
    const durationMs = Math.min(Math.max(totalTime * 1000, 1500), 20000)

    setVideoExporting(true)
    setVideoMessage(`Recording ${(durationMs / 1000).toFixed(1)}s`)
    setFrameIndex(0)
    setPlaying(true)
    try {
      await worldView.recordWebm(durationMs)
      setVideoMessage('Downloaded WebM')
    } catch (err) {
      setVideoMessage(err instanceof Error ? err.message : 'Video export failed')
    } finally {
      setVideoExporting(false)
      window.setTimeout(() => setVideoMessage(null), 3000)
    }
  }

  // Keyboard playback: Space toggles play/pause, ←/→ step frames. Ignored while
  // typing in a field so it doesn't hijack form input.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (!trace) return
      if (e.code === 'Space') {
        e.preventDefault()
        followLiveRef.current = false
        setPlaying((p) => !p)
      } else if (e.code === 'ArrowRight') {
        e.preventDefault()
        followLiveRef.current = false
        setPlaying(false)
        setFrameIndex((i) => Math.min(i + 1, trace.frames.length - 1))
      } else if (e.code === 'ArrowLeft') {
        e.preventDefault()
        followLiveRef.current = false
        setPlaying(false)
        setFrameIndex((i) => Math.max(i - 1, 0))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [trace])

  const running = runStatus === 'running' || runStatus === 'connecting'
  const disconnected = runStatus === 'disconnected'
  // Below ~1100px the fixed rails squeeze the viewport — stack them instead.
  const narrow = useMediaQuery('(max-width: 1100px)')
  const topBarStatus = status === 'error' || disconnected
    ? 'offline'
    : runStatus === 'connecting'
      ? 'connecting'
      : 'online'
  const activeRunId = runId ?? trace?.run_id ?? null

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <TopBar projectName={challengeName || 'AgentGymnasium'} status={topBarStatus} />

      {/* Studio header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '8px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--surface-1)',
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-1)' }}>
          Simulation World
        </span>
        {(() => {
          const tone =
            status === 'error' || disconnected
              ? 'var(--danger)'
              : running
                ? 'var(--warn)'
                : 'var(--ok)'
          const label =
            status === 'error'
              ? 'Run error'
              : disconnected
                ? 'Connection lost'
                : runStatus === 'connecting'
                  ? 'Connecting…'
                  : runStatus === 'running'
                    ? 'Building…'
                    : 'Finished'
          return (
            <span
              style={{ fontSize: 11, color: tone, display: 'flex', alignItems: 'center', gap: 4 }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: tone,
                  display: 'inline-block',
                }}
              />
              {label}
            </span>
          )
        })()}
        <span style={{ marginLeft: 'auto' }}>
          <RunRelaunchActions runId={activeRunId} compact disabled={!activeRunId} />
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-2)' }}>
          run: {activeRunId ?? '—'}
        </span>
      </div>

      {/* Three-region layout — stacks vertically on narrow widths */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: narrow ? 'column' : 'row',
          overflowY: narrow ? 'auto' : 'hidden',
          overflowX: 'hidden',
        }}
      >
        {/* Left rail — briefing & agent status */}
        <div
          style={{
            width: narrow ? 'auto' : 280,
            flexShrink: 0,
            borderRight: narrow ? 'none' : '1px solid var(--border)',
            borderBottom: narrow ? '1px solid var(--border)' : 'none',
            padding: 12,
            overflowY: narrow ? 'visible' : 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          <ChallengeBriefing
            challengeName={challengeName}
            objective={objective}
            reward={reward}
            constraints={briefingConstraints}
            caps={caps}
          />
          <AgentStatusPanel
            agents={agents}
            designByAgent={designByAgent}
            latestScoreByAgent={latestScoreByAgent}
            winnerAgentId={cooperative ? null : winnerAgentId}
            running={running}
            cooperative={cooperative}
            ownershipByAgent={ownershipByAgent}
            sharedScore={cooperative ? latestScore : null}
          />
          <ScoreCardTable
            agents={agents}
            latestScoreByAgent={latestScoreByAgent}
            bestScoreByAgent={bestScoreByAgent}
            winnerAgentId={cooperative ? null : winnerAgentId}
            cooperative={cooperative}
            sharedLatest={cooperative ? (latestScoreByAgent.shared?.score_total ?? null) : null}
            sharedBest={cooperative ? (bestScoreByAgent.shared ?? null) : null}
          />
        </div>

        {/* Center — toolbar + world viewport + telemetry */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            // Keep the viewport usable when the layout is stacked vertically.
            minHeight: narrow ? 460 : undefined,
          }}
        >
          <PlaybackToolbar
            playing={playing}
            onTogglePlay={handleTogglePlay}
            onStop={handleStop}
            speed={speed}
            onSpeedChange={setSpeed}
            frameIndex={frameIndex}
            totalFrames={totalFrames}
            onFullscreen={handleFullscreen}
            cameraLabel={trace?.camera === 'iso' ? 'Isometric' : 'Side View'}
          />

          {/* Build Timeline toggle — shown for live and historical traces that
              have persisted per-step snapshots. */}
          {buildSteps.length > 0 && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '6px 12px',
                borderBottom: '1px solid var(--border)',
                background: 'var(--surface-1)',
                flexShrink: 0,
              }}
            >
              <div style={{ display: 'flex', gap: 4 }}>
                {(['build', 'physics'] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setViewMode(m)}
                    style={{
                      padding: '3px 10px',
                      borderRadius: 6,
                      border: '1px solid var(--border)',
                      background: viewMode === m ? 'var(--accent)' : 'var(--surface-2)',
                      color: viewMode === m ? 'var(--on-accent)' : 'var(--text-2)',
                      fontSize: 11,
                      fontWeight: 600,
                      textTransform: 'capitalize',
                      cursor: 'pointer',
                    }}
                  >
                    {m === 'build' ? 'Build' : 'Physics'}
                  </button>
                ))}
              </div>
              {viewMode === 'build' && (
                <>
                  <input
                    type="range"
                    aria-label="Build step"
                    min={0}
                    max={Math.max(0, buildSteps.length - 1)}
                    step={1}
                    value={clampedBuildStep}
                    onChange={(e) => setBuildStepIndex(Number(e.target.value))}
                    style={{ flex: 1, accentColor: 'var(--accent)' }}
                  />
                  <span
                    style={{
                      fontSize: 11,
                      color: 'var(--text-2)',
                      fontVariantNumeric: 'tabular-nums',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    Step {clampedBuildStep + 1} / {buildSteps.length}
                  </span>
                  <span
                    title={currentBuildStep?.label}
                    style={{
                      minWidth: 0,
                      maxWidth: 300,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      fontSize: 11,
                      color:
                        currentBuildStep?.status === 'rejected'
                          ? 'var(--danger)'
                          : currentBuildStep?.visual_change
                            ? 'var(--text-1)'
                            : 'var(--text-2)',
                    }}
                  >
                    {currentBuildStep?.label}
                  </span>
                </>
              )}
            </div>
          )}

          {/* Viewport */}
          <div
            ref={viewportRef}
            style={{
              flex: 1,
              background: 'var(--surface-2)',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            <WorldView ref={worldViewRef} trace={displayedTrace} frameIndex={viewMode === 'build' ? 0 : frameIndex} />
            <ViewportOverlay
              status={status}
              runStatus={runStatus}
              hasTrace={!!trace}
              errorDetail={errorDetail}
              agentName={latestAgentName}
              attemptNumber={latestAttemptIndex != null ? latestAttemptIndex + 1 : null}
              totalAttempts={caps?.effectiveAttempts ?? null}
              toolCallCount={toolLog.length}
              hint={latestScore?.improvement_hint ?? latestScore?.summary ?? null}
            />
          </div>

          {/* Telemetry strip */}
          <div
            style={{
              height: 160,
              flexShrink: 0,
              borderTop: '1px solid var(--border)',
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 1fr',
              background: 'var(--surface-1)',
            }}
          >
            <TelemetryPanel
              agents={agents}
              attemptsByAgent={attemptsByAgent}
              latest={latestScore}
              latestAgentName={latestAgentName}
              latestAttemptIndex={latestAttemptIndex}
              running={running}
            />
          </div>
        </div>

        {/* Right rail — log, design, replay */}
        <div
          style={{
            width: narrow ? 'auto' : 300,
            flexShrink: 0,
            borderLeft: narrow ? 'none' : '1px solid var(--border)',
            borderTop: narrow ? '1px solid var(--border)' : 'none',
            padding: 12,
            overflowY: narrow ? 'visible' : 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          <AttemptHistory
            attempts={activeAttempts}
            traceByIndex={activeTraceByIndex}
            bestAttemptIndex={
              // Attempt indices are per-agent and overlap; only mark the best on
              // the agent it belongs to (the winner in competitive mode).
              !winnerAgentId || activeAgentId === winnerAgentId ? bestAttemptIndex : null
            }
            onReplay={(id) => void replayTraceRunId(id)}
          />
          <AttemptDiffPanel diff={latestDiff} attemptIndex={latestAttemptIndex} />
          <ToolCallLog records={toolLog} onClear={() => setToolLog([])} />
          <ModelInspector interactions={modelInteractions} />
          <DesignSummaryPanel
            summary={designSummary}
            byAgent={cooperative ? ownershipByAgent : null}
            agents={agents}
            onExport={
              trace?.run_id
                ? () => downloadUrl(`/exports/${trace.run_id}/design?format=yaml`)
                : undefined
            }
            onViewReport={
              trace?.run_id ? () => downloadUrl(`/exports/${trace.run_id}/report`) : undefined
            }
          />
          <ReplayTimeline
            frameIndex={frameIndex}
            totalFrames={totalFrames}
            playing={playing}
            onSeek={handleSeek}
            onTogglePlay={handleTogglePlay}
            speed={speed}
            frames={trace?.frames}
            attemptLabel={currentAttemptLabel}
            onExportVideo={handleExportVideo}
            videoExporting={videoExporting}
            videoMessage={videoMessage}
          />
        </div>
      </div>
    </div>
  )
}

/** Overlay shown on top of the (empty) viewport while loading, on error, or when
 *  the connection drops — so a failed run isn't just a blank black canvas. It
 *  surfaces what the agent is doing right now (thinking / building) and gives a
 *  meaningful end state when a run finishes without producing a simulation. */
function ViewportOverlay({
  status,
  runStatus,
  hasTrace,
  errorDetail,
  agentName,
  attemptNumber,
  totalAttempts,
  toolCallCount,
  hint,
}: {
  status: 'loading' | 'ready' | 'error'
  runStatus: 'connecting' | 'running' | 'finished' | 'disconnected'
  hasTrace: boolean
  errorDetail?: string | null
  agentName?: string
  attemptNumber?: number | null
  totalAttempts?: number | null
  toolCallCount?: number
  hint?: string | null
}) {
  // Nothing to overlay once a trace is rendering and there's no error.
  if (hasTrace && status !== 'error' && runStatus !== 'disconnected') return null

  let title: string
  let detail: string
  let tone = 'var(--text-2)'
  let busy = false
  if (status === 'error') {
    title = 'Run error'
    detail = errorDetail || 'Something went wrong loading this run. Try launching again.'
    tone = 'var(--danger)'
  } else if (runStatus === 'disconnected') {
    title = 'Connection lost'
    detail = 'The live connection dropped before the run finished.'
    tone = 'var(--danger)'
  } else if (runStatus === 'finished') {
    // Finished but no trace ever loaded: the agent never produced a movable
    // design. Say so plainly instead of hanging on "Waiting for the first build".
    title = 'No simulation produced'
    detail =
      hint ||
      'The run finished without a simulatable design — the agent’s tool calls did not create a movable body. Try the mock provider, a stronger model, or enabling more building tools.'
    tone = 'var(--warn)'
  } else if (runStatus === 'connecting') {
    title = 'Connecting…'
    detail = 'Establishing the live run connection.'
    tone = 'var(--warn)'
    busy = true
  } else {
    // Running. Distinguish "calling the model" from "applying tool calls" using
    // whether any tool calls have streamed in for the run yet.
    busy = true
    const who = agentName ? `${agentName} · ` : ''
    const of =
      attemptNumber != null
        ? `Attempt ${attemptNumber}${totalAttempts ? ` of ${totalAttempts}` : ''}`
        : 'Working'
    if (toolCallCount && toolCallCount > 0) {
      title = `${who}${of}`
      detail = `Building the design — ${toolCallCount} tool call${toolCallCount === 1 ? '' : 's'} so far. The world will appear once it simulates.`
    } else {
      title = `${who}${of}`
      detail = 'Thinking — calling the selected model. First responses can take a while.'
    }
  }

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        textAlign: 'center',
        padding: 24,
        pointerEvents: 'none',
        background: 'color-mix(in srgb, var(--surface-2) 70%, transparent)',
      }}
    >
      {busy && (
        <div
          style={{
            width: 26,
            height: 26,
            borderRadius: '50%',
            border: '3px solid var(--border)',
            borderTopColor: 'var(--accent)',
            animation: 'agentarium-spin 0.8s linear infinite',
          }}
        />
      )}
      <div style={{ fontSize: 14, fontWeight: 600, color: tone }}>{title}</div>
      <div style={{ fontSize: 12, color: 'var(--text-2)', maxWidth: 340 }}>{detail}</div>
    </div>
  )
}
