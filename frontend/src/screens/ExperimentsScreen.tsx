import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type {
  ExperimentAggregate,
  ExperimentPairwise,
  ExperimentRecord,
  ExperimentSpec,
  LaunchConfig,
  LLMProvider,
  WorkspaceConfigResponse,
} from '../api/types'
import { TopBar } from '../components/shared/TopBar'

export function ExperimentsScreen() {
  const [baseConfig, setBaseConfig] = useState<LaunchConfig | null>(null)
  const [records, setRecords] = useState<ExperimentRecord[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [aggregates, setAggregates] = useState<ExperimentAggregate[]>([])
  const [pairwise, setPairwise] = useState<ExperimentPairwise[]>([])
  const [name, setName] = useState('LLM physical reasoning comparison')
  const [provider, setProvider] = useState<LLMProvider>('mock')
  const [models, setModels] = useState('mock-a\nmock-b')
  const [endpoint, setEndpoint] = useState('http://127.0.0.1:8000/v1')
  const [apiKey, setApiKey] = useState('')
  const [resumeKeys, setResumeKeys] = useState<Record<string, string>>({})
  const [seeds, setSeeds] = useState('7, 11, 42')
  const [repeats, setRepeats] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selected = records.find((record) => record.id === selectedId) ?? records[0]
  const active = records.some((record) => record.status === 'queued' || record.status === 'running')

  const refresh = useCallback(async () => {
    try {
      const next = await api.get<ExperimentRecord[]>('/experiments')
      setRecords(next)
      setSelectedId((current) => current ?? next[0]?.id ?? null)
      setError(null)
    } catch {
      setError('Could not load experiments.')
    }
  }, [])

  useEffect(() => {
    void Promise.all([
      api.get<WorkspaceConfigResponse>('/setup/workspace-config').then((response) => {
        setBaseConfig(response.config)
        const agent = response.config.agents?.participants?.[0]
        if (agent?.provider) setProvider(agent.provider)
        if (agent?.model) setModels(`${agent.model}\nmock`)
        if (agent?.endpoint_url) setEndpoint(agent.endpoint_url)
      }),
      api.get<ExperimentRecord[]>('/experiments').then((next) => {
        setRecords(next)
        setSelectedId(next[0]?.id ?? null)
      }),
    ])
  }, [refresh])

  useEffect(() => {
    if (!active) return
    const id = window.setInterval(() => void refresh(), 1000)
    return () => window.clearInterval(id)
  }, [active, refresh])

  useEffect(() => {
    if (!selected?.id) return
    void Promise.all([
      api
        .get<ExperimentAggregate[]>(`/experiments/${selected.id}/aggregates`)
        .then(setAggregates),
      api
        .get<ExperimentPairwise[]>(`/experiments/${selected.id}/pairwise`)
        .then(setPairwise),
    ]).catch(() => {
      setAggregates([])
      setPairwise([])
    })
  }, [selected?.id, selected?.status])

  const progress = useMemo(() => {
    if (!selected || selected.cells.length === 0) return 0
    const done = selected.cells.filter((cell) =>
      ['completed', 'failed', 'cancelled'].includes(cell.status),
    ).length
    return done / selected.cells.length
  }, [selected])

  async function launch(event: React.FormEvent) {
    event.preventDefault()
    if (!baseConfig || busy) return
    const modelIds = models
      .split(/[\n,]/)
      .map((value) => value.trim())
      .filter(Boolean)
    const seedValues = seeds
      .split(',')
      .map((value) => Number(value.trim()))
      .filter(Number.isFinite)
      .map(Math.trunc)
    if (modelIds.length === 0 || seedValues.length === 0) {
      setError('Enter at least one model and one numeric seed.')
      return
    }
    const spec: ExperimentSpec = {
      name,
      base_config: baseConfig,
      models: modelIds.map((model, index) => ({
        id: `model-${index + 1}`,
        label: model,
        provider,
        model,
        endpoint_url: provider === 'mock' ? null : endpoint,
        api_key: apiKey || null,
        temperature: baseConfig.agents?.participants?.[0]?.temperature ?? 0.2,
      })),
      seeds: seedValues,
      repeats,
    }
    setBusy(true)
    setError(null)
    try {
      const created = await api.post<ExperimentRecord>('/experiments', spec)
      setSelectedId(created.id)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Experiment launch failed.')
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    if (!selected) return
    await api.post(`/experiments/${selected.id}/cancel`, {})
    await refresh()
  }

  async function resume() {
    if (!selected || busy) return
    setBusy(true)
    setError(null)
    try {
      const pendingIds = new Set(selected.cells.filter((cell) => cell.status === 'queued').map((cell) => cell.model_variant_id))
      const apiKeys = Object.fromEntries([...pendingIds].map((id) => [id, resumeKeys[`${selected.id}:${id}`]]).filter(([, value]) => value))
      await api.post(`/experiments/${selected.id}/resume`, { api_keys: apiKeys })
      setResumeKeys({})
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not resume experiment.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <TopBar projectName="Experiments" status={error ? 'offline' : 'online'} />
      <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 360px) 1fr', gap: 16 }}>
          <form onSubmit={(event) => void launch(event)} style={panel()}>
            <h1 style={title()}>New model comparison</h1>
            <p style={muted()}>
              Every model receives the same task, tools, seeds, and attempt budget.
            </p>
            <Field label="Experiment name">
              <input value={name} onChange={(e) => setName(e.target.value)} style={input()} />
            </Field>
            <Field label="Provider protocol">
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value as LLMProvider)}
                style={input()}
              >
                <option value="mock">Mock / offline</option>
                <option value="localdeploy">LocalDeploy</option>
                <option value="openai_compatible">OpenAI-compatible</option>
              </select>
            </Field>
            <Field label="Models (one per line)">
              <textarea
                value={models}
                onChange={(e) => setModels(e.target.value)}
                rows={4}
                style={{ ...input(), resize: 'vertical' }}
              />
            </Field>
            {provider !== 'mock' && (
              <>
                <Field label="Endpoint">
                  <input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} style={input()} />
                </Field>
                <Field label="API key (never persisted)">
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    style={input()}
                  />
                </Field>
              </>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px', gap: 8 }}>
              <Field label="Paired seeds">
                <input value={seeds} onChange={(e) => setSeeds(e.target.value)} style={input()} />
              </Field>
              <Field label="Repeats">
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={repeats}
                  onChange={(e) => setRepeats(Math.max(1, Number(e.target.value)))}
                  style={input()}
                />
              </Field>
            </div>
            {error && <div style={{ color: 'var(--danger)', fontSize: 11 }}>{error}</div>}
            <button disabled={!baseConfig || busy} style={primary()}>
              {busy ? 'Scheduling…' : 'Run experiment'}
            </button>
          </form>

          <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
            <section style={panel()}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                <div>
                  <h2 style={title()}>{selected?.spec.name ?? 'No experiments yet'}</h2>
                  {selected && (
                    <p style={muted()}>
                      {selected.status} · {Math.round(progress * 100)}% · {selected.cells.length} cells
                    </p>
                  )}
                </div>
                {selected && ['queued', 'running'].includes(selected.status) && (
                  <button type="button" onClick={() => void cancel()} style={secondary()}>
                    Cancel after current cell
                  </button>
                )}
              </div>
              {selected?.interrupted && (
                <div style={muted()}>
                  <p>The server restarted. Any in-flight cell was not retried and may have incurred a provider charge. Completed cells are preserved.</p>
                  {selected.recovery_safe && selected.cells.some((cell) => cell.status === 'queued') ? (
                    <>
                      <p>Resume only the remaining queued cells. Provider calls may incur charges. Re-enter keys if needed; they are not saved.</p>
                      {selected.spec.models.filter((model) => model.provider !== 'mock' && selected.cells.some((cell) => cell.status === 'queued' && cell.model_variant_id === model.id)).map((model) => (
                        <Field key={model.id} label={`API key for ${model.label} (optional)`}>
                          <input type="password" value={resumeKeys[`${selected.id}:${model.id}`] ?? ''} onChange={(event) => setResumeKeys((keys) => ({ ...keys, [`${selected.id}:${model.id}`]: event.target.value }))} style={input()} />
                        </Field>
                      ))}
                      <button type="button" disabled={busy} onClick={() => void resume()} style={secondary()}>Resume queued cells</button>
                    </>
                  ) : selected.recovery_safe ? <p>No queued cells remain to resume.</p> : <p>This older experiment cannot be resumed safely; start a new one if needed.</p>}
                </div>
              )}
              <div style={{ height: 6, background: 'var(--surface-2)', borderRadius: 8, marginTop: 12 }}>
                <div
                  style={{
                    height: '100%',
                    width: `${progress * 100}%`,
                    borderRadius: 8,
                    background: 'var(--accent)',
                  }}
                />
              </div>
              {aggregates.length > 0 && (
                <>
                <p style={muted()}>95% intervals use Student-t and assume independent observations.
                  Fewer than five observations are preliminary; one observation has no interval.</p>
                <table style={table()}>
                  <thead>
                    <tr><Th>Model</Th><Th>n</Th><Th>Success</Th><Th>Mean ± SD</Th><Th>95% CI</Th><Th>Tokens</Th><Th>Latency</Th></tr>
                  </thead>
                  <tbody>
                    {aggregates.map((aggregate) => (
                      <tr key={aggregate.model_variant_id}>
                        <Td>{aggregate.model_label}</Td>
                        <Td>{aggregate.n}</Td>
                        <Td>{(aggregate.success_rate * 100).toFixed(0)}%</Td>
                        <Td>{aggregate.mean_score.toFixed(1)} ± {aggregate.stddev_score.toFixed(1)}</Td>
                        <Td>{aggregate.ci95_low == null || aggregate.ci95_high == null ? 'n < 2' : `${aggregate.ci95_low.toFixed(1)}–${aggregate.ci95_high.toFixed(1)}`}</Td>
                        <Td>{aggregate.mean_tokens.toFixed(0)}</Td>
                        <Td>{aggregate.mean_latency_ms.toFixed(0)}ms</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </>
              )}
              {pairwise.some((comparison) => comparison.n_pairs > 0) && (
                <>
                  <h3 style={{ ...title(), marginTop: 8 }}>Paired seed comparisons</h3>
                  <table style={table()}>
                    <thead>
                      <tr><Th>Models</Th><Th>Pairs</Th><Th>W / T / L</Th><Th>Mean Δ</Th><Th>95% CI</Th></tr>
                    </thead>
                    <tbody>
                      {pairwise.filter((comparison) => comparison.n_pairs > 0).map((comparison) => (
                        <tr key={`${comparison.model_a_id}-${comparison.model_b_id}`}>
                          <Td>{comparison.model_a_label} − {comparison.model_b_label}</Td>
                          <Td>{comparison.n_pairs}</Td>
                          <Td>{comparison.wins_a} / {comparison.ties} / {comparison.wins_b}</Td>
                          <Td>{comparison.mean_score_delta.toFixed(2)}</Td>
                          <Td>{comparison.ci95_low == null || comparison.ci95_high == null ? 'n < 2' : `${comparison.ci95_low.toFixed(2)}…${comparison.ci95_high.toFixed(2)}`}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </section>

            {selected && (
              <section style={panel()}>
                <h2 style={title()}>Trials</h2>
                <table style={table()}>
                  <thead><tr><Th>Model</Th><Th>Seed</Th><Th>Repeat</Th><Th>Status</Th><Th>Score</Th><Th>Result</Th></tr></thead>
                  <tbody>
                    {selected.cells.map((cell) => (
                      <tr key={cell.id}>
                        <Td>{cell.model_label}</Td><Td>{cell.seed}</Td><Td>{cell.repeat_index + 1}</Td>
                        <Td>{cell.status}</Td><Td>{cell.score?.toFixed(1) ?? '—'}</Td>
                        <Td>
                          {cell.trace_run_id ? (
                            <Link to={`/studio/${cell.trace_run_id}`} style={{ color: 'var(--accent)' }}>
                              Replay
                            </Link>
                          ) : cell.error ?? '—'}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}

            {records.length > 0 && (
              <section style={panel()}>
                <h2 style={title()}>Previous experiments</h2>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {records.map((record) => (
                    <button
                      key={record.id}
                      type="button"
                      onClick={() => setSelectedId(record.id)}
                      style={record.id === selected?.id ? primary() : secondary()}
                    >
                      {record.spec.name} · {record.status}
                    </button>
                  ))}
                </div>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label style={{ display: 'grid', gap: 4 }}><span style={muted()}>{label}</span>{children}</label>
}
function Th({ children }: { children: React.ReactNode }) {
  return <th style={{ padding: '7px 8px', textAlign: 'left', color: 'var(--text-2)' }}>{children}</th>
}
function Td({ children }: { children: React.ReactNode }) {
  return <td style={{ padding: '7px 8px', borderTop: '1px solid var(--border)' }}>{children}</td>
}
function panel(): React.CSSProperties {
  return { display: 'grid', gap: 10, padding: 16, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--surface-1)', overflow: 'auto' }
}
function input(): React.CSSProperties {
  return { width: '100%', padding: '7px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--surface-2)', color: 'var(--text-1)' }
}
function primary(): React.CSSProperties {
  return { padding: '7px 11px', border: 0, borderRadius: 6, background: 'var(--accent)', color: 'var(--on-accent)', fontWeight: 700, cursor: 'pointer' }
}
function secondary(): React.CSSProperties {
  return { padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface-2)', color: 'var(--text-1)', cursor: 'pointer' }
}
function title(): React.CSSProperties {
  return { fontSize: 16, color: 'var(--text-1)', fontWeight: 700 }
}
function muted(): React.CSSProperties {
  return { fontSize: 11, color: 'var(--text-2)' }
}
function table(): React.CSSProperties {
  return { width: '100%', borderCollapse: 'collapse', fontSize: 11, marginTop: 8 }
}
