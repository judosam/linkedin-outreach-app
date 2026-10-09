export type Role = 'admin' | 'campaign_manager';

export interface Me {
  user: string;
  name: string;
  role: Role;
  must_change_password: boolean;
  allowed_campaign_ids: number[];
  allowed_account_ids: number[];
  can_manage_licenses?: boolean;
}

export interface Summary {
  totals: {
    leads_total: number;
    leads_untagged: number;
    campaigns_active: number;
    accounts_active: number;
  };
  window_days: number;
  today: {
    invites: number;
    inmails: number;
    invites_limit: number;
    inmails_limit: number;
    followups: number;
    followups_limit: number;
    contacted: number;
    contacted_yesterday: number;
    contacted_window: number;
    leads_added: number;
  };
  replies: { total: number; today: number; window: number };
  funnel: Record<string, number>;
  campaign_rates: {
    id: number;
    campaign_key: string;
    leads: number;
    replied: number;
    rate: number;
  }[];
  recent_runs: Run[];
  scheduler_healthy: boolean;
  kpis?: {
    accounts_active: number;
    campaigns_active: number;
    leads_total: number;
    connections_sent: number;
    acceptance_rate: number;
    inmails_sent: number;
    replies_received: number;
    positive_replies: number;
    meetings_booked: number;
    pending_followups: number;
    accounts_attention: number;
    pending_reviews: number;
  };
}

export interface TrendPoint {
  date: string;
  invites: number;
  inmails: number;
  messages: number;
}

export interface Trends {
  days: TrendPoint[];
  runs_24h: {
    total: number;
    success: number;
    success_rate: number | null;
    avg_duration_s: number | null;
  };
}

export interface ActivityEvent {
  id: number;
  kind: 'outbound' | 'reply' | 'error' | 'assignment';
  detail: string;
  created_at: string;
  lead_name: string | null;
  company: string | null;
  account: string | null;
  campaign: string | null;
  campaign_id: number | null;
  job: string | null;
}

export interface Run {
  id: number;
  job: string;
  target: string | null;
  dry_run: boolean;
  schedule_id?: number | null;
  status: string;
  started_at: string | null;
  finished_at?: string | null;
  duration_s: number | null;
  stats?: unknown;
  errors?: string[] | null;
}

export interface JobInfo {
  key: string;
  schedule: string[];
  last_run: { id: number; status: string; started_at: string | null; duration_s: number | null; dry_run: boolean } | null;
  running_now: boolean;
  description: string;
}

export interface JobsPayload {
  jobs: JobInfo[];
  nav?: {
    accounts_active?: number;
    campaigns_active?: number;
    unread_replies?: number;
    scheduler_healthy?: boolean;
  };
  live?: {
    status?: string;
    job?: string;
    run_id?: number;
    execution_id?: string;
    started_at?: string;
    account_runs?: Record<string, number>;
  } | null;
  running?: { execution_id?: string; job?: string; run_id?: number }[];
}

export interface CampaignStatRow {
  campaign_id: number;
  campaign: string;
  account_id: number | null;
  account: string;
  invites: number;
  inmails: number;
  messages: number;
  replies: number;
  runs: number;
  last_run: { id: number; job: string; status: string; started_at: string } | null;
}

export interface CampaignStats {
  rows: CampaignStatRow[];
  days: number;
  timezone: string;
  start: string | null;
  end: string;
}
