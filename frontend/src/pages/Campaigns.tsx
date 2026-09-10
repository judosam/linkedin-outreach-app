import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type CampaignListItem } from '../api'
import { Shell, StatusPill, Icon, Spinner, EmptyState } from '../ui'

export default function Campaigns() {
  const [rows, setRows] = useState<CampaignListItem[] | null>(null)

  useEffect(() => {
    api.get<CampaignListItem[]>('/api/campaigns').then(setRows).catch(() => setRows([]))
  }, [])

  if (!rows) return <Shell title="Outreach Campaigns"><Spinner label="Loading campaigns…" /></Shell>

  return (
    <Shell title="Outreach Campaigns" subtitle="Load balancing, budgets and reply performance per campaign"
           actions={<Link to="/campaigns/new" className="btn-primary"><Icon name="add" />New Campaign</Link>}>
      {rows.length === 0 ? (
        <EmptyState icon="rocket_launch" title="No campaigns yet"
                    hint="Run the migration to import campaigns from campaigns.py, or create one to get started."
                    action={<Link to="/campaigns/new" className="btn-primary">Create campaign</Link>} />
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[980px]">
            <thead>
              <tr className="h-8 bg-inset border-b border-accentline">
                <th className="text-th uppercase text-slate-500 text-left px-4">Status</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Campaign</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Load Balancer (order matters)</th>
                <th className="text-th uppercase text-slate-500 text-right px-4">Leads</th>
                <th className="text-th uppercase text-slate-500 text-right px-4">Contacted</th>
                <th className="text-th uppercase text-slate-500 text-right px-4">Reply Rate</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(c => (
                <tr key={c.id} className="h-9 border-b border-hairline last:border-0 hover:bg-canvas transition-colors duration-150">
                  <td className="px-4">
                    <StatusPill tone={c.status === 'active' ? 'ok' : 'warn'} label={c.status} />
                  </td>
                  <td className="px-4">
                    <Link to={`/campaigns/${c.id}`} className="font-medium text-slate-900 hover:text-primary hover:underline">
                      {c.name}
                    </Link>
                    <div className="mono text-label-code text-slate-400">key: {c.campaign_key}</div>
                  </td>
                  <td className="px-4">
                    <div className="flex items-center flex-wrap gap-1">
                      {c.accounts.map((a, i) => (
                        <span key={a.account_id} className="inline-flex items-center gap-1 h-5 px-2 rounded-full bg-inset border border-accentline text-label-code text-slate-600">
                          <span className="mono text-slate-400">{i + 1}</span> {a.account_name}
                        </span>
                      ))}
                      {c.accounts.length === 0 && <span className="text-warn-text text-[11px]">No accounts assigned</span>}
                    </div>
                  </td>
                  <td className="px-4 text-right mono text-metric-sm text-slate-900">{c.leads}</td>
                  <td className="px-4 text-right mono text-metric-sm text-slate-600">{c.contacted}</td>
                  <td className="px-4 text-right">
                    <span className="mono text-metric-sm text-slate-900">{c.reply_rate}%</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Shell>
  )
}
