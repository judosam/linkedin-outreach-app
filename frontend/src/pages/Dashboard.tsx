import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  Activity,
  ArrowUpRight,
  Building2,
  CheckCircle2,
  ChevronDown,
  Circle,
  Mail,
  MailOpen,
  MessageSquareReply,
  Play,
  RefreshCw,
  Repeat,
  Rocket,
  Send,
  Target,
  Timer,
  TriangleAlert,
  UserCheck,
  Users,
} from 'lucide-react';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Pill,
  Progress,
  Ring,
  Segmented,
  cn,
} from '@/components/ui';
import { apiGet } from '@/lib/api';
import { FUNNEL_ORDER, JOB_LABELS, RUN_TONE, WORKERS } from '@/lib/constants';
import { fmtDay, fmtDT, fmtDur, ago, nf } from '@/lib/format';
import { useJobs } from '@/lib/jobs';
import { useLiveConsole } from '@/lib/console';
import { ConsoleButton } from '@/components/run';
import { RunJobDialog, RunLogModal } from '@/components/run';
import { Modal } from '@/components/Modal';
import type { ActivityEvent, CampaignStats, Run, Summary, Trends } from '@/lib/types';

type Range = 1 | 7 | 30;

interface DashboardData {
  summary: Summary;
  trends: Trends;
  stats: CampaignStats;
  activity: ActivityEvent[];
  runs: Run[];
  accounts: AccountLite[];
  campaigns: CampaignLite[];
}

interface AccountLite {
  id: number;
  name: string;
  status: string;
  weekly_invites?: { used: number; limit: number; remaining: number };
  usage_today: { invites: number; inmails: number; messages: number };
  daily_invite_cap: number;
}

interface CampaignLite {
  id: number;
  name: string;
  status: string;
  leads: number;
  contacted: number;
  replied: number;
  reply_rate: number;
  accounts: { account_id: number; account_name: string }[];
}

export default function Dashboard() {
  const jobs = useJobs();
  const console = useLiveConsole();
  const [range, setRange] = useState<Range>(1);
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  /* Workers are dispatched right here: the run dialog and the last log open
     in place, with no redirect to the scheduler page. */
  const [runJob, setRunJob] = useState<string | null>(null);
  const [presetCampaign, setPresetCampaign] = useState<number | null>(null);
  const [logId, setLogId] = useState<number | null>(null);
  const [selectedCampaignForRuns, setSelectedCampaignForRuns] = useState<CampaignLite | null>(null);

  const load = useCallback(
    async (r: Range) => {
      setBusy(true);
      setError('');
      try {
        const [summary, trends, stats, activity, runs, accounts, campaigns] = await Promise.all([
          apiGet<Summary>(`/api/dashboard/summary?days=${r}`),
          apiGet<Trends>(`/api/dashboard/trends?days=${r === 30 ? 30 : 7}`),
          apiGet<CampaignStats>(`/api/dashboard/campaign-stats?days=${r}&active_only=true`),
          apiGet<ActivityEvent[]>('/api/dashboard/activity?limit=12'),
          apiGet<Run[]>('/api/runs?limit=10'),
          apiGet<AccountLite[]>('/api/accounts'),
          apiGet<CampaignLite[]>('/api/campaigns'),
        ]);
        setData({ summary, trends, stats, activity, runs, accounts, campaigns });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(range);
  }, [load, range]);

  const rangeLabel = range === 1 ? 'Today' : `Last ${range} days`;

  return (
    <div className="flex flex-col gap-5">
      {/* Hero band: identity, live state and the one control that changes the
          whole view. The tint is a single radial wash from the top-left rather
          than a full gradient, so text contrast is unaffected everywhere. */}
      <Card className="relative overflow-hidden p-[18px]">
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(680px 150px at 0% 0%, var(--primary-tint), transparent 72%)',
          }}
        />
        <div className="relative flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-ink shadow-2xs">
              <Activity size={18} aria-hidden />
            </span>
            <div className="min-w-0">
              <h1 className="text-[19px] font-bold tracking-tight text-foreground">Command dashboard</h1>
              <p className="mt-0.5 text-[12px] text-muted">
                {rangeLabel} (UTC)
                {data && (
                  <>
                    {' · '}
                    {nf.format(data.summary.totals.leads_total)} leads ·{' '}
                    {data.summary.totals.campaigns_active} active campaigns ·{' '}
                    {data.summary.totals.accounts_active} sending accounts
                  </>
                )}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <ConsoleButton count={console.liveCount} onClick={() => console.open()} />
            <Pill tone="ok" dot>
              Live
            </Pill>
            <Segmented
              label="Date range"
              value={range}
              onChange={(v) => setRange(v as Range)}
              options={[
                { value: 1, label: 'Today' },
                { value: 7, label: '7 days' },
                { value: 30, label: '30 days' },
              ]}
            />
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw size={13} aria-hidden className={busy ? 'animate-spin' : undefined} />}
              onClick={() => {
                void load(range);
                void jobs.refresh();
              }}
              isStatic
            >
              Refresh
            </Button>
          </div>
        </div>
      </Card>

      {error && !data ? (
        <ErrorState message={error} onRetry={() => void load(range)} />
      ) : !data ? (
        <Loading label="Loading dashboard…" />
      ) : (
        <>
          <KpiRow data={data} range={range} />

          <WorkersPanel onRun={setRunJob} onOpenLog={setLogId} />

          <ActiveCampaigns
            campaigns={data.campaigns}
            onSelectCampaign={setSelectedCampaignForRuns}
            onRun={(job, campaignId) => {
              setPresetCampaign(campaignId);
              setRunJob(job);
            }}
          />

          <PipelineByStage funnel={data.summary.funnel} />

          <div className="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
            <TrendCard data={data} range={range} />
            <FleetCard data={data} />
          </div>

          <div className="grid items-stretch gap-5 md:grid-cols-2">
            <ActivityFeed events={data.activity} />
            <RunsCard runs={data.runs} onOpenLog={setLogId} />
          </div>
        </>
      )}

      <CampaignAccountRunModal
        campaign={selectedCampaignForRuns}
        stats={data?.stats ?? null}
        accounts={data?.accounts ?? []}
        rangeLabel={rangeLabel}
        onClose={() => setSelectedCampaignForRuns(null)}
        onOpenLog={(id) => setLogId(id)}
        onRun={(job, campaignId) => {
          setSelectedCampaignForRuns(null);
          setPresetCampaign(campaignId);
          setRunJob(job);
        }}
      />

      <RunJobDialog
        job={runJob}
        presetCampaignId={presetCampaign}
        onClose={() => {
          setRunJob(null);
          setPresetCampaign(null);
        }}
        onStarted={async () => {
          setRunJob(null);
          setPresetCampaign(null);
          await jobs.refresh();
          void load(range);
        }}
      />

      <RunLogModal runId={logId} onClose={() => setLogId(null)} />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* KPI row                                                                    */
/* -------------------------------------------------------------------------- */

function KpiRow({ data, range }: { data: DashboardData; range: Range }) {
  const { today, replies } = data.summary;
  const delta = today.contacted - today.contacted_yesterday;

  const cards = [
    {
      label: 'Connection invites',
      value: today.invites,
      limit: today.invites_limit,
      icon: <Send size={13} aria-hidden />,
      foot: `${nf.format(today.contacted)} contacted ${range === 1 ? 'today' : 'in window'}`,
    },
    {
      label: 'InMails',
      value: today.inmails,
      limit: today.inmails_limit,
      icon: <Rocket size={13} aria-hidden />,
      foot: `${nf.format(today.contacted_window)} total contacts`,
    },
    {
      label: 'Follow-up messages',
      value: today.followups,
      limit: today.followups_limit,
      icon: <MessageSquareReply size={13} aria-hidden />,
      foot: `${nf.format(today.leads_added)} leads added`,
    },
    {
      label: 'Replies',
      value: replies.window,
      limit: undefined,
      icon: <Target size={13} aria-hidden />,
      foot: `${nf.format(replies.today)} today · ${nf.format(replies.total)} all time`,
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((c) => {
        const p = c.limit ? Math.min(100, Math.round((c.value / c.limit) * 100)) : 0;
        const tone = p >= 100 ? 'crit' : p >= 80 ? 'warn' : 'primary';
        return (
          <Card key={c.label} className="surface-hover flex flex-col justify-between px-3.5 py-3 shadow-2xs">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[12px] font-medium text-muted">{c.label}</span>
                <span
                  className={cn(
                    'flex h-6 w-6 shrink-0 items-center justify-center rounded-md',
                    tone === 'crit'
                      ? 'bg-[var(--crit-tint)] text-crit'
                      : tone === 'warn'
                        ? 'bg-[var(--warn-tint)] text-warn'
                        : 'bg-primary-tint text-primary',
                  )}
                >
                  {c.icon}
                </span>
              </div>
              <div className="num mt-1 flex items-baseline gap-1.5">
                <span className="text-[21px] font-bold leading-none tracking-tight text-foreground">
                  {nf.format(c.value)}
                </span>
                {c.limit !== undefined && (
                  <span className="text-[12px] font-medium text-muted">/ {nf.format(c.limit)}</span>
                )}
              </div>
              {c.limit !== undefined && <Progress value={c.value} limit={c.limit} className="!h-1 mt-2" />}
            </div>
            <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-line/40 pt-1.5 text-[11px] text-muted">
              {c.label === 'Connection invites' && delta !== 0 ? (
                <span className={cn('inline-flex items-center gap-0.5 font-medium', delta > 0 ? 'text-ok' : 'text-warn')}>
                  <ArrowUpRight size={12} aria-hidden className={delta < 0 ? 'rotate-90' : undefined} />
                  {delta > 0 ? '+' : ''}{delta} vs yest.
                </span>
              ) : (
                <span />
              )}
              <span className="truncate">{c.foot}</span>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Volume trend                                                               */
/* -------------------------------------------------------------------------- */

function TrendCard({ data, range }: { data: DashboardData; range: Range }) {
  const points = useMemo(
    () =>
      data.trends.days.map((d) => ({
        ...d,
        label: fmtDay(d.date),
      })),
    [data.trends.days],
  );
  const total = points.reduce((a, p) => a + p.invites + p.inmails + p.messages, 0);

  return (
    <Card className="flex flex-col p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px]">Outreach volume</h2>
          <p className="card-sub">
            Invites, InMails and follow-ups · {range === 30 ? '30 days' : '7 days'}
          </p>
        </div>
        <div className="flex items-center gap-3 text-[12px] text-muted">
          <Legend color="var(--primary)" label="Invites" />
          <Legend color="var(--info)" label="InMails" />
          <Legend color="var(--ok)" label="Messages" />
        </div>
      </div>

      <div className="mt-2 flex items-baseline gap-2">
        <span className="num text-[22px] font-semibold">{nf.format(total)}</span>
        <span className="text-[12px] text-muted">total sends</span>
      </div>

      <div className="mt-3 h-[220px] w-full">
        {points.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
              <defs>
                {[
                  ['gInv', 'var(--primary)'],
                  ['gIm', 'var(--info)'],
                  ['gMsg', 'var(--ok)'],
                ].map(([id, color]) => (
                  <linearGradient key={id} id={id} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                    <stop offset="100%" stopColor={color} stopOpacity={0.02} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: 'var(--muted)' }}
                tickLine={false}
                axisLine={{ stroke: 'var(--border)' }}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 11, fill: 'var(--muted)' }}
                tickLine={false}
                axisLine={false}
                width={44}
                allowDecimals={false}
              />
              <Tooltip
                cursor={{ stroke: 'var(--border-strong)' }}
                contentStyle={{
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 12,
                  fontSize: 12,
                  boxShadow: 'var(--shadow-pop)',
                  color: 'var(--text)',
                }}
                labelStyle={{ color: 'var(--muted)', marginBottom: 4 }}
              />
              <Area type="monotone" dataKey="invites" name="Invites" stroke="var(--primary)" strokeWidth={2} fill="url(#gInv)" />
              <Area type="monotone" dataKey="inmails" name="InMails" stroke="var(--info)" strokeWidth={2} fill="url(#gIm)" />
              <Area type="monotone" dataKey="messages" name="Messages" stroke="var(--ok)" strokeWidth={2} fill="url(#gMsg)" />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState title="No volume recorded" body="Outreach sends will chart here as workers run." />
        )}
      </div>
    </Card>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Fleet + pipeline                                                           */
/* -------------------------------------------------------------------------- */

function FleetCard({ data }: { data: DashboardData }) {
  const { summary } = data;
  const r24 = data.trends.runs_24h;

  /* Accounts needing attention: any non-active status blocks or slows sends. */
  const attention = data.accounts.filter((a) => a.status !== 'active' && a.status !== 'paused');
  const weeklyUsed = data.accounts.reduce((n, a) => n + (a.weekly_invites?.used ?? 0), 0);
  const weeklyLimit = data.accounts.reduce((n, a) => n + (a.weekly_invites?.limit ?? 0), 0);

  const tiles = [
    { label: 'Active campaigns', value: summary.totals.campaigns_active, icon: <Rocket size={15} aria-hidden /> },
    { label: 'Active accounts', value: summary.totals.accounts_active, icon: <Building2 size={15} aria-hidden /> },
    { label: 'Leads tracked', value: summary.totals.leads_total, icon: <Users size={15} aria-hidden /> },
    { label: 'Untagged leads', value: summary.totals.leads_untagged, icon: <Target size={15} aria-hidden /> },
    {
      label: 'Accounts need attention',
      value: attention.length,
      icon: <TriangleAlert size={15} aria-hidden />,
      crit: attention.length > 0,
      sub: attention.length ? attention.map((a) => a.name).join(', ') : 'All sessions healthy',
    },
    {
      label: 'Weekly invite usage',
      value: weeklyLimit ? Math.round((weeklyUsed / weeklyLimit) * 100) : 0,
      icon: <Repeat size={15} aria-hidden />,
      suffix: '%',
      sub: `${nf.format(weeklyUsed)} of ${nf.format(weeklyLimit)} invites this week`,
    },
  ];

  return (
    <Card className="flex flex-col gap-3.5 p-3.5 shadow-2xs">
      <div className="grid grid-cols-2 gap-2.5">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-lg bg-inset p-2.5">
            <div className="flex items-center gap-1.5 text-muted">
              {t.icon}
              <span className="text-[10.5px] font-medium uppercase tracking-wide">{t.label}</span>
            </div>
            <div className="num mt-1 text-[19px] font-bold tracking-tight text-foreground">
              {nf.format(t.value)}
              {'suffix' in t && t.suffix ? t.suffix : ''}
            </div>
            {'sub' in t && t.sub ? (
              <div className="mt-0.5 truncate text-[10.5px] text-muted" title={t.sub}>
                {t.sub}
              </div>
            ) : null}
            {'crit' in t && t.crit ? (
              <span className="mt-1 inline-block h-1 w-6 rounded-full bg-crit" aria-hidden />
            ) : null}
          </div>
        ))}
      </div>

      <div className="rounded-lg bg-inset p-2.5">
        <div className="flex items-center justify-between">
          <span className="text-[11.5px] font-medium text-muted">Run health · 24h</span>
          {r24.success_rate != null ? (
            <Pill tone={r24.success_rate >= 90 ? 'ok' : r24.success_rate >= 70 ? 'warn' : 'crit'}>
              {r24.success_rate}% success
            </Pill>
          ) : (
            <Pill tone="idle">No runs</Pill>
          )}
        </div>
        <div className="mt-2 flex items-center gap-4 text-[12px] text-muted">
          <span className="inline-flex items-center gap-1.5">
            <CheckCircle2 size={14} aria-hidden className="text-ok" />
            {r24.success}/{r24.total} runs
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Timer size={14} aria-hidden />
            avg {fmtDur(r24.avg_duration_s)}
          </span>
        </div>
      </div>

    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Pipeline by stage                                                          */
/* -------------------------------------------------------------------------- */

/* Stage → icon + hue family. Follow-ups share their family's hue, so the eye
   groups invite vs InMail stages; colour stays redundant with the printed label
   and count so the tiles survive greyscale. */
type StageTone = 'idle' | 'invite' | 'inmail' | 'accepted';

const STAGE_META: Record<string, { icon: typeof Circle; tone: StageTone }> = {
  '': { icon: Circle, tone: 'idle' },
  INVITE_SENT: { icon: Send, tone: 'invite' },
  INVITE_AFTER_ACCEPT: { icon: UserCheck, tone: 'accepted' },
  INVITE_FOLLOWUP_1: { icon: Repeat, tone: 'invite' },
  INVITE_FOLLOWUP_2: { icon: Repeat, tone: 'invite' },
  INVITE_FOLLOWUP_3: { icon: Repeat, tone: 'invite' },
  INMAIL_SENT: { icon: Mail, tone: 'inmail' },
  INMAIL_FOLLOWUP_1: { icon: MailOpen, tone: 'inmail' },
  INMAIL_FOLLOWUP_2: { icon: MailOpen, tone: 'inmail' },
  INMAIL_FOLLOWUP_3: { icon: MailOpen, tone: 'inmail' },
};

/* The idle chip must not be --inset: the tile it sits on is already --inset, so
   the icon would vanish. Surface + a hairline ring keeps it legible in both themes. */
const TONE_CLASS: Record<StageTone, string> = {
  idle: 'bg-[var(--surface)] text-muted shadow-border',
  invite: 'bg-primary-tint text-primary',
  inmail: 'bg-[var(--info-tint)] text-info',
  accepted: 'bg-[var(--ok-tint)] text-ok',
};

const TONE_BAR: Record<StageTone, string> = {
  idle: 'var(--border-strong)',
  invite: 'var(--primary)',
  inmail: 'var(--info)',
  accepted: 'var(--ok)',
};

function PipelineByStage({ funnel }: { funnel: Record<string, number> }) {
  const rows = FUNNEL_ORDER.map((f) => ({
    ...f,
    count: funnel[f.key] ?? 0,
    ...(STAGE_META[f.key] ?? STAGE_META['']),
  }));
  const total = rows.reduce((a, r) => a + r.count, 0);
  const max = Math.max(1, ...rows.map((r) => r.count));
  const untouched = rows[0]?.count ?? 0;
  const inOutreach = total - untouched;
  const pct = (n: number) => (total ? (n / total) * 100 : 0);

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px]">Pipeline by stage</h2>
          <p className="card-sub">Every lead by its current outreach stage · all time</p>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-right">
            <span className="num block text-[15px] leading-none font-semibold">
              {nf.format(inOutreach)}
            </span>
            <span className="text-[11px] text-muted">in outreach</span>
          </span>
          <span className="text-right">
            <span className="num block text-[15px] leading-none font-semibold">
              {total ? Math.round(pct(inOutreach)) : 0}%
            </span>
            <span className="text-[11px] text-muted">of {nf.format(total)} leads</span>
          </span>
        </div>
      </div>

      {/* One stacked strip summarises the same split the tiles detail. */}
      <div className="mt-3 flex h-1.5 w-full overflow-hidden rounded-full bg-inset">
        {rows
          .filter((r) => r.count > 0)
          .map((r) => (
            <span
              key={r.key || 'untouched'}
              style={{ width: `${pct(r.count)}%`, background: TONE_BAR[r.tone] }}
              title={`${r.label}: ${nf.format(r.count)}`}
            />
          ))}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
        {rows.map((r) => {
          const Icon = r.icon;
          const share = pct(r.count);
          return (
            <div
              key={r.key || 'untouched'}
              className="flex items-center gap-2.5 rounded-[12px] bg-inset px-3 py-2.5 transition-shadow duration-150 ease-out hover:shadow-border"
            >
              <span
                className={cn(
                  'flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px]',
                  TONE_CLASS[r.tone],
                )}
              >
                <Icon size={15} aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-[12.5px] text-ink2" title={r.label}>
                    {r.label}
                  </span>
                  <span className="num text-[13px] font-semibold">{nf.format(r.count)}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-2">
                  <span className="h-1 flex-1 overflow-hidden rounded-full bg-[var(--border)]">
                    <span
                      className="block h-full rounded-full transition-[width] duration-500 ease-out"
                      style={{ width: `${(r.count / max) * 100}%`, background: TONE_BAR[r.tone] }}
                    />
                  </span>
                  <span className="num w-10 text-right text-[10.5px] text-muted">
                    {r.count && share < 0.1 ? '<0.1%' : `${share.toFixed(1)}%`}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Workers                                                                    */
/* -------------------------------------------------------------------------- */

function WorkersPanel({ onRun, onOpenLog }: { onRun: (job: string) => void; onOpenLog: (runId: number) => void }) {
  const jobs = useJobs();
  const workers = (jobs.data?.jobs ?? []).filter((j) => WORKERS.includes(j.key));
  if (!workers.length) return null;

  return (
    <section aria-label="Workers" className="flex flex-col gap-3">
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-[16px]">Workers</h2>
          <p className="card-sub">Dispatch a worker right here — runs follow each campaign's mapped accounts</p>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {workers.map((job) => {
          const last = job.last_run;
          const isRunning = job.running_now;
          return (
            <Card key={job.key} className="surface-hover flex flex-col gap-2 p-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-[13.5px] font-semibold text-foreground">{JOB_LABELS[job.key] ?? job.key}</h3>
                {isRunning ? <Pill tone="primary" dot>Running</Pill> : last?.status === 'error' ? <Pill tone="crit" dot>Error</Pill> : <Pill tone="idle" dot>Idle</Pill>}
              </div>
              <p className="line-clamp-1 text-[11.5px] text-muted">{job.description}</p>
              <div className="flex items-center justify-between rounded-lg bg-inset/60 px-2 py-1 text-[11px] text-muted">
                <span className="truncate" title={last ? fmtDT(last.started_at) : 'Never'}>
                  Last: {last ? `${fmtDT(last.started_at).split(',')[0]} · ${fmtDur(last.duration_s)}` : 'Never'}
                </span>
                <span className="shrink-0 font-medium">
                  {job.schedule.length ? job.schedule[0] : 'Manual'}
                </span>
              </div>
              <div className="mt-auto flex items-center gap-1.5 pt-0.5">
                <Button
                  size="sm"
                  variant="primary"
                  className="h-8 px-3 text-xs rounded-lg font-medium"
                  icon={<Play size={12} aria-hidden fill="currentColor" />}
                  onClick={() => onRun(job.key)}
                  isStatic
                >
                  Run now
                </Button>
                {last && (
                  <Button
                    size="sm"
                    variant="secondary"
                    className="h-8 px-2.5 text-xs rounded-lg font-medium"
                    onClick={() => onOpenLog(last.id)}
                    isStatic
                  >
                    Last log
                  </Button>
                )}
              </div>
            </Card>
          );
        })}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Active campaigns — modern tile view                                        */
/* -------------------------------------------------------------------------- */

const TILE_RUNS: [string, string][] = [
  ['send_connections', 'Send connections'],
  ['check_replies', 'Replies'],
  ['send_followups', 'Follow-ups'],
];

/* Split menu so each tile can send any of the three workers against just that
   campaign (scope dialog opens pre-pinned to it).

   Stack note: every .surface card creates its own stacking context
   (backdrop-filter), so a z-index inside this menu can never climb past the
   *next* tile card. The fix lives in ActiveCampaigns: while a menu is open it
   raises the whole tile card (menuOpen=true -> relative z-30). */
function RunMenu({
  campaignId,
  onRun,
  onMenuChange,
}: {
  campaignId: number;
  onRun: (job: string, campaignId: number) => void;
  onMenuChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const setMenu = useCallback(
    (v: boolean) => {
      setOpen(v);
      onMenuChange?.(v);
    },
    [onMenuChange],
  );
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open, setMenu]);
  const picked = TILE_RUNS[0];
  return (
    <div ref={wrap} className="relative inline-flex items-center">
      {/* Joined group: perfectly matched height (h-8), rounded-control (10px),
          subtle primary gradient, and tactile hover feedback. */}
      <div className="inline-flex h-8 items-stretch overflow-hidden rounded-control shadow-2xs border border-primary/40 bg-primary">
        <button
          type="button"
          onClick={() => onRun(picked[0], campaignId)}
          className="inline-flex h-full items-center gap-1.5 bg-gradient-to-b from-primary to-[color-mix(in_srgb,var(--primary)_88%,black)] px-3 text-[12.5px] font-medium text-primary-ink transition-all duration-150 ease-out hover:brightness-105 active:brightness-95 cursor-pointer"
        >
          <Play size={12} aria-hidden fill="currentColor" />
          Run
        </button>
        <button
          type="button"
          aria-label="More run options"
          aria-expanded={open}
          onClick={() => setMenu(!open)}
          className="inline-flex h-full w-7 items-center justify-center border-l border-white/25 bg-gradient-to-b from-primary to-[color-mix(in_srgb,var(--primary)_88%,black)] text-primary-ink transition-all duration-150 ease-out hover:brightness-105 active:brightness-95 cursor-pointer"
        >
          <ChevronDown
            size={12}
            aria-hidden
            className={cn('transition-transform duration-150 ease-out', open && 'rotate-180')}
          />
        </button>
      </div>
      {open && (
        <div
          role="menu"
          className="absolute left-0 top-[calc(100%+6px)] z-50 min-w-[190px] flex-col overflow-hidden rounded-xl border border-border bg-[var(--surface-solid)] p-1.5 shadow-2xl backdrop-blur-none"
        >
          {TILE_RUNS.map(([job, label]) => (
            <button
              key={job}
              type="button"
              role="menuitem"
              onClick={() => {
                setMenu(false);
                onRun(job, campaignId);
              }}
              className="flex w-full items-center rounded-lg px-2.5 py-1.5 text-left text-[12.5px] font-medium text-foreground transition-colors duration-150 ease-out hover:bg-inset hover:text-primary cursor-pointer"
            >
              {label}
            </button>
          ))}
          <p className="border-t border-line/70 px-2.5 pb-1 pt-1.5 text-[10.5px] font-medium text-muted">Runs this campaign only</p>
        </div>
      )}
    </div>
  );
}

function ActiveCampaigns({
  campaigns,
  onRun,
  onSelectCampaign,
}: {
  campaigns: CampaignLite[];
  onRun: (job: string, campaignId: number) => void;
  onSelectCampaign: (campaign: CampaignLite) => void;
}) {
  const active = campaigns.filter((c) => c.status === 'active');
  const [openMenuFor, setOpenMenuFor] = useState<number | null>(null);
  if (!active.length) return null;
  return (
    <section aria-label="Active campaigns" className="flex flex-col gap-3">
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-[16px] font-semibold">Active campaigns</h2>
          <p className="card-sub">Click any campaign to inspect per-account run details and live metrics</p>
        </div>
        <a
          href="#/campaigns"
          className="text-[13px] font-medium text-primary hover:underline"
        >
          Manage campaigns
        </a>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {active.map((c) => (
          <Card
            key={c.id}
            onClick={() => onSelectCampaign(c)}
            className={cn(
              'surface-hover group relative flex cursor-pointer flex-col gap-3 p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md',
              openMenuFor === c.id && 'z-30',
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h3 className="truncate text-[14.5px] font-semibold text-foreground transition-colors group-hover:text-primary" title={c.name}>
                  {c.name}
                </h3>
                <p className="truncate text-[11.5px] text-muted">
                  {c.accounts.length
                    ? c.accounts.map((a) => a.account_name).join(', ')
                    : 'No sending account mapped'}
                </p>
              </div>
              <Ring value={c.replied} limit={Math.max(1, c.contacted)} size={46} stroke={5}>
                {c.reply_rate}%
              </Ring>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              {(
                [
                  ['Leads', c.leads],
                  ['Contacted', c.contacted],
                  ['Replied', c.replied],
                ] as const
              ).map(([label, value]) => (
                <div key={label} className="rounded-[10px] bg-inset px-2 py-1.5 transition-colors group-hover:bg-primary-tint/30">
                  <div className="num text-[15px] font-semibold">{nf.format(value)}</div>
                  <div className="text-[10.5px] uppercase tracking-wide text-muted">{label}</div>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between text-[11px] text-muted transition-colors group-hover:text-primary">
              <span>{c.accounts.length} sending {c.accounts.length === 1 ? 'account' : 'accounts'}</span>
              <span className="font-medium underline decoration-primary/40 underline-offset-2">View account runs →</span>
            </div>
            <div className="mt-auto flex items-center gap-2 border-t border-line/50 pt-2" onClick={(e) => e.stopPropagation()}>
              <RunMenu
                campaignId={c.id}
                onRun={onRun}
                onMenuChange={(open) =>
                  setOpenMenuFor((cur) => (open ? c.id : cur === c.id ? null : cur))
                }
              />
              <a
                href={`#/leads?${new URLSearchParams({ campaign_id: String(c.id) }).toString()}`}
                className="inline-flex h-8 items-center rounded-control border border-border/80 bg-surface px-3 text-[12.5px] font-medium text-ink shadow-2xs transition-colors duration-150 ease-out hover:border-primary/50 hover:bg-surface-2 hover:text-primary active:scale-[0.98]"
              >
                View leads
              </a>
            </div>
          </Card>
        ))}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Campaign run details per account popup modal                                */
/* -------------------------------------------------------------------------- */

function CampaignAccountRunModal({
  campaign,
  stats,
  accounts,
  rangeLabel,
  onClose,
  onOpenLog,
  onRun,
}: {
  campaign: CampaignLite | null;
  stats: CampaignStats | null;
  accounts: AccountLite[];
  rangeLabel: string;
  onClose: () => void;
  onOpenLog: (id: number) => void;
  onRun: (job: string, campaignId: number) => void;
}) {
  if (!campaign) return null;

  const rows = (stats?.rows ?? []).filter(
    (r) =>
      r.campaign_id === campaign.id ||
      r.campaign.toLowerCase() === campaign.name.toLowerCase(),
  );

  return (
    <Modal
      open={!!campaign}
      onClose={onClose}
      title={`Run Details · ${campaign.name}`}
      size="lg"
      footer={
        <div className="flex w-full items-center justify-between gap-3">
          <a
            href={`#/leads?campaign_id=${campaign.id}`}
            className="inline-flex h-8 items-center rounded-control border border-border/80 bg-surface px-3 text-[12.5px] font-medium text-ink shadow-2xs transition-colors duration-150 ease-out hover:border-primary/50 hover:bg-surface-2 hover:text-primary active:scale-[0.98]"
          >
            View campaign leads ({campaign.leads})
          </a>
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              icon={<Play size={12} aria-hidden fill="currentColor" />}
              onClick={() => {
                onClose();
                onRun('send_connections', campaign.id);
              }}
              isStatic
            >
              Run worker
            </Button>
            <Button variant="secondary" size="sm" onClick={onClose} isStatic>
              Close
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {/* Campaign summary banner */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[12px] bg-inset p-3.5">
          <div className="flex items-center gap-3">
            <Ring value={campaign.replied} limit={Math.max(1, campaign.contacted)} size={44} stroke={4}>
              {campaign.reply_rate}%
            </Ring>
            <div>
              <div className="text-[14.5px] font-semibold text-foreground">{campaign.name}</div>
              <p className="text-[12px] text-muted">
                {nf.format(campaign.leads)} leads tracked · {nf.format(campaign.contacted)} contacted · {nf.format(campaign.replied)} replied
              </p>
            </div>
          </div>
          <Pill tone={campaign.status === 'active' ? 'ok' : 'idle'} dot>
            {campaign.status}
          </Pill>
        </div>

        <div>
          <h3 className="text-[13.5px] font-semibold text-foreground">Per-account run details &amp; statistics</h3>
          <p className="card-sub text-[11.5px]">Outreach performance ({rangeLabel}) for each mapped sending account</p>
        </div>

        {campaign.accounts.length === 0 ? (
          <EmptyState
            title="No accounts assigned"
            body="Assign LinkedIn accounts to this campaign to start running workers."
          />
        ) : (
          <div className="flex flex-col gap-3">
            {campaign.accounts.map((accLink) => {
              const row = rows.find(
                (r) =>
                  r.account_id === accLink.account_id ||
                  r.account.toLowerCase() === accLink.account_name.toLowerCase(),
              );
              const fullAccount = accounts.find((a) => a.id === accLink.account_id);
              const lastRun = row?.last_run;

              return (
                <Card key={accLink.account_id} className="flex flex-col gap-3 border border-line p-3.5">
                  <div className="flex items-center justify-between gap-2 border-b border-line pb-2.5">
                    <div className="flex items-center gap-2">
                      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-tint text-[11px] font-bold text-primary">
                        {accLink.account_name.slice(0, 2).toUpperCase()}
                      </span>
                      <span className="text-[13.5px] font-semibold text-foreground">{accLink.account_name}</span>
                    </div>
                    {fullAccount && (
                      <Pill
                        tone={
                          fullAccount.status === 'active'
                            ? 'ok'
                            : fullAccount.status === 'paused'
                              ? 'idle'
                              : 'crit'
                        }
                        dot
                      >
                        {fullAccount.status.replace(/_/g, ' ')}
                      </Pill>
                    )}
                  </div>

                  {/* Send metrics grid */}
                  <div className="grid grid-cols-4 gap-2 text-center">
                    <div className="rounded-[8px] bg-inset p-2">
                      <div className="num text-[14px] font-semibold">{row ? row.invites : 0}</div>
                      <div className="text-[10px] uppercase tracking-wide text-muted">Invites</div>
                    </div>
                    <div className="rounded-[8px] bg-inset p-2">
                      <div className="num text-[14px] font-semibold">{row ? row.inmails : 0}</div>
                      <div className="text-[10px] uppercase tracking-wide text-muted">InMails</div>
                    </div>
                    <div className="rounded-[8px] bg-inset p-2">
                      <div className="num text-[14px] font-semibold">{row ? row.messages : 0}</div>
                      <div className="text-[10px] uppercase tracking-wide text-muted">Messages</div>
                    </div>
                    <div className="rounded-[8px] bg-inset p-2">
                      <div className="num text-[14px] font-semibold">{row ? row.replies : 0}</div>
                      <div className="text-[10px] uppercase tracking-wide text-muted">Replies</div>
                    </div>
                  </div>

                  {/* Last Run Info */}
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[12px] text-muted">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="font-medium text-foreground">Last run:</span>
                      {lastRun ? (
                        <>
                          <Pill
                            tone={
                              lastRun.status === 'success'
                                ? 'ok'
                                : lastRun.status === 'running'
                                  ? 'info'
                                  : 'crit'
                            }
                          >
                            {lastRun.status}
                          </Pill>
                          <span className="truncate">{JOB_LABELS[lastRun.job] ?? lastRun.job}</span>
                          <span>·</span>
                          <span title={fmtDT(lastRun.started_at)}>{ago(lastRun.started_at)}</span>
                        </>
                      ) : (
                        <span>No runs recorded in this date range</span>
                      )}
                    </div>
                    {lastRun && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-[11.5px] text-primary"
                        onClick={() => {
                          onClose();
                          onOpenLog(lastRun.id);
                        }}
                        isStatic
                      >
                        Inspect run log
                      </Button>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/* Activity + runs                                                            */
/* -------------------------------------------------------------------------- */

function ActivityFeed({ events }: { events: ActivityEvent[] }) {
  if (!events.length) {
    return (
      <Card className="p-4">
        <h2 className="text-[15px]">Recent activity</h2>
        <EmptyState
          icon={<MessageSquareReply size={22} aria-hidden />}
          title="No outreach activity yet"
          body="Invites, InMails, follow-ups and replies appear here as workers process leads."
          action={
            <a href="#/jobs" className="text-[13px] font-medium text-primary hover:underline">
              Open workers
            </a>
          }
        />
      </Card>
    );
  }

  const icon = (kind: string, job: string | null) =>
    kind === 'reply' ? (
      <MessageSquareReply size={15} aria-hidden />
    ) : kind === 'error' ? (
      <TriangleAlert size={15} aria-hidden />
    ) : job === 'send_connections' ? (
      <Send size={15} aria-hidden />
    ) : (
      <Target size={15} aria-hidden />
    );

  const tone = (kind: string) => (kind === 'reply' ? 'ok' : kind === 'error' ? 'crit' : 'primary');

  return (
    <Card className="flex h-[460px] flex-col p-4">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line pb-3">
        <div>
          <h2 className="text-[15px] font-semibold">Recent activity</h2>
          <p className="card-sub text-[11.5px]">Outreach events across your accounts</p>
        </div>
        <Pill tone="ok" dot>
          Live feed
        </Pill>
      </div>

      <div className="scroll-y mt-2 flex-1 min-h-0 overflow-y-auto pr-1">
        <ul className="flex flex-col gap-1">
          {events.map((e) => {
            const t = tone(e.kind);
            return (
              <li key={e.id} className="flex gap-3 rounded-[10px] p-2.5 transition-colors duration-150 ease-out hover:bg-inset">
                <span
                  className={cn(
                    'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg',
                    t === 'ok' ? 'bg-[var(--ok-tint)] text-ok' : t === 'crit' ? 'bg-[var(--crit-tint)] text-crit' : 'bg-primary-tint text-primary',
                  )}
                >
                  {icon(e.kind, e.job)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[13px] font-medium">
                      {e.kind === 'reply' ? 'Reply from ' : ''}
                      {e.lead_name || 'Lead'}
                      {e.company && <span className="font-normal text-muted"> · {e.company}</span>}
                    </span>
                    <time className="shrink-0 text-[11px] text-muted" title={fmtDT(e.created_at)}>
                      {ago(e.created_at)}
                    </time>
                  </div>
                  <p className="truncate text-[12.5px] text-muted" title={e.detail}>
                    {e.detail}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="shrink-0 border-t border-line/60 pt-2.5">
        <a href="#/leads" className="inline-flex items-center gap-1 text-[13px] font-medium text-primary hover:underline">
          View pipeline <ArrowUpRight size={14} aria-hidden />
        </a>
      </div>
    </Card>
  );
}

function RunsCard({ runs, onOpenLog }: { runs: Run[]; onOpenLog: (runId: number) => void }) {
  return (
    <Card className="flex h-[460px] flex-col p-4">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line pb-3">
        <div>
          <h2 className="text-[15px] font-semibold">Worker runs</h2>
          <p className="card-sub text-[11.5px]">Latest execution results — click a run to open console</p>
        </div>
        <a href="#/jobs" className="text-[12.5px] font-medium text-primary hover:underline">
          History
        </a>
      </div>

      <div className="scroll-y mt-2 flex-1 min-h-0 overflow-y-auto pr-1">
        {runs.length ? (
          <ul className="flex flex-col gap-1">
            {runs.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => onOpenLog(r.id)}
                  className="flex w-full items-center gap-3 rounded-[10px] p-2.5 text-left transition-colors duration-150 ease-out hover:bg-inset"
                >
                  <span className="num text-[12px] text-muted">#{r.id}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium">{JOB_LABELS[r.job] ?? r.job}</span>
                    <span className="block truncate text-[11.5px] text-muted">
                      {ago(r.started_at)} · {fmtDur(r.duration_s)}
                    </span>
                  </span>
                  <Pill tone={RUN_TONE[r.status] ?? 'idle'}>{r.status}</Pill>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No runs recorded" body="Worker executions will be listed here once they run." />
        )}
      </div>

      <div className="shrink-0 border-t border-line/60 pt-2.5">
        <a href="#/jobs" className="inline-flex items-center gap-1 text-[13px] font-medium text-primary hover:underline">
          View all worker runs <ArrowUpRight size={14} aria-hidden />
        </a>
      </div>
    </Card>
  );
}
