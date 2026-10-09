/* The backend stamps UTC without a suffix, so parse defensively before
   rendering local time — exactly as the legacy views did. */
function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = /Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`;
  const d = new Date(normalized);
  return isNaN(d.getTime()) ? null : d;
}

export function fmtDT(value?: string | null): string {
  const d = parse(value);
  if (!d) return '—';
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function fmtDay(value?: string | null): string {
  const d = parse(value);
  if (!d) return '—';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/* Date only — used by the pipeline columns where the exact day matters but the
   clock time would just add noise (the sub-line carries the relative age). */
export function fmtDate(value?: string | null): string {
  const d = parse(value);
  if (!d) return '—';
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export function ago(value?: string | null): string {
  const d = parse(value);
  if (!d) return 'never';
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export function fmtDur(s?: number | null): string {
  if (s == null) return '—';
  return s >= 90 ? `${Math.round(s / 60)}m ${Math.round(s % 60)}s` : `${Math.round(s)}s`;
}

export function initials(name?: string | null): string {
  return String(name || '?')
    .split(' ')
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

const AVATAR_COLORS = ['#4F46E5', '#6063EE', '#7C3AED', '#0E7490', '#B45309', '#4D7C0F', '#BE185D', '#334155'];

export function avatarColor(name?: string | null): string {
  let h = 0;
  for (const ch of String(name ?? '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

export function pct(used: number, limit: number): number {
  return limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
}

export const nf = new Intl.NumberFormat();
