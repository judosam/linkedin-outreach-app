import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { apiGet } from '@/lib/api';
import type { JobsPayload } from '@/lib/types';

interface JobsValue {
  data: JobsPayload | null;
  refresh: () => Promise<void>;
}

const JobsCtx = createContext<JobsValue>({ data: null, refresh: async () => {} });
export const useJobs = () => useContext(JobsCtx);

/* Poll cadence tightens while any worker is live so the running chip and stop
   control feel immediate, then relaxes to a calm 10s. The latest payload is
   read from a ref so the loop itself never restarts. */
export function JobsProvider({ children, enabled = true }: { children: ReactNode; enabled?: boolean }) {
  const [data, setData] = useState<JobsPayload | null>(null);
  const latest = useRef<JobsPayload | null>(null);

  const refresh = useCallback(async () => {
    try {
      const payload = await apiGet<JobsPayload>('/api/jobs');
      latest.current = payload;
      setData(payload);
    } catch {
      /* a transient poll failure must not tear down the shell */
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer = 0;

    const tick = async () => {
      await refresh();
      if (cancelled) return;
      const running =
        latest.current?.live?.status === 'running' || (latest.current?.running?.length ?? 0) > 0;
      timer = window.setTimeout(tick, running ? 3000 : 10000);
    };

    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [enabled, refresh]);

  const value = useMemo(() => ({ data, refresh }), [data, refresh]);
  return <JobsCtx.Provider value={value}>{children}</JobsCtx.Provider>;
}
