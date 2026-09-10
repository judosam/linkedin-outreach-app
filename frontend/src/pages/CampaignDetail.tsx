import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, type AccountRow, type CampaignDetail as Detail, type CampaignAccountLink } from '../api'
import { Shell, StatusPill, Icon, Spinner, Toast } from '../ui'

type TabKey = 'invite' | 'invite_seq' | 'inmail' | 'inmail_seq'
const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: 'invite', label: 'Connection Invite', icon: 'person_add' },
  { key: 'invite_seq', label: 'Invite Follow-up Sequence', icon: 'cached' },
  { key: 'inmail', label: 'InMail', icon: 'send' },
  { key: 'inmail_seq', label: 'InMail Follow-up Sequence', icon: 'forum' },
]

const PLACEHOLDER_HINT = 'Placeholders: {first_name} · {calendar_url}'

export default function CampaignDetail() {
  const { id } = useParams()
  const isNew = id === undefined || id === 'new'
  const navigate = useNavigate()

  const [detail, setDetail] = useState<Detail | null>(null)
  const [accounts, setAccounts] = useState<AccountRow[]>([])
  const [tab, setTab] = useState<TabKey>('invite')
  const [toast, setToast] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (isNew) return
    api.get<Detail>(`/api/campaigns/${id}`).then(setDetail).catch(e => setToast(e.message))
  }, [id, isNew])

  useEffect(() => {
    api.get<AccountRow[]>('/api/accounts').then(setAccounts).catch(() => {})
  }, [])

  if (!isNew && !detail) return <Shell title="Campaign"><Spinner label="Loading campaign…" /></Shell>

  const d: Detail = detail ?? {
    id: 0, campaign_key: '', name: '', status: 'active', search_url: '',
    invite_text: '', invite_track: ['', '', '', ''], inmail_subject: '', inmail_text: '',
    inmail_track: [{ subject: '', body: '' }, { subject: '', body: '' }, { subject: '', body: '' }],
    accounts: [],
  }

  const patch = (u: Partial<Detail>) => setDetail({ ...d, ...u })

  const setLink = (idx: number, u: Partial<CampaignAccountLink>) => {
    const accounts = d.accounts.map((a, i) => (i === idx ? { ...a, ...u } : a))
    patch({ accounts })
  }

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      const payload = {
        name: d.name,
        campaign_key: d.campaign_key || undefined,
        search_url: d.search_url,
        status: d.status,
        invite_text: d.invite_text,
        invite_track: (d.invite_track || []).map(s => s ?? ''),
        inmail_subject: d.inmail_subject,
        inmail_text: d.inmail_text,
        inmail_track: (d.inmail_track || []).map(t => ({ subject: t.subject ?? '', body: t.body ?? '' })),
        accounts: d.accounts.map((a, i) => ({
          account_id: a.account_id, order_index: i,
          invite_limit: Number(a.invite_limit) || 0,
          inmail_limit: Number(a.inmail_limit) || 0,
          message_limit: Number(a.message_limit) || 0,
          calendar_url: a.calendar_url || null,
          search_url_override: a.search_url_override || null,
        })),
      }
      if (isNew) {
        const created = await api.post<{ id: number }>('/api/campaigns', payload)
        navigate(`/campaigns/${created.id}`)
      } else {
        await api.put(`/api/campaigns/${d.id}`, payload)
        setDetail(await api.get<Detail>(`/api/campaigns/${d.id}`))
      }
      setToast('Campaign saved')
    } catch (err) {
      setToast(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const addAccount = () => {
    const used = new Set(d.accounts.map(a => a.account_id))
    const next = accounts.find(a => !used.has(a.id))
    if (!next) { setToast('All accounts are already assigned'); return }
    patch({ accounts: [...d.accounts, {
      account_id: next.id, account_name: next.name, order_index: d.accounts.length,
      invite_limit: 10, inmail_limit: 10, message_limit: 30,
      calendar_url: null, search_url_override: null,
    } as CampaignAccountLink] })
  }

  return (
    <Shell
      title={isNew ? 'New Campaign' : d.name || 'Campaign'}
      subtitle={isNew ? 'Create a campaign and assign accounts' : `key: ${d.campaign_key} (immutable - it tags every lead row)`}
      actions={
        <>
          <StatusPill tone={d.status === 'active' ? 'ok' : 'warn'} label={d.status} />
          <button className="btn-primary" onClick={save} disabled={saving}>
            <Icon name="save" />{saving ? 'Saving…' : 'Save'}
          </button>
        </>
      }
    >
      <Toast message={toast} onClose={() => setToast(null)} />
      <form onSubmit={save} className="grid grid-cols-1 xl:grid-cols-3 gap-3 items-start">
        {/* Left: identity + load balancer */}
        <div className="space-y-3">
          <div className="card p-4 space-y-3">
            <h2 className="font-semibold text-slate-900">Campaign</h2>
            <label className="block">
              <span className="text-th uppercase text-slate-500">Name</span>
              <input className="input mt-1" value={d.name} required
                     onChange={e => patch({ name: e.target.value })} />
            </label>
            <label className="block">
              <span className="text-th uppercase text-slate-500">Campaign key {isNew ? '' : '(immutable)'}</span>
              <input className="input mt-1 mono" value={d.campaign_key} required disabled={!isNew}
                     onChange={e => patch({ campaign_key: e.target.value })}
                     placeholder="e.g. SCM Podcast" />
            </label>
            <label className="block">
              <span className="text-th uppercase text-slate-500">Search URL (campaign-level)</span>
              <textarea className="input mt-1 h-16 py-1.5 mono !text-[12px]" value={d.search_url}
                        onChange={e => patch({ search_url: e.target.value })}
                        placeholder="https://www.linkedin.com/sales/search/people?savedSearchId=…" />
            </label>
            <label className="block">
              <span className="text-th uppercase text-slate-500">Status</span>
              <select className="input mt-1" value={d.status} onChange={e => patch({ status: e.target.value })}>
                <option value="active">active</option>
                <option value="paused">paused</option>
              </select>
            </label>
          </div>

          <div className="card p-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-semibold text-slate-900">Accounts &amp; quota balancing</h2>
              <button type="button" className="btn-secondary h-7" onClick={addAccount}><Icon name="add" />Add</button>
            </div>
            <p className="text-[11px] text-slate-500 mb-3">
              Leads fill the first account until its daily budget is exhausted, then roll to the next.
            </p>
            <div className="space-y-2">
              {d.accounts.map((a, i) => (
                <div key={`${a.account_id}-${i}`} className="border border-hairline rounded-control p-2.5 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="mono text-label-code text-slate-400">#{i + 1}</span>
                    <select className="input !h-7" value={a.account_id}
                            onChange={e => setLink(i, { account_id: Number(e.target.value) })}>
                      {accounts.map(acc => <option key={acc.id} value={acc.id}>{acc.name}</option>)}
                    </select>
                    <button type="button" className="btn-ghost" aria-label={`Remove ${a.account_name}`}
                            onClick={() => patch({ accounts: d.accounts.filter((_, j) => j !== i) })}>
                      <Icon name="close" />
                    </button>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <label className="text-[10px] uppercase text-slate-400">Invite/day
                      <input className="input mt-0.5 mono" type="number" min={0} value={a.invite_limit}
                             onChange={e => setLink(i, { invite_limit: Number(e.target.value) })} />
                    </label>
                    <label className="text-[10px] uppercase text-slate-400">InMail/day
                      <input className="input mt-0.5 mono" type="number" min={0} value={a.inmail_limit}
                             onChange={e => setLink(i, { inmail_limit: Number(e.target.value) })} />
                    </label>
                    <label className="text-[10px] uppercase text-slate-400">Msg/day
                      <input className="input mt-0.5 mono" type="number" min={0} value={a.message_limit}
                             onChange={e => setLink(i, { message_limit: Number(e.target.value) })} />
                    </label>
                  </div>
                  <label className="block text-[10px] uppercase text-slate-400">Calendar URL (optional)
                    <input className="input mt-0.5 mono !text-[11px]" value={a.calendar_url ?? ''}
                           onChange={e => setLink(i, { calendar_url: e.target.value })}
                           placeholder="https://calendly.com/…" />
                  </label>
                </div>
              ))}
              {d.accounts.length === 0 && (
                <p className="text-slate-400 text-[12px] py-2 text-center">No accounts assigned yet.</p>
              )}
            </div>
          </div>
        </div>

        {/* Right: message template editor (4 tabs) */}
        <div className="card xl:col-span-2">
          <div className="border-b border-hairline px-3 pt-2 flex gap-1" role="tablist" aria-label="Message templates">
            {TABS.map(t => (
              <button key={t.key} type="button" role="tab" aria-selected={tab === t.key}
                      onClick={() => setTab(t.key)}
                      className={`h-9 px-3 rounded-t-control inline-flex items-center gap-1.5 text-[12px] font-medium border-b-2 transition-colors duration-150 ${
                        tab === t.key ? 'border-primary text-primary' : 'border-transparent text-slate-500 hover:text-slate-800'
                      }`}>
                <Icon name={t.icon} />{t.label}
              </button>
            ))}
          </div>
          <div className="p-4">
            <p className="text-[11px] text-slate-500 mb-3">{PLACEHOLDER_HINT}</p>

            {tab === 'invite' && (
              <label className="block">
                <span className="text-th uppercase text-slate-500">First-touch invite note (with connection request)</span>
                <textarea className="input mt-1 h-40 py-2 leading-relaxed" value={d.invite_text}
                          onChange={e => patch({ invite_text: e.target.value })} />
              </label>
            )}

            {tab === 'invite_seq' && (
              <div className="space-y-3">
                {[0, 1, 2, 3].map(i => (
                  <label key={i} className="block">
                    <span className="text-th uppercase text-slate-500">
                      {i === 0 ? 'After acceptance (sent by Check Replies)' : `Follow-up ${i} (+${i === 1 ? 3 : i === 2 ? 5 : 7} days)`}
                    </span>
                    <textarea
                      className="input mt-1 h-28 py-2 leading-relaxed"
                      value={d.invite_track[i] ?? ''}
                      onChange={e => {
                        const track = [...(d.invite_track || [])]
                        while (track.length < 4) track.push('')
                        track[i] = e.target.value
                        patch({ invite_track: track })
                      }}
                    />
                    {i > (d.invite_track?.length ?? 0) - 1 && (
                      <span className="text-[11px] text-warn-text">Empty — this stage is skipped for this campaign.</span>
                    )}
                  </label>
                ))}
              </div>
            )}

            {tab === 'inmail' && (
              <div className="space-y-3">
                <label className="block">
                  <span className="text-th uppercase text-slate-500">InMail subject</span>
                  <input className="input mt-1" value={d.inmail_subject}
                         onChange={e => patch({ inmail_subject: e.target.value })} />
                </label>
                <label className="block">
                  <span className="text-th uppercase text-slate-500">First-touch InMail body</span>
                  <textarea className="input mt-1 h-40 py-2 leading-relaxed" value={d.inmail_text}
                            onChange={e => patch({ inmail_text: e.target.value })} />
                </label>
              </div>
            )}

            {tab === 'inmail_seq' && (
              <div className="space-y-3">
                {[0, 1, 2].map(i => (
                  <fieldset key={i} className="border border-hairline rounded-control p-3">
                    <legend className="text-th uppercase text-slate-500 px-1">InMail Follow-up {i + 1} (+{i === 0 ? 3 : i === 1 ? 5 : 7} days)</legend>
                    <input className="input mb-2" placeholder="Subject"
                           value={d.inmail_track[i]?.subject ?? ''}
                           onChange={e => {
                             const track = [...(d.inmail_track || [])]
                             while (track.length < 3) track.push({ subject: '', body: '' })
                             track[i] = { ...track[i], subject: e.target.value }
                             patch({ inmail_track: track })
                           }} />
                    <textarea className="input h-24 py-2 leading-relaxed" placeholder="Body"
                              value={d.inmail_track[i]?.body ?? ''}
                              onChange={e => {
                                const track = [...(d.inmail_track || [])]
                                while (track.length < 3) track.push({ subject: '', body: '' })
                                track[i] = { ...track[i], body: e.target.value }
                                patch({ inmail_track: track })
                              }} />
                  </fieldset>
                ))}
              </div>
            )}
          </div>
        </div>
        {/* Hidden submit for Enter-key save */}
        <button type="submit" className="hidden" aria-hidden="true" />
      </form>
    </Shell>
  )
}
