import { useCallback, useEffect, useState } from 'react'
import { api, type AccountRow, type Dashboard } from '../api'
import { Shell, StatusPill, Icon, Spinner, EmptyState, Toast } from '../ui'

export default function Accounts() {
  const [rows, setRows] = useState<AccountRow[] | null>(null)
  const [dash, setDash] = useState<Dashboard | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  const load = useCallback(async () => {
    const [accounts, summary] = await Promise.all([
      api.get<AccountRow[]>('/api/accounts'),
      api.get<Dashboard>('/api/dashboard/summary'),
    ])
    setRows(accounts); setDash(summary)
  }, [])

  useEffect(() => { load().catch(e => setToast(e.message)) }, [load])

  const refreshCookies = async (a: AccountRow) => {
    setBusyId(a.id)
    try {
      await api.post(`/api/accounts/${a.id}/refresh-cookies`)
      await load()
      setToast(`Session cookies refreshed for ${a.name}`)
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Refresh failed')
    } finally {
      setBusyId(null)
    }
  }

  if (!rows) return <Shell title="LinkedIn Accounts"><Spinner label="Loading accounts…" /></Shell>

  return (
    <Shell title="LinkedIn Accounts" subtitle="Session state and campaign assignments across the fleet"
           actions={<button className="btn-secondary" onClick={() => load().catch(() => {})}><Icon name="refresh" />Refresh</button>}>
      <Toast message={toast} onClose={() => setToast(null)} />

      {rows.length === 0 ? (
        <EmptyState icon="manage_accounts" title="No accounts configured"
                    hint="Run the migration script to import the 8 legacy LinkedIn accounts from get_cookies.py." />
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[900px]">
            <thead>
              <tr className="h-8 bg-inset border-b border-accentline">
                <th className="text-th uppercase text-slate-500 text-left px-4">Account &amp; Identity</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Session State</th>
                <th className="text-th uppercase text-slate-500 text-right px-4">Last Refresh</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Assigned Campaigns</th>
                <th className="text-th uppercase text-slate-500 text-right px-4">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(a => {
                const stale = a.session_state === 'stale'
                const needsAuth = a.session_state === 'needs_reauth'
                return (
                  <tr key={a.id} className="h-9 border-b border-hairline last:border-0 hover:bg-canvas transition-colors duration-150">
                    <td className="px-4">
                      <div className="flex items-center gap-2.5">
                        <div className="w-6 h-6 rounded-full bg-gradient-to-br from-primary to-violet text-white text-[10px] font-bold flex items-center justify-center">
                          {a.name.split(' ').map(p => p[0]).slice(0, 2).join('')}
                        </div>
                        <span className="font-medium text-slate-900">{a.name}</span>
                      </div>
                    </td>
                    <td className="px-4">
                      {a.status !== 'active'
                        ? <StatusPill tone="warn" label={a.status} />
                        : stale ? <StatusPill tone="warn" label="Cookie expiring" />
                        : needsAuth ? <StatusPill tone="crit" label="Needs re-auth" />
                        : <StatusPill tone="ok" label="Active" />}
                    </td>
                    <td className="px-4 text-right mono text-metric-sm text-slate-600">
                      {a.last_cookie_refresh_at ? new Date(a.last_cookie_refresh_at + 'Z').toLocaleDateString() : 'never'}
                    </td>
                    <td className="px-4">
                      <div className="flex flex-wrap gap-1">
                        {a.campaigns.length === 0 && <span className="text-slate-400">—</span>}
                        {a.campaigns.map(c => (
                          <span key={c} className="inline-flex h-5 px-2 items-center rounded-full bg-primary-subdued text-primary text-label-code border border-indigo-200">{c}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 text-right">
                      <button
                        className="btn-secondary h-7"
                        disabled={busyId === a.id || !a.session_configured}
                        onClick={() => refreshCookies(a)}
                        title={a.session_configured ? 'Relaunch the browser capture for this account' : 'No browser profile configured'}
                      >
                        <Icon name={busyId === a.id ? 'hourglass_top' : 'autorenew'} />
                        {busyId === a.id ? 'Capturing…' : 'Refresh session'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {dash && (
        <p className="mt-3 text-[11px] text-slate-500 flex items-center gap-1.5">
          <Icon name="info" className="!text-[14px]" />
          Sessions are stored as files on the server and are never returned by the API. Cookies older than 7 days are flagged for refresh.
        </p>
      )}
    </Shell>
  )
}
