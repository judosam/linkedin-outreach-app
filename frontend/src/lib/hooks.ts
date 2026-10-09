import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api';

/* A small data-fetch hook with stale-response guarding: a slow response from a
   previous filter can never overwrite the current view. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);

  const run = useCallback(async () => {
    const id = ++seq.current;
    setLoading(true);
    setError('');
    try {
      const result = await fn();
      if (id === seq.current) setData(result);
    } catch (e) {
      if (id === seq.current) {
        setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e));
      }
    } finally {
      if (id === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    void run();
  }, [run]);

  return { data, error, loading, reload: run, setData };
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return debounced;
}
