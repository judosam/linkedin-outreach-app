// Typed API client. All requests send credentials (session cookie).
export const api = {
  async get<T>(url: string): Promise<T> {
    const res = await fetch(url, { credentials: 'include' })
    if (res.status === 401) { window.location.hash = '#/login'; throw new ApiError('Not authenticated', 401) }
    if (!res.ok) throw new ApiError((await jsonOrText(res)) || res.statusText, res.status)
    return res.json()
  },
  async send<T>(method: string, url: string, body?: unknown): Promise<T> {
    const res = await fetch(url, {
      method,
      credentials: 'include',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    if (res.status === 401) { window.location.hash = '#/login'; throw new ApiError('Not authenticated', 401) }
    if (!res.ok) throw new ApiError((await jsonOrText(res)) || res.statusText, res.status)
    return res.json()
  },
  post<T>(url: string, body?: unknown) { return this.send<T>('POST', url, body) },
  put<T>(url: string, body?: unknown) { return this.send<T>('PUT', url, body) },
}

async function jsonOrText(res: Response) {
  try {
    const j = await res.json()
    return j.detail ? String(j.detail) : JSON.stringify(j)
  } catch {
    return res.text()
  }
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}

// ---------- shared types ----------
export interface Dashboard {
  totals: { leads_total: number; leads_untagged: number; campaigns_active: number; accounts_active: number }
  today: { invites: number; inmails: number; invites_limit: number; inmails_limit: number; followups: number; followups_limit: number; contacted: number; contacted_yesterday: number }
  replies: { total: number; today: number }
  funnel: Record<string, number>
  campaign_rates: { id: number; campaign_key: string; leads: number; replied: number; rate: number }[]
  recent_runs: { id: number; job: string; status: string; started_at: string | null; duration_s: number | null; dry_run: boolean }[]
  scheduler_healthy: boolean
}

export interface AccountRow {
  id: number; name: string; status: string; session_configured: boolean
  last_cookie_refresh_at: string | null; cookie_age_hours: number | null
  session_state: string; campaigns: string[]
}

export interface CampaignAccountLink {
  account_id: number; account_name: string; order_index: number
  invite_limit: number; inmail_limit: number; message_limit: number
  calendar_url: string | null; search_url_override: string | null
}

export interface CampaignListItem {
  id: number; campaign_key: string; name: string; status: string; search_url: string
  accounts: CampaignAccountLink[]; leads: number; contacted: number; replied: number; reply_rate: number
}

export interface CampaignDetail extends Omit<CampaignListItem, 'leads' | 'contacted' | 'replied' | 'reply_rate'> {
  invite_text: string
  invite_track: string[]
  inmail_subject: string
  inmail_text: string
  inmail_track: { subject: string; body: string }[]
}

export interface LeadRow {
  id: number; sales_nav_id: string; full_name: string; title: string; company: string
  location: string; opentomsg: boolean | null; source: string
  campaign: string | null; associate_account: string | null
  status: string; received_replies: boolean; reply_message: string; created_at: string | null
}

export interface LeadPage { total: number; page: number; page_size: number; items: LeadRow[] }

export interface ThreadRow {
  id: number; full_name: string; title: string; company: string
  campaign: string | null; account: string | null
  reply_message: string | null; reply_received_at: string | null; status: string
}

export interface JobRow {
  key: string; schedule: string[]; running_now: boolean; description: string
  last_run: { id: number; status: string; started_at: string | null; duration_s: number | null; dry_run: boolean } | null
}

export interface RunRow {
  id: number; job: string; target: string; dry_run: boolean; status: string
  started_at: string | null; finished_at: string | null; duration_s: number | null
  stats: Record<string, unknown> | null; errors: string[] | null
}

export interface NotificationSettings {
  gchat_webhook_url: string; webhook_configured: boolean
  email_recipients: string[]
  alert_critical: boolean; alert_run_summary: boolean; alert_send_errors: boolean; alert_reply_digest: boolean
}

// ---------- status metadata (color + label + icon = never color alone) ----------
export const STATUS_META: Record<string, { label: string; tone: 'ok' | 'warn' | 'crit' | 'idle' | 'primary' }> = {
  '': { label: 'Untouched', tone: 'idle' },
  INVITE_SENT: { label: 'Invite Sent', tone: 'primary' },
  INMAIL_SENT: { label: 'InMail Sent', tone: 'primary' },
  INVITE_AFTER_ACCEPT: { label: 'After Accept', tone: 'ok' },
  INVITE_FOLLOWUP_1: { label: 'Invite FU 1', tone: 'primary' },
  INVITE_FOLLOWUP_2: { label: 'Invite FU 2', tone: 'primary' },
  INVITE_FOLLOWUP_3: { label: 'Invite FU 3', tone: 'primary' },
  INMAIL_FOLLOWUP_1: { label: 'InMail FU 1', tone: 'primary' },
  INMAIL_FOLLOWUP_2: { label: 'InMail FU 2', tone: 'primary' },
  INMAIL_FOLLOWUP_3: { label: 'InMail FU 3', tone: 'primary' },
}
