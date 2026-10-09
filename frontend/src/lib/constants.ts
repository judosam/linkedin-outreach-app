export type Tone = 'ok' | 'warn' | 'crit' | 'info' | 'primary' | 'idle';

export const STATUS_META: Record<string, { label: string; tone: Tone }> = {
  '': { label: 'Untouched', tone: 'idle' },
  BLOCKED_ERROR: { label: 'Error', tone: 'crit' },
  INVITE_SENT: { label: 'Invite Sent', tone: 'primary' },
  INMAIL_SENT: { label: 'InMail Sent', tone: 'info' },
  INVITE_AFTER_ACCEPT: { label: 'After Accept', tone: 'ok' },
  INVITE_FOLLOWUP_1: { label: 'Invite FU 1', tone: 'primary' },
  INVITE_FOLLOWUP_2: { label: 'Invite FU 2', tone: 'primary' },
  INVITE_FOLLOWUP_3: { label: 'Invite FU 3', tone: 'primary' },
  INMAIL_FOLLOWUP_1: { label: 'InMail FU 1', tone: 'info' },
  INMAIL_FOLLOWUP_2: { label: 'InMail FU 2', tone: 'info' },
  INMAIL_FOLLOWUP_3: { label: 'InMail FU 3', tone: 'info' },
};

export const JOB_LABELS: Record<string, string> = {
  sync_leads: 'Import SavedSearch',
  import_list: 'Import SavedList',
  send_connections: 'Send Connections',
  check_replies: 'Check Replies',
  send_followups: 'Send Follow-ups',
};

export const WORKERS = ['send_connections', 'check_replies', 'send_followups'];

export const RUN_TONE: Record<string, Tone> = {
  success: 'ok',
  partial: 'warn',
  error: 'crit',
  running: 'primary',
  stopping: 'warn',
  stopped: 'warn',
  skipped: 'idle',
};

/* Mirrors app/classify.CATEGORY_LABELS — the server rejects anything else. */
export const REPLY_CATEGORIES: { value: string; label: string }[] = [
  { value: 'positive', label: 'Positive / Interested' },
  { value: 'meeting', label: 'Meeting requested' },
  { value: 'followup_later', label: 'Follow up later' },
  { value: 'referral', label: 'Referral' },
  { value: 'declined', label: 'Declined / Not interested' },
  { value: 'unsubscribe', label: 'Unsubscribe / Do not contact' },
  { value: 'ooo', label: 'Out of office' },
  { value: 'unclassified', label: 'Unclassified' },
];

export const FUNNEL_ORDER = [
  { key: '', label: 'Untouched' },
  { key: 'INVITE_SENT', label: 'Invite sent' },
  { key: 'INVITE_AFTER_ACCEPT', label: 'After accept' },
  { key: 'INVITE_FOLLOWUP_1', label: 'Invite FU 1' },
  { key: 'INVITE_FOLLOWUP_2', label: 'Invite FU 2' },
  { key: 'INVITE_FOLLOWUP_3', label: 'Invite FU 3' },
  { key: 'INMAIL_SENT', label: 'InMail sent' },
  { key: 'INMAIL_FOLLOWUP_1', label: 'InMail FU 1' },
  { key: 'INMAIL_FOLLOWUP_2', label: 'InMail FU 2' },
  { key: 'INMAIL_FOLLOWUP_3', label: 'InMail FU 3' },
];
