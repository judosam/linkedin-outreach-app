import { useMemo, useState } from 'react';
import { AlertTriangle, Copy, KeyRound, Link2, Plus, RefreshCw, Search, UserMinus, UserPlus } from 'lucide-react';
import {
  Avatar,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Pill,
  Progress,
  Segmented,
} from '@/components/ui';
import { Field, Input, PageHeader } from '@/components/form';
import { Modal } from '@/components/Modal';
import { apiGet, apiPost } from '@/lib/api';
import { useAsync } from '@/lib/hooks';
import { useToast } from '@/lib/toast';
import type { Tone } from '@/lib/constants';

interface LicenseEntry {
  email: string;
  status: string;
  profile_id: string;
  name?: string;
  protected?: boolean;
}

interface Snapshot {
  licenses?: LicenseEntry[];
  others?: LicenseEntry[];
  used?: number;
  max_licenses?: number;
  remaining?: number;
}

interface ResultRow {
  email: string;
  action?: string;
  status?: string;
  detail?: string;
  profile_id?: string;
  link?: string;
}

interface ResultsPayload {
  results: ResultRow[];
  used?: number;
  max_licenses?: number;
  remaining?: number;
  removed?: number;
  created?: number;
}

const STATUS_TONE: Record<string, Tone> = {
  ACTIVATED: 'ok',
  ACTIVE: 'ok',
  INVITED: 'warn',
  PENDING: 'warn',
  DECLINED: 'crit',
  NONE: 'idle',
  UNKNOWN: 'idle',
};

/* A seat is held by any of these — the rest are roster entries waiting for one,
   which is what makes "give" vs "remove" decidable per row. */
const LICENSED_STATES = new Set(['ACTIVATED', 'ACTIVE', 'INVITED', 'PENDING']);
const holdsSeat = (status?: string) => LICENSED_STATES.has((status || '').toUpperCase());

/* An activation link only exists while the invitation is outstanding, so the
   control is shown for INVITED and hidden for every other status. */
const isInvited = (status?: string) => (status || '').toUpperCase() === 'INVITED';

type Mode = 'available' | 'licensed' | 'all';

export default function SalesNav() {
  const toast = useToast();
  const { data, error, loading, reload } = useAsync<Snapshot>(() => apiGet('/api/salesnav/licenses'), []);
  const [mode, setMode] = useState<Mode>('all');
  const [filter, setFilter] = useState('');
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [result, setResult] = useState<ResultsPayload | null>(null);
  const [links, setLinks] = useState<Record<string, string>>({});
  const [adding, setAdding] = useState(false);
  const [confirmRemoveEmails, setConfirmRemoveEmails] = useState<string[] | null>(null);

  const licenses = data?.licenses ?? [];
  const others = (data?.others ?? []).filter((o) => o.email);
  const used = data?.used ?? 0;
  const max = data?.max_licenses ?? 0;
  const remaining = Math.max(0, max - used);
  const utilization = max > 0 ? Math.round((used / max) * 100) : 0;
  const activeSeats = licenses.filter((l) => ['ACTIVATED', 'ACTIVE'].includes((l.status || '').toUpperCase())).length;
  const pendingInvites = licenses.filter((l) => ['INVITED', 'PENDING'].includes((l.status || '').toUpperCase())).length;
  const unassigned = others.length;
  const totalRoster = licenses.length + others.length;

  /* One roster, newest profiles and seat-holders together, so the licence
     controls sit on the same row as the account they apply to. */
  const roster = useMemo(() => [...licenses, ...others], [licenses, others]);
  const entryOf = (email: string) => roster.find((p) => p.email === email);
  const statusOf = (email: string) => entryOf(email)?.status || '';

  const visible = useMemo(() => {
    const inMode = roster.filter((p) =>
      mode === 'all' ? true : mode === 'licensed' ? holdsSeat(p.status) : !holdsSeat(p.status),
    );
    const needle = filter.trim().toLowerCase();
    if (!needle) return inMode;
    return inMode.filter(
      (p) => p.email.toLowerCase().includes(needle) || (p.name || '').toLowerCase().includes(needle),
    );
  }, [roster, mode, filter]);

  const visibleEmails = visible.map((p) => p.email);
  const selected = chosen.filter((e) => roster.some((p) => p.email === e));
  const allVisibleSelected = visibleEmails.length > 0 && visibleEmails.every((e) => chosen.includes(e));

  /* Only the profiles a bulk action can actually change are ever sent. */
  const giveTargets = selected.filter((e) => !holdsSeat(statusOf(e)));
  const removeTargets = selected.filter((e) => holdsSeat(statusOf(e)) && !entryOf(e)?.protected);
  const linkTargets = selected.filter((e) => isInvited(statusOf(e)));

  const toggle = (email: string) =>
    setChosen((prev) => (prev.includes(email) ? prev.filter((e) => e !== email) : [...prev, email]));

  const toggleAllVisible = () =>
    setChosen((prev) =>
      allVisibleSelected
        ? prev.filter((e) => !visibleEmails.includes(e))
        : [...new Set([...prev, ...visibleEmails])],
    );

  /* Activation links are the manual step of seat assignment, so they are fetched
     opportunistically: whatever the assignment call already returned is kept, and
     any invited profile still without a link is looked up once, right after. */
  const collectLinks = async (res: ResultsPayload) => {
    const found: Record<string, string> = {};
    for (const r of res.results) if (r.link) found[r.email] = r.link;
    const missing = res.results
      .filter((r) => !r.link && r.profile_id && isInvited(r.status))
      .map((r) => r.email);
    if (missing.length) {
      try {
        const linkRes = await apiPost<ResultsPayload>('/api/salesnav/link', { emails: missing });
        for (const r of linkRes.results) if (r.link) found[r.email] = r.link;
      } catch {
        /* A missing link must not mask a successful assignment. */
      }
    }
    if (Object.keys(found).length) setLinks((prev) => ({ ...prev, ...found }));
    return found;
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast('Activation link copied', 'ok');
    } catch {
      toast('Copy blocked by the browser — select the link and copy it manually', 'crit');
    }
  };

  const run = async (action: 'activate' | 'remove' | 'link' | 'add', emails: string[]) => {
    if (!emails.length) return;
    if (action === 'remove') {
      setConfirmRemoveEmails(emails);
      return;
    }
    await executeAction(action, emails);
  };

  const executeAction = async (action: 'activate' | 'remove' | 'link' | 'add', emails: string[]) => {
    if (!emails.length) return;
    const one = emails.length === 1 ? emails[0] : null;
    if (one) setRowBusy(one);
    else setBusy(true);
    try {
      const res = await apiPost<ResultsPayload>(`/api/salesnav/${action}`, { emails });
      setResult(res);
      if (action === 'activate' || action === 'link') await collectLinks(res);
      const summary =
        action === 'activate'
          ? `Licence given to ${res.results.filter((r) => r.action === 'activated').length || res.results.length} profile(s)`
          : action === 'remove'
            ? `${res.removed ?? 0} licence(s) removed`
            : action === 'add'
              ? `${res.created ?? 0} enterprise profile(s) created`
              : 'Activation links fetched';
      toast(summary, 'ok');
      setChosen([]);
      if (action !== 'link') await reload();
    } catch (ex) {
      toast(ex instanceof Error ? ex.message : String(ex), 'crit');
    } finally {
      if (one) setRowBusy(null);
      else setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Licences Manager"
        subtitle="Enterprise seat management and allocation across your team. Requires a live LinkedIn admin session on the server."
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus size={14} aria-hidden />}
              onClick={() => setAdding(true)}
              isStatic
            >
              Add profile
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw size={14} aria-hidden />}
              disabled={loading}
              onClick={() => void reload()}
              isStatic
            >
              Refresh
            </Button>
          </>
        }
      />

      {max > 0 && (
        <Card className="flex flex-col gap-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-tint text-primary">
                <KeyRound size={15} aria-hidden />
              </span>
              <div>
                <span className="text-[14px] font-semibold text-foreground">Seats in use</span>
                <span className="ml-2 text-[12px] text-muted">
                  {used} of {max} seats allocated ({remaining} available)
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Pill tone={used >= max ? 'crit' : used >= max * 0.85 ? 'warn' : 'ok'}>
                {utilization}% allocated
              </Pill>
            </div>
          </div>

          <Progress value={used} limit={max} className="h-2" />

          {/* Compact multi-stat grid */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6 pt-1">
            <div className="flex flex-col rounded-lg border border-border/70 bg-surface-2/60 px-3 py-2">
              <span className="text-[11px] uppercase tracking-wider text-muted font-medium">Total Seats</span>
              <span className="mt-0.5 text-[17px] font-bold text-foreground num">{max}</span>
            </div>
            <div className="flex flex-col rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2">
              <span className="text-[11px] uppercase tracking-wider text-emerald-600 dark:text-emerald-400 font-medium">Active Seats</span>
              <span className="mt-0.5 text-[17px] font-bold text-emerald-600 dark:text-emerald-400 num">{activeSeats || used}</span>
            </div>
            <div className="flex flex-col rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2">
              <span className="text-[11px] uppercase tracking-wider text-amber-600 dark:text-amber-400 font-medium">Pending Invites</span>
              <span className="mt-0.5 text-[17px] font-bold text-amber-600 dark:text-amber-400 num">{pendingInvites}</span>
            </div>
            <div className="flex flex-col rounded-lg border border-blue-500/20 bg-blue-500/5 px-3 py-2">
              <span className="text-[11px] uppercase tracking-wider text-blue-600 dark:text-blue-400 font-medium">Available Seats</span>
              <span className="mt-0.5 text-[17px] font-bold text-blue-600 dark:text-blue-400 num">{remaining}</span>
            </div>
            <div className="flex flex-col rounded-lg border border-purple-500/20 bg-purple-500/5 px-3 py-2">
              <span className="text-[11px] uppercase tracking-wider text-purple-600 dark:text-purple-400 font-medium">No Licence</span>
              <span className="mt-0.5 text-[17px] font-bold text-purple-600 dark:text-purple-400 num">{unassigned}</span>
            </div>
            <div className="flex flex-col rounded-lg border border-border/70 bg-surface-2/60 px-3 py-2">
              <span className="text-[11px] uppercase tracking-wider text-muted font-medium">Total Roster</span>
              <span className="mt-0.5 text-[17px] font-bold text-foreground num">{totalRoster}</span>
            </div>
          </div>
        </Card>
      )}

      {result && (
        <Card className="p-4">
          <h2 className="text-[15px]">Last action</h2>
          <p className="card-sub">Activation links are generated automatically — copy them straight from here.</p>
          <div className="scroll-y mt-3 max-h-[320px]">
            <table className="dt min-w-[720px]">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Action</th>
                  <th>Status</th>
                  <th>Detail</th>
                  <th className="col-actions">Activation link</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((r, i) => {
                  const link = isInvited(r.status) ? r.link || links[r.email] : '';
                  return (
                    <tr key={`${r.email}-${i}`}>
                      <td className="max-w-[220px] truncate">{r.email || '—'}</td>
                      <td className="text-muted">{r.action || '—'}</td>
                      <td>
                        {r.status ? <Pill tone={STATUS_TONE[r.status.toUpperCase()] ?? 'idle'}>{r.status}</Pill> : '—'}
                      </td>
                      <td className="max-w-[280px] text-muted">{r.detail || '—'}</td>
                      <td className="col-actions">
                        {link ? (
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              size="sm"
                              variant="secondary"
                              icon={<Copy size={13} aria-hidden />}
                              onClick={() => void copy(link)}
                              isStatic
                            >
                              Copy link
                            </Button>
                            <a
                              href={link}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[12.5px] text-primary hover:underline"
                            >
                              Open
                            </a>
                          </div>
                        ) : (
                          <span className="text-[12.5px] text-muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {loading && !data ? (
        <Loading label="Loading licences…" />
      ) : error ? (
        <ErrorState
          message={`${error} — this view needs a live LinkedIn enterprise session, so it cannot load offline.`}
          onRetry={reload}
        />
      ) : (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-end justify-between gap-3 p-4">
            <div>
              <h2 className="text-[15px]">Enterprise roster</h2>
              <p className="card-sub">
                {roster.length} profile(s) known to the enterprise account. Give or remove a licence in one click.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Segmented
                label="Licence state"
                value={mode}
                onChange={(v) => setMode(v as Mode)}
                options={[
                  { value: 'all', label: 'All' },
                  { value: 'licensed', label: `Licensed (${licenses.length})` },
                  { value: 'available', label: `No licence (${others.length})` },
                ]}
              />
              <div className="relative">
                <Search
                  size={14}
                  aria-hidden
                  className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted"
                />
                <Input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Filter…"
                  aria-label="Filter profiles"
                  className="h-8 pl-8 sm:w-[200px]"
                />
              </div>
            </div>
          </div>

          {selected.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-y border-line bg-inset px-4 py-2.5">
              <span className="text-[13px] font-medium">{selected.length} selected</span>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                {linkTargets.length > 0 && (
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<Link2 size={13} aria-hidden />}
                    disabled={busy}
                    onClick={() => void run('link', linkTargets)}
                    isStatic
                  >
                    Get activation links ({linkTargets.length})
                  </Button>
                )}
                {removeTargets.length > 0 && (
                  <Button
                    variant="danger"
                    size="sm"
                    icon={<UserMinus size={13} aria-hidden />}
                    disabled={busy}
                    onClick={() => void run('remove', removeTargets)}
                    isStatic
                  >
                    Remove licence ({removeTargets.length})
                  </Button>
                )}
                {giveTargets.length > 0 && (
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<UserPlus size={13} aria-hidden />}
                    disabled={busy}
                    onClick={() => void run('activate', giveTargets)}
                    isStatic
                  >
                    Give licence ({giveTargets.length})
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => setChosen([])} isStatic>
                  Clear
                </Button>
              </div>
            </div>
          )}

          {visible.length ? (
            <div className="dt-wrap">
              <table className="dt min-w-[1000px]">
                <thead>
                  <tr>
                    <th className="w-8">
                      <input
                        type="checkbox"
                        aria-label="Select all visible profiles"
                        checked={allVisibleSelected}
                        onChange={toggleAllVisible}
                      />
                    </th>
                    <th>Name</th>
                    <th>Account</th>
                    <th>Licence</th>
                    <th>Status</th>
                    <th>Profile</th>
                    <th>Seat</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((p) => {
                    const licensed = holdsSeat(p.status);
                    const invited = isInvited(p.status);
                    const pending = rowBusy === p.email;
                    const link = links[p.email];
                    return (
                      <tr key={p.email}>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`Select ${p.email}`}
                            checked={chosen.includes(p.email)}
                            onChange={() => toggle(p.email)}
                          />
                        </td>
                        <td className="max-w-[200px]">
                          <div className="flex items-center gap-2">
                            <Avatar name={p.name || p.email} size="sm" />
                            <span className="truncate font-medium">{p.name || '—'}</span>
                          </div>
                        </td>
                        <td className="max-w-[220px] truncate text-ink2">{p.email || '—'}</td>
                        {/* One click, right beside the account it applies to. */}
                        <td className="whitespace-nowrap">
                          <div className="flex items-center gap-1.5">
                            {licensed ? (
                              <Button
                                variant="secondary"
                                size="sm"
                                icon={<UserMinus size={13} aria-hidden />}
                                disabled={pending || p.protected}
                                onClick={() => void run('remove', [p.email])}
                                isStatic
                              >
                                Remove
                              </Button>
                            ) : (
                              <Button
                                variant="primary"
                                size="sm"
                                icon={<UserPlus size={13} aria-hidden />}
                                disabled={pending}
                                onClick={() => void run('activate', [p.email])}
                                isStatic
                              >
                                Give
                              </Button>
                            )}
                            {/* Hidden unless the invitation is outstanding. */}
                            {invited &&
                              (link ? (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  icon={<Copy size={13} aria-hidden />}
                                  onClick={() => void copy(link)}
                                  isStatic
                                >
                                  Copy link
                                </Button>
                              ) : (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  icon={<Link2 size={13} aria-hidden />}
                                  disabled={pending}
                                  onClick={() => void run('link', [p.email])}
                                  isStatic
                                >
                                  Activate link
                                </Button>
                              ))}
                          </div>
                        </td>
                        <td>
                          <Pill tone={STATUS_TONE[p.status?.toUpperCase()] ?? 'idle'}>{p.status || 'NONE'}</Pill>
                        </td>
                        <td className="num max-w-[170px] truncate text-[12px] text-muted">{p.profile_id || '—'}</td>
                        <td className="whitespace-nowrap">
                          {p.protected ? <Pill tone="warn">Protected</Pill> : <span className="text-muted">Removable</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={<KeyRound size={22} aria-hidden />}
              title={roster.length ? 'No profiles match' : 'No enterprise profiles returned'}
              body={
                roster.length
                  ? 'Change the licence-state filter or clear the search.'
                  : 'The roster is empty, or the server has no live LinkedIn admin session.'
              }
            />
          )}
        </Card>
      )}

      {/* Confirmation Modal for Removing Licences */}
      <Modal
        open={!!confirmRemoveEmails && confirmRemoveEmails.length > 0}
        onClose={() => setConfirmRemoveEmails(null)}
        title="Revoke Licence Confirmation"
      >
        {confirmRemoveEmails && (
          <div className="flex flex-col gap-4">
            <div className="flex items-start gap-3 rounded-xl border border-rose-500/25 bg-rose-500/10 p-3.5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-rose-500/20 text-rose-500">
                <AlertTriangle className="h-5 w-5" aria-hidden />
              </div>
              <div className="text-[13px] text-foreground/90">
                <p className="font-semibold text-rose-500 dark:text-rose-400">
                  {confirmRemoveEmails.length === 1
                    ? `Remove licence from ${entryOf(confirmRemoveEmails[0])?.name || confirmRemoveEmails[0]}?`
                    : `Remove licences from ${confirmRemoveEmails.length} profiles?`}
                </p>
                <p className="mt-1 text-[12px] text-muted">
                  The LinkedIn Sales Navigator seat will be released immediately and returned to the enterprise pool.
                </p>
              </div>
            </div>

            {confirmRemoveEmails.length > 1 && (
              <div className="max-h-44 overflow-y-auto rounded-lg border border-border/70 bg-inset/50 p-2.5">
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
                  Affected profiles ({confirmRemoveEmails.length})
                </p>
                <div className="flex flex-col gap-1">
                  {confirmRemoveEmails.map((email) => {
                    const entry = entryOf(email);
                    return (
                      <div key={email} className="flex items-center justify-between text-[12px]">
                        <span className="font-medium text-foreground">{entry?.name || email}</span>
                        <span className="text-muted">{email}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 border-t border-line pt-2.5">
              <Button
                variant="secondary"
                onClick={() => setConfirmRemoveEmails(null)}
                isStatic
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                disabled={busy}
                onClick={async () => {
                  const targets = confirmRemoveEmails;
                  setConfirmRemoveEmails(null);
                  if (targets) await executeAction('remove', targets);
                }}
                isStatic
              >
                {busy
                  ? 'Removing…'
                  : confirmRemoveEmails.length === 1
                    ? 'Remove licence'
                    : `Remove ${confirmRemoveEmails.length} licences`}
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <AddProfileDialog
        open={adding}
        onClose={() => setAdding(false)}
        onAdded={async (payload) => {
          setResult(payload);
          setAdding(false);
          await reload();
        }}
      />
    </div>
  );
}

/* Creating a brand-new enterprise profile still needs an address that is not yet
   in the roster, so it keeps one field — behind a dialog rather than a bulk paste
   box in the middle of the page. */
function AddProfileDialog({
  open,
  onClose,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  onAdded: (payload: ResultsPayload) => void | Promise<void>;
}) {
  const toast = useToast();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add enterprise profile"
      size="md"
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose} isStatic>
            Cancel
          </Button>
          <Button variant="primary" size="sm" type="submit" form="add-profile-form" disabled={busy} isStatic>
            {busy ? 'Adding…' : 'Add profile'}
          </Button>
        </>
      }
    >
      <form
        id="add-profile-form"
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const target = email.trim().toLowerCase();
          if (!target) return;
          setBusy(true);
          try {
            const res = await apiPost<ResultsPayload>('/api/salesnav/add', { emails: [target] });
            toast(res.created ? 'Enterprise profile created' : 'Profile already existed', 'ok');
            setEmail('');
            await onAdded(res);
          } catch (ex) {
            toast(ex instanceof Error ? ex.message : String(ex), 'crit');
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field
          label="Work email"
          hint="Creates the roster entry only. It consumes no seat — give the licence afterwards."
        >
          <Input
            required
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="teammate@example.com"
          />
        </Field>
      </form>
    </Modal>
  );
}
