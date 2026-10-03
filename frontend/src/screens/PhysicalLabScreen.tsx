import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type {
  EmbodimentActionReceipt,
  EmbodimentDevice,
  EmbodimentEpisodeResult,
  EmbodimentEvent,
  EmbodimentObservation,
  LLMProvider,
} from '../api/types'
import { PhysicalWorkspaceMap } from '../components/physical/PhysicalWorkspaceMap'
import { TopBar } from '../components/shared/TopBar'

type ArmResponse = {
  device_id: string
  control_token: string
  heartbeat_timeout_s: number
}

export function PhysicalLabScreen() {
  const [devices, setDevices] = useState<EmbodimentDevice[]>([])
  const [deviceId, setDeviceId] = useState('')
  const [observation, setObservation] = useState<EmbodimentObservation | null>(null)
  const [poseTrail, setPoseTrail] = useState<EmbodimentObservation[]>([])
  const [events, setEvents] = useState<EmbodimentEvent[]>([])
  const [controlToken, setControlToken] = useState<string | null>(null)
  const [operatorKey, setOperatorKey] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [targetX, setTargetX] = useState(0.5)
  const [targetY, setTargetY] = useState(0)
  const [speed, setSpeed] = useState(0.25)
  const [duration, setDuration] = useState(1)
  const [missionObjective, setMissionObjective] = useState('Reach the target safely.')
  const [modelProvider, setModelProvider] = useState<LLMProvider>('mock')
  const [modelName, setModelName] = useState('mock')
  const [modelEndpoint, setModelEndpoint] = useState('http://127.0.0.1:8000/v1')
  const [modelApiKey, setModelApiKey] = useState('')
  const [missionResult, setMissionResult] = useState<EmbodimentEpisodeResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const device = devices.find((item) => item.id === deviceId) ?? devices[0]
  const armed = device?.safety_state === 'armed' && Boolean(controlToken)

  const acceptObservation = useCallback((next: EmbodimentObservation | null) => {
    setObservation(next)
    if (!next) return
    setPoseTrail((current) => {
      if (current.at(-1)?.sequence === next.sequence) return current
      return [...current, next].slice(-80)
    })
  }, [])

  const refresh = useCallback(async () => {
    const next = await api.get<EmbodimentDevice[]>('/embodiments')
    setDevices(next)
    setDeviceId((current) => current || next[0]?.id || '')
    const selected = next.find((item) => item.id === deviceId) ?? next[0]
    if (!selected) return
    const [nextObservation, nextEvents] = await Promise.all([
      api.get<EmbodimentObservation>(`/embodiments/${selected.id}/observation`),
      api.get<EmbodimentEvent[]>(`/embodiments/events?device_id=${selected.id}&limit=30`),
    ])
    acceptObservation(nextObservation)
    setEvents(nextEvents)
    if (selected.safety_state !== 'armed') setControlToken(null)
  }, [acceptObservation, deviceId])

  useEffect(() => {
    void api.get<EmbodimentDevice[]>('/embodiments').then((next) => {
      setDevices(next)
      setDeviceId(next[0]?.id ?? '')
    })
  }, [])

  useEffect(() => {
    if (!deviceId) return
    const id = window.setInterval(() => void refresh().catch(() => setError('Device poll failed.')), 750)
    return () => window.clearInterval(id)
  }, [deviceId, refresh])

  useEffect(() => {
    if (!deviceId || !controlToken) return
    const timeoutMs = Math.max(200, (device?.limits.heartbeat_timeout_s ?? 2) * 350)
    const id = window.setInterval(() => {
      void api
        .post(`/embodiments/${deviceId}/heartbeat`, {}, controlHeaders(controlToken))
        .catch(() => {
          setControlToken(null)
          setError('Control heartbeat failed; the watchdog will emergency-stop the device.')
        })
    }, timeoutMs)
    return () => window.clearInterval(id)
  }, [controlToken, device?.limits.heartbeat_timeout_s, deviceId])

  function explain(err: unknown): string {
    if (err instanceof ApiError && typeof err.body === 'object' && err.body) {
      const detail = (err.body as { detail?: unknown }).detail
      if (typeof detail === 'string') return detail
    }
    return err instanceof Error ? err.message : 'Physical command failed.'
  }

  async function arm() {
    if (!device || busy) return
    setBusy(true)
    setError(null)
    try {
      const response = await api.post<ArmResponse>(
        `/embodiments/${device.id}/arm`,
        { confirmation },
        operatorHeaders(operatorKey),
      )
      setControlToken(response.control_token)
      setConfirmation('')
      await refresh()
    } catch (err) {
      setError(explain(err))
    } finally {
      setBusy(false)
    }
  }

  async function move() {
    if (!device || !controlToken || busy) return
    setBusy(true)
    setError(null)
    try {
      const receipt = await api.post<EmbodimentActionReceipt>(
        `/embodiments/${device.id}/actions`,
        {
          kind: 'drive_to',
          target_x: targetX,
          target_y: targetY,
          max_speed_mps: speed,
          duration_s: duration,
        },
        controlHeaders(controlToken),
      )
      acceptObservation(receipt.observation)
      await refresh()
    } catch (err) {
      setError(explain(err))
    } finally {
      setBusy(false)
    }
  }

  async function stop() {
    if (!device) return
    setBusy(true)
    try {
      await api.post(`/embodiments/${device.id}/emergency-stop`, {})
      setControlToken(null)
      await refresh()
    } catch (err) {
      setError(explain(err))
    } finally {
      setBusy(false)
    }
  }

  async function resetEmergencyStop() {
    if (!device) return
    setBusy(true)
    try {
      await api.post(
        `/embodiments/${device.id}/reset-emergency-stop`,
        { confirmation: `RESET ESTOP ${device.id}` },
        operatorHeaders(operatorKey),
      )
      await refresh()
    } catch (err) {
      setError(explain(err))
    } finally {
      setBusy(false)
    }
  }

  async function disarm() {
    if (!device || !controlToken) return
    setBusy(true)
    try {
      await api.post(`/embodiments/${device.id}/disarm`, {}, controlHeaders(controlToken))
      setControlToken(null)
      await refresh()
    } catch (err) {
      setError(explain(err))
    } finally {
      setBusy(false)
    }
  }

  async function runMission() {
    if (!device || !controlToken || busy) return
    setBusy(true)
    setError(null)
    setMissionResult(null)
    try {
      const result = await api.post<EmbodimentEpisodeResult>(
        `/embodiments/${device.id}/episodes`,
        {
          objective: missionObjective,
          goal: { x: targetX, y: targetY, heading_rad: 0 },
          tolerance_m: 0.15,
          max_turns: 4,
          reset_before_run:
            device.mode !== 'real' && device.mode !== 'hardware_in_the_loop',
          seed: 7,
          agent: {
            id: 'physical-pilot',
            name: 'Physical Pilot',
            provider: modelProvider,
            model: modelName,
            endpoint_url: modelProvider === 'mock' ? null : modelEndpoint,
            api_key: modelApiKey || null,
            temperature: 0.2,
          },
        },
        controlHeaders(controlToken),
      )
      setMissionResult(result)
      setObservation(result.observations.at(-1) ?? null)
      setPoseTrail(result.observations.slice(-80))
      await refresh()
    } catch (err) {
      setError(explain(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <TopBar projectName="Physical Lab" status={error ? 'offline' : 'online'} />
      <div style={{ flex: 1, overflow: 'auto', padding: 18 }}>
        <div style={{ maxWidth: 1180, margin: '0 auto', display: 'grid', gap: 14 }}>
          <div style={{ ...panel(), borderColor: 'var(--warn)' }}>
            <strong style={{ color: 'var(--warn)' }}>Experimental embodiment boundary</strong>
            <span style={muted()}>
              AgentGymnasium only sends bounded, high-level actions. Real hardware must independently
              enforce a robot-side watchdog, actuator limits, collision avoidance, and a physical
              emergency stop. This software is not a certified safety controller.
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 360px) 1fr', gap: 14 }}>
            <section style={panel()}>
              <h1 style={title()}>Device & safety interlock</h1>
              <select
                value={device?.id ?? ''}
                onChange={(event) => {
                  setDeviceId(event.target.value)
                  setPoseTrail([])
                  setObservation(null)
                }}
                style={input()}
              >
                {devices.map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
              {device && (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7 }}>
                    <Stat label="Adapter" value={device.adapter} />
                    <Stat label="Mode" value={device.mode} />
                    <Stat label="Safety state" value={device.safety_state} />
                    <Stat label="Watchdog" value={`${device.limits.heartbeat_timeout_s}s`} />
                  </div>
                  {device.safety_state === 'disarmed' && (
                    <>
                      {(device.mode === 'real' || device.mode === 'hardware_in_the_loop') && (
                        <label style={field()}>
                          <span style={muted()}>Operator key (memory only)</span>
                          <input
                            type="password"
                            value={operatorKey}
                            onChange={(event) => setOperatorKey(event.target.value)}
                            style={input()}
                          />
                        </label>
                      )}
                      <label style={field()}>
                        <span style={muted()}>Type “ARM {device.id}”</span>
                        <input
                          value={confirmation}
                          onChange={(event) => setConfirmation(event.target.value)}
                          style={input()}
                        />
                      </label>
                      <button
                        type="button"
                        disabled={busy || confirmation !== `ARM ${device.id}`}
                        onClick={() => void arm()}
                        style={primary()}
                      >
                        Arm control session
                      </button>
                    </>
                  )}
                  {device.safety_state === 'armed' && (
                    <button type="button" disabled={!armed || busy} onClick={() => void disarm()} style={secondary()}>
                      Stop and disarm
                    </button>
                  )}
                  {device.safety_state === 'emergency_stopped' && (
                    <button type="button" disabled={busy} onClick={() => void resetEmergencyStop()} style={secondary()}>
                      Reset latched emergency stop
                    </button>
                  )}
                  <button type="button" disabled={busy} onClick={() => void stop()} style={estop()}>
                    EMERGENCY STOP
                  </button>
                </>
              )}
              {error && <div style={{ color: 'var(--danger)', fontSize: 11 }}>{error}</div>}
            </section>

            <section style={panel()}>
              <h2 style={title()}>Geofenced workspace</h2>
              {device && (
                <PhysicalWorkspaceMap
                  device={device}
                  observation={observation}
                  trail={poseTrail}
                  target={{ x: targetX, y: targetY }}
                />
              )}
              <p style={muted()}>
                X {device?.limits.min_x ?? '—'}…{device?.limits.max_x ?? '—'} m · Y{' '}
                {device?.limits.min_y ?? '—'}…{device?.limits.max_y ?? '—'} m · pose{' '}
                {observation ? `(${observation.pose.x.toFixed(2)}, ${observation.pose.y.toFixed(2)})` : '—'}
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 7 }}>
                <NumberField label="Target X" value={targetX} onChange={setTargetX} />
                <NumberField label="Target Y" value={targetY} onChange={setTargetY} />
                <NumberField label="Speed m/s" value={speed} onChange={setSpeed} />
                <NumberField label="Duration s" value={duration} onChange={setDuration} />
              </div>
              <button type="button" disabled={!armed || busy} onClick={() => void move()} style={primary()}>
                {busy ? 'Executing…' : 'Execute bounded drive_to'}
              </button>
            </section>
          </div>

          <section style={panel()}>
            <h2 style={title()}>LLM embodied episode</h2>
            <p style={muted()}>
              The model observes normalized device state and can choose only the same bounded
              drive_to / stop contract. Mock and shadow runs reset for comparable starting state;
              hardware-backed devices never software-reset.
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr 1fr', gap: 7 }}>
              <label style={field()}>
                <span style={muted()}>Objective</span>
                <input value={missionObjective} onChange={(event) => setMissionObjective(event.target.value)} style={input()} />
              </label>
              <label style={field()}>
                <span style={muted()}>Provider</span>
                <select value={modelProvider} onChange={(event) => setModelProvider(event.target.value as LLMProvider)} style={input()}>
                  <option value="mock">Mock / offline</option>
                  <option value="localdeploy">LocalDeploy</option>
                  <option value="openai_compatible">OpenAI-compatible</option>
                </select>
              </label>
              <label style={field()}>
                <span style={muted()}>Model</span>
                <input value={modelName} onChange={(event) => setModelName(event.target.value)} style={input()} />
              </label>
            </div>
            {modelProvider !== 'mock' && (
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 7 }}>
                <label style={field()}>
                  <span style={muted()}>Model endpoint</span>
                  <input value={modelEndpoint} onChange={(event) => setModelEndpoint(event.target.value)} style={input()} />
                </label>
                <label style={field()}>
                  <span style={muted()}>Model API key (memory only)</span>
                  <input type="password" value={modelApiKey} onChange={(event) => setModelApiKey(event.target.value)} style={input()} />
                </label>
              </div>
            )}
            <button type="button" disabled={!armed || busy} onClick={() => void runMission()} style={primary()}>
              {busy ? 'Running bounded episode…' : `Run ${modelName} on target (${targetX}, ${targetY})`}
            </button>
            {missionResult && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 7 }}>
                <Stat label="Outcome" value={missionResult.success ? 'Reached target' : missionResult.error ?? 'Missed target'} />
                <Stat label="Score" value={missionResult.score.toFixed(1)} />
                <Stat label="Final distance" value={`${missionResult.final_distance_m.toFixed(3)}m`} />
                <Stat label="Model turns / actions" value={`${missionResult.interactions.length} / ${missionResult.actions.length}`} />
              </div>
            )}
          </section>

          <section style={panel()}>
            <h2 style={title()}>Session audit stream</h2>
            <div style={{ maxHeight: 240, overflow: 'auto', fontFamily: 'monospace', fontSize: 11 }}>
              {[...events].reverse().map((event, index) => (
                <div key={`${event.timestamp}-${index}`} style={{ padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ color: 'var(--text-2)' }}>{new Date(event.timestamp * 1000).toLocaleTimeString()} </span>
                  <strong>{event.event}</strong>{' '}
                  <span style={{ color: 'var(--text-2)' }}>{JSON.stringify(event.detail)}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

function controlHeaders(token: string): Record<string, string> {
  return { 'X-AgentGymnasium-Control-Token': token }
}
function operatorHeaders(key: string): Record<string, string> {
  return key ? { 'X-AgentGymnasium-Operator-Key': key } : {}
}
function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label style={field()}>
      <span style={muted()}>{label}</span>
      <input type="number" step="0.05" value={value} onChange={(event) => onChange(Number(event.target.value))} style={input()} />
    </label>
  )
}
function Stat({ label, value }: { label: string; value: string }) {
  return <div style={{ padding: 7, borderRadius: 6, background: 'var(--surface-2)' }}><span style={muted()}>{label}</span><div>{value}</div></div>
}
function panel(): React.CSSProperties {
  return { display: 'grid', gap: 10, alignContent: 'start', padding: 15, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--surface-1)' }
}
function field(): React.CSSProperties {
  return { display: 'grid', gap: 4 }
}
function input(): React.CSSProperties {
  return { width: '100%', padding: '7px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--surface-2)', color: 'var(--text-1)' }
}
function title(): React.CSSProperties {
  return { fontSize: 15, color: 'var(--text-1)' }
}
function muted(): React.CSSProperties {
  return { fontSize: 11, color: 'var(--text-2)' }
}
function primary(): React.CSSProperties {
  return { padding: '8px 11px', border: 0, borderRadius: 6, background: 'var(--accent)', color: 'var(--on-accent)', fontWeight: 700, cursor: 'pointer' }
}
function secondary(): React.CSSProperties {
  return { padding: '7px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface-2)', color: 'var(--text-1)', cursor: 'pointer' }
}
function estop(): React.CSSProperties {
  return { padding: 14, border: '2px solid #ff8a8a', borderRadius: 8, background: 'var(--danger)', color: 'white', fontWeight: 900, letterSpacing: 1, cursor: 'pointer' }
}
