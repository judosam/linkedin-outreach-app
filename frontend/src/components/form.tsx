import type { ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes, InputHTMLAttributes } from 'react';
import { cn } from '@/components/ui';

/* Form primitives. Every control gets a real <label> and shares one hit target
   with its text, per the accessibility floor in the interface guidelines. */

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: ReactNode;
  hint?: string;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn('flex flex-col gap-1.5', className)}>
      <span className="text-[13px] font-medium text-ink">{label}</span>
      {hint && <span className="-mt-1 text-[12px] text-muted">{hint}</span>}
      {children}
      {error && (
        <span role="alert" className="text-[12px] text-crit">
          {error}
        </span>
      )}
    </label>
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn('cm-input', className)} {...props} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn('cm-input cursor-pointer', className)} {...props}>
      {children}
    </select>
  );
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'w-full rounded-control border border-[var(--border-strong)] bg-surface px-3 py-2 text-[13px] text-ink',
        'transition-[border-color,box-shadow] duration-150 ease-out hover:border-[var(--muted)]',
        'placeholder:text-muted',
        className,
      )}
      {...props}
    />
  );
}

export function Switch({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-[10px] p-2 transition-colors duration-150 ease-out hover:bg-inset">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={cn(
          'mt-0.5 h-5 w-9 shrink-0 rounded-full p-0.5 transition-colors duration-150 ease-out',
          checked ? 'bg-primary' : 'bg-[var(--border-strong)]',
        )}
      >
        <span
          className={cn(
            'block h-4 w-4 rounded-full bg-white shadow-border transition-transform duration-150 ease-out',
            checked ? 'translate-x-4' : 'translate-x-0',
          )}
        />
      </button>
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-ink">{label}</span>
        {hint && <span className="block text-[12px] text-muted">{hint}</span>}
      </span>
    </label>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 pb-0.5">
      <div className="min-w-0">
        <h1 className="text-[21px] font-bold tracking-tight text-foreground">{title}</h1>
        {subtitle && <p className="mt-0.5 text-[12px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 shrink-0">{actions}</div>}
    </header>
  );
}

export function Toolbar({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-end gap-2.5', className)}>{children}</div>
  );
}

/* Compact key/value pair used inside detail panels. */
export function KV({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wide text-muted">{k}</span>
      <span className="text-[13px]">{v}</span>
    </div>
  );
}
