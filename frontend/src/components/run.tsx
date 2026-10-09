import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Copy, Maximize2, Minimize2, Rocket, Users, Square, Terminal, X } from 'lucide-react';
import { Button, ErrorState, IconButton, Loading, Pill, cn } from '@/components/ui';
import { Modal } from '@/components/Modal';
import { Switch } from '@/components/form';
import { apiGet, apiPost } from '@/lib/api';
import { useToast } from '@/lib/toast';
import { JOB_LABELS, RUN_TONE } from '@/lib/constants';
import { fmtDT, fmtDur, ago } from '@/lib/format';
import { useLiveConsole } from '@/lib/console';
import { requestNotifyPermission } from '@/lib/notify';

interface CampaignRow {
  id: number;
  name: string;
  status: string;
  accounts: { account_id: number; account_name: string }[];
}
interface AccountRow {
  id: number;
  name: string;
  status: string;
}
export interface RunLog {
  id: number;
  job: string;
  status: string;
  dry_run: boolean;
  target: string | null;
  log_text: string;
  errors: string[] | null;
  duration_s: number | null;
  started_at: string | null;
  finished_at: string | null;
  stats?: Record<string, unknown>;
}
const SKIP_LABELS: Record<string, string> = {
  seat_required: 'Sales Nav required',
  needs_reauth: 'Needs re-auth',
  paused: 'Paused',
};
type Mode = 'all' | 'pick';
function useScope(open: boolean) {
  const [campaigns, setCampaigns] = useState<CampaignRow[]>([]),
    [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [loading, setLoading] = useState(false),
    [error, setError] = useState('');
  const [campMode, setCampMode] = useState<Mode>('all'),
    [acctMode, setAcctMode] = useState<Mode>('all');
  const [campaignIds, setCampaignIds] = useState<Set<number>>(new Set()),
    [accountIds, setAccountIds] = useState<Set<number>>(new Set());
  const [seeded, setSeeded] = useState(false);
  if (open && !seeded) {
    setSeeded(true);
    setCampMode('all');
    setAcctMode('all');
    setCampaignIds(new Set());
    setAccountIds(new Set());
  }
  if (!open && seeded) setSeeded(false);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    Promise.all([apiGet<CampaignRow[]>('/api/campaigns'), apiGet<AccountRow[]>('/api/accounts')])
      .then(([c, a]) => {
        if (!cancelled) {
          setCampaigns(c);
          setAccounts(a);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e.message || e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);
  const eligible = campaigns.filter((c) => c.status === 'active');
  const chosen = eligible.filter((c) => campMode === 'all' || campaignIds.has(c.id));
  const mappedIds = new Set(chosen.flatMap((c) => c.accounts.map((a) => a.account_id)));
  const mapped = accounts.filter((a) => mappedIds.has(a.id));
  const chosenKey = [...mappedIds].sort((a, b) => a - b).join(',');
  useEffect(() => {
    setAccountIds((prev) => new Set([...prev].filter((id) => mappedIds.has(id))));
  }, [chosenKey]);
  const activeIds = new Set(
    mapped
      .filter((a) => a.status === 'active' && (acctMode === 'all' || accountIds.has(a.id)))
      .map((a) => a.id),
  );
  const pairs = chosen.map((c) => ({
    campaign: c,
    links: c.accounts.filter((a) => activeIds.has(a.account_id)),
  }));
  const pairCount = pairs.reduce((n, p) => n + p.links.length, 0);
  return {
    eligible,
    chosen,
    mapped,
    activeIds,
    pairs,
    pairCount,
    loading,
    error,
    campMode,
    setCampMode,
    acctMode,
    setAcctMode,
    campaignIds,
    setCampaignIds,
    accountIds,
    setAccountIds,
  };
}
type Scope = ReturnType<typeof useScope>;
function toggle(ids: Set<number>, id: number) {
  const next = new Set(ids);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
export function RunScope({ scope: s, batch = false }: { scope: Scope; batch?: boolean }) {
  if (s.loading) return <Loading />;
  if (s.error) return <ErrorState message={s.error} />;
  return (
    <>
      <p className="text-[13px] text-muted">Choose your campaigns. Only their mapped accounts can run.</p>
      <div className="grid gap-5 sm:grid-cols-2">
        <fieldset className="min-w-0">
          <legend className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Rocket size={17} className="text-primary" />
            Campaigns
          </legend>
          <div className="mb-3 flex gap-4 text-[12.5px]">
            {(['all', 'pick'] as Mode[]).map((m) => (
              <label key={m} className="flex items-center gap-1.5">
                <input
                  type="radio"
                  name="camp"
                  checked={s.campMode === m}
                  onChange={() => s.setCampMode(m)}
                />
                {m === 'all' ? 'All active' : 'Select campaigns'}
              </label>
            ))}
          </div>
          <div className="scope-list">
            {s.eligible.length ? (
              s.eligible.map((c) => (
                <label
                  key={c.id}
                  className={cn(
                    'scope-row',
                    (s.campMode === 'all' || s.campaignIds.has(c.id)) && 'scope-selected',
                  )}
                >
                  <input
                    type="checkbox"
                    disabled={s.campMode === 'all'}
                    checked={s.campMode === 'all' || s.campaignIds.has(c.id)}
                    onChange={() => s.setCampaignIds((prev) => toggle(prev, c.id))}
                  />
                  <span>
                    <strong>{c.name}</strong>
                    <small>
                      {c.accounts.length} mapped account{c.accounts.length === 1 ? '' : 's'}
                    </small>
                  </span>
                </label>
              ))
            ) : (
              <p className="p-3 text-sm text-muted">No active campaigns. Activate a campaign first.</p>
            )}
          </div>
        </fieldset>
        <fieldset className="min-w-0">
          <legend className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Users size={17} className="text-primary" />
            Mapped accounts
          </legend>
          <div className="mb-3 flex gap-4 text-[12.5px]">
            {(['all', 'pick'] as Mode[])
              .filter((m) => !batch || m === 'all')
              .map((m) => (
                <label key={m} className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name="acct"
                    checked={s.acctMode === m}
                    disabled={batch}
                    onChange={() => s.setAcctMode(m)}
                  />
                  {m === 'all' ? 'All mapped' : 'Select accounts'}
                </label>
              ))}
          </div>
          <div className="scope-list">
            {s.mapped.length ? (
              s.mapped.map((a) => (
                <label
                  key={a.id}
                  className={cn(
                    'scope-row',
                    a.status !== 'active' && 'opacity-60',
                    (s.acctMode === 'all' || s.accountIds.has(a.id)) && 'scope-selected',
                  )}
                >
                  <input
                    type="checkbox"
                    disabled={batch || s.acctMode === 'all' || a.status !== 'active'}
                    checked={s.acctMode === 'all' || s.accountIds.has(a.id)}
                    onChange={() => s.setAccountIds((prev) => toggle(prev, a.id))}
                  />
                  <span>
                    <strong>{a.name}</strong>
                    {a.status !== 'active' && (
                      <span className="ml-2" title={SKIP_LABELS[a.status] || a.status}>
                        <Pill tone="warn">{a.status.replace(/_/g, ' ')}</Pill>
                      </span>
                    )}
                    <small>
                      {s.chosen
                        .filter((c) => c.accounts.some((l) => l.account_id === a.id))
                        .map((c) => c.name)
                        .join(', ')}
                    </small>
                  </span>
                </label>
              ))
            ) : (
              <p className="p-3 text-sm text-muted">
                No mapped accounts in this selection. Edit the campaign to assign accounts.
              </p>
            )}
          </div>
          {batch && (
            <p className="mt-2 text-xs text-muted">Run batch always covers every mapped active account.</p>
          )}
        </fieldset>
      </div>
      <section className="overflow-hidden rounded-panel border border-line">
        <div className="flex justify-between gap-2 bg-inset px-3 py-2 text-xs">
          <strong>Run preview</strong>
          <span>
            {s.chosen.length} campaign{s.chosen.length === 1 ? '' : 's'} · {s.activeIds.size} account
            {s.activeIds.size === 1 ? '' : 's'}
          </span>
        </div>
        <div className="max-h-[200px] overflow-y-auto">
          {s.pairs.map((p) => (
            <div
              key={p.campaign.id}
              className="grid grid-cols-[1fr_auto_1.5fr] items-center gap-3 border-t border-line px-3 py-2 text-xs"
            >
              <span>{p.campaign.name}</span>
              <ArrowRight size={13} />
              <span className={p.links.length ? 'text-primary' : 'text-warn'}>
                {p.links.length
                  ? p.links.map((a) => a.account_name).join(', ')
                  : 'Skipped · no selected active account'}
              </span>
            </div>
          ))}
          {!s.chosen.length && (
            <p className="p-3 text-xs text-muted">Select a campaign to preview its accounts.</p>
          )}
        </div>
      </section>
      {!s.pairCount && (
        <p role="status" className="text-xs text-warn">
          {!s.chosen.length
            ? 'Select at least one campaign.'
            : 'Select an active mapped account, or update the campaign mapping.'}
        </p>
      )}
    </>
  );
}

export function RunJobDialog({
  job,
  onClose,
  onStarted,
  presetCampaignId,
}: {
  job: string | null;
  onClose: () => void;
  onStarted: () => void | Promise<void>;
  /* Tile “Run” buttons preselect one campaign — scope auto-switches to pick. */
  presetCampaignId?: number | null;
}) {
  const s = useScope(!!job),
    toast = useToast(),
    console = useLiveConsole();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (job) setBusy(false);
  }, [job]);
  /* A preset from a campaign tile pins the scope to that campaign only. */
  useEffect(() => {
    if (job && presetCampaignId != null) {
      s.setCampMode('pick');
      s.setCampaignIds(new Set([presetCampaignId]));
      s.setAccountIds(new Set());
    }
  }, [job, presetCampaignId]);
  if (!job) return null;
  const valid = !s.loading && !s.error && s.pairCount > 0;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    requestNotifyPermission();
    try {
      const body: Record<string, unknown> = {};
      if (s.campMode === 'pick') body.campaign_ids = [...s.campaignIds];
      if (s.acctMode === 'pick') body.account_ids = [...s.activeIds];
      const res = await apiPost<{ message?: string; warnings?: string[]; execution_id?: string }>(
        '/api/jobs/' + job + '/run',
        body,
      );
      toast(res.message || 'Run started', 'ok');
      res.warnings?.forEach((w) => toast(w, 'warn'));
      onClose();
      console.open(res.execution_id);
      await onStarted();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={'Run ' + (JOB_LABELS[job] || job)}
      size="xl"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} isStatic>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="run-form" disabled={busy || !valid} isStatic>
            {busy ? 'Starting…' : 'Run now'}
          </Button>
        </>
      }
    >
      <form id="run-form" onSubmit={submit} className="flex flex-col gap-4">
        <RunScope scope={s} />
      </form>
    </Modal>
  );
}
export function BatchDialog({
  open,
  onClose,
  onStarted,
}: {
  open: boolean;
  onClose: () => void;
  onStarted: () => void | Promise<void>;
}) {
  const s = useScope(open),
    toast = useToast(),
    console = useLiveConsole();
  const [connections, setConnections] = useState(true),
    [followups, setFollowups] = useState(false),
    [busy, setBusy] = useState(false),
    [seeded, setSeeded] = useState(false);
  if (open && !seeded) {
    setSeeded(true);
    setConnections(true);
    setFollowups(false);
    setBusy(false);
  }
  if (!open && seeded) setSeeded(false);
  const valid =
    !s.loading && !s.error && s.pairCount > 0 && s.chosen.length > 0 && (connections || followups);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    requestNotifyPermission();
    try {
      const res = await apiPost<{ message?: string; warnings?: string[]; execution_id?: string }>(
        '/api/jobs/batch',
        { connections, followups, campaign_ids: s.chosen.map((c) => c.id) },
      );
      toast(res.message || 'Batch started', 'ok');
      res.warnings?.forEach((w) => toast(w, 'warn'));
      onClose();
      console.open(res.execution_id);
      await onStarted();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Run batch"
      size="xl"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} isStatic>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="batch-form" disabled={busy || !valid} isStatic>
            {busy ? 'Starting…' : 'Start batch'}
          </Button>
        </>
      }
    >
      <form id="batch-form" className="flex flex-col gap-4" onSubmit={submit}>
        <div className="grid gap-2 sm:grid-cols-2">
          <Switch checked={connections} onChange={setConnections} label="Run Connections" />
          <Switch checked={followups} onChange={setFollowups} label="Run Follow-ups" />
        </div>
        <RunScope scope={s} batch />
      </form>
    </Modal>
  );
}

export function RunLogModal({ runId, onClose }: { runId: number | null; onClose: () => void }) {
  if (runId == null) return null;
  return <RunLogBody runId={runId} onClose={onClose} />;
}

function RunLogBody({ runId, onClose }: { runId: number; onClose: () => void }) {
  const { data, error, loading, reload } = useRunLog(runId);

  return (
    <Modal open onClose={onClose} title={`Run #${runId}`} size="lg">
      {loading && !data ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : data ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
            <Pill tone={RUN_TONE[data.status] ?? 'idle'}>{data.status}</Pill>
            <span>{JOB_LABELS[data.job] ?? data.job}</span>
            {data.target && <span>· {data.target}</span>}
            <span>· started {fmtDT(data.started_at)}</span>
            <span>· {fmtDur(data.duration_s)}</span>
            {data.dry_run && <Pill tone="idle">dry run</Pill>}
            <span className="ml-auto">
              {ago(data.finished_at) === 'never' ? '' : `finished ${ago(data.finished_at)}`}
            </span>
          </div>
          {data.errors?.length ? (
            <pre className="scroll-y max-h-[200px] rounded-[10px] bg-[var(--crit-tint)] p-3 text-[12px] text-crit">
              {data.errors.join('\n')}
            </pre>
          ) : null}
          <pre
            tabIndex={0}
            className="scroll-y num max-h-[52vh] rounded-[12px] bg-nav p-3 text-[12px] leading-relaxed text-[var(--nav-text)]"
          >
            {data.log_text || 'No console output recorded for this run.'}
          </pre>
        </div>
      ) : null}
    </Modal>
  );
}

function useRunLog(runId: number) {
  const [data, setData] = useState<RunLog | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const reload = () => {
    setLoading(true);
    setError('');
    return apiGet<RunLog>(`/api/runs/${runId}/log`)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);
  return { data, error, loading, reload };
}

/* -------------------------------------------------------------------------- */
/* Live console popup — streams the active run, then holds the last one        */
/* -------------------------------------------------------------------------- */

/* Shape of GET /api/runs/live: the live execution when one is active, otherwise
   the most recent recorded run. `log_text` is always the full transcript. */
export interface LivePayload {
  running: { execution_id: string; job: string; run_id: number | null; status: string; target?: string }[];
  running_count: number;
  execution_id: string | null;
  active: boolean;
  run_id: number | null;
  job: string | null;
  target: string | null;
  started_at: string | null;
  status: string;
  errors?: string[];
  batch_jobs?: string[];
  duration_s?: number | null;
  seq: number;
  total_lines: number;
  log_text: string;
  finished: boolean;
}

const LIVE_STATUS_TEXT: Record<string, string> = {
  success: 'Completed',
  error: 'Failed',
  partial: 'Completed with warnings',
  running: 'Running',
  stopping: 'Stopping',
  stopped: 'Stopped',
  idle: 'Idle',
};

/* Legacy floating dock: a collapsed ball with the live-run count plus an
   expanded panel (workspace.js parity). Unlike the old modal this is mounted
   for the whole session — closing minimizes instead of unmounting, so a run
   started elsewhere is never lost. */
export function LiveConsoleDock({
  open,
  onOpen,
  onClose,
  execId,
  onExecIdChange: setExecId,
}: {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  execId: string | null;
  onExecIdChange: (id: string | null) => void;
}) {
  const toast = useToast();
  const [payload, setPayload] = useState<LivePayload | null>(null);
  const [stopping, setStopping] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [clearedRunId, setClearedRunId] = useState<number | null>(null);
  const [maximized, setMaximized] = useState(false);
  const box = useRef<HTMLPreElement>(null);

  const effectiveExecId = payload?.running?.length && !execId ? payload.execution_id : execId;

  useEffect(() => {
    let cancelled = false;
    let timer = 0;

    const tick = async () => {
      try {
        const data = await apiGet<LivePayload>(
          effectiveExecId
            ? `/api/runs/live?execution_id=${encodeURIComponent(effectiveExecId)}`
            : '/api/runs/live',
        );
        if (cancelled) return;
        setPayload(data);
        timer = window.setTimeout(tick, data.active ? 1500 : 8000);
      } catch {
        /* A poll failure must not blank the console or kill the loop. */
        if (!cancelled) timer = window.setTimeout(tick, 6000);
      }
    };

    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [effectiveExecId]);

  const text =
    payload && (clearedRunId == null || clearedRunId !== payload.run_id) ? payload.log_text || '' : '';

  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = autoScroll ? el.scrollHeight : el.scrollTop;
  }, [text, autoScroll]);

  const copyLog = () => {
    if (!text) return;
    void navigator.clipboard.writeText(text);
    toast('Console output copied to clipboard', 'ok');
  };

  const active = !!payload?.active;
  const batch = payload?.batch_jobs ?? [];
  const runs = payload?.running ?? [];

  const elapsed =
    payload?.active && payload.started_at
      ? Math.max(
          0,
          Math.floor(
            (Date.now() -
              new Date(
                /Z$|[+-]\d\d:\d\d$/.test(payload.started_at) ? payload.started_at : `${payload.started_at}Z`,
              ).getTime()) /
              1000,
          ),
        )
      : (payload?.duration_s ?? null);

  const stop = async () => {
    if (!window.confirm('Stop the currently running job?')) return;
    setStopping(true);
    try {
      await apiPost('/api/jobs/stop', {
        run_id: payload?.run_id ?? null,
        execution_id: payload?.execution_id ?? null,
      });
      toast('Stop requested. Terminating worker…', 'warn');
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setStopping(false);
    }
  };

  return (
    <aside
      aria-label="Live job console"
      className="fixed bottom-4 right-4 z-40 print:hidden"
      onKeyDown={(e) => {
        if (open && e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          onClose();
        }
      }}
    >
      {/* Conditional render: Tailwind flex would beat the hidden attribute's UA display:none. */}
      {open && (
      <section
        aria-label="Live job output"
        className={cn(
          'surface flex flex-col overflow-hidden rounded-[16px] shadow-pop transition-all duration-200 ease-out',
          maximized
            ? 'w-[min(1080px,calc(100vw-2rem))] max-h-[min(94vh,920px)]'
            : 'w-[min(780px,calc(100vw-2rem))] max-h-[min(88vh,800px)]',
        )}
      >
        <header className="flex items-center gap-3 border-b border-line bg-inset/60 px-4 py-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-primary text-primary-ink">
            <Terminal size={15} aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <strong className="block text-[13.5px] leading-tight">Live job console</strong>
            <span
              role="status"
              className="flex items-center gap-1.5 text-[11.5px] text-muted"
            >
              {active ? (
                <>
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ok" aria-hidden />
                  Streaming{elapsed != null ? ` · ${fmtDur(elapsed)}` : ''}
                </>
              ) : (
                <>
                  <span className="h-1.5 w-1.5 rounded-full bg-muted" aria-hidden />
                  {LIVE_STATUS_TEXT[payload?.status ?? 'idle'] ?? payload?.status ?? 'Connecting…'}
                </>
              )}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {text ? (
              <IconButton label="Copy console output" size="sm" onClick={copyLog}>
                <Copy size={15} aria-hidden />
              </IconButton>
            ) : null}
            <IconButton
              label={maximized ? 'Restore console size' : 'Maximize console'}
              size="sm"
              onClick={() => setMaximized((v) => !v)}
            >
              {maximized ? <Minimize2 size={15} aria-hidden /> : <Maximize2 size={15} aria-hidden />}
            </IconButton>
            <IconButton label="Minimize live job console" size="sm" onClick={onClose}>
              <X size={16} aria-hidden />
            </IconButton>
          </div>
        </header>

        <div className="scroll-y flex min-h-0 flex-1 flex-col gap-2.5 px-4 py-3">
          <p className="card-sub truncate">
            {payload?.job
              ? `${JOB_LABELS[payload.job] ?? payload.job}${payload.target ? ` · ${payload.target}` : ''}${payload.run_id ? ` · run #${payload.run_id}` : ''}`
              : 'No run recorded yet'}
          </p>

          {runs.length > 1 && (
            <label className="flex items-center gap-2 text-[12.5px]">
              <span className="text-muted">{runs.length} running jobs</span>
              <select
                className="rounded-control bg-surface-solid px-2 py-1.5 text-[13px] shadow-border"
                value={payload?.execution_id ?? ''}
                onChange={(e) => setExecId(e.target.value || null)}
              >
                {runs.map((r) => (
                  <option key={r.execution_id} value={r.execution_id}>
                    {JOB_LABELS[r.job] ?? r.job} · {r.target || 'Starting'} · {r.status}
                  </option>
                ))}
              </select>
            </label>
          )}

          {batch.length > 1 && (
            <div className="flex flex-wrap gap-1.5">
              {batch.map((k) => (
                <Pill key={k} tone={k === payload?.job ? 'primary' : 'idle'} dot={k === payload?.job}>
                  {JOB_LABELS[k] ?? k}
                </Pill>
              ))}
            </div>
          )}

          {payload?.errors?.length ? (
            <pre className="scroll-y max-h-[110px] rounded-[10px] bg-[var(--crit-tint)] p-3 text-[12px] text-crit">
              {payload.errors.join('\n')}
            </pre>
          ) : null}

          <pre
            ref={box}
            tabIndex={0}
            className={cn(
              'scroll-y num rounded-[12px] bg-nav p-3.5 text-[12.5px] leading-relaxed text-[var(--nav-text)] select-text',
              maximized ? 'h-[540px] max-h-[66vh]' : 'h-[360px] max-h-[50vh] min-h-[220px]',
            )}
          >
            {text || 'No console output recorded yet. Console output streams here while a worker runs.'}
          </pre>
        </div>

        <footer className="flex flex-wrap items-center gap-2 border-t border-line bg-inset/60 px-3 py-2.5">
          {active ? (
            <Button
              size="sm"
              variant="danger"
              icon={<Square size={12} aria-hidden fill="currentColor" />}
              disabled={stopping}
              onClick={() => void stop()}
              isStatic
            >
              {payload?.status === 'stopping' ? 'Stopping…' : 'Stop run'}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              disabled={!payload?.run_id}
              onClick={() => setClearedRunId(payload?.run_id ?? null)}
              isStatic
            >
              Clear completed
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
            aria-pressed={autoScroll}
            onClick={() => setAutoScroll((v) => !v)}
            isStatic
          >
            Auto-scroll {autoScroll ? 'on' : 'paused'}
          </Button>
          <a
            href="#/dashboard?history=1"
            className="ml-auto text-[12.5px] font-medium text-primary hover:underline"
          >
            History
          </a>
        </footer>
      </section>
      )}

      {/* Collapsed ball — legacy floating-ball parity with the live count. */}
      {!open && (
        <button
          type="button"
          aria-label="Open live job console"
          aria-expanded={false}
          onClick={onOpen}
          className={cn(
            'flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-ink shadow-lift',
            'transition-transform duration-150 ease-out hover:scale-105 active:scale-95',
          )}
        >
          <Terminal size={18} aria-hidden />
          {(payload?.running_count ?? 0) > 0 && (
            <span
              className="absolute -right-0.5 -top-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-crit px-1 text-[10px] font-bold leading-none text-white"
              aria-hidden
            >
              {payload?.running_count}
            </span>
          )}
        </button>
      )}
    </aside>
  );
}

/* Compact trigger used by page headers — badge shows the live run count. */
export function ConsoleButton({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <Button
      size="sm"
      variant="secondary"
      icon={
        <span className="relative inline-flex">
          <Terminal size={13} aria-hidden />
          {count > 0 && (
            <span
              className="absolute -right-1.5 -top-1.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-primary px-1 text-[9px] font-semibold leading-none text-primary-ink"
              aria-hidden
            >
              {count}
            </span>
          )}
        </span>
      }
      onClick={onClick}
      isStatic
    >
      {count > 0 ? `Console · ${count}` : 'Console'}
    </Button>
  );
}

export function RunCompletedModal({
  run,
  onClose,
  onLog,
}: {
  run: RunLog | null;
  onClose: () => void;
  onLog: (id: number) => void;
}) {
  if (!run) return null;
  return (
    <Modal
      open
      title="Run completed"
      onClose={onClose}
      size="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} isStatic>
            Dismiss
          </Button>
          <Button variant="primary" onClick={() => onLog(run.id)} isStatic>
            Open full log
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <strong>{JOB_LABELS[run.job] || run.job}</strong>
          <Pill tone={RUN_TONE[run.status] || 'idle'}>{run.status}</Pill>
        </div>
        <p className="text-sm text-muted">
          {run.target || 'All assigned campaigns'} · {fmtDur(run.duration_s)}
        </p>
        {run.stats && (
          <p className="text-xs text-muted">
            {Object.entries(run.stats)
              .filter(([, v]) => typeof v === 'number')
              .slice(0, 5)
              .map(([k, v]) => k.replace(/_/g, ' ') + ': ' + v)
              .join(' · ')}
          </p>
        )}
        {!!run.errors?.length && (
          <pre className="max-h-[180px] overflow-auto rounded-panel bg-[var(--crit-tint)] p-3 text-xs text-crit">
            {run.errors.join('\n')}
          </pre>
        )}
      </div>
    </Modal>
  );
}
