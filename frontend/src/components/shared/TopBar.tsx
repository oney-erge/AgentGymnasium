import { Link } from 'react-router-dom'

type ConnectionStatus = 'online' | 'offline' | 'connecting'

interface TopBarProps {
  projectName?: string
  status?: ConnectionStatus
}

const STATUS_META: Record<ConnectionStatus, { color: string; label: string }> = {
  online: { color: 'var(--ok)', label: 'Connected' },
  connecting: { color: 'var(--warn)', label: 'Connecting…' },
  offline: { color: 'var(--danger)', label: 'Server offline' },
}

export function TopBar({ projectName = 'AgentGymnasium', status = 'connecting' }: TopBarProps) {
  const meta = STATUS_META[status]
  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        height: 44,
        background: 'var(--surface-1)',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}
    >
      {/* Left: wordmark (→ home/setup) + project */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Link
          to="/setup"
          title="Back to Simulation Setup"
          style={{
            color: 'var(--accent)',
            fontWeight: 700,
            fontSize: 15,
            letterSpacing: '-0.3px',
            textDecoration: 'none',
          }}
        >
          AgentGymnasium
        </Link>
        {projectName !== 'AgentGymnasium' && (
          <>
            <span style={{ color: 'var(--border)' }}>›</span>
            <span style={{ color: 'var(--text-2)', fontSize: 12 }}>{projectName}</span>
          </>
        )}
      </div>

      {/* Right: status + actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <span style={{ fontSize: 11, color: meta.color, display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: meta.color, display: 'inline-block' }} />
          {meta.label}
        </span>
        <Link
          to="/setup"
          style={{
            color: 'var(--accent)',
            fontSize: 12,
            fontWeight: 600,
            textDecoration: 'none',
            border: '1px solid var(--accent)',
            borderRadius: 6,
            padding: '3px 10px',
          }}
        >
          + New Simulation
        </Link>
        <Link to="/history" style={{ color: 'var(--text-2)', fontSize: 12, textDecoration: 'none' }}>
          History
        </Link>
        <Link to="/experiments" style={{ color: 'var(--text-2)', fontSize: 12, textDecoration: 'none' }}>
          Experiments
        </Link>
        <Link to="/compare" style={{ color: 'var(--text-2)', fontSize: 12, textDecoration: 'none' }}>
          Compare
        </Link>
        <Link to="/physical" style={{ color: 'var(--text-2)', fontSize: 12, textDecoration: 'none' }}>
          Physical Lab
        </Link>
        <Link to="/visuals" style={{ color: 'var(--text-2)', fontSize: 12, textDecoration: 'none' }}>
          Visuals
        </Link>
        <a
          href="https://github.com/oney-erge/agentarium#readme"
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: 'var(--text-2)', fontSize: 12, textDecoration: 'none' }}
        >
          Docs
        </a>
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: '50%',
            background: 'var(--accent-soft)',
            border: '1px solid var(--accent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 11,
            color: 'var(--accent)',
            fontWeight: 600,
          }}
        >
          AD
        </div>
      </div>
    </header>
  )
}
