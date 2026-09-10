import { useCallback, useEffect, useState } from 'react'
import { api, type JobRow, type RunRow } from '../api'
import { Shell, StatusPill, Icon, Spinner, Toast } from '../ui'

const JOB_META: Record<string, { label: string; icon: string }> = {
  sync_leads: { label: 'Sync Campaign Leads', icon: 'filter_alt' },
  import_list: { label: 'Import from List', icon: 'playlist_add_check' },
  send_connections: { label: 'Send Connections', icon: 'person_add' },
  check_replies: { label: 'Check Replies', icon: 'mark_email_read' },
  send_followups: { label: 'Send Follow-ups', icon: 'schedule_send' },
}

export default function Jobs() {
  const [jobs, setJobs] = useState<JobRow[] | null>(null)
  const [runs, setRuns] = useState<RunRow[]>([])
  const [live, setLive] = useState<{ job: string | null; status: string; target: string } | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [dryRun, setDryRun] = useState(false)
  const [selectedRun, setSelectedRun] = useState<RunRow | null>(null)

  // import-list form
  const [accounts, setAccounts] = useState<{ id: number; name: string }[]>([])
  const [importAccount, setImportAccount] = useState('')
  const [importListId, setImportListId] = useState('')

  const load = useCallback(async () => {
    const [jobsData, runsData] = await Promise.all([
      api.get<{ jobs: JobRow[]; live: { job: string | null; status: string; target: string } }>('/api/jobs'),
      api.get<RunRow[]>('/api/runs?limit=25'),
    ])
    setJobs(jobsData.jobs); setLive(jobsData.live); setRuns(runsData)
  }, [])

  useEffect(() => {
    load().catch(e => setToast(e.message))
    const t = setInterval(() => load().catch(() => {}), 5000)
    return () => clearInterval(t)
  }, [load])

  useEffect(() => {
    api.get<{ id: number; name: string }[]>('/api/accounts').then(setAccounts).catch(() => {})
  }, [])

  const run = async (key: string, extra?: Record<string, unknown>) => {
    try {
      await api.post(`/api/jobs/${key}/run`, { dry_run: dryRun, ...extra })
      setToast(`${JOB_META[key]?.label ?? key} dispatched${dryRun ? ' (dry run)' : ''}`)
      setTimeout(load, 1500)
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Could not start job')
    }
  }

  const runImport = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!importAccount || !importListId) { setToast('Pick an account and enter a list ID'); return }
    await run('import_list', { account_id: Number(importAccount), list_id: importListId })
  }

  const openRun = async (r: RunRow) => {
    setSelectedRun(r)
    try {
      const full = await api.get<{ log_text: string }>(`/api/runs/${r.id}/log`)
      setSelectedRun({ ...r, log: full.log_text } as RunRow & { log: string })
    } catch { /* keep summary */ }
  }

  if (!jobs) return <Shell title="Jobs & Automation Scheduler"><Spinner label="Loading daemons…" /></Shell>

  const running = live?.status === 'running'

  return (
    <Shell title="Jobs & Automation Scheduler" subtitle={running ? `Running: ${live?.job}` : '5 core workers · single-flight enforced'}
           actions={
             <label className="flex items-center gap-2 text-[12px] text-slate-600 select-none">
               <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)}
                      className="accent-[#4F46E5] w-3.5 h-3.5" />
               Dry run
             </label>
           }>
      <Toast message={toast} onClose={() => setToast(null)} />

      {/* Job cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
        {jobs.map(j => {
          const meta = JOB_META[j.key] ?? { label: j.key, icon: 'bolt' }
          const isRunning = j.running_now
          return (
            <div key={j.key} className={`card p-4 ${isRunning ? 'ring-2 ring-primary' : ''}`}>
              <div className="flex items-start gap-2.5">
                <div className="w-8 h-8 rounded-control bg-primary-subdued text-primary flex items-center justify-center shrink-0">
                  <Icon name={meta.icon} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="font-semibold text-slate-900 truncate">{meta.label}</h2>
                    {isRunning && <StatusPill tone="ok" label="running" />}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">{j.description}</p>
                </div>
              </div>

              <div className="mt-3 flex items-center gap-2 flex-wrap">
                {j.schedule.length > 0 ? (
                  <span className="inline-flex items-center gap-1 h-5 px-2 rounded-full bg-inset border border-accentline text-label-code text-slate-600">
                    <Icon name="schedule" className="!text-[12px]" />
                    {j.schedule.join(' · ')} UTC
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 h-5 px-2 rounded-full bg-inset border border-accentline text-label-code text-slate-500">
                    manual trigger
                  </span>
                )}
                {j.last_run && (
                  <StatusPill
                    dot={false}
                    tone={j.last_run.status === 'success' ? 'ok' : j.last_run.status === 'error' ? 'crit' : j.last_run.status === 'partial' ? 'warn' : 'idle'}
                    label={j.last_run.status === 'running' ? 'running…'
                      : `last: ${j.last_run.status}${j.last_run.duration_s != null ? ` · ${Math.round(j.last_run.duration_s)}s` : ''}`}
                  />
                )}
              </div>

              {j.key === 'import_list' ? (
                <form onSubmit={runImport} className="mt-3 flex gap-2 flex-wrap">
                  <select className="input !h-8 !w-40" value={importAccount} onChange={e => setImportAccount(e.target.value)} aria-label="Import account">
                    <option value="">Account…</option>
                    {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                  </select>
                  <input className="input !h-8 !w-28 mono" placeholder="List ID" value={importListId}
                         onChange={e => setImportListId(e.target.value)} aria-label="Sales Navigator list ID" />
                  <button type="submit" className="btn-primary" disabled={running}>
                    <Icon name="play_arrow" />Import
                  </button>
                </form>
              ) : (
                <button className="btn-primary mt-3 w-full justify-center" disabled={running} onClick={() => run(j.key)}>
                  <Icon name="play_arrow" />Run now
                </button>
              )}
            </div>
          )
        })}
      </div>

      {/* Run history audit table */}
      <div className="card mt-3">
        <div className="px-4 py-3 border-b border-hairline flex items-center gap-2">
          <Icon name="history" />
          <h2 className="font-semibold text-slate-900">Run-History Audit Table</h2>
        </div>
        {runs.length === 0 ? (
          <div className="p-6 text-center text-slate-500">No runs recorded yet — dispatch a job above.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px]">
              <thead>
                <tr className="h-8 bg-inset border-b border-accentline">
                  <th className="text-th uppercase text-slate-500 text-left px-4">Timestamp</th>
                  <th className="text-th uppercase text-slate-500 text-left px-4">Job Type</th>
                  <th className="text-th uppercase text-slate-500 text-left px-4">Target</th>
                  <th className="text-th uppercase text-slate-500 text-right px-4">Duration</th>
                  <th className="text-th uppercase text-slate-500 text-left px-4">Result</th>
                  <th className="text-th uppercase text-slate-500 text-left px-4">Diagnostics</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.id} className={`h-9 border-b border-hairline last:border-0 cursor-pointer transition-colors duration-150 ${selectedRun?.id === r.id ? 'bg-primary-subdued' : 'hover:bg-canvas'}`}
                      onClick={() => openRun(r)}>
                    <td className="px-4 mono text-metric-sm text-slate-600">
                      {r.started_at ? new Date(r.started_at + 'Z').toLocaleString() : '—'}
                    </td>
                    <td className="px-4 text-slate-800">{JOB_META[r.job]?.label ?? r.job}{r.dry_run && <span className="text-slate-400"> · dry</span>}</td>
                    <td className="px-4 text-slate-600 max-w-52 truncate">{r.target}</td>
                    <td className="px-4 text-right mono text-metric-sm text-slate-600">
                      {r.duration_s != null ? `${r.duration_s.toFixed(0)}s` : '—'}
                    </td>
                    <td className="px-4">
                      <StatusPill tone={r.status === 'success' ? 'ok' : r.status === 'error' ? 'crit' : r.status === 'partial' ? 'warn' : 'idle'}
                                   label={r.status} />
                    </td>
                    <td className="px-4 text-slate-500 max-w-72 truncate">
                      {r.errors && r.errors.length > 0 ? r.errors[0] : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {selectedRun && (
          <div className="border-t border-hairline">
            <div className="px-4 py-2.5 flex items-center justify-between bg-inset">
              <span className="text-th uppercase text-slate-500">Run #{selectedRun.id} log</span>
              <button className="btn-ghost" aria-label="Close log" onClick={() => setSelectedRun(null)}><Icon name="close" /></button>
            </div>
            <pre className="p-4 text-[11px] leading-relaxed mono text-slate-700 max-h-72 overflow-y-auto scroll-thin whitespace-pre-wrap">
              {(selectedRun as RunRow & { log?: string }).log || 'Log unavailable for this run.'}
            </pre>
          </div>
        )}
      </div>
    </Shell>
  )
}
