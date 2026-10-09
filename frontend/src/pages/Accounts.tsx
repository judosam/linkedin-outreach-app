import { useState, useRef, useEffect } from 'react';
import {
  BadgeCheck,
  Building2,
  ChevronDown,
  ExternalLink,
  FileUp,
  Pause,
  Pencil,
  Play,
  Plus,
  RotateCw,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { Button, Card, EmptyState, ErrorState, Loading, Meter, Pill, Progress, cn } from '@/components/ui';
import { Field, Input, PageHeader, Select } from '@/components/form';
import { Modal } from '@/components/Modal';
import { apiDelete, apiGet, apiPost, apiPut } from '@/lib/api';
import { useAsync } from '@/lib/hooks';
import { useToast } from '@/lib/toast';
import { fmtDT, ago, nf, initials } from '@/lib/format';
import type { Tone } from '@/lib/constants';

interface Account {
  id: number;
  name: string;
  status: string;
  session_configured: boolean;
  last_cookie_refresh_at: string | null;
  cookie_age_hours: number | null;
  session_state: string;
  campaigns: string[];
  campaign_ids: number[];
  daily_invite_cap: number;
  weekly_invite_cap: number;
  weekly_invites: { used: number; limit: number; remaining: number };
  daily_inmail_cap: number;
  daily_message_cap: number;
  usage_today: { invites: number; inmails: number; messages: number };
  total_runs: number;
}

interface CampaignRow {
  id: number;
  name: string;
  campaign_key: string;
  status: string;
}

const STATUS_TONE: Record<string, Tone> = {
  active: 'ok',
  paused: 'idle',
  needs_reauth: 'crit',
  seat_required: 'warn',
};

function sessionLabel(status: string): string {
  if (status === 'active') return 'Active';
  if (status === 'seat_required') return 'Sales Nav required';
  if (status === 'needs_reauth') return 'Needs reauth';
  if (status === 'paused') return 'Paused';
  return status.replace(/_/g, ' ');
}

const ACCOUNT_AVATARS = [
  'bg-blue-500/15 text-blue-500 border-blue-500/25',
  'bg-emerald-500/15 text-emerald-500 border-emerald-500/25',
  'bg-purple-500/15 text-purple-500 border-purple-500/25',
  'bg-amber-500/15 text-amber-500 border-amber-500/25',
  'bg-indigo-500/15 text-indigo-500 border-indigo-500/25',
  'bg-rose-500/15 text-rose-500 border-rose-500/25',
];

export default function Accounts() {
  const toast = useToast();
  const accounts = useAsync<Account[]>(() => apiGet('/api/accounts'), []);
  const campaigns = useAsync<CampaignRow[]>(() => apiGet('/api/campaigns'), []);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Account | null>(null);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [verifyingAll, setVerifyingAll] = useState(false);

  const verifyAll = async () => {
    setVerifyingAll(true);
    try {
      const res = await apiPost<{
        ok: boolean;
        verified_count: number;
        failed_count: number;
        skipped_count: number;
        total: number;
      }>('/api/accounts/verify-all');
      if (res.failed_count === 0 && res.verified_count > 0) {
        toast(`All ${res.verified_count} account sessions verified`, 'ok');
      } else if (res.verified_count === 0 && res.skipped_count > 0) {
        toast(`No configured sessions to verify (${res.skipped_count} need cookies)`, 'warn');
      } else {
        toast(
          `Verified ${res.verified_count} accounts (${res.failed_count} failed${
            res.skipped_count ? `, ${res.skipped_count} skipped` : ''
          })`,
          res.verified_count > 0 ? 'warn' : 'crit',
        );
      }
      await accounts.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
      await accounts.reload();
    } finally {
      setVerifyingAll(false);
    }
  };

  /* Cookie upload straight from the row — one of the three legacy entry
     points for /api/accounts/{id}/upload-cookies. */
  const uploadCookies = (a: Account, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return act(a.id, () => apiPost(`/api/accounts/${a.id}/upload-cookies`, fd), `Cookies uploaded for ${a.name}`);
  };

  const act = async (id: number, fn: () => Promise<unknown>, message: string) => {
    setBusyId(id);
    try {
      await fn();
      toast(message, 'ok');
      await accounts.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
      await accounts.reload();
    } finally {
      setBusyId(null);
    }
  };

  const rows = accounts.data ?? [];
  // Derive from the live list so the popup never shows stale numbers.
  const detail = detailId != null ? rows.find((a) => a.id === detailId) ?? null : null;

  /* The server refuses a status change on an account that still needs
     verification, so only active/paused accounts get a working toggle. */
  const toggleStatus = (a: Account) => {
    const next = a.status === 'active' ? 'paused' : 'active';
    return act(
      a.id,
      () => apiPut(`/api/accounts/${a.id}`, { name: a.name, status: next }),
      `${a.name} ${next === 'paused' ? 'paused' : 'resumed'}`,
    );
  };
  const canToggle = (a: Account) => a.status === 'active' || a.status === 'paused';

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Accounts"
        subtitle={accounts.data ? `${rows.filter((a) => a.status === 'active').length} active of ${rows.length}` : 'LinkedIn sending accounts'}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              icon={
                <RotateCw
                  size={14}
                  className={cn('text-muted', verifyingAll && 'animate-spin text-primary')}
                  aria-hidden
                />
              }
              onClick={() => void verifyAll()}
              disabled={verifyingAll || rows.length === 0}
              title="Verify sessions and cookies for all accounts"
              isStatic
            >
              {verifyingAll ? 'Verifying all…' : 'Verify all'}
            </Button>
            <Button variant="primary" icon={<Plus size={15} aria-hidden />} onClick={() => setCreating(true)} isStatic>
              Add account
            </Button>
          </div>
        }
      />

      {accounts.loading && !accounts.data ? (
        <Loading />
      ) : accounts.error ? (
        <ErrorState message={accounts.error} onRetry={accounts.reload} />
      ) : rows.length ? (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1160px] table-fixed border-collapse text-[13px]">
              <colgroup>
                <col style={{ width: '21%' }} /> {/* Account */}
                <col style={{ width: '12%' }} /> {/* Session */}
                <col style={{ width: '8%' }} />  {/* Refreshed */}
                <col style={{ width: '8%' }} />  {/* InMail */}
                <col style={{ width: '8%' }} />  {/* Invites */}
                <col style={{ width: '10%' }} /> {/* Invites / week */}
                <col style={{ width: '8%' }} />  {/* Messages */}
                <col style={{ width: '25%' }} /> {/* Actions */}
              </colgroup>
              <thead>
                <tr className="border-b border-line/70 text-left text-[11.5px] font-medium text-muted">
                  <th className="py-3 px-3">Account</th>
                  <th className="py-3 px-3">Session</th>
                  <th className="py-3 px-3">Refreshed</th>
                  <th className="py-3 px-3">InMail</th>
                  <th className="py-3 px-3">Invites</th>
                  <th className="py-3 px-3">Invites / week</th>
                  <th className="py-3 px-3">Messages</th>
                  <th className="py-3 pr-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {rows.map((a, idx) => {
                  const u = a.usage_today;
                  const weeklyLimit = a.weekly_invites?.limit ?? a.weekly_invite_cap;
                  const weeklyUsed = a.weekly_invites?.used ?? 0;
                  const weeklyLeft = a.weekly_invites?.remaining ?? Math.max(0, weeklyLimit - weeklyUsed);
                  return (
                    <tr
                      key={a.id}
                      onClick={() => setDetailId(a.id)}
                      className="group cursor-pointer transition-colors hover:bg-surface-2/60"
                      title="Click to view account details and settings"
                    >
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-2.5">
                          <span
                            className={cn(
                              'flex h-9 w-9 shrink-0 items-center justify-center rounded-full border text-[12px] font-bold shadow-xs',
                              ACCOUNT_AVATARS[idx % ACCOUNT_AVATARS.length],
                            )}
                            aria-hidden
                          >
                            {initials(a.name)}
                          </span>
                          <div className="flex flex-col min-w-0">
                            <span className="truncate font-semibold text-[13.5px] text-foreground group-hover:text-primary transition-colors">
                              {a.name}
                            </span>
                            <div className="flex items-center gap-1 mt-0.5">
                              {a.campaigns.length > 0 ? (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setDetailId(a.id);
                                  }}
                                  className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:text-primary-hover hover:underline cursor-pointer"
                                  title={`Mapped to: ${a.campaigns.join(', ')}`}
                                >
                                  <span>{a.campaigns.length} {a.campaigns.length === 1 ? 'campaign' : 'campaigns'}</span>
                                  <ExternalLink size={10} className="opacity-70 shrink-0" aria-hidden />
                                </button>
                              ) : (
                                <span className="text-[11px] text-muted">0 campaigns</span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <Pill tone={STATUS_TONE[a.status] ?? 'idle'} dot>
                          {sessionLabel(a.status)}
                        </Pill>
                      </td>
                      <td className="py-3 px-3">
                        <span className="whitespace-nowrap text-[12px] text-muted">
                          {a.session_configured ? ago(a.last_cookie_refresh_at) : 'No session'}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-1.5 whitespace-nowrap">
                          <Meter
                            value={u.inmails}
                            limit={Math.max(1, a.daily_inmail_cap)}
                            width={38}
                            className="bg-line/90 border border-border/40 shadow-2xs shrink-0"
                          />
                          <span className="font-sans tabular-nums text-[12px] font-semibold text-foreground whitespace-nowrap">
                            {u.inmails}/{a.daily_inmail_cap}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-1.5 whitespace-nowrap">
                          <Meter
                            value={u.invites}
                            limit={Math.max(1, a.daily_invite_cap)}
                            width={38}
                            className="bg-line/90 border border-border/40 shadow-2xs shrink-0"
                          />
                          <span className="font-sans tabular-nums text-[12px] font-semibold text-foreground whitespace-nowrap">
                            {u.invites}/{a.daily_invite_cap}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <div className="flex flex-col gap-0.5 whitespace-nowrap">
                          <div className="flex items-center gap-1.5">
                            <Meter
                              value={weeklyUsed}
                              limit={Math.max(1, weeklyLimit)}
                              width={44}
                              className="bg-line/90 border border-border/40 shadow-2xs shrink-0"
                            />
                            <span className="font-sans tabular-nums text-[12px] font-semibold text-foreground whitespace-nowrap">
                              {weeklyUsed}/{weeklyLimit}
                            </span>
                          </div>
                          <span className="text-[10.5px] text-muted">{weeklyLeft} left</span>
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-1.5 whitespace-nowrap">
                          <Meter
                            value={u.messages}
                            limit={Math.max(1, a.daily_message_cap)}
                            width={38}
                            className="bg-line/90 border border-border/40 shadow-2xs shrink-0"
                          />
                          <span className="font-sans tabular-nums text-[12px] font-semibold text-foreground whitespace-nowrap">
                            {u.messages}/{a.daily_message_cap}
                          </span>
                        </div>
                      </td>
                      <td className="py-3 pr-4 text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1.5 w-full whitespace-nowrap">
                          {/* Upload cookies button */}
                          <label
                            className={cn(
                              'inline-flex h-8 shrink-0 cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-border/80 bg-surface px-2.5 text-[12px] font-medium text-foreground shadow-2xs hover:border-primary/50 hover:bg-surface-2 hover:text-primary active:scale-[0.97] transition-all',
                              busyId === a.id && 'opacity-50 pointer-events-none',
                            )}
                            title="Upload cookies JSON file"
                          >
                            <FileUp size={13} className="text-muted shrink-0" aria-hidden />
                            <span>Upload</span>
                            <input
                              type="file"
                              accept="application/json,.json"
                              className="hidden"
                              disabled={busyId === a.id}
                              onChange={(e) => {
                                const f = e.target.files?.[0];
                                if (f) void uploadCookies(a, f);
                                e.target.value = '';
                              }}
                            />
                          </label>

                          {/* Pause / Resume button */}
                          <button
                            type="button"
                            disabled={busyId === a.id || !canToggle(a)}
                            onClick={() => void toggleStatus(a)}
                            title={a.status === 'active' ? 'Pause account activity' : 'Resume account activity'}
                            className={cn(
                              'inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border/80 bg-surface px-2.5 text-[12px] font-medium shadow-2xs active:scale-[0.97] transition-all disabled:opacity-50 disabled:pointer-events-none cursor-pointer',
                              a.status === 'active'
                                ? 'text-foreground hover:border-border hover:bg-surface-2'
                                : 'text-primary border-primary/30 bg-primary/5 hover:bg-primary/10',
                            )}
                          >
                            {a.status === 'active' ? (
                              <Pause size={12} className="text-muted shrink-0" aria-hidden />
                            ) : (
                              <Play size={12} className="text-primary fill-primary/20 shrink-0" aria-hidden />
                            )}
                            <span>{a.status === 'active' ? 'Pause' : 'Resume'}</span>
                          </button>

                          {/* Verify button */}
                          <button
                            type="button"
                            disabled={busyId === a.id || !a.session_configured}
                            onClick={() => void act(a.id, () => apiPost(`/api/accounts/${a.id}/verify-session`), `${a.name} verified`)}
                            title="Verify account session and cookies"
                            className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border/80 bg-surface px-2.5 text-[12px] font-medium text-foreground shadow-2xs hover:border-primary/50 hover:bg-surface-2 hover:text-primary active:scale-[0.97] transition-all disabled:opacity-50 disabled:pointer-events-none cursor-pointer"
                          >
                            <RotateCw size={12} className={cn('text-muted shrink-0', busyId === a.id && 'animate-spin')} aria-hidden />
                            <span>Verify</span>
                          </button>

                          {/* Delete account */}
                          <button
                            type="button"
                            disabled={busyId === a.id}
                            onClick={async () => {
                              if (!window.confirm(`Delete ${a.name}? Outreach history is kept.`)) return;
                              await act(a.id, () => apiDelete(`/api/accounts/${a.id}`), `${a.name} deleted`);
                            }}
                            title={`Delete ${a.name}`}
                            aria-label={`Delete ${a.name}`}
                            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border/80 bg-surface text-ink2 shadow-2xs hover:border-crit/50 hover:bg-crit-tint/40 hover:text-crit active:scale-[0.97] transition-all disabled:opacity-50 disabled:pointer-events-none cursor-pointer"
                          >
                            <Trash2 size={13} aria-hidden />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <Card className="p-6">
          <EmptyState
            icon={<Building2 size={22} aria-hidden />}
            title="No accounts yet"
            body="Add a LinkedIn account, upload its cookie file, then verify the session."
            action={
              <Button variant="primary" onClick={() => setCreating(true)} isStatic>
                Add account
              </Button>
            }
          />
        </Card>
      )}

      <AccountDetail
        account={detail}
        busyId={busyId}
        onClose={() => setDetailId(null)}
        onVerify={(a) => void act(a.id, () => apiPost(`/api/accounts/${a.id}/verify-session`), `${a.name} verified`)}
        onUploadCookies={(a, file) => void uploadCookies(a, file)}
        onDelete={async (a) => {
          if (!window.confirm(`Delete ${a.name}? Outreach history is kept.`)) return;
          setDetailId(null);
          await act(a.id, () => apiDelete(`/api/accounts/${a.id}`), `${a.name} deleted`);
        }}
        onEdit={(a) => {
          setDetailId(null);
          setEditing(a);
        }}
      />

      <AccountDialog
        open={creating || !!editing}
        account={editing}
        campaigns={campaigns.data ?? []}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
        onSaved={() => {
          setCreating(false);
          setEditing(null);
          void accounts.reload();
        }}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Detail popup — everything the compact row cannot show                     */
/* -------------------------------------------------------------------------- */

function AccountDetail({
  account,
  busyId,
  onClose,
  onVerify,
  onUploadCookies,
  onDelete,
  onEdit,
}: {
  account: Account | null;
  busyId: number | null;
  onClose: () => void;
  onVerify: (a: Account) => void;
  onUploadCookies: (a: Account, file: File) => void;
  onDelete: (a: Account) => void;
  onEdit: (a: Account) => void;
}) {
  if (!account) return null;
  const u = account.usage_today;
  const weeklyLimit = account.weekly_invites?.limit ?? account.weekly_invite_cap;
  const weeklyUsed = account.weekly_invites?.used ?? 0;

  return (
    <Modal
      open
      onClose={onClose}
      title={account.name}
      size="lg"
      footer={
        <div className="flex w-full items-center justify-between">
          <Button
            variant="danger"
            size="sm"
            icon={<Trash2 size={13} aria-hidden />}
            disabled={busyId === account.id}
            onClick={() => onDelete(account)}
            isStatic
          >
            Delete account
          </Button>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<BadgeCheck size={13} className="text-emerald-500 dark:text-emerald-400" aria-hidden />}
              disabled={busyId === account.id || !account.session_configured}
              onClick={() => onVerify(account)}
              isStatic
            >
              Verify session
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<Pencil size={13} aria-hidden />}
              onClick={() => onEdit(account)}
              isStatic
            >
              Edit account
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {/* Badges */}
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone={STATUS_TONE[account.status] ?? 'idle'} dot>
            {account.status.replace(/_/g, ' ')}
          </Pill>
          {account.session_configured ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-500 dark:text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Session configured
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-medium text-amber-500 dark:text-amber-400">
              No session
            </span>
          )}
          <span className="text-[11.5px] text-muted">{nf.format(account.total_runs)} lifetime actions</span>
        </div>

        {/* Daily & Weekly Outreach Usage (Combined compact card) */}
        <section className="rounded-xl border border-line bg-surface-2/40 p-3">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-[11px] font-bold uppercase tracking-wider text-muted">Daily outreach usage</h3>
            <span className="text-[11px] text-muted">24-hour limit counters</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            {(
              [
                ['Invites', u.invites, account.daily_invite_cap],
                ['InMails', u.inmails, account.daily_inmail_cap],
                ['Messages', u.messages, account.daily_message_cap],
              ] as const
            ).map(([label, used, cap]) => (
              <div key={label} className="rounded-lg border border-line/60 bg-card p-2.5">
                <div className="flex items-center justify-between text-[12px]">
                  <span className="font-semibold text-foreground">{label}</span>
                  <span className="num font-semibold text-muted text-[11.5px]">
                    {used} / {cap}
                  </span>
                </div>
                <Progress value={used} limit={Math.max(1, cap)} className="mt-1.5 h-1.5" />
                <div className="mt-1 text-[10.5px] text-muted text-right">
                  {Math.max(0, cap - used)} left today
                </div>
              </div>
            ))}
          </div>

          {/* Weekly invitations row */}
          <div className="mt-2.5 pt-2 border-t border-line/60">
            <div className="flex items-center justify-between text-[11.5px]">
              <span className="font-semibold uppercase tracking-wider text-muted text-[10.5px]">
                Weekly invitations · rolling 7 days
              </span>
              <span className="num font-semibold text-foreground">
                {weeklyUsed} / {weeklyLimit}{' '}
                <span className="text-muted font-normal text-[11px]">
                  ({account.weekly_invites?.remaining ?? Math.max(0, weeklyLimit - weeklyUsed)} remaining)
                </span>
              </span>
            </div>
            <Progress value={weeklyUsed} limit={Math.max(1, weeklyLimit)} className="mt-1.5 h-1.5" />
          </div>
        </section>

        {/* Session & cookies (Compact card) */}
        <section className="rounded-xl border border-line bg-surface-2/40 p-3">
          <div className="flex items-center justify-between pb-2 border-b border-line/60">
            <div>
              <h3 className="text-[12px] font-semibold text-foreground">Session &amp; cookies</h3>
              <p className="text-[11px] text-muted">Authentication token &amp; cookie freshness</p>
            </div>
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary hover:bg-primary/20 shadow-xs active:scale-95 transition-all">
              <Upload size={12} aria-hidden />
              <span>Upload cookies</span>
              <input
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onUploadCookies(account, f);
                  e.target.value = '';
                }}
              />
            </label>
          </div>
          <div className="mt-2.5 grid gap-2 sm:grid-cols-3">
            <div className="rounded-lg border border-line/60 bg-card p-2">
              <span className="text-[10.5px] uppercase tracking-wide text-muted font-medium">Cookie file</span>
              <p className="mt-0.5 text-[12px] font-semibold text-foreground truncate">
                {account.session_configured ? 'Uploaded & active' : 'Not uploaded'}
              </p>
            </div>
            <div className="rounded-lg border border-line/60 bg-card p-2">
              <span className="text-[10.5px] uppercase tracking-wide text-muted font-medium">Last refresh</span>
              <p className="mt-0.5 text-[12px] font-semibold text-foreground truncate">
                {account.last_cookie_refresh_at ? fmtDT(account.last_cookie_refresh_at) : 'Never'}
              </p>
            </div>
            <div className="rounded-lg border border-line/60 bg-card p-2">
              <span className="text-[10.5px] uppercase tracking-wide text-muted font-medium">Session state</span>
              <p className="mt-0.5 text-[12px] font-semibold text-foreground truncate">
                {account.session_state || 'Not verified'}
              </p>
            </div>
          </div>
        </section>

        {/* Campaigns (Compact card) */}
        <section className="rounded-xl border border-line bg-surface-2/40 p-3">
          <div className="flex items-center justify-between">
            <h3 className="text-[11px] font-bold uppercase tracking-wider text-muted">Assigned campaigns</h3>
            <span className="text-[11px] text-muted">
              {account.campaigns.length ? `${account.campaigns.length} mapped` : 'None'}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {account.campaigns.length ? (
              account.campaigns.map((c) => (
                <span
                  key={c}
                  className="rounded-md border border-line bg-card px-2 py-0.5 text-[11.5px] font-medium text-foreground"
                >
                  {c}
                </span>
              ))
            ) : (
              <span className="text-[11.5px] text-muted italic">Not mapped to any campaign</span>
            )}
          </div>
        </section>
      </div>
    </Modal>
  );
}




/* -------------------------------------------------------------------------- */
/* Add / edit dialog                                                          */
/* -------------------------------------------------------------------------- */

function CampaignMultiSelect({
  campaigns,
  selectedIds,
  onChange,
}: {
  campaigns: CampaignRow[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const filtered = campaigns.filter((c) =>
    c.name.toLowerCase().includes(query.toLowerCase()),
  );

  const toggle = (id: number) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((x) => x !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  };

  const selectAll = () => {
    const ids = Array.from(new Set([...selectedIds, ...filtered.map((c) => c.id)]));
    onChange(ids);
  };

  const clearAll = () => {
    onChange([]);
  };

  return (
    <div className="flex flex-col gap-1.5" ref={ref}>
      <div className="flex items-center justify-between">
        <label className="text-[13px] font-medium text-foreground">
          Assigned campaigns
        </label>
        <span className="text-[11.5px] text-muted">
          {selectedIds.length} of {campaigns.length} selected
        </span>
      </div>

      <div className="relative">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          className="flex h-9 w-full items-center justify-between rounded-control border border-border/80 bg-surface px-3 text-[13px] shadow-2xs hover:border-primary/60 transition-colors cursor-pointer text-left"
          aria-expanded={open}
        >
          <span className="truncate">
            {selectedIds.length === 0 ? (
              <span className="text-muted">Select campaigns to map to this account…</span>
            ) : selectedIds.length === 1 ? (
              <span className="font-medium text-foreground">
                {campaigns.find((c) => c.id === selectedIds[0])?.name || '1 campaign selected'}
              </span>
            ) : (
              <span className="font-semibold text-primary">
                {selectedIds.length} campaigns selected
              </span>
            )}
          </span>
          <ChevronDown
            size={16}
            className={cn('text-muted transition-transform duration-200 shrink-0 ml-2', open && 'rotate-180')}
            aria-hidden
          />
        </button>

        {open && (
          <div className="mt-2 rounded-xl border border-lineStrong/80 bg-white dark:bg-[#111b2f] p-2.5 flex flex-col gap-2 shadow-2xl ring-1 ring-black/5 transition-all">
            <div className="relative">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search campaigns…"
                className="h-8 w-full rounded-md border border-border bg-slate-50 dark:bg-slate-800/80 pl-8 pr-2.5 text-[12.5px] text-foreground focus:border-primary focus:outline-hidden"
                autoFocus
              />
            </div>

            <div className="flex items-center justify-between border-b border-line/60 pb-1.5 px-0.5 text-[11.5px]">
              <button
                type="button"
                onClick={selectAll}
                className="font-medium text-primary hover:underline cursor-pointer"
              >
                Select all ({filtered.length})
              </button>
              <button
                type="button"
                onClick={clearAll}
                className="font-medium text-muted hover:text-crit cursor-pointer"
              >
                Clear all
              </button>
            </div>

            <div className="max-h-48 overflow-y-auto flex flex-col gap-0.5 pr-1">
              {filtered.length ? (
                filtered.map((c) => {
                  const checked = selectedIds.includes(c.id);
                  return (
                    <label
                      key={c.id}
                      className={cn(
                        'flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[12.5px] cursor-pointer transition-colors',
                        checked ? 'bg-primary-tint/30 text-primary font-medium' : 'text-foreground hover:bg-surface-2',
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(c.id)}
                        className="h-3.5 w-3.5 rounded border-border text-primary cursor-pointer"
                      />
                      <span className="truncate">{c.name}</span>
                    </label>
                  );
                })
              ) : (
                <p className="py-3 text-center text-[12px] text-muted">No campaigns found</p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Selected campaign chips */}
      {selectedIds.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {selectedIds.map((id) => {
            const camp = campaigns.find((c) => c.id === id);
            if (!camp) return null;
            return (
              <span
                key={id}
                className="inline-flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 py-0.5 text-[11.5px] font-medium text-primary"
              >
                <span className="max-w-[180px] truncate">{camp.name}</span>
                <button
                  type="button"
                  onClick={() => onChange(selectedIds.filter((x) => x !== id))}
                  className="text-primary hover:text-crit cursor-pointer"
                  title={`Remove ${camp.name}`}
                >
                  <X size={12} aria-hidden />
                </button>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AccountDialog({
  open,
  account,
  campaigns,
  onClose,
  onSaved,
}: {
  open: boolean;
  account: Account | null;
  campaigns: CampaignRow[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState({
    name: '',
    status: 'active',
    daily_invite_cap: 30,
    weekly_invite_cap: 100,
    daily_inmail_cap: 10,
    daily_message_cap: 60,
  });
  const [campaignIds, setCampaignIds] = useState<number[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [seededFor, setSeededFor] = useState<number | 'new' | null>(null);

  // Re-seed whenever the dialog targets a different account.
  const target = account?.id ?? 'new';
  if (open && seededFor !== target) {
    setSeededFor(target);
    setFile(null);
    setForm({
      name: account?.name ?? '',
      status: account?.status ?? 'active',
      daily_invite_cap: account?.daily_invite_cap ?? 30,
      weekly_invite_cap: account?.weekly_invite_cap ?? 100,
      daily_inmail_cap: account?.daily_inmail_cap ?? 10,
      daily_message_cap: account?.daily_message_cap ?? 60,
    });
    setCampaignIds(account?.campaign_ids ?? []);
  }
  if (!open && seededFor !== null) setSeededFor(null);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={account ? `Edit ${account.name}` : 'Add account'}
      size="lg"
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose} isStatic>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            form="account-form"
            disabled={busy || (!account && !file)}
            title={!account && !file ? 'Please select a JSON cookie file' : undefined}
            isStatic
          >
            {busy ? 'Saving…' : account ? 'Save account' : 'Add account'}
          </Button>
        </>
      }
    >
      <form
        id="account-form"
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!account && !file) {
            toast('Cookie file is required for new accounts. Please select a JSON cookie file.', 'crit');
            return;
          }
          setBusy(true);
          try {
            const body = { ...form, name: form.name.trim(), campaign_ids: campaignIds };
            /* Create first — the cookie upload needs the new account's id. */
            const created = account ? null : await apiPost<{ id: number }>('/api/accounts', body);
            if (account) await apiPut(`/api/accounts/${account.id}`, body);

            // Cookie upload is a separate multipart call, done right after save.
            const targetId = account?.id ?? created?.id;
            if (file && targetId) {
              const fd = new FormData();
              fd.append('file', file);
              await apiPost(`/api/accounts/${targetId}/upload-cookies`, fd);
            }
            toast(account ? 'Account saved' : 'Account added', 'ok');
            onSaved();
          } catch (ex) {
            toast(ex instanceof Error ? ex.message : String(ex), 'crit');
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Account name *">
            <Input
              required
              placeholder="e.g. Samuel P"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
          <Field label="Account status">
            <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              <option value="active">Active</option>
              <option value="paused">Paused</option>
              <option value="needs_reauth">Needs re-auth</option>
              <option value="seat_required">Seat required</option>
            </Select>
          </Field>
        </div>

        {/* Outreach limits & caps with slide bars */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-semibold text-foreground">Outreach limits &amp; caps</span>
            <span className="text-[11.5px] text-muted">Adjust sliders to set volume limits</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {[
              { key: 'daily_invite_cap', label: 'Daily invite cap', min: 0, max: 50, step: 1 },
              { key: 'weekly_invite_cap', label: 'Weekly invite cap', min: 0, max: 150, step: 5 },
              { key: 'daily_inmail_cap', label: 'Daily InMail cap', min: 0, max: 30, step: 1 },
              { key: 'daily_message_cap', label: 'Daily message cap', min: 0, max: 100, step: 5 },
            ].map((k) => (
              <div key={k.key} className="flex flex-col gap-1.5 rounded-xl border border-line/70 bg-surface-2/40 p-3">
                <div className="flex items-center justify-between">
                  <label htmlFor={k.key} className="text-[12px] font-semibold text-foreground">
                    {k.label}
                  </label>
                  <div className="flex items-center gap-1">
                    <input
                      id={k.key}
                      type="number"
                      min={k.min}
                      max={k.max}
                      value={form[k.key as keyof typeof form]}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          [k.key]: Math.max(0, Number(e.target.value) || 0),
                        })
                      }
                      className="h-7 w-14 rounded-md border border-border bg-surface px-1.5 text-right font-mono text-[12px] font-bold text-foreground focus:border-primary focus:outline-hidden"
                    />
                    <span className="text-[10.5px] text-muted font-medium">/ {k.max}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2 pt-0.5">
                  <span className="text-[10.5px] font-medium text-muted w-3">{k.min}</span>
                  <input
                    type="range"
                    min={k.min}
                    max={k.max}
                    step={k.step}
                    value={form[k.key as keyof typeof form]}
                    onChange={(e) => setForm({ ...form, [k.key]: Number(e.target.value) })}
                    className="h-2 flex-1 cursor-pointer appearance-none rounded-lg bg-line accent-primary"
                    aria-label={k.label}
                  />
                  <span className="text-[10.5px] font-medium text-muted w-6 text-right">{k.max}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Campaigns multi-select dropdown */}
        <CampaignMultiSelect
          campaigns={campaigns}
          selectedIds={campaignIds}
          onChange={setCampaignIds}
        />

        {/* Cookie file */}
        <div className="flex flex-col gap-1.5 pt-1">
          <label className="text-[13px] font-medium text-foreground">
            Cookie file {!account ? <span className="text-crit font-bold">*</span> : <span className="text-muted text-[11.5px] font-normal">(Optional when updating)</span>}
          </label>
          <p className="text-[11.5px] text-muted">
            {!account
              ? 'Required. Upload a JSON cookie capture to configure this account session.'
              : 'Upload a JSON cookie capture to refresh this account session.'}
          </p>
          <div className="mt-1 flex items-center gap-3">
            <label
              className={cn(
                'inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold shadow-2xs transition-all active:scale-95',
                !account && !file
                  ? 'border-amber-500/60 bg-amber-500/10 text-amber-700 dark:text-amber-300 hover:border-amber-600'
                  : 'border-border/80 bg-surface text-foreground hover:border-primary/50 hover:bg-surface-2',
              )}
            >
              <Upload size={14} className={!account && !file ? 'text-amber-600 dark:text-amber-400' : 'text-primary'} />
              <span>Choose JSON file</span>
              <input
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <span className={cn('text-xs truncate max-w-[280px]', !file && !account ? 'text-amber-600 dark:text-amber-400 font-medium' : 'text-muted')}>
              {file ? file.name : !account ? 'No file chosen (JSON required)' : 'No file chosen'}
            </span>
          </div>
        </div>

        {account?.session_configured && (
          <p className="flex items-center gap-1.5 text-[12px] text-muted">
            <Upload size={12} aria-hidden />
            Session file already configured. Last refresh {fmtDT(account.last_cookie_refresh_at)}.
          </p>
        )}
      </form>
    </Modal>
  );
}
