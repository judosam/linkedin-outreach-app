import { useState } from 'react';
import { ArrowRight, Radar, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui';
import { useAuth } from '@/lib/auth';

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.05fr_0.95fr]">
      {/* Identity panel */}
      <div className="relative hidden flex-col justify-between overflow-hidden bg-nav p-10 text-[var(--nav-text)] lg:flex">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.16]"
          style={{
            backgroundImage:
              'radial-gradient(760px circle at 12% 8%, var(--primary) 0%, transparent 62%), radial-gradient(560px circle at 88% 96%, #2a5e6b 0%, transparent 60%)',
          }}
          aria-hidden
        />
        <div className="relative flex items-center gap-2.5">
          <img src="/static/campaign-manager.svg" alt="" className="h-9 w-9 rounded-control" />
          <span>
            <span className="block text-[15px] font-semibold text-white">Campaign Manager</span>
            <span className="block text-[12px] text-[var(--nav-muted)]">Sales Nav Core · Ops v2.4</span>
          </span>
        </div>

        <div className="relative max-w-[34ch]">
          <h1 className="text-[38px] font-semibold leading-[1.1] text-white text-balance">
            Mission control for your Sales&nbsp;Nav outreach fleet.
          </h1>
          <p className="mt-4 text-[14px] leading-relaxed text-[var(--nav-muted)]">
            Multi-account outreach with quota balancing, follow-up sequencing, reply detection and
            run-level audit logs.
          </p>
        </div>

        <ul className="relative flex flex-col gap-3 text-[13px] text-[var(--nav-muted)]">
          <li className="flex items-center gap-2.5">
            <Radar size={16} aria-hidden className="text-primary" />
            Live worker status and per-run console output
          </li>
          <li className="flex items-center gap-2.5">
            <ShieldCheck size={16} aria-hidden className="text-primary" />
            Every outbound action recorded against the lead
          </li>
        </ul>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center p-6">
        <form
          className="surface w-full max-w-[400px] p-7"
          onSubmit={async (e) => {
            e.preventDefault();
            setError('');
            setBusy(true);
            try {
              await login(username, password);
            } catch (ex) {
              const msg = ex instanceof Error ? ex.message : String(ex);
              setError(
                msg.includes('Incorrect')
                  ? 'Incorrect username or password.'
                  : msg.includes('deactivated')
                    ? msg
                    : 'Login failed — is the server running?',
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="mb-6 flex items-center gap-2.5 lg:hidden">
            <img src="/static/campaign-manager.svg" alt="" className="h-9 w-9 rounded-control" />
            <span className="text-[15px] font-semibold">Campaign Manager</span>
          </div>

          <h2 className="text-[22px]">Sign in</h2>
          <p className="mt-1 text-[13px] text-muted">Use your personal credentials to open the command center.</p>

          <div className="mt-6 flex flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium">Username</span>
              <input
                className="cm-input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                name="username"
                autoComplete="username"
                required
                autoFocus
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium">Password</span>
              <input
                className="cm-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>

            {error && (
              <p role="alert" className="text-[13px] text-crit">
                {error}
              </p>
            )}

            <Button
              type="submit"
              variant="primary"
              block
              disabled={busy}
              isStatic
              iconRight={<ArrowRight size={16} aria-hidden />}
            >
              {busy ? 'Signing in…' : 'Sign in'}
            </Button>
            <p>
              <a
                href="/legacy"
                className="text-[12px] text-muted underline decoration-line underline-offset-4 hover:text-ink"
              >
                Open the classic interface
              </a>
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}
