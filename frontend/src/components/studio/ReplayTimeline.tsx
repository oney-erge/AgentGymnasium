import type { Frame } from '../../api/types'

interface ReplayTimelineProps {
  frameIndex: number
  totalFrames: number
  playing: boolean
  onSeek: (frameIndex: number) => void
  onTogglePlay: () => void
  speed: number
  frames?: Frame[]
  attemptLabel?: string
  onExportVideo?: () => void
  videoExporting?: boolean
  videoMessage?: string | null
}

const TICK_COUNT = 5

/** Index of the frame whose time is closest to ``t`` seconds. */
function frameIndexAtTime(frames: Frame[], t: number): number {
  let best = 0
  let bestDelta = Infinity
  for (let i = 0; i < frames.length; i++) {
    const delta = Math.abs(frames[i].t - t)
    if (delta < bestDelta) {
      bestDelta = delta
      best = i
    }
  }
  return best
}

export function ReplayTimeline({
  frameIndex,
  totalFrames,
  playing,
  onSeek,
  onTogglePlay,
  speed,
  frames,
  attemptLabel,
  onExportVideo,
  videoExporting = false,
  videoMessage,
}: ReplayTimelineProps) {
  const max = Math.max(0, totalFrames - 1)
  const hasFrames = !!frames && frames.length > 0
  const currentTime = hasFrames ? (frames[Math.min(frameIndex, frames.length - 1)]?.t ?? 0) : 0
  const totalTime = hasFrames ? (frames[frames.length - 1]?.t ?? 0) : 0

  // Evenly spaced, clickable time ticks derived from the trace duration.
  const ticks = hasFrames
    ? Array.from({ length: TICK_COUNT }, (_, i) => (totalTime * i) / (TICK_COUNT - 1))
    : []
  const eventLabels: Record<string, string> = {
    contact_started: 'First contact',
    structure_stressed: 'Stress detected',
    body_destroyed: 'Body lost',
    goal_reached: 'Goal reached',
    object_sorted: 'Object sorted',
  }
  const seen = new Set<string>()
  const moments: { index: number; time: number; label: string }[] = []
  frames?.forEach((frame, index) => frame.events?.forEach((event) => {
    const label = eventLabels[event.type]
    if (label && !seen.has(event.type)) {
      seen.add(event.type)
      moments.push({ index, time: frame.t, label })
    }
  }))

  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: 'var(--text-2)',
          textTransform: 'uppercase',
          letterSpacing: '0.6px',
          marginBottom: 6,
        }}
      >
        Replay Timeline
      </div>

      <div
        style={{
          padding: 10,
          borderRadius: 6,
          border: '1px solid var(--border)',
          background: 'var(--surface-2)',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        {/* Attempt label + speed readout */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: 11, color: 'var(--text-1)', fontWeight: 600 }}>
            {attemptLabel ?? (hasFrames ? 'Replay' : 'No attempt loaded')}
          </span>
          <span
            style={{
              fontSize: 10,
              color: 'var(--text-2)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {speed.toFixed(2)}x
          </span>
        </div>

        {/* Scrubber + play/pause */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={onTogglePlay}
            title={playing ? 'Pause' : 'Play'}
            disabled={!hasFrames}
            style={{
              width: 26,
              height: 26,
              flexShrink: 0,
              borderRadius: 6,
              border: '1px solid var(--border)',
              background: 'var(--accent)',
              color: '#fff',
              fontSize: 12,
              lineHeight: 1,
              cursor: hasFrames ? 'pointer' : 'not-allowed',
              opacity: hasFrames ? 1 : 0.5,
            }}
          >
            {playing ? '❚❚' : '►'}
          </button>

          <input
            type="range"
            min={0}
            max={max}
            step={1}
            value={Math.min(frameIndex, max)}
            onChange={(e) => onSeek(Number(e.target.value))}
            disabled={!hasFrames}
            style={{ flex: 1, accentColor: 'var(--accent)' }}
          />

          <span
            style={{
              fontSize: 10,
              color: 'var(--text-2)',
              fontVariantNumeric: 'tabular-nums',
              width: 78,
              textAlign: 'right',
            }}
          >
            {hasFrames ? `${currentTime.toFixed(1)}s / ${totalTime.toFixed(1)}s` : `${frameIndex} / ${max}`}
          </span>
        </div>

        {/* Real time ticks — click to seek to that point in the replay. */}
        {hasFrames && (
          <div style={{ display: 'flex', gap: 6 }}>
            {ticks.map((t, i) => {
              const targetFrame = frameIndexAtTime(frames!, t)
              const active = Math.abs(targetFrame - frameIndex) <= 1
              return (
                <button
                  key={i}
                  title={`Seek to ${t.toFixed(1)}s`}
                  onClick={() => onSeek(targetFrame)}
                  style={{
                    flex: 1,
                    height: 26,
                    borderRadius: 4,
                    border: active ? '1px solid var(--accent)' : '1px solid var(--border)',
                    background: active ? 'var(--accent-soft)' : 'var(--surface-1)',
                    color: active ? 'var(--accent)' : 'var(--text-2)',
                    fontSize: 9,
                    fontVariantNumeric: 'tabular-nums',
                    cursor: 'pointer',
                  }}
                >
                  {t.toFixed(1)}s
                </button>
              )
            })}
          </div>
        )}

        {moments.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }} aria-label="Recorded events">
            {moments.map((moment) => (
              <button key={moment.label} onClick={() => onSeek(moment.index)}
                style={{ padding: '4px 6px', color: 'var(--text-1)', background: 'var(--surface-1)', border: '1px solid var(--border)', borderRadius: 4, fontSize: 10 }}>
                {moment.label} · {moment.time.toFixed(1)}s
              </button>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            onClick={onExportVideo}
            disabled={!hasFrames || !onExportVideo || videoExporting}
            title="Export replay video"
            style={{
              padding: '6px 9px',
              borderRadius: 5,
              border: '1px solid var(--border)',
              background: 'var(--surface-1)',
              color: 'var(--text-1)',
              fontSize: 10,
              fontWeight: 700,
              cursor: hasFrames && onExportVideo && !videoExporting ? 'pointer' : 'not-allowed',
              opacity: hasFrames && onExportVideo && !videoExporting ? 1 : 0.55,
            }}
          >
            {videoExporting ? 'Recording…' : 'Export WebM'}
          </button>
          {videoMessage && (
            <span style={{ fontSize: 10, color: 'var(--text-2)' }}>{videoMessage}</span>
          )}
        </div>
      </div>
    </div>
  )
}
