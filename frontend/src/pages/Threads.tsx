import { useCallback, useEffect, useState } from 'react'
import { api, type ThreadRow } from '../api'
import { Shell, StatusPill, Icon, Spinner, EmptyState } from '../ui'

type Channel = 'all' | 'recent' | 'booked'
const CHANNELS: { key: Channel; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'recent', label: 'Last 7 days' },
  { key: 'booked', label: 'Mentions booking' },
]

export default function Threads() {
  const [rows, setRows] = useState<ThreadRow[] | null>(null)
  const [selected, setSelected] = useState<ThreadRow | null>(null)
  const [channel, setChannel] = useState<Channel>('all')
  const [q, setQ] = useState('')

  const load = useCallback(async () => {
    const usp = new URLSearchParams()
    if (q) usp.set('q', q)
    const data = await api.get<{ items: ThreadRow[] }>(`/api/threads?${usp}`)
    setRows(data.items)
    setSelected(prev => data.items.find(r => r.id === prev?.id) ?? data.items[0] ?? null)
  }, [q])

  useEffect(() => { load().catch(() => setRows([])) }, [load])

  // "Mentions booking" filter is client-side (reply text contains a calendar link)
  const filtered = (rows ?? []).filter(r => {
    if (channel === 'booked') return /calendly|calendar|book a|schedule a/i.test(r.reply_message ?? '')
    if (channel === 'recent') {
      if (!r.reply_received_at) return false
      return Date.now() - new Date(r.reply_received_at + 'Z').getTime() < 7 * 86400_000
    }
    return true
  })

  if (!rows) return <Shell title="Inbox & Reply Matrix"><Spinner label="Loading replies…" /></Shell>

  return (
    <Shell title="Inbox & Reply Matrix" subtitle={`${filtered.length} reply conversation(s)`}
           actions={<button className="btn-secondary" onClick={() => load().catch(() => {})}><Icon name="sync_alt" />Refresh</button>}>
      <div className="flex rounded-control border border-accentline bg-white w-fit mb-3 overflow-hidden" role="group" aria-label="Channels">
        {CHANNELS.map(c => (
          <button key={c.key}
                  className={`h-8 px-3 text-[12px] font-medium transition-colors duration-150 ${channel === c.key ? 'bg-primary text-white' : 'text-slate-600 hover:bg-canvas'}`}
                  onClick={() => setChannel(c.key)}>
            {c.label}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon="forum" title="No replies here yet"
                    hint="When Check Replies finds lead responses, they appear here with campaign and account attribution." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-3 items-start">
          {/* Reply list */}
          <div className="card lg:col-span-2 divide-y divide-hairline max-h-[70vh] overflow-y-auto scroll-thin">
            {filtered.map(r => {
              const initials = r.full_name.split(' ').map(p => p[0]).slice(0, 2).join('').toUpperCase()
              return (
                <button key={r.id} onClick={() => setSelected(r)}
                        className={`w-full text-left p-3 flex gap-2.5 transition-colors duration-150 ${selected?.id === r.id ? 'bg-primary-subdued' : 'hover:bg-canvas'}`}>
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-violet text-white text-[11px] font-bold flex items-center justify-center shrink-0">
                    {initials}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-slate-900 truncate">{r.full_name}</span>
                      <span className="mono text-label-code text-slate-400 whitespace-nowrap">
                        {r.reply_received_at ? new Date(r.reply_received_at + 'Z').toLocaleDateString() : ''}
                      </span>
                    </div>
                    <p className="text-[12px] text-slate-500 truncate mt-0.5">
                      “{(r.reply_message ?? '').slice(0, 80)}”
                    </p>
                    <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                      {r.campaign && (
                        <span className="inline-flex h-4.5 px-1.5 items-center rounded-full bg-primary-subdued text-primary text-[10px] font-semibold border border-indigo-200">
                          🎯 {r.campaign}
                        </span>
                      )}
                      {r.account && (
                        <span className="inline-flex h-4.5 px-1.5 items-center rounded-full bg-inset text-slate-600 text-[10px] font-semibold border border-accentline">
                          👤 {r.account}
                        </span>
                      )}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>

          {/* Thread detail */}
          <div className="card lg:col-span-3 p-5 min-h-64">
            {selected ? (
              <>
                <div className="flex items-start gap-3 pb-4 border-b border-hairline">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary to-violet text-white text-sm font-bold flex items-center justify-center">
                    {selected.full_name.split(' ').map(p => p[0]).slice(0, 2).join('').toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-slate-900">{selected.full_name}</div>
                    <div className="text-[12px] text-slate-500">{selected.title} {selected.company && `· ${selected.company}`}</div>
                  </div>
                  <StatusPill tone="ok" label="Replied" />
                </div>
                <div className="mt-4 rounded-card bg-inset border border-hairline border-l-4 border-l-primary p-4">
                  <p className="whitespace-pre-wrap text-slate-800 leading-relaxed">{selected.reply_message}</p>
                </div>
                <div className="mt-4 flex items-center gap-4 text-[12px] text-slate-500">
                  <span><Icon name="rocket_launch" className="!text-[14px] align-[-2px]" /> {selected.campaign ?? '—'}</span>
                  <span><Icon name="person" className="!text-[14px] align-[-2px]" /> {selected.account ?? '—'}</span>
                  {selected.reply_received_at && (
                    <span><Icon name="schedule" className="!text-[14px] align-[-2px]" /> {new Date(selected.reply_received_at + 'Z').toLocaleString()}</span>
                  )}
                </div>
              </>
            ) : (
              <p className="text-slate-400 text-center py-10">Select a reply from the list.</p>
            )}
          </div>
        </div>
      )}
    </Shell>
  )
}
