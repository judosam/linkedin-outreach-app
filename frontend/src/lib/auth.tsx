import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { apiGet, apiPost, ApiError } from '@/lib/api';
import type { Me } from '@/lib/types';

interface AuthValue {
  me: Me | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthCtx = createContext<AuthValue>({
  me: null,
  loading: true,
  login: async () => {},
  logout: async () => {},
});

export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setMe(await apiGet<Me>('/api/me'));
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) {
        // Any non-auth failure still means "not signed in" for the shell.
      }
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    await apiPost('/api/login', { username: username.trim(), password });
    setMe(await apiGet<Me>('/api/me'));
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiPost('/api/logout');
    } catch {
      /* the session is being discarded either way */
    }
    setMe(null);
  }, []);

  const value = useMemo(() => ({ me, loading, login, logout }), [me, loading, login, logout]);
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}
