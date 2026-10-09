import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  LiveConsoleDock,
  RunCompletedModal,
  RunLogModal,
  type LivePayload,
  type RunLog,
} from '@/components/run';
import { apiGet } from '@/lib/api';
import { JOB_LABELS } from '@/lib/constants';
import { desktopNotify, notificationsEnabled } from '@/lib/notify';

const LiveConsoleCtx = createContext<{
  open: (executionId?: string | null) => void;
  close: () => void;
  isOpen: boolean;
  liveCount: number;
}>({ open: () => {}, close: () => {}, isOpen: false, liveCount: 0 });
export const useLiveConsole = () => useContext(LiveConsoleCtx);

export function LiveConsoleProvider({ children }: { children: ReactNode }) {
  /* Always minimized by default; auto-expands when a worker run is active or triggered */
  const [isOpen, setOpen] = useState(false);
  const wasRunningRef = useRef(false);
  const [execId, setExecId] = useState<string | null>(null);
  const [liveCount, setLiveCount] = useState(0);
  const [watchVersion, setWatchVersion] = useState(0);
  const [completed, setCompleted] = useState<RunLog[]>([]);
  const [logId, setLogId] = useState<number | null>(null);
  const tracked = useRef(new Map<string, string | null>());
  const shown = useRef(new Set<number>());
  const open = useCallback((id?: string | null) => {
    setExecId(id ?? null);
    setOpen(true);
    // Track immediately, including jobs which finish before the next poll.
    if (id) {
      tracked.current.set(id, null);
      setWatchVersion((version) => version + 1);
    }
  }, []);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    const tick = async () => {
      try {
        const live = await apiGet<LivePayload>('/api/runs/live');
        if (cancelled) return;
        const currentCount = live.running_count || (live.active ? 1 : 0);
        setLiveCount(currentCount);
        const isRunning = Boolean(live.active || currentCount > 0);
        if (isRunning && !wasRunningRef.current) {
          setOpen(true);
        }
        wasRunningRef.current = isRunning;
        const active = new Set((live.running ?? []).map((r) => r.execution_id));
        for (const run of live.running ?? []) tracked.current.set(run.execution_id, run.job);
        if (live.active && live.execution_id) {
          active.add(live.execution_id);
          tracked.current.set(live.execution_id, live.job);
        }
        // Each execution is checked separately so concurrent jobs cannot hide
        // one another's completion behind the server's default live selection.
        for (const [id, job] of tracked.current) {
          if (active.has(id)) continue;
          try {
            const end =
              live.execution_id === id
                ? live
                : await apiGet<LivePayload>(`/api/runs/live?execution_id=${encodeURIComponent(id)}`);
            if (cancelled) return;
            if (end.active || !end.finished) continue;
            let runId = end.run_id;
            if (!runId && job) {
              const recent = await apiGet<(RunLog & { execution_id?: string })[]>(
                `/api/runs?job=${encodeURIComponent(job)}&limit=1`,
              );
              // Never report a different execution's result.
              if (recent[0]?.execution_id === id) runId = recent[0].id;
            }
            if (!runId) continue;
            if (shown.current.has(runId)) {
              tracked.current.delete(id);
              continue;
            }
            const run = await apiGet<RunLog>(`/api/runs/${runId}/log`);
            if (cancelled) return;
            tracked.current.delete(id);
            shown.current.add(runId);
            if (!notificationsEnabled()) continue;
            const stats = Object.entries(run.stats ?? {})
              .filter(([, v]) => typeof v === 'number')
              .slice(0, 4)
              .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`)
              .join(' · ');
            if (document.visibilityState === 'hidden')
              desktopNotify(
                'Run completed',
                [JOB_LABELS[run.job] ?? run.job, run.target, run.status, stats].filter(Boolean).join(' · '),
              );
            else setCompleted((prev) => [...prev, run]);
          } catch {
            /* Retain tracked execution and retry after a transient failure. */
          }
        }
      } catch {
        /* Keep polling after a transient network failure. */
      }
      if (!cancelled) timer = window.setTimeout(tick, tracked.current.size ? 3000 : 10000);
    };
    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [watchVersion]);

  return (
    <LiveConsoleCtx.Provider value={{ open, close, isOpen, liveCount }}>
      {children}
      <LiveConsoleDock
        open={isOpen}
        onOpen={() => setOpen(true)}
        onClose={close}
        execId={execId}
        onExecIdChange={setExecId}
      />
      <RunCompletedModal
        run={completed[0] ?? null}
        onClose={() => setCompleted((prev) => prev.slice(1))}
        onLog={(id) => {
          setCompleted((prev) => prev.slice(1));
          setLogId(id);
        }}
      />
      <RunLogModal runId={logId} onClose={() => setLogId(null)} />
    </LiveConsoleCtx.Provider>
  );
}
