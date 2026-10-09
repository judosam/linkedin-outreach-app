import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { CheckCircle2, Info, TriangleAlert, X, XCircle } from 'lucide-react';
import { cn } from '@/components/ui';

type ToastTone = 'info' | 'ok' | 'warn' | 'crit';
interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
}

const ToastCtx = createContext<(message: string, tone?: ToastTone) => void>(() => {});

export const useToast = () => useContext(ToastCtx);

const ICONS: Record<ToastTone, ReactNode> = {
  info: <Info size={16} aria-hidden />,
  ok: <CheckCircle2 size={16} aria-hidden />,
  warn: <TriangleAlert size={16} aria-hidden />,
  crit: <XCircle size={16} aria-hidden />,
};

const TONE_TEXT: Record<ToastTone, string> = {
  info: 'text-info',
  ok: 'text-ok',
  warn: 'text-warn',
  crit: 'text-crit',
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const counter = useRef(0);
  const last = useRef({ message: '', at: 0 });

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (message: string, tone: ToastTone = 'info') => {
      // The API layer and call sites can fire the same message milliseconds
      // apart; show it once.
      const now = Date.now();
      if (message === last.current.message && now - last.current.at < 2000) return;
      last.current = { message, at: now };
      const id = ++counter.current;
      setItems((prev) => [...prev.slice(-3), { id, message, tone }]);
      window.setTimeout(() => dismiss(id), 6000);
    },
    [dismiss],
  );

  const value = useMemo(() => push, [push]);

  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-[80] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2"
        aria-live="polite"
        aria-atomic="false"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className={cn(
              'pointer-events-auto flex items-start gap-2.5 p-3 pr-2 text-sm',
              'surface shadow-pop animate-[toast-in_200ms_cubic-bezier(0.2,0,0,1)]',
            )}
          >
            <span className={cn('mt-0.5 shrink-0', TONE_TEXT[t.tone])}>{ICONS[t.tone]}</span>
            <span className="min-w-0 flex-1 break-words">{t.message}</span>
            <button
              type="button"
              aria-label="Dismiss notification"
              onClick={() => dismiss(t.id)}
              className="shrink-0 rounded-md p-1 text-muted transition-colors duration-150 ease-out hover:bg-inset hover:text-ink"
            >
              <X size={14} aria-hidden />
            </button>
          </div>
        ))}
      </div>
      <style>{`@keyframes toast-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}`}</style>
    </ToastCtx.Provider>
  );
}
