import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type {
  EpisodeTrace,
  ModelInteraction,
  RunConfigResponse,
  ScoreCard,
} from '../api/types'
import { TopBar } from '../components/shared/TopBar'
import { WorldView } from '../components/studio/WorldView'

type ComparedRun = {
  id: string
  trace: EpisodeTrace
  score: ScoreCard
  config: RunConfigResponse
  interactions: ModelInteraction[]
}

export function CompareScreen() {
  const [params, setParams] = useSearchParams()
  const initial = params.get('runs') ?? ''
  const [runInput, setRunInput] = useState(initial)
  const [runs, setRuns] = useState<ComparedRun[]>([])
  const [progress, setProgress] = useState(0)
  const [alignment, setAlignment] = useState<'time' | 'duration'>('time')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (initial) void load(initial)
    // The URL is the shareable source only on mount; edits use the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function load(value: string) {
    const ids = value.split(',').map((id) => id.trim()).filter(Boolean).slice(0, 4)
    if (ids.length < 2) {
      setError('Enter at least two trace run IDs.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const loaded = await Promise.all(
        ids.map(async (id): Promise<ComparedRun> => {
          const [trace, score, config, interactions] = await Promise.all([
            api.get<EpisodeTrace>(`/runs/${id}/trace`),
            api.get<ScoreCard>(`/runs/${id}/score`),
            api.get<RunConfigResponse>(`/runs/${id}/config`),
            api.get<ModelInteraction[]>(`/runs/${id}/model-interactions`),
          ])
          return { id, trace, score, config, interactions }
        }),
      )
      setRuns(loaded)
      setProgress(0)
      setParams({ runs: ids.join(',') })
    } catch {
      setError('One or more runs could not be loaded. Use attempt trace IDs from History.')
    } finally {
      setLoading(false)
    }
  }

  const maxTime = useMemo(
    () => Math.max(0, ...runs.map((run) => run.trace.frames.at(-1)?.t ?? 0)),
    [runs],
  )
  const frameIndices = useMemo(() => runs.map((run) => {
    const frames = run.trace.frames
    if (alignment === 'duration') return Math.round(progress * Math.max(0, frames.length - 1))
    const time = progress * maxTime
    // Use the last recorded frame at or before the shared time. A shorter run
    // remains at its final frame rather than advancing faster than its peers.
    let low = 0
    let high = frames.length - 1
    while (low < high) {
      const mid = Math.ceil((low + high) / 2)
      if (frames[mid].t <= time) low = mid
      else high = mid - 1
    }
    return Math.max(0, low)
  }), [alignment, maxTime, progress, runs])

  const comparisonConditions = runs.map(({ config }) => {
    const { visual_style: _visualStyle, visual_seed: _visualSeed, seed: _seed, ...world } = config.config.world
    return JSON.stringify({
      scenario: config.config.scenario,
      world,
      constraints: config.config.constraints,
      tools: [...(config.config.tools?.enabled ?? [])].sort(),
    })
  })
  const conditionsDiffer = new Set(comparisonConditions).size > 1

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <TopBar projectName="Run Comparison" status={error ? 'offline' : 'online'} />
      <div style={{ padding: 14, borderBottom: '1px solid var(--border)', display: 'flex', gap: 8 }}>
        <input
          value={runInput}
          onChange={(e) => setRunInput(e.target.value)}
          placeholder="trace-run-id-1, trace-run-id-2"
          style={{ flex: 1, ...input() }}
        />
        <button onClick={() => void load(runInput)} disabled={loading} style={primary()}>
          {loading ? 'Loading…' : 'Compare'}
        </button>
      </div>
      {error && <div style={{ padding: 12, color: 'var(--danger)' }}>{error}</div>}
      {runs.length > 0 && (
        <>
          <div style={{ padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
            <label style={muted()}>
              Alignment{' '}
              <select value={alignment} onChange={(e) => setAlignment(e.target.value as 'time' | 'duration')} style={input()}>
                <option value="time">Simulation time</option>
                <option value="duration">Percent of each run</option>
              </select>
            </label>
            <input
              type="range"
              min={0}
              max={1000}
              value={Math.round(progress * 1000)}
              onChange={(e) => setProgress(Number(e.target.value) / 1000)}
              style={{ flex: 1 }}
            />
            <span style={muted()}>{alignment === 'time' ? `${(progress * maxTime).toFixed(2)} s` : `${(progress * 100).toFixed(0)}%`}</span>
          </div>
          {conditionsDiffer && (
            <div role="alert" style={{ padding: '0 16px 10px', color: 'var(--warn)', fontSize: 12 }}>
              Challenge, world, tools, or constraints differ. Scores may not be directly comparable.
            </div>
          )}
          <div
            style={{
              flex: 1,
              minHeight: 0,
              display: 'grid',
              gridTemplateColumns: `repeat(${runs.length}, minmax(280px, 1fr))`,
              gap: 10,
              padding: '0 12px 12px',
              overflow: 'auto',
            }}
          >
            {runs.map((run, index) => {
              const agent = run.config.config.agents?.participants?.[0]
              const usage = run.interactions.reduce(
                (total, item) => ({
                  input: total.input + item.result.usage.input_tokens,
                  output: total.output + item.result.usage.output_tokens,
                  latency: total.latency + item.result.latency_ms,
                }),
                { input: 0, output: 0, latency: 0 },
              )
              return (
                <section key={run.id} style={panel()}>
                  <div>
                    <h2 style={{ fontSize: 14 }}>{agent?.model ?? run.id}</h2>
                    <p style={muted()}>
                      {agent?.provider ?? '—'} · provider seed {agent?.provider_seed ?? run.config.config.world.seed ?? '—'} ·{' '}
                      <Link to={`/studio/${run.id}`} style={{ color: 'var(--accent)' }}>open Studio</Link>
                    </p>
                    <p style={muted()}>
                      {run.config.config.scenario.preset} · {run.config.config.world.template} · {run.trace.engine}
                      {' '}· {run.trace.frames.at(-1)?.t.toFixed(2) ?? '0.00'} s
                    </p>
                  </div>
                  <div style={{ height: 260, borderRadius: 6, overflow: 'hidden' }}>
                    <WorldView trace={run.trace} frameIndex={frameIndices[index] ?? 0} />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6 }}>
                    <Stat label="Score" value={run.score.score_total.toFixed(1)} />
                    <Stat label="Success" value={run.score.success ? 'Yes' : 'No'} />
                    <Stat label="Input tokens" value={String(usage.input)} />
                    <Stat label="Output tokens" value={String(usage.output)} />
                    <Stat label="Model latency" value={`${usage.latency.toFixed(0)}ms`} />
                    <Stat label="Tool protocol" value={run.interactions.some((i) => i.result.native_tool_calls) ? 'Native' : 'Prompt JSON'} />
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                    <tbody>
                      {Object.entries(run.score.metrics).sort().map(([key, value]) => (
                        <tr key={key}>
                          <td style={{ padding: 4, color: 'var(--text-2)' }}>{key}</td>
                          <td style={{ padding: 4, textAlign: 'right' }}>{value.toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div style={{ padding: 7, borderRadius: 6, background: 'var(--surface-2)' }}><div style={muted()}>{label}</div><strong>{value}</strong></div>
}
function panel(): React.CSSProperties {
  return { alignSelf: 'start', display: 'grid', gap: 10, padding: 12, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--surface-1)' }
}
function input(): React.CSSProperties {
  return { padding: '7px 9px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface-2)', color: 'var(--text-1)' }
}
function primary(): React.CSSProperties {
  return { padding: '7px 12px', border: 0, borderRadius: 6, background: 'var(--accent)', color: 'var(--on-accent)', fontWeight: 700, cursor: 'pointer' }
}
function muted(): React.CSSProperties {
  return { fontSize: 11, color: 'var(--text-2)' }
}
