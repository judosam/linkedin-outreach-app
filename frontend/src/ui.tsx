import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { api } from './api'

export function Icon({ name, className = '' }: { name: string; className?: string }) {
  return <span className={`msym ${className}`} aria-hidden="true">{name}</span>
}

const TONES: Record<string, string> = {
  ok: 'text-ok-text bg-ok-bg border-ok-border',
  warn: 'text-warn-text bg-warn-bg border-warn-border',
  crit: 'text-crit-text bg-crit-bg border-crit-border',
  idle: 'text-idle-text bg-idle-bg border-idle-border',
  primary: 'text-primary bg-primary-subdued border-indigo-200',
}
const DOTS: Record<string, string> = {
  ok: 'bg-ok-dot', warn: 'bg-warn-dot', crit: 'bg-crit-dot', idle: 'bg-idle-dot', primary: 'bg-primary',
}

export function StatusPill({ tone, label, dot = true }: { tone: keyof typeof TONES; label: string; dot?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 h-5 px-2 rounded-full border text-label-code ${TONES[tone]}`}>
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${DOTS[tone]}`} aria-hidden="true" />}
      {label}
    </span>
  )
}

export function QuotaBar({ used, limit }: { used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0
  const color = pct >= 100 ? 'bg-crit-dot' : pct >= 80 ? 'bg-warn-dot' : 'bg-gradient-to-r from-primary to-indigo-500'
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="h-1 w-full min-w-16 rounded-full bg-hairline overflow-hidden" role="progressbar"
           aria-valuenow={used} aria-valuemin={0} aria-valuemax={limit}>
        <div className={`h-full rounded-full ${color} transition-all duration-300`} style={{ width: `${pct}%` }} />
      </div>
      <span className="mono text-metric-sm text-slate-600 whitespace-nowrap">{used}/{limit}</span>
    </div>
  )
}

export function EmptyState({ icon, title, hint, action }: { icon: string; title: string; hint: string; action?: ReactNode }) {
  return (
    <div className="card p-10 text-center">
      <div className="mx-auto w-12 h-12 rounded-full bg-inset flex items-center justify-center text-slate-400">
        <Icon name={icon} className="!text-[24px]" />
      </div>
      <div className="mt-3 font-semibold text-slate-800">{title}</div>
      <div className="mt-1 text-slate-500 max-w-sm mx-auto">{hint}</div>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-slate-400" role="status">
      <span className="w-4 h-4 border-2 border-slate-300 border-t-primary rounded-full animate-spin" aria-hidden="true" />
      {label && <span>{label}</span>}
    </div>
  )
}

export function Toast({ message, onClose }: { message: string | null; onClose: () => void }) {
  useEffect(() => {
    if (!message) return
    const t = setTimeout(onClose, 4000)
    return () => clearTimeout(t)
  }, [message, onClose])
  if (!message) return null
  return (
    <div className="fixed bottom-5 right-5 z-50 max-w-sm card px-4 py-3 shadow-overlay text-[13px] text-slate-800" role="status" aria-live="polite">
      {message}
    </div>
  )
}

// ---------- App shell (dark sidebar + 48px command header) ----------

const NAV = [
  { to: '/', icon: 'grid_view', label: 'Dashboard' },
  { to: '/accounts', icon: 'manage_accounts', label: 'Accounts' },
  { to: '/campaigns', icon: 'rocket_launch', label: 'Campaigns' },
  { to: '/leads', icon: 'filter_alt', label: 'Leads' },
  { to: '/threads', icon: 'forum', label: 'Threads & Replies' },
  { to: '/jobs', icon: 'schedule', label: 'Jobs & Scheduler' },
  { to: '/settings', icon: 'tune', label: 'Settings' },
]

export function Shell({ children, title, subtitle, actions }: {
  children: ReactNode; title: string; subtitle?: string; actions?: ReactNode
}) {
  const navigate = useNavigate()
  const [live, setLive] = useState<{ job: string | null; status: string }>({ job: null, status: 'idle' })

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const data = await api.get<{ jobs: { running_now: boolean; key: string }[]; live: { job: string | null; status: string } }>('/api/jobs')
        if (alive) setLive({ job: data.live?.job ?? null, status: data.live?.status ?? 'idle' })
      } catch { /* logged out etc. */ }
    }
    poll()
    const t = setInterval(poll, 10000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  const logout = async () => {
    await api.post('/api/logout')
    navigate('/login')
  }

  return (
    <div className="min-h-screen flex">
      {/* Dark chrome sidebar */}
      <aside className="w-[240px] shrink-0 bg-chrome-900 text-slate-300 flex flex-col border-r border-chrome-800">
        <div className="h-12 flex items-center gap-2.5 px-4 border-b border-chrome-800">
          <div className="w-6 h-6 rounded-md bg-gradient-to-br from-primary to-violet flex items-center justify-center text-white">
            <Icon name="bolt" className="!text-[14px]" />
          </div>
          <div className="leading-tight">
            <div className="text-white text-[13px] font-semibold">Outreach Command</div>
            <div className="text-[10px] text-chrome-400 font-mono">SALES NAV CORE</div>
          </div>
        </div>
        <nav className="flex-1 py-2" aria-label="Main navigation">
          {NAV.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `mx-2 px-3 h-9 rounded-control flex items-center gap-2.5 text-[13px] transition-colors duration-150 ` +
                (isActive ? 'bg-chrome-800 text-white font-medium' : 'hover:bg-chrome-800/60 hover:text-white')
              }
            >
              <Icon name={item.icon} />
              <span className="flex-1">{item.label}</span>
              {item.label === 'Jobs & Scheduler' && live.status === 'running' && (
                <span className="w-1.5 h-1.5 rounded-full bg-ok-dot animate-pulse" title={`Running: ${live.job}`} />
              )}
            </NavLink>
          ))}
        </nav>
        <div className="p-2 border-t border-chrome-800">
          <button onClick={logout}
                  className="w-full h-9 px-3 rounded-control flex items-center gap-2.5 text-[13px] text-chrome-400 hover:bg-chrome-800/60 hover:text-white transition-colors duration-150">
            <Icon name="logout" /> Sign out
          </button>
        </div>
      </aside>

      {/* Workspace */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-12 shrink-0 bg-white border-b border-hairline flex items-center px-4 gap-3 sticky top-0 z-20">
          <div className="min-w-0">
            <h1 className="text-[15px] font-semibold text-slate-900 leading-tight truncate">{title}</h1>
            {subtitle && <p className="text-[11px] text-slate-500 leading-tight truncate">{subtitle}</p>}
          </div>
          <div className="flex-1" />
          {live.status === 'running' && (
            <StatusPill tone="ok" label={`Running: ${live.job?.replace('_', ' ')}`} />
          )}
          {actions}
        </header>
        <main className="flex-1 p-4 min-w-0">{children}</main>
      </div>
    </div>
  )
}
