import { notificationsEnabled, requestNotifyPermission } from '@/lib/notify';
import { useState } from 'react';
import { Activity, Bell, Plus, RefreshCw, Save, Search, Trash2 } from 'lucide-react';
import { Button, Card, EmptyState, ErrorState, Loading, Pill, cn } from '@/components/ui';
import { Input, PageHeader, Select, Switch } from '@/components/form';
import { apiGet, apiPost, apiPut } from '@/lib/api';
import { useAsync } from '@/lib/hooks';
import { useToast } from '@/lib/toast';
import { useAuth } from '@/lib/auth';
import { ago, fmtDT } from '@/lib/format';
import type { Tone } from '@/lib/constants';
import UsersPage from '@/pages/Users';

interface NotificationSettings {
  gchat_webhook_url: string;
  webhook_configured: boolean;
  email_recipients: string[];
  alert_critical: boolean;
  alert_run_summary: boolean;
  alert_send_errors: boolean;
  alert_reply_digest: boolean;
}

interface ActivityItem {
  id: number;
  username: string;
  action: string;
  detail: string;
  result: string;
  run_id: number | null;
  created_at: string;
}

interface UserActivityResponse {
  total: number;
  page: number;
  items: ActivityItem[];
}

export default function Settings() {
  const { me } = useAuth();
  const isAdmin = me?.role === 'admin';

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Settings"
        subtitle="Access management, notification routing, and audit trail"
      />

      {/* Users & Access section: moved to top */}
      {isAdmin && <UsersPage compact />}

      {/* Side-by-side compact Notifications & User Activity Log */}
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
        <NotificationsCard />
        <UserActivityCard />
      </div>
    </div>
  );
}

function UserActivityCard() {
  const [page, setPage] = useState(1);
  const [username, setUsername] = useState('');
  const [action, setAction] = useState('');
  const [queryUser, setQueryUser] = useState('');

  const url = `/api/user-activity?page=${page}&action=${encodeURIComponent(action)}&username=${encodeURIComponent(queryUser)}`;
  const { data, error, loading, reload } = useAsync<UserActivityResponse>(() => apiGet(url), [page, action, queryUser]);

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 50));

  const formatAction = (act: string) => act.replace(/_/g, ' ');

  const getActionTone = (act: string, res: string): Tone => {
    if (res.startsWith('rejected')) return 'crit';
    if (act.includes('delete') || act.includes('remove')) return 'warn';
    if (act.includes('create') || act.includes('add')) return 'primary';
    if (act === 'login') return 'ok';
    return 'info';
  };

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-3 border-b border-line pb-3">
        <div>
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-primary" />
            <h2 className="text-[15px] font-semibold">User activity log</h2>
          </div>
          <p className="card-sub text-[11.5px]">Audit trail of every user account activity</p>
        </div>
        <div className="flex items-center gap-2">
          {total > 0 && <span className="num text-[11.5px] text-muted">{total} events</span>}
          <Button
            size="sm"
            variant="secondary"
            icon={<RefreshCw size={13} className={loading ? 'animate-spin' : undefined} />}
            onClick={() => void reload()}
            isStatic
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <div className="flex min-w-[140px] flex-1 items-center gap-1.5">
          <Input
            placeholder="Filter by user…"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                setPage(1);
                setQueryUser(username.trim());
              }
            }}
            className="h-8 text-[12px]"
          />
          <Button
            size="sm"
            variant="secondary"
            className="h-8 px-2.5 text-[12px]"
            onClick={() => {
              setPage(1);
              setQueryUser(username.trim());
            }}
            isStatic
          >
            <Search size={13} aria-hidden />
          </Button>
        </div>
        <Select
          value={action}
          onChange={(e) => {
            setPage(1);
            setAction(e.target.value);
          }}
          className="h-8 w-auto min-w-[130px] text-[12px]"
        >
          <option value="">All actions</option>
          <option value="login">Login</option>
          <option value="create_campaign">Create campaign</option>
          <option value="update_campaign">Update campaign</option>
          <option value="delete_campaign">Delete campaign</option>
          <option value="pause_campaign">Pause campaign</option>
          <option value="reassign_leads">Reassign leads</option>
          <option value="upload_cookies">Upload cookies</option>
          <option value="refresh_cookies">Refresh cookies</option>
          <option value="verify_session">Verify session</option>
        </Select>
      </div>

      {loading && !data ? (
        <Loading label="Loading user activity…" />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !items.length ? (
        <EmptyState title="No activity recorded" body="User account actions will appear here." />
      ) : (
        <div className="scroll-y flex max-h-[380px] flex-col divide-y divide-line pr-1">
          {items.map((it) => (
            <div key={it.id} className="flex flex-col gap-1 py-2 text-[12.5px] first:pt-1 last:pb-1">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate font-semibold text-foreground">{it.username}</span>
                  <Pill tone={getActionTone(it.action, it.result)}>
                    {formatAction(it.action)}
                  </Pill>
                </div>
                <span className="shrink-0 text-[11px] text-muted" title={fmtDT(it.created_at)}>
                  {ago(it.created_at)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 text-[12px]">
                <span className="max-w-[85%] truncate text-muted" title={it.detail}>
                  {it.detail || '—'}
                </span>
                <span
                  className={cn(
                    'shrink-0 text-[11px] font-medium',
                    it.result === 'success' ? 'text-ok' : 'text-crit',
                  )}
                >
                  {it.result}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-line pt-2 text-[12px] text-muted">
          <span>
            Page {page} of {totalPages}
          </span>
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-[12px]"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              isStatic
            >
              Prev
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-[12px]"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              isStatic
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

function NotificationsCard() {
  const [desktop, setDesktop] = useState(notificationsEnabled);
  const toast = useToast();
  const { data, error, loading, reload } = useAsync<NotificationSettings>(
    () => apiGet('/api/settings/notifications'),
    [],
  );
  const [draft, setDraft] = useState<NotificationSettings | null>(null);
  const [busy, setBusy] = useState(false);

  const current = draft ?? data;

  if (loading && !data) return <Loading label="Loading notification settings…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!current) return null;

  const set = <K extends keyof NotificationSettings>(k: K, v: NotificationSettings[K]) =>
    setDraft({ ...current, [k]: v });

  const save = async () => {
    setBusy(true);
    try {
      await apiPut('/api/settings/notifications', {
        gchat_webhook_url: current.gchat_webhook_url,
        email_recipients: current.email_recipients,
        alert_critical: current.alert_critical,
        alert_run_summary: current.alert_run_summary,
        alert_send_errors: current.alert_send_errors,
        alert_reply_digest: current.alert_reply_digest,
      });
      toast('Notification settings saved', 'ok');
      setDraft(null);
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-3 border-b border-line pb-2.5">
        <div>
          <h2 className="flex items-center gap-2 text-[14.5px] font-semibold">
            <Bell size={15} aria-hidden className="text-primary" /> Notifications
          </h2>
          <p className="card-sub text-[11px]">Alert routing and reply digest email</p>
        </div>
        <Button
          size="sm"
          variant="secondary"
          icon={<Bell size={12} aria-hidden />}
          onClick={async () => {
            try {
              const res = await apiPost<{ ok: boolean }>('/api/settings/test-webhook');
              toast(res.ok ? 'Test message sent' : 'Delivery failed — check the webhook', res.ok ? 'ok' : 'crit');
            } catch (e) {
              toast(e instanceof Error ? e.message : String(e), 'crit');
            }
          }}
          isStatic
        >
          Send test
        </Button>
      </div>

      <div className="mt-2.5 flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-[12.5px] font-medium text-foreground">Email recipients</span>
          <Button
            size="sm"
            variant="secondary"
            className="h-6 px-2 text-[11px]"
            icon={<Plus size={11} aria-hidden />}
            onClick={() => set('email_recipients', [...current.email_recipients, ''])}
            isStatic
          >
            Add email
          </Button>
        </div>
        <div className="flex flex-col gap-1.5">
          {current.email_recipients.length === 0 && (
            <p className="rounded-lg bg-inset/60 px-3 py-1.5 text-[11.5px] text-muted">
              No recipients configured. Add an email to receive alert summaries.
            </p>
          )}
          {current.email_recipients.map((r, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <Input
                aria-label={`Recipient ${i + 1}`}
                placeholder="name@company.com"
                value={r}
                onChange={(e) =>
                  set(
                    'email_recipients',
                    current.email_recipients.map((x, j) => (j === i ? e.target.value : x)),
                  )
                }
                className="h-8 flex-1 text-[12.5px]"
              />
              <button
                type="button"
                aria-label={`Remove recipient ${i + 1}`}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border/80 bg-surface text-muted transition-all hover:border-crit/50 hover:bg-crit-tint/40 hover:text-crit active:scale-95"
                onClick={() =>
                  set('email_recipients', current.email_recipients.filter((_, j) => j !== i))
                }
              >
                <Trash2 size={13} aria-hidden />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-2.5">
        <div className="rounded-lg border border-border/70 bg-surface-2/60 p-2 px-2.5 transition-colors hover:border-border">
          <Switch
            checked={desktop}
            onChange={(v) => {
              setDesktop(v);
              localStorage.setItem('cm-desktop-notify', v ? 'on' : 'off');
              if (v) requestNotifyPermission();
            }}
            label="Desktop notification when a run finishes"
            hint="Completion alert when browser tab is inactive."
          />
        </div>
      </div>

      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border/70 bg-surface-2/60 p-2 px-2.5 transition-colors hover:border-border">
          <Switch
            checked={current.alert_critical}
            onChange={(v) => set('alert_critical', v)}
            label="Critical alerts"
            hint="Job halts or fatal errors."
          />
        </div>
        <div className="rounded-lg border border-border/70 bg-surface-2/60 p-2 px-2.5 transition-colors hover:border-border">
          <Switch
            checked={current.alert_run_summary}
            onChange={(v) => set('alert_run_summary', v)}
            label="Run summaries"
            hint="Recap after worker finishes."
          />
        </div>
        <div className="rounded-lg border border-border/70 bg-surface-2/60 p-2 px-2.5 transition-colors hover:border-border">
          <Switch
            checked={current.alert_send_errors}
            onChange={(v) => set('alert_send_errors', v)}
            label="Send errors"
            hint="Individual send failures."
          />
        </div>
        <div className="rounded-lg border border-border/70 bg-surface-2/60 p-2 px-2.5 transition-colors hover:border-border">
          <Switch
            checked={current.alert_reply_digest}
            onChange={(v) => set('alert_reply_digest', v)}
            label="Reply digest"
            hint="Batched email of new replies."
          />
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-line pt-2.5">
        <span className="text-[11.5px] text-muted">
          {draft ? 'Unsaved changes' : 'All settings saved'}
        </span>
        <Button
          variant="primary"
          size="sm"
          className="h-8 px-3 font-medium text-[12px]"
          icon={<Save size={13} aria-hidden />}
          disabled={busy || !draft}
          onClick={() => void save()}
          isStatic
        >
          {busy ? 'Saving…' : 'Save notifications'}
        </Button>
      </div>
    </Card>
  );
}
