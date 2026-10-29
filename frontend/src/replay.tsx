import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import type { EpisodeTrace, ScoreCard } from './api/types'
import { WorldView } from './components/studio/WorldView'
import './index.css'

declare global {
  interface Window {
    AGENTGYMNASIUM_REPLAY: { trace: EpisodeTrace; score: ScoreCard | null }
  }
}

function Replay() {
  const { trace, score } = window.AGENTGYMNASIUM_REPLAY
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const duration = trace.frames.at(-1)?.t ?? 0

  useEffect(() => {
    if (!playing) return
    let previous = performance.now()
    const timer = window.setInterval(() => {
      const now = performance.now()
      const delta = (now - previous) / 1000
      previous = now
      setTime((current) => Math.min(duration, current + delta))
    }, 33)
    return () => window.clearInterval(timer)
  }, [playing, duration])

  useEffect(() => {
    if (time >= duration) setPlaying(false)
  }, [time, duration])

  let low = 0
  let high = trace.frames.length - 1
  while (low < high) {
    const mid = Math.ceil((low + high) / 2)
    if (trace.frames[mid].t <= time) low = mid
    else high = mid - 1
  }

  return (
    <main style={{ height: '100%', display: 'flex', flexDirection: 'column', padding: 16, gap: 12 }}>
      <header>
        <h1 style={{ fontSize: 20 }}>AgentGymnasium recorded replay</h1>
        <p style={{ color: 'var(--text-2)' }}>
          {trace.run_id} · {trace.engine} · {score ? `${score.success ? 'Success' : 'Not successful'} · score ${score.score_total.toFixed(2)}` : 'No score recorded'}
        </p>
        <p style={{ color: 'var(--text-2)', fontSize: 11 }}>Recorded frames only; no simulation or model runs in this page.</p>
      </header>
      <div style={{ flex: 1, minHeight: 240, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        <WorldView trace={trace} frameIndex={Math.max(0, low)} />
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <button onClick={() => { if (time >= duration) setTime(0); setPlaying(!playing) }} style={{ padding: '6px 12px' }}>
          {playing ? 'Pause' : 'Play'}
        </button>
        <input type="range" aria-label="Replay time" min={0} max={duration || 1} step="any" value={time} onChange={(e) => setTime(Number(e.target.value))} style={{ flex: 1 }} />
        <span>{time.toFixed(2)} / {duration.toFixed(2)} s</span>
      </div>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(<Replay />)
