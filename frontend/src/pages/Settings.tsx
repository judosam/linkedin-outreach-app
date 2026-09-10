import { useEffect, useState, type FormEvent } from 'react'
import { api, type NotificationSettings } from '../api'
import { Shell, Icon, Toast } from '../ui'

export default function Settings() {
  const [notif, setNotif] = useState<NotificationSettings | null>(null)
  const [webhookInput, setWebhookInput] = useState('')
  const [recipientsText, setRecipientsText] = useState('')
  const [schedule, setSchedule] = useState<Record<string, string[]>>({})
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    api.get<NotificationSettings>('/api/settings/notifications')
      .then(s => {
        setNotif(s)
        setRecipientsText(s.email_recipients.join(', '))
      })
      .catch(e => setToast(e.message))
    api.get<Record<string, string[]>>('/api/settings/schedule').then(setSchedule).catch(() => {})
  }, [])

  const saveNotif = async (e: FormEvent) => {
    e.preventDefault()
    if (!notif) return
    try {
      await api.put('/api/settings/notifications', {
        gchat_webhook_url: webhookInput || notif.gchat_webhook_url,
        email_recipients: recipientsText.split(',').map(s => s.trim()).filter(Boolean),
        alert_critical: notif.alert_critical,
        alert_run_summary: notif.alert_run_summary,
        alert_send_errors: notif.alert_send_errors,
        alert_reply_digest: notif.alert_reply_digest,
      })
      setWebhookInput('')
      const fresh = await api.get<NotificationSettings>('/api/settings/notifications')
      setNotif(fresh); setRecipientsText(fresh.email_recipients.join(', '))
      setToast('Configuration saved')
    } catch (err) {
      setToast(err instanceof Error ? err.message : 'Save failed')
    }
  }

  const testWebhook = async () => {
    try {
      const res = await api.post<{ ok: boolean }>('/api/settings/test-webhook')
      setToast(res.ok ? 'Test notification sent — check Google Chat' : 'Webhook test failed (see server log)')
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Test failed')
    }
  }

  const saveSchedule = async () => {
    try {
      await api.put('/api/settings/schedule', { schedule })
      setToast('Schedule saved (applies to future cron ticks)')
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Save failed')
    }
  }

  const setJobTime = (job: string, slot: number, value: string) => {
    const times = [...(schedule[job] ?? ['',''])]
    times[slot] = value
    setSchedule({ ...schedule, [job]: times })
  }

  if (!notif) return <Shell title="Settings"><Toast message={toast} onClose={() => setToast(null)} /></Shell>

  const JOBS = ['sync_leads', 'send_connections', 'check_replies', 'send_followups']
  const pretty = (s: string) => s.replaceAll('_', ' ')

  return (
    <Shell title="Settings & Fleet Orchestration" subtitle="Notifications, alert routing and job schedules">
      <Toast message={toast} onClose={() => setToast(null)} />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 items-start">
        {/* Notifications */}
        <form onSubmit={saveNotif} className="card p-4 space-y-4">
          <div className="flex items-center gap-2">
            <Icon name="notifications_active" />
            <h2 className="font-semibold text-slate-900">Alerts &amp; Notifications</h2>
          </div>

          <label className="block">
            <span className="text-th uppercase text-slate-500">Google Chat webhook URL</span>
            <div className="flex gap-2 mt-1">
              <input
                className="input mono !text-[11px]" type="url"
                placeholder={notif.webhook_configured ? notif.gchat_webhook_url : 'https://chat.googleapis.com/v1/spaces/…'}
                value={webhookInput} onChange={e => setWebhookInput(e.target.value)}
              />
              <button type="button" className="btn-secondary shrink-0" onClick={testWebhook}>
                <Icon name="send" />Test
              </button>
            </div>
            <span className="text-[11px] text-slate-400 mt-1 block">
              {notif.webhook_configured ? `Configured (ends “${notif.gchat_webhook_url}”)` : 'Not configured yet'}
              {' '}— never returned in full by the API.
            </span>
          </label>

          <label className="block">
            <span className="text-th uppercase text-slate-500">Operational email recipients (comma-separated)</span>
            <textarea className="input mt-1 h-16 py-1.5" value={recipientsText}
                      onChange={e => setRecipientsText(e.target.value)}
                      placeholder="ops@company.com, alerts@company.com" />
          </label>

          <fieldset className="space-y-2">
            <legend className="text-th uppercase text-slate-500 mb-1">Alert routing</legend>
            {([
              ['alert_critical', 'Critical errors — immediate'],
              ['alert_run_summary', 'Run summaries — end of every run'],
              ['alert_send_errors', 'Send-error digests — deduplicated'],
              ['alert_reply_digest', 'Reply digest email — new replies only'],
            ] as const).map(([key, label]) => (
              <label key={key} className="flex items-center gap-2.5 text-[13px] text-slate-700 select-none">
                <input type="checkbox" className="accent-[#4F46E5] w-3.5 h-3.5"
                       checked={notif[key]} onChange={e => setNotif({ ...notif, [key]: e.target.checked })} />
                {label}
              </label>
            ))}
          </fieldset>

          <button type="submit" className="btn-primary"><Icon name="save" />Save configuration</button>
        </form>

        {/* Schedule */}
        <div className="card p-4">
          <div className="flex items-center gap-2 mb-1">
            <Icon name="schedule" />
            <h2 className="font-semibold text-slate-900">Job schedule (UTC)</h2>
          </div>
          <p className="text-[11px] text-slate-500 mb-4">
            Two slots per job, mirroring the legacy Task Scheduler pattern (±15m jitter applies).
            Import from List is manual-only.
          </p>
          <div className="space-y-2.5">
            {JOBS.map(job => (
              <div key={job} className="flex items-center gap-2">
                <span className="flex-1 text-[13px] text-slate-700 capitalize">{pretty(job)}</span>
                <input type="time" className="input !w-28" value={schedule[job]?.[0] ?? ''}
                       onChange={e => setJobTime(job, 0, e.target.value)} aria-label={`${job} first run time`} />
                <input type="time" className="input !w-28" value={schedule[job]?.[1] ?? ''}
                       onChange={e => setJobTime(job, 1, e.target.value)} aria-label={`${job} second run time`} />
              </div>
            ))}
          </div>
          <button className="btn-primary mt-4" onClick={saveSchedule}><Icon name="save" />Save schedule</button>

          <div className="mt-6 pt-4 border-t border-hairline text-[11px] text-slate-500 leading-relaxed">
            <p className="flex items-start gap-1.5">
              <Icon name="verified_user" className="!text-[14px] mt-px shrink-0" />
              <span>
                Session cookies and Sales Navigator credentials are never exposed by the API and are
                never rendered in this interface — only session health and status indicators are shown.
              </span>
            </p>
          </div>
        </div>
      </div>
    </Shell>
  )
}
