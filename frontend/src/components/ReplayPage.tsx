import { useEffect, useState } from 'react'
import type { EpisodeTrace, ScoreCard } from '../api/types'
import { WorldView } from './studio/WorldView'

declare global {
  interface Window {
    AGENTGYMNASIUM_REPLAY: { trace: EpisodeTrace; score: ScoreCard | null }
  }
}

/** The standalone replay page: recorded frames, a play button and a time slider. */
export function ReplayPage() {
  const { trace, score } = window.AGENTGYMNASIUM_REPLAY
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const duration = trace.frames.at(-1)?.t ?? 0

  // Playing stops by itself at the end: the clock runs only while there is time left.
  const running = playing && time < duration

  useEffect(() => {
    if (!running) return
    let previous = performance.now()
    const timer = window.setInterval(() => {
      const now = performance.now()
      const delta = (now - previous) / 1000
      previous = now
      setTime((current) => Math.min(duration, current + delta))
    }, 33)
    return () => window.clearInterval(timer)
  }, [running, duration])

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
        <button
          onClick={() => {
            if (time >= duration) {
              setTime(0)
              setPlaying(true)
            } else setPlaying(!running)
          }}
          style={{ padding: '6px 12px' }}
        >
          {running ? 'Pause' : 'Play'}
        </button>
        <input type="range" aria-label="Replay time" min={0} max={duration || 1} step="any" value={time} onChange={(e) => setTime(Number(e.target.value))} style={{ flex: 1 }} />
        <span>{time.toFixed(2)} / {duration.toFixed(2)} s</span>
      </div>
    </main>
  )
}

