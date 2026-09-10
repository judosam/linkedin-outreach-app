import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { api, type Dashboard as Data } from '../api'
import { Shell, StatusPill, Icon, Spinner, EmptyState } from '../ui'

function StatCard({ icon, label, value, limit, hint, tone }: {
  icon: string; label: string; value: number; limit?: number; hint?: string; tone?: 'warn' | 'crit'
}) {
  const pct = limit ? Math.round((value / limit) * 100) : 0
  const bar = pct >= 100 ? 'bg-crit-dot' : pct >= 80 ? 'bg-warn-dot' : 'bg-gradient-to-r from-primary to-indigo-500'
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 text-slate-500">
        <Icon name={icon} />
        <span className="text-th uppercase">{label}</span>
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="mono text-metric text-slate-900">{value.toLocaleString()}</span>
        {limit !== undefined && <span className="mono text-metric-sm text-slate-400">/ {limit.toLocaleString()}</span>}
      </div>
      {limit !== undefined && (
        <div className="mt-2 h-1 rounded-full bg-hairline overflow-hidden">
          <div className={`h-full rounded-full ${bar} transition-all duration-300`} style={{ width: `${Math.min(100, pct)}%` }} />
        </div>
      )}
      <div className="mt-2 flex items-center gap-2">
        {hint && <span className="text-[11px] text-slate-500">{hint}</span>}
        {tone === 'warn' && pct >= 80 && pct < 100 && <StatusPill tone="warn" label="Near cap" />}
        {tone === 'crit' && pct >= 100 && <StatusPill tone="crit" label="At cap" />}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<Data>('/api/dashboard/summary').then(setData).catch(e => setError(e.message))
  }, [])

  if (error) return <Shell title="Dashboard"><EmptyState icon="cloud_off" title="Couldn't load the dashboard" hint={error} /></Shell>
  if (!data) return <Shell title="Dashboard"><Spinner label="Loading fleet status…" /></Shell>

  const t = data.today
  const delta = t.contacted - t.contacted_yesterday
  const rate = data.totals.leads_total
    ? ((data.replies.total / data.totals.leads_total) * 100).toFixed(1)
    : '0.0'

  const rateData = data.campaign_rates.filter(c => c.leads > 0)

  return (
    <Shell
      title="Dashboard"
      subtitle={`Production · ${data.totals.accounts_active} accounts active · scheduler ${data.scheduler_healthy ? 'healthy' : 'off'}`}
      actions={<Link to="/jobs" className="btn-primary"><Icon name="play_arrow" />Run Jobs</Link>}
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <StatCard icon="person_add" label="Invites today" value={t.invites} limit={t.invites_limit}
                  hint={`${t.invites_limit ? Math.round(t.invites / t.invites_limit * 100) : 0}% quota`} tone="warn" />
        <StatCard icon="send" label="InMails today" value={t.inmails} limit={t.inmails_limit}
                  hint={`${t.inmails_limit ? Math.round(t.inmails / t.inmails_limit * 100) : 0}% quota`} tone="warn" />
        <StatCard icon="cached" label="Follow-up messages" value={t.followups} limit={t.followups_limit}
                  hint="shared daily budget" tone="warn" />
        <StatCard icon="forum" label="New replies" value={data.replies.today}
                  hint={`${rate}% lifetime reply rate`} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
        {/* Campaign reply rates */}
        <div className="card p-4 xl:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-slate-900">Reply rate by campaign</h2>
            <span className="text-[11px] text-slate-500">replied / total leads</span>
          </div>
          {rateData.length === 0 ? (
            <EmptyState icon="query_stats" title="No campaign data yet"
                        hint="Run Sync Campaign Leads to pull prospects, then send connections to start the funnel." />
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rateData} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                  <XAxis dataKey="campaign_key" tick={{ fontSize: 10, fill: '#64748B' }}
                         tickFormatter={(v: string) => (v.length > 14 ? v.slice(0, 13) + '…' : v)} />
                  <YAxis tick={{ fontSize: 10, fill: '#64748B' }} unit="%" />
                  <Tooltip formatter={(v: number) => [`${v}%`, 'Reply rate']}
                           contentStyle={{ borderRadius: 8, borderColor: '#E2E8F0', fontSize: 12 }} />
                  <Bar dataKey="rate" fill="#4F46E5" radius={[4, 4, 0, 0]} maxBarSize={42} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Pipeline funnel */}
        <div className="card p-4">
          <h2 className="font-semibold text-slate-900 mb-3">Pipeline funnel</h2>
          <ul className="space-y-1.5">
            {Object.entries(data.funnel).sort((a, b) => (a[0] || '').localeCompare(b[0] || '')).map(([status, count]) => (
              <li key={status || 'untouched'} className="flex items-center justify-between h-7">
                <span className="text-slate-600">{status === '' ? 'Untouched' : status.replaceAll('_', ' ').toLowerCase()}</span>
                <span className="mono text-metric-sm text-slate-900">{count}</span>
              </li>
            ))}
            {Object.keys(data.funnel).length === 0 && (
              <li className="text-slate-400 text-center py-6">No leads yet — run Sync Campaign Leads.</li>
            )}
          </ul>
          <div className="mt-3 pt-3 border-t border-hairline flex items-center justify-between">
            <span className="text-slate-600">Untagged (list import)</span>
            <span className="mono text-metric-sm text-slate-900">{data.totals.leads_untagged}</span>
          </div>
        </div>
      </div>

      {/* Recent runs */}
      <div className="card mt-3">
        <div className="px-4 py-3 border-b border-hairline flex items-center justify-between">
          <h2 className="font-semibold text-slate-900">Recent runs</h2>
          <Link to="/jobs" className="text-primary text-[12px] font-medium hover:underline">View all →</Link>
        </div>
        {data.recent_runs.length === 0 ? (
          <div className="p-6 text-center text-slate-500">No jobs have run yet. Trigger one from <Link className="text-primary hover:underline" to="/jobs">Jobs &amp; Scheduler</Link>.</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="h-8 bg-inset border-b border-accentline">
                <th className="th-th uppercase text-slate-500 text-left px-4">Job</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Started</th>
                <th className="text-th uppercase text-slate-500 text-right px-4">Duration</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_runs.map(r => (
                <tr key={r.id} className="h-9 border-b border-hairline hover:bg-canvas transition-colors duration-150">
                  <td className="px-4 text-slate-800">{r.job.replaceAll('_', ' ')}</td>
                  <td className="px-4 mono text-metric-sm text-slate-600">
                    {r.started_at ? new Date(r.started_at + 'Z').toLocaleString() : '—'}
                  </td>
                  <td className="px-4 mono text-metric-sm text-slate-600 text-right">
                    {r.duration_s != null ? `${r.duration_s.toFixed(0)}s` : '—'}
                  </td>
                  <td className="px-4">
                    <StatusPill
                      tone={r.status === 'success' ? 'ok' : r.status === 'error' ? 'crit' : r.status === 'partial' ? 'warn' : 'idle'}
                      label={r.status + (r.dry_run ? ' · dry' : '')}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Shell>
  )
}
