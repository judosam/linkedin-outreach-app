import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  Bell,
  Building2,
  CalendarClock,
  Terminal,
  ChevronLeft,
  ChevronRight,
  KeyRound,
  LayoutDashboard,
  ListFilter,
  LogOut,
  MessagesSquare,
  Moon,
  Play,
  Rocket,
  Search,
  Settings,
  Square,
  ShieldAlert,
  Sun,
  UserRound,
  X,
} from 'lucide-react';
import { cn, Button, IconButton, Pill } from '@/components/ui';
import { Modal } from '@/components/Modal';
import { LiveConsoleProvider, useLiveConsole } from '@/lib/console';
import { useAuth } from '@/lib/auth';
import { useJobs } from '@/lib/jobs';
import { useToast } from '@/lib/toast';
import { apiGet, apiPost } from '@/lib/api';
import { JOB_LABELS } from '@/lib/constants';
import { initials } from '@/lib/format';

interface NavItem {
  key: string;
  label: string;
  to: string;
  icon: ReactNode;
  adminOnly?: boolean;
}

const NAV: NavItem[] = [
  { key: 'dashboard', label: 'Dashboard', to: '/dashboard', icon: <LayoutDashboard size={18} aria-hidden /> },
  { key: 'accounts', label: 'Accounts', to: '/accounts', icon: <Building2 size={18} aria-hidden /> },
  { key: 'campaigns', label: 'Campaigns', to: '/campaigns', icon: <Rocket size={18} aria-hidden /> },
  { key: 'leads', label: 'Leads', to: '/leads', icon: <ListFilter size={18} aria-hidden /> },
  { key: 'threads', label: 'Threads & Replies', to: '/threads', icon: <MessagesSquare size={18} aria-hidden /> },
  { key: 'jobs', label: 'Scheduler', to: '/jobs', icon: <CalendarClock size={18} aria-hidden /> },
  { key: 'salesnav', label: 'Licences Manager', to: '/salesnav', icon: <KeyRound size={18} aria-hidden />, adminOnly: true },
  { key: 'settings', label: 'Settings', to: '/settings', icon: <Settings size={18} aria-hidden /> },
];

/* Both apps are hash-routed, so a legacy link keeps its deep-link semantics. */
export const legacyHref = (path: string) => `/legacy#${path}`;

export function AppShell({ children }: { children: ReactNode }) {
  return <LiveConsoleProvider><ShellContent>{children}</ShellContent></LiveConsoleProvider>;
}

function ShellContent({ children }: { children: ReactNode }) {
  const console = useLiveConsole();
  const { me, logout } = useAuth();
  const jobs = useJobs();
  const toast = useToast();
  const navigate = useNavigate();

  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('cm-rail') === 'collapsed');
  const [drawer, setDrawer] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  /* The live job console is a popup available from any page. */

  const [theme, setTheme] = useState<'light' | 'dark'>(
    () => (localStorage.getItem('cm-theme') as 'light' | 'dark') || 'light',
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('cm-theme', theme);
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', theme === 'dark' ? '#0b1418' : '#f4f6f7');
  }, [theme]);

  useEffect(() => {
    localStorage.setItem('cm-rail', collapsed ? 'collapsed' : 'expanded');
  }, [collapsed]);

  const nav = jobs.data?.nav ?? {};
  const live = jobs.data?.live ?? null;
  const running = live?.status === 'running' || (jobs.data?.running?.length ?? 0) > 0;

  const badges: Record<string, string> = {
    accounts: nav.accounts_active ? String(nav.accounts_active) : '',
    campaigns: nav.campaigns_active ? `${nav.campaigns_active} active` : '',
    threads: nav.unread_replies ? String(nav.unread_replies) : '',
    jobs: nav.scheduler_healthy === false ? 'Off' : '',
  };

  const visibleNav = NAV.filter((n) => {
    if (n.key === 'salesnav') {
      return me?.role === 'admin' || !!me?.can_manage_licenses;
    }
    return !n.adminOnly || me?.role === 'admin';
  });

  return (
    <div className="min-h-dvh bg-canvas text-ink">
      {/* ---------------- Sidebar ---------------- */}
      <aside
        id="app-rail"
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex flex-col bg-nav text-[var(--nav-text)]',
          'transition-[transform,width] duration-200 ease-out',
          collapsed ? 'lg:w-[76px]' : 'lg:w-[248px]',
          'w-[248px]',
          drawer ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
        )}
      >
        <div className="flex items-center gap-2.5 px-4 py-4">
          <img
            src="/static/campaign-manager.svg"
            alt=""
            className="h-9 w-9 shrink-0 rounded-control outline outline-1 -outline-offset-1 outline-white/10"
          />
          {!collapsed && (
            <span className="min-w-0">
              <span className="block truncate text-[15px] font-semibold text-white">Campaign Manager</span>
              <span className="block truncate text-[12px] text-[var(--nav-muted)]">Sales Nav Core · Ops v2.4</span>
            </span>
          )}
        </div>

        <nav className="scroll-y flex-1 px-2 py-2" aria-label="Main navigation">
          <ul className="flex flex-col gap-0.5">
            {visibleNav.map((item) => (
              <li key={item.key}>
                <NavLink
                  to={item.to}
                  onClick={() => setDrawer(false)}
                  title={collapsed ? item.label : undefined}
                  className={({ isActive }) =>
                    cn(
                      'group flex items-center gap-3 rounded-[10px] px-3 py-2 text-sm font-medium',
                      'transition-[background-color,color] duration-150 ease-out',
                      isActive
                        ? 'bg-[var(--nav-2)] text-white'
                        : 'text-[var(--nav-muted)] hover:bg-white/5 hover:text-white',
                      collapsed && 'lg:justify-center lg:px-0',
                    )
                  }
                >
                  <span className="shrink-0">{item.icon}</span>
                  {!collapsed && <span className="truncate">{item.label}</span>}
                  {!collapsed && badges[item.key] && (
                    <span className="ml-auto rounded-full bg-white/10 px-2 py-0.5 text-[11px] font-semibold text-white">
                      {badges[item.key]}
                    </span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="hidden px-3 pb-2 lg:block">
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className={cn(
              'flex w-full items-center gap-2 rounded-[10px] px-2 py-2 text-[13px] text-[var(--nav-muted)]',
              'transition-colors duration-150 ease-out hover:bg-white/5 hover:text-white',
              collapsed && 'justify-center',
            )}
          >
            {collapsed ? <ChevronRight size={18} aria-hidden /> : <ChevronLeft size={18} aria-hidden />}
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>

        <div className="relative border-t border-white/10 p-2.5">
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            className={cn(
              'flex w-full items-center gap-2.5 rounded-[10px] p-2 text-left',
              'transition-colors duration-150 ease-out hover:bg-white/5',
            )}
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--nav-2)] text-[12px] font-semibold text-white">
              {initials(me?.name || me?.user)}
            </span>
            {!collapsed && (
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium text-white">{me?.name || '—'}</span>
                <span className="block truncate text-[11px] text-[var(--nav-muted)]">
                  {me?.role === 'admin' ? 'Administrator' : 'Campaign manager'}
                </span>
              </span>
            )}
          </button>

          {menuOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} aria-hidden />
              <div
                role="menu"
                className="surface absolute bottom-[calc(100%-4px)] left-2 right-2 z-20 p-1.5 shadow-pop"
              >
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors duration-150 ease-out hover:bg-inset"
                  onClick={() => {
                    setMenuOpen(false);
                    setPwOpen(true);
                  }}
                >
                  <UserRound size={16} aria-hidden />
                  Change password
                </button>
                <hr className="my-1 border-line" />
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-crit transition-colors duration-150 ease-out hover:bg-[var(--crit-tint)]"
                  onClick={() => void logout()}
                >
                  <LogOut size={16} aria-hidden />
                  Log out
                </button>
              </div>
            </>
          )}
        </div>
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setDrawer(false)} aria-hidden />
      )}

      {/* ---------------- Main column ---------------- */}
      <div className={cn('flex min-h-dvh flex-col transition-[padding] duration-200 ease-out', collapsed ? 'lg:pl-[76px]' : 'lg:pl-[248px]')}>
        <header className="sticky top-0 z-20 flex items-center gap-2 border-b border-line bg-surface/85 px-3 py-2 backdrop-blur lg:px-6">
          <IconButton label="Toggle navigation" className="lg:hidden" onClick={() => setDrawer(true)}>
            <span className="flex flex-col gap-[3px]">
              <span className="h-[2px] w-[18px] rounded bg-current" />
              <span className="h-[2px] w-[18px] rounded bg-current" />
              <span className="h-[2px] w-[18px] rounded bg-current" />
            </span>
          </IconButton>

          <SearchBox />

          <button
            type="button"
            onClick={() => console.open()}
            title="Open live job console"
            className="ml-auto hidden items-center gap-1.5 rounded-lg border border-border/80 bg-surface px-2.5 py-1 text-[11.5px] font-medium text-ink2 shadow-2xs transition-colors duration-150 ease-out hover:border-primary/50 hover:bg-surface-2 hover:text-primary sm:inline-flex cursor-pointer"
          >
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                running ? 'animate-pulse bg-primary' : nav.scheduler_healthy === false ? 'bg-warn' : 'bg-ok',
              )}
              aria-hidden
            />
            {running ? `Running ${JOB_LABELS[live?.job ?? ''] ?? live?.job ?? ''}` : nav.scheduler_healthy === false ? 'Scheduler off' : 'Console'}
          </button>

          <IconButton
            label="Open live job console"
            size="sm"
            onClick={() => console.open()}
            className={cn('sm:hidden', running && 'text-primary')}
          >
            <Terminal size={14} aria-hidden />
          </IconButton>

          {running && (
            <Button
              size="sm"
              variant="danger"
              icon={<Square size={12} aria-hidden fill="currentColor" />}
              className="hidden sm:inline-flex"
              onClick={async () => {
                if (!window.confirm('Stop the currently running job?')) return;
                try {
                  await apiPost('/api/jobs/stop', {
                    run_id: typeof live?.run_id === 'number' ? live.run_id : null,
                    execution_id: typeof live?.execution_id === 'string' ? live.execution_id : null,
                  });
                  toast('Stop requested. Terminating worker…', 'warn');
                  void jobs.refresh();
                } catch (e) {
                  toast(e instanceof Error ? e.message : String(e), 'crit');
                }
              }}
            >
              Stop job
            </Button>
          )}

          <Button
            size="sm"
            variant="primary"
            icon={<Play size={13} aria-hidden />}
            onClick={() => navigate('/jobs')}
            className="hidden md:inline-flex"
          >
            Run job
          </Button>

          <NotificationsPopover />

          <IconButton
            size="sm"
            label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
          >
            {theme === 'dark' ? <Sun size={15} aria-hidden /> : <Moon size={15} aria-hidden />}
          </IconButton>
        </header>

        <main className="mx-auto w-full max-w-content flex-1 px-3 py-5 lg:px-6 lg:py-7">{children}</main>
      </div>

      <PasswordDialog open={pwOpen} onClose={() => setPwOpen(false)} />


    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Global search                                                              */
/* -------------------------------------------------------------------------- */

interface SearchHit {
  to: string;
  title: string;
  sub?: string;
}

function SearchBox() {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<{ label: string; items: SearchHit[] }[]>([]);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (q.trim().length < 2) {
      setGroups([]);
      setOpen(false);
      return;
    }
    const t = window.setTimeout(async () => {
      try {
        const r = await apiGet<{
          leads: { full_name: string; company: string | null }[];
          campaigns: { id: number; name: string; campaign_key: string }[];
          accounts: { name: string; status: string }[];
        }>(`/api/search?q=${encodeURIComponent(q.trim())}`);
        setGroups(
          [
            { label: 'Leads', items: r.leads.map((l) => ({ to: `#/leads?q=${encodeURIComponent(l.full_name)}`, title: l.full_name, sub: l.company ?? '' })) },
            { label: 'Campaigns', items: r.campaigns.map((c) => ({ to: `#/campaign/${c.id}`, title: c.name, sub: c.campaign_key })) },
            { label: 'Accounts', items: r.accounts.map((a) => ({ to: '#/accounts', title: a.name, sub: a.status })) },
          ].filter((g) => g.items.length),
        );
        setOpen(true);
      } catch {
        /* search is best-effort */
      }
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  return (
    <div ref={wrap} className="relative min-w-0 flex-1 max-w-lg">
      <Search size={16} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => groups.length && setOpen(true)}
        placeholder="Search campaigns, prospects, accounts…"
        aria-label="Global search"
        className={cn(
          'h-9 w-full rounded-control bg-inset pl-9 pr-3 text-[13px] text-ink placeholder:text-muted',
          'transition-shadow duration-150 ease-out focus:bg-surface',
        )}
      />
      {open && (
        <div className="surface scroll-y absolute left-0 right-0 top-[calc(100%+6px)] z-30 max-h-[60vh] p-1.5 shadow-pop">
          {groups.length ? (
            groups.map((g) => (
              <div key={g.label}>
                <div className="label px-2.5 pb-1 pt-2">{g.label}</div>
                {g.items.slice(0, 6).map((it, i) => (
                  <a
                    key={`${g.label}-${i}`}
                    href={it.to}
                    className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors duration-150 ease-out hover:bg-inset"
                  >
                    <span className="truncate">{it.title}</span>
                    {it.sub && <span className="ml-auto truncate text-[12px] text-muted">{it.sub}</span>}
                  </a>
                ))}
              </div>
            ))
          ) : (
            <div className="px-2.5 py-3 text-sm text-muted">No matches for &ldquo;{q}&rdquo;</div>
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Notifications                                                              */
/* -------------------------------------------------------------------------- */

function NotificationsPopover() {
  const jobs = useJobs();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const nav = jobs.data?.nav ?? {};
  const live = jobs.data?.live ?? null;

  const items = useMemo(() => {
    const out: { icon: ReactNode; text: string; to: string }[] = [];
    if ((nav.unread_replies ?? 0) > 0)
      out.push({ icon: <MessagesSquare size={16} aria-hidden />, text: `${nav.unread_replies} new replies (7d)`, to: '#/threads' });
    if (live?.status === 'running')
      out.push({ icon: <Play size={16} aria-hidden />, text: `Job running: ${JOB_LABELS[live.job ?? ''] ?? live.job}`, to: '#/jobs' });
    if (nav.scheduler_healthy === false)
      out.push({ icon: <ShieldAlert size={16} aria-hidden />, text: 'Scheduler is off', to: '#/jobs' });
    return out;
  }, [nav.unread_replies, nav.scheduler_healthy, live?.status, live?.job]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  return (
    <div ref={wrap} className="relative">
      <IconButton label="Notifications" onClick={() => setOpen((o) => !o)}>
        <span className="relative flex">
          <Bell size={18} aria-hidden />
          {items.length > 0 && (
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-crit" aria-hidden />
          )}
        </span>
      </IconButton>
      {open && (
        <div className="surface absolute right-0 top-[calc(100%+6px)] z-30 w-[280px] p-1.5 shadow-pop">
          <div className="flex items-center justify-between px-2.5 py-1.5">
            <span className="text-[13px] font-semibold">Notifications</span>
            <IconButton label="Dismiss notifications" size="xs" onClick={() => setOpen(false)}>
              <X size={14} aria-hidden />
            </IconButton>
          </div>
          {items.length ? (
            items.map((it, i) => (
              <a
                key={i}
                href={it.to}
                className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors duration-150 ease-out hover:bg-inset"
              >
                <span className="text-ink2">{it.icon}</span>
                <span>{it.text}</span>
              </a>
            ))
          ) : (
            <div className="px-2.5 py-3 text-sm text-muted">All quiet — no alerts.</div>
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Change password                                                            */
/* -------------------------------------------------------------------------- */

function PasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Change password"
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} isStatic>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="pw-form" disabled={busy} isStatic>
            {busy ? 'Working…' : 'Update password'}
          </Button>
        </>
      }
    >
      <form
        id="pw-form"
        className="flex flex-col gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          const next = String(f.get('next') || '');
          const confirm = String(f.get('confirm') || '');
          setError('');
          if (next !== confirm) {
            setError('New passwords do not match.');
            return;
          }
          setBusy(true);
          try {
            await apiPost('/api/me/password', {
              current_password: String(f.get('current') || ''),
              new_password: next,
            });
            toast('Password updated', 'ok');
            onClose();
          } catch (ex) {
            setError(ex instanceof Error ? ex.message : String(ex));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium">Current password</span>
          <input name="current" type="password" autoComplete="current-password" required className="cm-input" />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium">New password</span>
          <input name="next" type="password" autoComplete="new-password" minLength={8} required className="cm-input" />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium">Confirm new password</span>
          <input name="confirm" type="password" autoComplete="new-password" minLength={8} required className="cm-input" />
        </label>
        {error && (
          <p role="alert" className="text-[13px] text-crit">
            {error}
          </p>
        )}
        <p className="flex items-center gap-1.5 text-[12px] text-muted">
          <Pill tone="idle">Note</Pill>
          Changing your password signs out your other sessions on all devices.
        </p>
      </form>
    </Modal>
  );
}
