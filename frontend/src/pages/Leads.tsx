import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, STATUS_META, type CampaignListItem, type LeadPage, type LeadRow } from '../api'
import { Shell, StatusPill, Icon, Spinner, EmptyState, Toast } from '../ui'

const PAGE_SIZE = 50

export default function Leads() {
  const [params] = useSearchParams()
  const [data, setData] = useState<LeadPage | null>(null)
  const [campaigns, setCampaigns] = useState<CampaignListItem[]>([])
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [toast, setToast] = useState<string | null>(null)

  const campaignId = params.get('campaign') ?? ''
  const status = params.get('status') ?? ''
  const source = params.get('source') ?? ''
  const replied = params.get('replied') ?? ''

  const load = useCallback(async () => {
    const usp = new URLSearchParams()
    if (campaignId) usp.set('campaign_id', campaignId)
    if (status) usp.set('status', status === '__untouched__' ? '__untouched__' : status)
    if (source) usp.set('source', source)
    if (replied) usp.set('replied', replied)
    if (q) usp.set('q', q)
    usp.set('page', String(page)); usp.set('page_size', String(PAGE_SIZE))
    setData(await api.get<LeadPage>(`/api/leads?${usp}`))
  }, [campaignId, status, source, replied, q, page])

  useEffect(() => { load().catch(e => setToast(e.message)) }, [load])
  useEffect(() => { api.get<CampaignListItem[]>('/api/campaigns').then(setCampaigns).catch(() => {}) }, [])

  const assign = async (lead: LeadRow, campaignId: string) => {
    try {
      await api.put(`/api/leads/${lead.id}/assign`, { campaign_id: campaignId ? Number(campaignId) : null })
      await load()
      setToast(`${lead.full_name} assigned`)
    } catch (e) { setToast(e instanceof Error ? e.message : 'Assignment failed') }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <Shell title="Leads & Prospect Pipeline" subtitle={`${data?.total ?? '…'} leads matching current filters`}
           actions={<button className="btn-secondary" onClick={() => load().catch(() => {})}><Icon name="refresh" />Refresh</button>}>
      <Toast message={toast} onClose={() => setToast(null)} />

      {/* Filters */}
      <div className="card p-2.5 mb-3 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-52">
          <Icon name="search" className="absolute left-2 top-2 text-slate-400 !text-[16px]" />
          <input className="input pl-8" placeholder="Search name, company, title…" value={q}
                 onChange={e => { setPage(1); setQ(e.target.value) }} aria-label="Search leads" />
        </div>
        <select className="input !w-44" aria-label="Filter by campaign" value={campaignId}
                onChange={e => { setPage(1); params.set('campaign', e.target.value); window.location.hash = `#/leads?${params}` }}>
          <option value="">All campaigns</option>
          {campaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select className="input !w-40" aria-label="Filter by status" value={status}
                onChange={e => { setPage(1); params.set('status', e.target.value); window.location.hash = `#/leads?${params}` }}>
          <option value="">All statuses</option>
          <option value="__untouched__">Untouched</option>
          {Object.entries(STATUS_META).filter(([k]) => k).map(([k, m]) => (
            <option key={k} value={k}>{m.label}</option>
          ))}
        </select>
        <div className="flex rounded-control border border-accentline overflow-hidden" role="group" aria-label="Source">
          <button className={`h-8 px-3 text-[12px] font-medium transition-colors duration-150 ${source === '' ? 'bg-primary text-white' : 'bg-white text-slate-600 hover:bg-canvas'}`}
                  onClick={() => { setPage(1); params.delete('source'); window.location.hash = `#/leads?${params}` }}>
            All sources
          </button>
          <button className={`h-8 px-3 text-[12px] font-medium border-l border-accentline transition-colors duration-150 ${source === 'campaign_search' ? 'bg-primary text-white' : 'bg-white text-slate-600 hover:bg-canvas'}`}
                  onClick={() => { setPage(1); params.set('source', 'campaign_search'); window.location.hash = `#/leads?${params}` }}>
            From campaigns
          </button>
          <button className={`h-8 px-3 text-[12px] font-medium border-l border-accentline transition-colors duration-150 ${source === 'list_import' ? 'bg-primary text-white' : 'bg-white text-slate-600 hover:bg-canvas'}`}
                  onClick={() => { setPage(1); params.set('source', 'list_import'); window.location.hash = `#/leads?${params}` }}>
            From list import
          </button>
        </div>
        <select className="input !w-36" aria-label="Replied filter" value={replied}
                onChange={e => { setPage(1); params.set('replied', e.target.value); window.location.hash = `#/leads?${params}` }}>
          <option value="">Any reply state</option>
          <option value="true">Replied</option>
          <option value="false">No reply yet</option>
        </select>
      </div>

      {!data ? <Spinner label="Loading leads…" /> : data.items.length === 0 ? (
        <EmptyState icon="filter_alt" title="No leads match these filters"
                    hint="Widen the filters, or run Sync Campaign Leads to pull fresh prospects into the pool." />
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[980px]">
            <thead>
              <tr className="h-8 bg-inset border-b border-accentline">
                <th className="text-th uppercase text-slate-500 text-left px-4">Lead</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Company</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Campaign</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Owner Account</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Stage</th>
                <th className="text-th uppercase text-slate-500 text-left px-4">Reply</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map(l => {
                const meta = STATUS_META[l.status] ?? { label: l.status || 'Untouched', tone: 'idle' as const }
                return (
                  <tr key={l.id} className="h-9 border-b border-hairline last:border-0 hover:bg-canvas transition-colors duration-150">
                    <td className="px-4">
                      <div className="font-medium text-slate-900">{l.full_name}</div>
                      <div className="text-[11px] text-slate-500 truncate max-w-56">{l.title}</div>
                    </td>
                    <td className="px-4 text-slate-700">{l.company}</td>
                    <td className="px-4">
                      {l.campaign
                        ? <span className="text-slate-800">{l.campaign}</span>
                        : <AssignInline lead={l} campaigns={campaigns} onAssign={assign} />}
                    </td>
                    <td className="px-4 text-slate-600">{l.associate_account ?? '—'}</td>
                    <td className="px-4"><StatusPill tone={meta.tone} label={meta.label} /></td>
                    <td className="px-4">
                      {l.received_replies
                        ? <span title={l.reply_message ?? ''}><StatusPill tone="ok" label="Replied" /></span>
                        : <span className="text-slate-400">—</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between mt-3 text-[12px] text-slate-600">
          <span className="mono text-metric-sm">Page {data.page} of {totalPages}</span>
          <div className="flex gap-2">
            <button className="btn-secondary" disabled={page <= 1} onClick={() => setPage(p => p - 1)}><Icon name="chevron_left" />Prev</button>
            <button className="btn-secondary" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next<Icon name="chevron_right" /></button>
          </div>
        </div>
      )}
    </Shell>
  )
}

function AssignInline({ lead, campaigns, onAssign }: {
  lead: LeadRow; campaigns: CampaignListItem[]
  onAssign: (lead: LeadRow, campaignId: string) => void
}) {
  return (
    <select
      className="input !h-7 !text-[12px] max-w-44"
      value=""
      aria-label={`Assign ${lead.full_name} to a campaign`}
      onChange={e => e.target.value && onAssign(lead, e.target.value)}
    >
      <option value="">Assign to campaign…</option>
      {campaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
    </select>
  )
}
