import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { LaunchConfig, LaunchResponse, ScenarioPreset } from '../api/types'
import { TopBar } from '../components/shared/TopBar'

type ChallengeCase = { id: string; preset: string; gravity: number; label: string }
type ChallengePack = { pack_id: string; status: string; cases: ChallengeCase[] }

const STARTERS: Record<string, { image: string; question: string }> = {
  bridge_builder: { image: '/presets/bridge-builder.png', question: 'Can a bridge carry the crate across the gap?' },
  sorter: { image: '/presets/sorter.png', question: 'Can ramps guide each ball into its matching bin?' },
}

export function WelcomeScreen() {
  const navigate = useNavigate()
  const [presets, setPresets] = useState<ScenarioPreset[]>([])
  const [pack, setPack] = useState<ChallengePack | null>(null)
  const [cases, setCases] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [launching, setLaunching] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.get<ScenarioPreset[]>('/presets'), api.get<ChallengePack>('/challenge-pack')])
      .then(([items, challengePack]) => {
        setPresets(items.filter((item) => item.id in STARTERS))
        setPack(challengePack)
      })
      .catch(() => setError('Could not load challenges. Check that the local server is running.'))
  }, [])

  async function runOffline(preset: ScenarioPreset) {
    if (launching) return
    setLaunching(preset.id)
    setError(null)
    try {
      // Resolve a fresh, versioned instance without modifying the saved workspace.
      const caseId = cases[preset.id] ?? `${preset.id}-standard`
      const config = await api.get<LaunchConfig>(`/challenge-pack/${encodeURIComponent(caseId)}`)
      const { run_id } = await api.post<LaunchResponse>('/setup/launch', config)
      navigate(`/studio/${run_id}`)
    } catch (err) {
      const detail = err instanceof ApiError ? err.body as { detail?: { missing?: string[] } } | null : null
      setError(detail?.detail?.missing?.join('; ') || 'The offline example could not start. Check the server and try again.')
      setLaunching(null)
    }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <TopBar status={error ? 'offline' : presets.length ? 'online' : 'connecting'} />
      <main style={{ flex: 1, overflowY: 'auto', padding: 'clamp(20px, 5vw, 56px)' }}>
        <div style={{ maxWidth: 1000, margin: 'auto' }}>
          <p style={{ color: 'var(--accent)', fontWeight: 700, fontSize: 12 }}>AI AGENTS · PHYSICS · REPLAY</p>
          <h1 style={{ fontSize: 'clamp(26px, 4vw, 42px)', margin: '8px 0 12px' }}>Watch an agent build. See what happens.</h1>
          <p style={{ color: 'var(--text-2)', maxWidth: 680, lineHeight: 1.6 }}>
            Choose a challenge to run a scripted offline example, then inspect the design, physics, and score.
            Connect a model when you are ready to try your own agent.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, margin: '22px 0 32px' }}>
            <a href="https://raw.githubusercontent.com/oney-erge/AgentGymnasium/main/docs/assets/demo.gif" target="_blank" rel="noreferrer" style={secondary()}>
              Watch recorded example ↗
            </a>
            <Link to="/setup" style={secondary()}>Connect a model or customize</Link>
            <Link to="/history" style={secondary()}>Open run history</Link>
          </div>
          {error && <p role="alert" style={{ color: 'var(--danger)' }}>{error}</p>}
          <h2 style={{ fontSize: 18, marginBottom: 12 }}>Start with a challenge</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
            {presets.map((preset) => (
              <article key={preset.id} style={{ border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden', background: 'var(--surface-1)' }}>
                <img src={STARTERS[preset.id].image} alt="" style={{ width: '100%', height: 160, objectFit: 'cover', display: 'block' }} />
                <div style={{ padding: 18 }}>
                  <h3 style={{ margin: '0 0 6px' }}>{preset.name}</h3>
                  <p style={{ color: 'var(--text-2)', minHeight: 40 }}>{STARTERS[preset.id].question}</p>
                  <label style={{ display: 'block', color: 'var(--text-2)', marginBottom: 10, fontSize: 12 }}>
                    Physical instance{' '}
                    <select value={cases[preset.id] ?? `${preset.id}-standard`} onChange={(e) => setCases({ ...cases, [preset.id]: e.target.value })}>
                      {pack?.cases.filter((item) => item.preset === preset.id).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                    </select>
                  </label>
                  <button onClick={() => void runOffline(preset)} disabled={launching !== null} style={{ ...secondary(), background: 'var(--accent)', color: 'var(--on-accent)', border: 0 }}>
                    {launching === preset.id ? 'Starting…' : 'Run offline example'}
                  </button>
                  <p style={{ color: 'var(--text-2)', fontSize: 11, marginTop: 10 }}>Scripted mock agent · one attempt · no API key</p>
                  <Link to={`/setup?case=${encodeURIComponent(cases[preset.id] ?? `${preset.id}-standard`)}`} style={{ color: 'var(--accent)', fontSize: 12 }}>
                    Configure a model for this instance →
                  </Link>
                </div>
              </article>
            ))}
          </div>
          {pack && <p style={{ color: 'var(--text-2)', fontSize: 11, marginTop: 16 }}>{pack.pack_id}: experimental starter cases, not validated reference solutions.</p>}
        </div>
      </main>
    </div>
  )
}

function secondary(): React.CSSProperties {
  return { padding: '9px 12px', border: '1px solid var(--border)', borderRadius: 7, color: 'var(--text-1)', textDecoration: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600, background: 'var(--surface-1)' }
}
