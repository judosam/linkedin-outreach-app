import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react';
import type { Tone } from '@/lib/constants';
import { initials } from '@/lib/format';

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}

/* -------------------------------------------------------------------------- */
/* Button — interruptible CSS transitions, tactile 0.96 press scale           */
/* -------------------------------------------------------------------------- */

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success';
type Size = 'sm' | 'md';

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-gradient-to-b from-primary to-[color-mix(in_srgb,var(--primary)_88%,black)] text-primary-ink shadow-sm hover:brightness-105 hover:shadow active:scale-[0.98] transition-all',
  secondary:
    'border border-border/80 bg-surface text-ink shadow-xs hover:border-primary/40 hover:bg-primary-tint/20 hover:text-primary active:scale-[0.98] transition-all',
  ghost:
    'bg-transparent text-ink2 hover:bg-inset hover:text-ink active:scale-[0.98] transition-all',
  danger:
    'bg-gradient-to-b from-crit to-[color-mix(in_srgb,var(--crit)_88%,black)] text-white shadow-sm hover:brightness-105 hover:shadow active:scale-[0.98] transition-all',
  success:
    'bg-gradient-to-b from-ok to-[color-mix(in_srgb,var(--ok)_88%,black)] text-white shadow-sm hover:brightness-105 hover:shadow active:scale-[0.98] transition-all',
};

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-[13px] gap-1.5',
  md: 'h-10 px-4 text-sm gap-2',
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  iconRight?: ReactNode;
  block?: boolean;
  /** Disable the press-scale where motion would distract (dense toolbars). */
  isStatic?: boolean;
}

export function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  iconRight,
  block,
  isStatic,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        'inline-flex items-center justify-center rounded-control font-medium whitespace-nowrap',
        'transition-[background-color,box-shadow,color,filter,transform] duration-150 ease-out',
        'disabled:opacity-50 disabled:pointer-events-none',
        !isStatic && 'active:not-disabled:scale-[0.96]',
        VARIANTS[variant],
        SIZES[size],
        block && 'w-full',
        className,
      )}
      {...props}
    >
      {icon}
      {children}
      {iconRight}
    </button>
  );
}

/* Size is a prop, never a className: cn() is a plain join, so an `h-7 w-7`
   passed in here would lose to the base `h-9 w-9` (same specificity — the one
   later in Tailwind's output wins, which is not the order you wrote them). */
type IconSize = 'xs' | 'sm' | 'md';

const ICON_SIZES: Record<IconSize, string> = {
  xs: 'h-6 w-6',
  sm: 'h-8 w-8',
  md: 'h-9 w-9',
};

export function IconButton({
  label,
  size = 'md',
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; size?: IconSize }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex items-center justify-center rounded-lg border border-border/70 bg-surface text-ink2 shadow-xs',
        ICON_SIZES[size],
        'transition-all duration-150 ease-out active:not-disabled:scale-[0.95]',
        'hover:border-primary/40 hover:bg-primary-tint/30 hover:text-primary disabled:opacity-50 disabled:pointer-events-none',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* Surfaces                                                                   */
/* -------------------------------------------------------------------------- */

export function Card({
  className,
  children,
  as: Tag = 'section',
  onClick,
}: {
  className?: string;
  children: ReactNode;
  as?: 'section' | 'div' | 'article';
  onClick?: (e: React.MouseEvent) => void;
}) {
  return <Tag onClick={onClick} className={cn('surface', className)}>{children}</Tag>;
}

/* -------------------------------------------------------------------------- */
/* Pill — colour never carries meaning alone; label always present            */
/* -------------------------------------------------------------------------- */

const TONE_STYLE: Record<Tone, string> = {
  ok: 'text-ok bg-[var(--ok-tint)]',
  warn: 'text-warn bg-[var(--warn-tint)]',
  crit: 'text-crit bg-[var(--crit-tint)]',
  info: 'text-info bg-[var(--info-tint)]',
  primary: 'text-primary bg-primary-tint',
  idle: 'text-muted bg-inset',
};

const DOT_STYLE: Record<Tone, string> = {
  ok: 'bg-ok',
  warn: 'bg-warn',
  crit: 'bg-crit',
  info: 'bg-info',
  primary: 'bg-primary',
  idle: 'bg-muted',
};

export function Pill({
  tone = 'idle',
  children,
  dot = false,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12px] font-medium whitespace-nowrap',
        TONE_STYLE[tone],
        className,
      )}
    >
      {dot && <span className={cn('h-1.5 w-1.5 rounded-full', DOT_STYLE[tone])} aria-hidden="true" />}
      {children}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Progress — the fill colour is redundant with the printed numeric value     */
/* -------------------------------------------------------------------------- */

export function Progress({
  value,
  limit,
  tone,
  className,
}: {
  value: number;
  limit: number;
  tone?: Tone;
  className?: string;
}) {
  const p = limit > 0 ? Math.min(100, Math.round((value / limit) * 100)) : 0;
  const resolved: Tone = tone ?? (p >= 100 ? 'crit' : p >= 80 ? 'warn' : 'primary');
  return (
    <div
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-inset', className)}
      role="progressbar"
      aria-valuenow={p}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn('h-full rounded-full transition-[width] duration-500 ease-out', DOT_STYLE[resolved])}
        style={{ width: `${p}%` }}
      />
    </div>
  );
}

/* Compact inline gauge for dense table rows — a fixed-width bar that reads at a
   glance without the height of a full Progress block. */
export function Meter({
  value,
  limit,
  width = 48,
  className,
}: {
  value: number;
  limit: number;
  width?: number;
  className?: string;
}) {
  const p = limit > 0 ? Math.min(100, Math.round((value / limit) * 100)) : 0;
  const tone = p >= 100 ? 'bg-crit' : p >= 80 ? 'bg-warn' : 'bg-primary';
  return (
    <span
      className={cn(
        'inline-block h-1.5 shrink-0 overflow-hidden rounded-full bg-inset align-middle',
        className,
      )}
      style={{ width }}
      role="progressbar"
      aria-valuenow={p}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <span className={cn('block h-full rounded-full', tone)} style={{ width: `${p}%` }} />
    </span>
  );
}

/* Radial ratio — a bar would be too wide inside a dense table cell, and the
   numeric label sits inside the ring so the value is never colour-only. */
export function Ring({
  value,
  limit,
  size = 40,
  stroke = 4,
  children,
}: {
  value: number;
  limit: number;
  size?: number;
  stroke?: number;
  children?: ReactNode;
}) {
  const p = limit > 0 ? Math.min(100, (value / limit) * 100) : 0;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const stroke_ = p >= 100 ? 'var(--crit)' : p >= 80 ? 'var(--warn)' : 'var(--primary)';
  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${Math.round(p)} percent`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--inset)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={stroke_}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c - (c * p) / 100}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          className="transition-[stroke-dashoffset] duration-500 ease-out"
        />
      </svg>
      {children && (
        <span className="num absolute inset-0 flex items-center justify-center text-[11px] font-semibold">
          {children}
        </span>
      )}
    </span>
  );
}

/* Initials avatar — the same visual identity used in the sidebar, so an account
   is recognisable before its name is read. */
export function Avatar({
  name,
  size = 'md',
  className,
}: {
  name: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  const dims = { sm: 'h-6 w-6 text-[10px]', md: 'h-8 w-8 text-[11.5px]', lg: 'h-10 w-10 text-[13px]' }[size];
  return (
    <span
      aria-hidden
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full bg-primary-tint font-semibold text-primary',
        dims,
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}

/* Sortable table header. `aria-sort` is carried on the th itself because that is
   where assistive tech looks for it — the button is only the hit target. */
export function SortHeader({
  label,
  active,
  direction,
  onClick,
  align = 'left',
  className,
  filter,
  sortLabel,
}: {
  label: string;
  sortLabel?: string;
  filter?: ReactNode;
  active: boolean;
  direction: 'asc' | 'desc' | null;
  onClick: () => void;
  align?: 'left' | 'right';
  className?: string;
}) {
  return (
    <th
      className={cn('sortable', align === 'right' && 'right', className)}
      aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <span className="th-inner">
        <button
          className="th-sort"
          type="button"
          onClick={onClick}
          title={`Sort by ${sortLabel || label}`}
          aria-label={`Sort by ${sortLabel || label}`}
        >
          {label}
          {active ? (
            direction === 'asc' ? (
              <ArrowUp size={11} aria-hidden />
            ) : (
              <ArrowDown size={11} aria-hidden />
            )
          ) : (
            <ChevronsUpDown size={11} aria-hidden />
          )}
        </button>
        {filter}
      </span>
    </th>
  );
}

/* -------------------------------------------------------------------------- */
/* States                                                                     */
/* -------------------------------------------------------------------------- */

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-block h-4 w-4 animate-spin rounded-full border-2 border-lineStrong border-t-primary',
        className,
      )}
      aria-hidden="true"
    />
  );
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 px-1 py-10 text-muted" role="status">
      <Spinner />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="surface flex flex-col items-start gap-3 p-6">
      <div>
        <h3 className="text-base">Couldn&rsquo;t load this view</h3>
        <p className="mt-1 max-w-[60ch] text-ink2">{message}</p>
      </div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      {icon && <div className="text-muted">{icon}</div>}
      <p className="font-medium">{title}</p>
      <p className="max-w-[46ch] text-[13px] text-muted">{body}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
