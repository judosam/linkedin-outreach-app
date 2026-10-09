import { useState } from 'react';
import {
  CalendarClock,
  CalendarPlus,
  History,
  Layers,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react';
import { Button, Card, EmptyState, ErrorState, IconButton, Loading, Pill, Segmented, cn } from '@/components/ui';
import { Field, Input, PageHeader, Select } from '@/components/form';
import { Modal } from '@/components/Modal';
import { BatchDialog, RunLogModal } from '@/components/run';
import { apiDelete, apiGet, apiPost, apiPut } from '@/lib/api';
import { useAsync } from '@/lib/hooks';
import { useJobs } from '@/lib/jobs';
import { useLiveConsole } from '@/lib/console';
import { ConsoleButton } from '@/components/run';
import { useToast } from '@/lib/toast';
import { JOB_LABELS, RUN_TONE } from '@/lib/constants';
import { fmtDT, fmtDur } from '@/lib/format';

interface Run {
  id: number;
  job: string;
  target: string | null;
  dry_run: boolean;
  status: string;
  schedule_id?: number | null;
  started_at: string | null;
  duration_s: number | null;
}

interface Schedule {
  id: number;
  name: string;
  run_time: string;
  days_of_week: string[];
  job_keys: string[];
  active: boolean;
  jitter_minutes: number;
  timezone?: string;
  window_end?: string | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
}

const DAYS: [string, string][] = [
  ['mon', 'Mon'],
  ['tue', 'Tue'],
  ['wed', 'Wed'],
  ['thu', 'Thu'],
  ['fri', 'Fri'],
  ['sat', 'Sat'],
  ['sun', 'Sun'],
];

const STATUS_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'success', label: 'Success' },
  { value: 'partial', label: 'Partial' },
  { value: 'error', label: 'Error' },
  { value: 'stopped', label: 'Stopped' },
];

export default function Jobs() {
  const jobs = useJobs();
  const console = useLiveConsole();
  const toast = useToast();
  const { data: runs, error, loading, reload } = useAsync<Run[]>(() => apiGet('/api/runs?limit=50'), []);
  const schedules = useAsync<Schedule[]>(() => apiGet('/api/schedules'), []);
  const [logId, setLogId] = useState<number | null>(null);
  const [batch, setBatch] = useState(false);
  const [modalSchedule, setModalSchedule] = useState<{ open: boolean; schedule: Schedule | null }>({
    open: false,
    schedule: null,
  });
  const [statusFilter, setStatusFilter] = useState('all');
  /* Per-schedule history filter (client-side on schedule_id, which the
     /api/runs serializer already returns). */
  const [historySchedule, setHistorySchedule] = useState<number | null>(null);

  const live = jobs.data?.live ?? null;
  const running = live?.status === 'running';
  const rows = runs ?? [];
  const filtered = rows.filter(
    (r) =>
      (statusFilter === 'all' || r.status === statusFilter) &&
      (historySchedule == null || r.schedule_id === historySchedule),
  );
  const historyScheduleName =
    historySchedule != null ? (schedules.data ?? []).find((s) => s.id === historySchedule)?.name ?? `#${historySchedule}` : null;

  const toggleSchedule = async (s: Schedule) => {
    try {
      await apiPut(`/api/schedules/${s.id}`, { ...s, active: !s.active });
      toast(s.active ? 'Schedule paused' : 'Schedule resumed', 'ok');
      await schedules.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    }
  };

  const removeSchedule = async (s: Schedule) => {
    if (!window.confirm(`Delete schedule "${s.name}"? Future runs will stop. Run history remains available.`)) return;
    try {
      await apiDelete(`/api/schedules/${s.id}`);
      toast('Schedule deleted', 'ok');
      await schedules.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    }
  };

  const runScheduleNow = async (s: Schedule) => {
    try {
      const res = await apiPost<{ ok: boolean; message: string }>(`/api/schedules/${s.id}/run`);
      toast(res.message || `Started ${s.name}`, 'ok');
      await jobs.refresh();
      await schedules.reload();
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Scheduler"
        subtitle="Automatic worker schedules and execution audit history"
        actions={
          <>
            <ConsoleButton count={console.liveCount} onClick={() => console.open()} />
            <Button
              variant="primary"
              size="sm"
              id="jsNew"
              icon={<CalendarPlus size={14} aria-hidden />}
              onClick={() => setModalSchedule({ open: true, schedule: null })}
              isStatic
            >
              Add schedule
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Layers size={14} aria-hidden />}
              onClick={() => setBatch(true)}
              isStatic
            >
              Run batch
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw size={14} aria-hidden />}
              onClick={() => {
                void jobs.refresh();
                void reload();
                void schedules.reload();
              }}
              isStatic
            >
              Refresh
            </Button>
          </>
        }
      />

      {/* Scheduler overview — the old page's engine card */}
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-[12px] bg-primary text-primary-ink shadow-border">
            <CalendarClock size={18} aria-hidden />
          </span>
          <div>
            <h2 className="text-[15px]">Scheduler</h2>
            <p className="card-sub">
              {schedules.data?.filter((s) => s.active).length ?? 0} active ·{' '}
              {schedules.data?.filter((s) => !s.active).length ?? 0} paused · Asia/Kolkata (IST · UTC+05:30)
            </p>
          </div>
        </div>
        <Pill tone={running ? 'primary' : 'ok'} dot>
          {running ? `Running: ${JOB_LABELS[live?.job ?? ''] ?? live?.job ?? ''}` : 'Ready'}
        </Pill>
      </Card>

      {/* Schedules — a proper table, with per-schedule history */}
      <ScheduleTable
        schedules={schedules.data ?? []}
        loading={schedules.loading && !schedules.data}
        error={schedules.error}
        onReload={schedules.reload}
        onAdd={() => setModalSchedule({ open: true, schedule: null })}
        onEdit={(s) => setModalSchedule({ open: true, schedule: s })}
        onRunNow={(s) => void runScheduleNow(s)}
        onToggle={(s) => void toggleSchedule(s)}
        onDelete={(s) => void removeSchedule(s)}
        onHistory={(id) => {
          setHistorySchedule(id);
          document.getElementById('run-history')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }}
        historySchedule={historySchedule}
      />

      {/* Run history — every execution with outcome, duration and console */}
      <div id="run-history">
        <Card className="min-w-0 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-[15px]">Run history</h2>
              <p className="card-sub">Every execution with its outcome, duration and console output.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {historySchedule != null && (
                <button
                  type="button"
                  className="filter-chip"
                  onClick={() => setHistorySchedule(null)}
                  aria-label="Clear schedule filter"
                >
                  <span>Schedule: {historyScheduleName}</span>
                  <X size={12} aria-hidden />
                </button>
              )}
              <Segmented
                label="Run history status filter"
                value={statusFilter}
                onChange={setStatusFilter}
                options={STATUS_FILTERS}
              />
            </div>
          </div>

          {loading && !runs ? (
            <Loading />
          ) : error ? (
            <ErrorState message={error} onRetry={reload} />
          ) : filtered.length ? (
            <div className="mt-3.5 max-h-[500px] overflow-y-auto overflow-x-auto rounded-xl border border-line/70 shadow-2xs overscroll-contain">
              <table className="w-full min-w-[760px] border-collapse text-[13px]">
                <thead className="sticky top-0 z-10 bg-surface/95 backdrop-blur-xs border-b border-line shadow-2xs">
                  <tr className="text-left text-[11px] uppercase tracking-wide text-muted">
                    <th className="py-2.5 px-3 font-semibold">Run</th>
                    <th className="py-2.5 px-3 font-semibold">Worker</th>
                    <th className="py-2.5 px-3 font-semibold">Target</th>
                    <th className="py-2.5 px-3 font-semibold">Started</th>
                    <th className="py-2.5 px-3 text-right font-semibold">Duration</th>
                    <th className="py-2.5 pr-4 text-right font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/60">
                  {filtered.map((r) => (
                    <tr
                      key={r.id}
                      className="cursor-pointer transition-colors duration-150 ease-out hover:bg-surface-2/80"
                      onClick={() => setLogId(r.id)}
                    >
                      <td className="num py-2.5 px-3 text-muted">#{r.id}</td>
                      <td className="py-2.5 px-3 font-medium text-foreground">{JOB_LABELS[r.job] ?? r.job}</td>
                      <td className="max-w-[220px] truncate py-2.5 px-3 text-muted">{r.target || '—'}</td>
                      <td className="py-2.5 px-3 text-muted">{fmtDT(r.started_at)}</td>
                      <td className="num py-2.5 px-3 text-right">{fmtDur(r.duration_s)}</td>
                      <td className="py-2.5 pr-4 text-right">
                        <Pill tone={RUN_TONE[r.status] ?? 'idle'}>
                          {r.status}
                          {r.dry_run ? ' · dry' : ''}
                        </Pill>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={<CalendarClock size={22} aria-hidden />}
              title="No runs recorded"
              body="Worker executions appear here once they run."
            />
          )}
        </Card>
      </div>

      <RunLogModal runId={logId} onClose={() => setLogId(null)} />

      <BatchDialog
        open={batch}
        onClose={() => setBatch(false)}
        onStarted={async () => {
          setBatch(false);
          await jobs.refresh();
          await reload();
        }}
      />

      <ScheduleModal
        open={modalSchedule.open}
        schedule={modalSchedule.schedule}
        onClose={() => setModalSchedule({ open: false, schedule: null })}
        onSaved={async () => {
          await schedules.reload();
          await jobs.refresh();
        }}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Schedules table — the separate, scannable view the user asked for          */
/* -------------------------------------------------------------------------- */

function ScheduleTable({
  schedules,
  loading,
  error,
  onReload,
  onAdd,
  onEdit,
  onRunNow,
  onToggle,
  onDelete,
  onHistory,
  historySchedule,
}: {
  schedules: Schedule[];
  loading: boolean;
  error: string;
  onReload: () => Promise<void>;
  onAdd: () => void;
  onEdit: (s: Schedule) => void;
  onRunNow: (s: Schedule) => void;
  onToggle: (s: Schedule) => void;
  onDelete: (s: Schedule) => void;
  onHistory: (id: number) => void;
  historySchedule: number | null;
}) {
  if (loading) {
    return (
      <Card className="p-4">
        <Loading />
      </Card>
    );
  }
  if (error) {
    return (
      <Card className="p-4">
        <ErrorState message={error} onRetry={() => void onReload()} />
      </Card>
    );
  }
  if (!schedules.length) {
    return (
      <Card className="p-6">
        <EmptyState
          icon={<CalendarPlus size={24} aria-hidden />}
          title="No schedules yet"
          body="Create a named schedule to run workers automatically on chosen days and times."
          action={
            <Button
              variant="primary"
              size="sm"
              icon={<CalendarPlus size={14} aria-hidden />}
              onClick={onAdd}
              isStatic
            >
              Add schedule
            </Button>
          }
        />
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line/70 px-4 py-3 bg-surface-2/40">
        <div className="flex items-center gap-2">
          <CalendarClock size={16} className="text-primary" aria-hidden />
          <span className="font-semibold text-[13.5px] text-foreground">Configured schedules</span>
          <span className="text-[12px] text-muted">({schedules.length})</span>
        </div>
        <Button
          variant="primary"
          size="sm"
          icon={<CalendarPlus size={13} aria-hidden />}
          onClick={onAdd}
          isStatic
        >
          Add schedule
        </Button>
      </div>
      <div className="dt-wrap">
        <table className="dt dt-fixed min-w-[1050px]">
          <colgroup>
            {[14, 7, 11, 14, 5, 10, 8, 7, 24].map((w, i) => (
              <col key={i} style={{ width: w + '%' }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th>Name</th>
              <th>Time (IST)</th>
              <th>Days</th>
              <th>Workers</th>
              <th>Jitter</th>
              <th>Next run</th>
              <th>Last run</th>
              <th>Status</th>
              <th className="col-actions" />
            </tr>
          </thead>
          <tbody>
            {schedules.map((s) => (
              <tr key={s.id} data-active={historySchedule === s.id}>
                <td>
                  <span className="block truncate font-medium" title={s.name}>
                    {s.name}
                  </span>
                </td>
                <td className="num">{s.run_time}</td>
                <td>
                  <span className="flex flex-wrap gap-1">
                    {DAYS.map(([val, label]) => {
                      const on = !s.days_of_week.length || s.days_of_week.includes(val);
                      return (
                        <span
                          key={val}
                          className={
                            on
                              ? 'rounded-full bg-primary px-1.5 py-0.5 text-[10px] font-medium text-primary-ink'
                              : 'rounded-full bg-inset px-1.5 py-0.5 text-[10px] text-muted'
                          }
                        >
                          {label}
                        </span>
                      );
                    })}
                  </span>
                </td>
                <td>
                  <span className="flex flex-wrap gap-1">
                    {s.job_keys.length ? (
                      s.job_keys.map((k) => (
                        <span key={k} className="chip">
                          {JOB_LABELS[k] ?? k}
                        </span>
                      ))
                    ) : (
                      <span className="text-[12px] text-muted">None</span>
                    )}
                  </span>
                </td>
                <td className="num text-[12px] text-muted">{s.jitter_minutes > 0 ? `±${s.jitter_minutes}m` : '—'}</td>
                <td className="text-[12px] text-muted">{s.next_run_at ? fmtDT(s.next_run_at) : '—'}</td>
                <td className="text-[12px] text-muted">{s.last_run_at ? fmtDT(s.last_run_at) : 'never'}</td>
                <td>
                  <Pill tone={s.active ? 'ok' : 'idle'} dot>
                    {s.active ? 'Active' : 'Paused'}
                  </Pill>
                </td>
                <td className="col-actions min-w-[260px]">
                  <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
                    <Button
                      size="sm"
                      variant="primary"
                      className="h-7 shrink-0 whitespace-nowrap px-2.5 text-[11px] font-medium"
                      onClick={() => onRunNow(s)}
                      title={`Run ${s.name} now`}
                      isStatic
                    >
                      <Play size={10} className="mr-1 inline shrink-0" fill="currentColor" aria-hidden />
                      Run now
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      className="h-7 shrink-0 whitespace-nowrap px-2.5 text-[11px] font-medium"
                      data-edit={s.id}
                      onClick={() => onEdit(s)}
                      title={`Edit ${s.name}`}
                      isStatic
                    >
                      <Pencil size={11} className="mr-1 inline shrink-0" aria-hidden />
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      className={cn(
                        'h-7 shrink-0 whitespace-nowrap px-2.5 text-[11px] font-medium transition-colors border',
                        s.active
                          ? 'text-amber-700 bg-amber-500/10 hover:bg-amber-500/20 border-amber-500/30 dark:text-amber-300'
                          : 'text-emerald-700 bg-emerald-500/10 hover:bg-emerald-500/20 border-emerald-500/30 dark:text-emerald-300',
                      )}
                      data-active={s.id}
                      onClick={() => onToggle(s)}
                      title={s.active ? `Pause ${s.name}` : `Resume ${s.name}`}
                      isStatic
                    >
                      {s.active ? (
                        <>
                          <Pause size={11} className="mr-1 inline shrink-0" aria-hidden />
                          Pause
                        </>
                      ) : (
                        <>
                          <Play size={11} className="mr-1 inline shrink-0" aria-hidden />
                          Resume
                        </>
                      )}
                    </Button>
                    <IconButton
                      label={`Show run history for ${s.name}`}
                      size="sm"
                      className="h-7 w-7 shrink-0 rounded-lg border border-border/80 bg-surface text-ink2 shadow-2xs hover:border-primary/50 hover:bg-primary-tint/30 hover:text-primary transition-all"
                      onClick={() => onHistory(s.id)}
                    >
                      <History size={12} aria-hidden />
                    </IconButton>
                    <IconButton
                      label={`Delete ${s.name}`}
                      size="sm"
                      data-del={s.id}
                      className="h-7 w-7 shrink-0 rounded-lg border border-border/80 bg-surface text-ink2 shadow-2xs hover:border-crit/50 hover:bg-crit-tint/30 hover:text-crit transition-all"
                      onClick={() => onDelete(s)}
                    >
                      <Trash2 size={12} aria-hidden />
                    </IconButton>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* Schedule Modal — Add / Edit schedule dialog                                */
/* -------------------------------------------------------------------------- */

function ScheduleModal({
  open,
  schedule,
  onClose,
  onSaved,
}: {
  open: boolean;
  schedule: Schedule | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState('');
  const [runTime, setRunTime] = useState('09:00');
  const [windowEnd, setWindowEnd] = useState('');
  const [days, setDays] = useState<string[]>(['mon', 'tue', 'wed', 'thu', 'fri']);
  const [workers, setWorkers] = useState<string[]>(['send_connections', 'check_replies', 'send_followups']);
  const [jitter, setJitter] = useState(5);
  const [active, setActive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [seeded, setSeeded] = useState(false);

  if (open && !seeded) {
    setSeeded(true);
    if (schedule) {
      setName(schedule.name || '');
      setRunTime(schedule.run_time || '09:00');
      setWindowEnd(schedule.window_end || '');
      setDays(schedule.days_of_week?.length ? [...schedule.days_of_week] : ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']);
      setWorkers(schedule.job_keys?.length ? [...schedule.job_keys] : ['send_connections', 'check_replies', 'send_followups']);
      setJitter(schedule.jitter_minutes ?? 5);
      setActive(schedule.active ?? true);
    } else {
      setName('');
      setRunTime('09:00');
      setWindowEnd('');
      setDays(['mon', 'tue', 'wed', 'thu', 'fri']);
      setWorkers(['send_connections', 'check_replies', 'send_followups']);
      setJitter(5);
      setActive(true);
    }
    setError('');
    setBusy(false);
  }
  if (!open && seeded) {
    setSeeded(false);
  }

  const toggleDay = (d: string) => {
    setDays((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]));
  };

  const toggleWorker = (w: string) => {
    setWorkers((prev) => (prev.includes(w) ? prev.filter((x) => x !== w) : [...prev, w]));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('Please enter a schedule name.');
      return;
    }
    if (!runTime.trim()) {
      setError('Please choose a start run time.');
      return;
    }
    if (!workers.length) {
      setError('Please select at least one worker to execute.');
      return;
    }
    if (windowEnd.trim() && windowEnd.trim() <= runTime.trim()) {
      setError('Window end time must be after the start time.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const payload = {
        name: name.trim(),
        run_time: runTime.trim(),
        window_end: windowEnd.trim() ? windowEnd.trim() : null,
        days_of_week: days.length === 7 ? [] : days,
        job_keys: workers,
        jitter_minutes: Number(jitter) || 0,
        active: active,
        timezone: 'Asia/Kolkata',
      };
      if (schedule && schedule.id) {
        await apiPut(`/api/schedules/${schedule.id}`, payload);
        toast(`Schedule "${name}" updated`, 'ok');
      } else {
        await apiPost('/api/schedules', payload);
        toast(`Schedule "${name}" created`, 'ok');
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={schedule ? `Edit schedule: ${schedule.name}` : 'New schedule'}
      size="lg"
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose} isStatic>
            Cancel
          </Button>
          <Button id="sSave" variant="primary" size="sm" type="submit" form="schedule-form" disabled={busy} isStatic>
            {busy ? 'Saving…' : schedule ? 'Save changes' : 'Create schedule'}
          </Button>
        </>
      }
    >
      <form id="schedule-form" onSubmit={submit} className="flex flex-col gap-4">
        {error && (
          <div role="alert" className="rounded-lg bg-crit-tint/50 border border-crit/20 p-3 text-xs text-crit">
            {error}
          </div>
        )}

        <Field label="Schedule name *">
          <Input
            id="sName"
            required
            placeholder="e.g. Daily Morning Outreach"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Start run time (IST) *" hint="Asia/Kolkata time (UTC+05:30)">
            <Input
              type="time"
              required
              value={runTime}
              onChange={(e) => setRunTime(e.target.value)}
            />
          </Field>
          <Field label="Window end time (Optional)" hint="Runs stop if past this time">
            <Input
              type="time"
              value={windowEnd}
              onChange={(e) => setWindowEnd(e.target.value)}
              placeholder="HH:MM"
            />
          </Field>
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <label className="text-[13px] font-medium text-ink">Recurrence days</label>
            <div className="flex items-center gap-1.5 text-[11.5px]">
              <button
                type="button"
                onClick={() => setDays(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])}
                className="text-primary hover:underline cursor-pointer"
              >
                Every day
              </button>
              <span className="text-muted">·</span>
              <button
                type="button"
                onClick={() => setDays(['mon', 'tue', 'wed', 'thu', 'fri'])}
                className="text-primary hover:underline cursor-pointer"
              >
                Weekdays
              </button>
              <span className="text-muted">·</span>
              <button
                type="button"
                onClick={() => setDays(['sat', 'sun'])}
                className="text-primary hover:underline cursor-pointer"
              >
                Weekends
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {DAYS.map(([code, label]) => {
              const selected = days.includes(code);
              return (
                <button
                  key={code}
                  type="button"
                  data-day={code}
                  onClick={() => toggleDay(code)}
                  className={cn(
                    'h-8 px-3 rounded-lg text-xs font-medium border transition-colors cursor-pointer',
                    selected
                      ? 'bg-primary text-primary-ink border-primary shadow-2xs'
                      : 'bg-surface-2 text-muted border-border hover:border-primary/50 hover:text-foreground',
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>
          <p className="text-[11.5px] text-muted">
            {days.length === 0 || days.length === 7
              ? 'Runs every day of the week.'
              : `Runs on ${days.map((d) => DAYS.find((x) => x[0] === d)?.[1]).join(', ')}.`}
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[13px] font-medium text-ink">Workers to execute *</label>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {[
              { key: 'send_connections', label: 'Send Connections', desc: 'Invites & InMails' },
              { key: 'check_replies', label: 'Check Replies', desc: 'Accepts & replies' },
              { key: 'send_followups', label: 'Send Follow-ups', desc: 'Sequence messages' },
            ].map((w) => {
              const on = workers.includes(w.key);
              return (
                <div
                  key={w.key}
                  data-job={w.key}
                  onClick={() => toggleWorker(w.key)}
                  className={cn(
                    'flex flex-col gap-1 p-2.5 rounded-xl border cursor-pointer transition-colors select-none',
                    on
                      ? 'border-primary/50 bg-primary-tint/30 text-foreground'
                      : 'border-border/70 bg-surface-2/60 text-muted hover:border-primary/30',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-[12.5px]">{w.label}</span>
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => {}}
                      className="h-3.5 w-3.5 rounded border-border text-primary cursor-pointer"
                    />
                  </div>
                  <span className="text-[11px] text-muted">{w.desc}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Random jitter delay" hint="Offset start time to vary human pattern">
            <Select value={String(jitter)} onChange={(e) => setJitter(Number(e.target.value))}>
              <option value="0">0 min (Exact time)</option>
              <option value="5">±5 minutes jitter</option>
              <option value="10">±10 minutes jitter</option>
              <option value="15">±15 minutes jitter</option>
              <option value="30">±30 minutes jitter</option>
            </Select>
          </Field>

          <div className="flex flex-col justify-center gap-1.5 pt-1">
            <span className="text-[13px] font-medium text-ink">Status</span>
            <label className="flex items-center gap-2.5 cursor-pointer rounded-lg border border-border/70 bg-surface-2/60 p-2.5 hover:border-border transition-colors">
              <input
                type="checkbox"
                checked={active}
                onChange={(e) => setActive(e.target.checked)}
                className="h-4 w-4 rounded border-border text-primary cursor-pointer"
              />
              <div className="flex flex-col">
                <span className="text-[12.5px] font-medium text-foreground">Active schedule</span>
                <span className="text-[11px] text-muted">Runs automatically when enabled</span>
              </div>
            </label>
          </div>
        </div>
      </form>
    </Modal>
  );
}
