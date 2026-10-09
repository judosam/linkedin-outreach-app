import { useState } from 'react';
import { AlertTriangle, Shield, ShieldCheck, SlidersHorizontal, Trash2, UserPlus } from 'lucide-react';
import { Button, Card, EmptyState, ErrorState, Loading, cn } from '@/components/ui';
import { Field, Input, Select } from '@/components/form';
import { Modal } from '@/components/Modal';
import { apiDelete, apiGet, apiPost, apiPut } from '@/lib/api';
import { useAsync } from '@/lib/hooks';
import { useToast } from '@/lib/toast';
import { ago, initials } from '@/lib/format';

interface UserRow {
  id: number;
  username: string;
  display_name: string;
  role: string;
  active: boolean;
  can_manage_licenses?: boolean;
  created_at: string | null;
  last_login_at: string | null;
  is_you: boolean;
  allowed_campaign_ids: number[];
  allowed_account_ids: number[];
}

interface IdName {
  id: number;
  name: string;
}

const AVATAR_PALETTE = [
  'bg-emerald-500/20 text-emerald-500 dark:text-emerald-400 border border-emerald-500/30',
  'bg-purple-500/20 text-purple-500 dark:text-purple-400 border border-purple-500/30',
  'bg-rose-500/20 text-rose-500 dark:text-rose-400 border border-rose-500/30',
  'bg-indigo-500/20 text-indigo-500 dark:text-indigo-400 border border-indigo-500/30',
  'bg-blue-500/20 text-blue-500 dark:text-blue-400 border border-blue-500/30',
  'bg-amber-500/20 text-amber-500 dark:text-amber-400 border border-amber-500/30',
];

const PRESET_USER_AVATARS: Record<string, string> = {
  admin: 'bg-emerald-500/20 text-emerald-500 dark:text-emerald-400 border border-emerald-500/30',
  jane: 'bg-purple-500/20 text-purple-500 dark:text-purple-400 border border-purple-500/30',
  nandhini: 'bg-rose-500/20 text-rose-500 dark:text-rose-400 border border-rose-500/30',
  prabhu: 'bg-indigo-500/20 text-indigo-500 dark:text-indigo-400 border border-indigo-500/30',
  swathini: 'bg-blue-500/20 text-blue-500 dark:text-blue-400 border border-blue-500/30',
};

function getAvatarStyle(u: UserRow) {
  const key = u.username.toLowerCase();
  if (PRESET_USER_AVATARS[key]) return PRESET_USER_AVATARS[key];
  let hash = u.id * 19;
  const str = u.display_name || u.username;
  for (let i = 0; i < str.length; i++) hash = (hash << 5) - hash + str.charCodeAt(i);
  return AVATAR_PALETTE[Math.abs(hash) % AVATAR_PALETTE.length];
}

export default function Users(_props: { compact?: boolean } = {}) {
  const toast = useToast();
  const users = useAsync<{ users: UserRow[] }>(() => apiGet('/api/users'), []);
  const campaigns = useAsync<{ id: number; name: string }[]>(() => apiGet('/api/campaigns'), []);
  const accounts = useAsync<IdName[]>(() => apiGet('/api/accounts'), []);
  const [editing, setEditing] = useState<UserRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<UserRow | null>(null);

  const rows = users.data?.users ?? [];

  const remove = async (u: UserRow) => {
    setBusyId(u.id);
    try {
      await apiDelete(`/api/users/${u.id}`);
      toast('User deleted', 'ok');
      await users.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setBusyId(null);
    }
  };

  const toggleActive = async (u: UserRow) => {
    setBusyId(u.id);
    try {
      await apiPut(`/api/users/${u.id}`, { active: !u.active });
      toast(u.active ? 'User deactivated' : 'User reactivated', 'ok');
      await users.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {users.loading && !users.data ? (
        <Loading />
      ) : users.error ? (
        <ErrorState message={users.error} onRetry={users.reload} />
      ) : (
        <Card className="min-w-0 p-4">
          <div className="flex items-center justify-between gap-3 border-b border-line pb-3">
            <div>
              <h2 className="text-[16px] font-bold tracking-tight text-foreground">Users &amp; Access</h2>
              <p className="text-[12px] text-muted">Logins with per-user campaign, account &amp; licences permissions</p>
            </div>
            <Button
              variant="primary"
              size="sm"
              icon={<UserPlus size={14} aria-hidden />}
              onClick={() => setCreating(true)}
              className="rounded-lg font-medium text-xs px-3 py-1.5"
              isStatic
            >
              Add user
            </Button>
          </div>

          {rows.length ? (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] border-collapse text-[12.5px]">
                  <thead>
                    <tr className="border-b border-line/70 text-left text-[11px] font-semibold uppercase tracking-wider text-muted">
                      <th className="py-2.5 px-3">USER</th>
                      <th className="py-2.5 px-3">ROLE &amp; ACCESS</th>
                      <th className="py-2.5 px-3">STATUS</th>
                      <th className="py-2.5 px-3">LAST LOGIN</th>
                      <th className="py-2.5 px-3 text-right">ACTIONS</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/60">
                    {rows.map((u) => {
                      const avatarStyle = getAvatarStyle(u);
                      const relativeLogin = u.last_login_at ? ago(u.last_login_at) : 'Never';
                      return (
                        <tr key={u.id} className="group transition-colors hover:bg-surface-2/40">
                          {/* USER */}
                          <td className="py-2.5 px-3">
                            <div className="flex items-center gap-2.5">
                              <div
                                className={cn(
                                  'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[12px] font-bold shadow-sm',
                                  avatarStyle,
                                )}
                              >
                                {initials(u.display_name || u.username)}
                              </div>
                              <div className="min-w-0">
                                <div className="truncate font-semibold text-[13px] text-foreground">
                                  {u.display_name || u.username}
                                </div>
                                <div className="truncate text-[11.5px] text-muted">
                                  {u.username}
                                  {u.is_you && <span className="text-muted"> · you</span>}
                                </div>
                              </div>
                            </div>
                          </td>

                          {/* ROLE & ACCESS */}
                          <td className="py-2.5 px-3">
                            <div className="flex flex-col gap-0.5">
                              <div className="flex flex-wrap items-center gap-1.5">
                                {u.role === 'admin' ? (
                                  <span className="inline-flex items-center gap-1 rounded-full border border-blue-500/30 bg-blue-500/10 px-2.5 py-0.5 text-[11px] font-medium text-blue-400">
                                    <Shield size={11} className="shrink-0" /> Administrator
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 rounded-full border border-border/80 bg-surface-2/90 px-2.5 py-0.5 text-[11px] font-medium text-foreground/80">
                                    Campaign manager
                                  </span>
                                )}
                                {u.role !== 'admin' && u.can_manage_licenses && (
                                  <span className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10.5px] font-semibold text-primary">
                                    Licences Manager
                                  </span>
                                )}
                              </div>
                              <div className="text-[11.5px] text-muted">
                                {u.role === 'admin'
                                  ? 'All campaigns & accounts'
                                  : `${u.allowed_campaign_ids.length} campaigns · ${u.allowed_account_ids.length} accounts`}
                              </div>
                            </div>
                          </td>

                          {/* STATUS */}
                          <td className="py-2.5 px-3">
                            {u.active ? (
                              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[11.5px] font-medium text-emerald-500 dark:text-emerald-400">
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400" />
                                Active
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5 rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-0.5 text-[11.5px] font-medium text-rose-500 dark:text-rose-400">
                                <span className="h-1.5 w-1.5 rounded-full bg-rose-500 dark:bg-rose-400" />
                                Deactivated
                              </span>
                            )}
                          </td>

                          {/* LAST LOGIN */}
                          <td className="py-2.5 px-3 text-[12.5px] font-medium text-foreground/90">
                            {relativeLogin}
                          </td>

                          {/* ACTIONS */}
                          <td className="py-2.5 px-3 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              <button
                                type="button"
                                onClick={() => setEditing(u)}
                                className="inline-flex h-7 items-center gap-1 text-[11.5px] font-medium text-muted transition-colors hover:text-foreground px-2 rounded-lg border border-border/80 bg-surface hover:bg-surface-2 shadow-2xs cursor-pointer"
                              >
                                <SlidersHorizontal size={12} aria-hidden />
                                Edit
                              </button>
                              {u.is_you ? (
                                <span className="text-[11.5px] text-muted ml-2">you</span>
                              ) : (
                                <>
                                  <button
                                    type="button"
                                    disabled={busyId === u.id}
                                    onClick={() => void toggleActive(u)}
                                    className="inline-flex h-7 items-center rounded-lg border border-border/80 bg-surface hover:bg-surface-2 px-2.5 text-[11.5px] font-medium text-foreground transition-all shadow-2xs active:scale-95 disabled:opacity-50 cursor-pointer"
                                  >
                                    {u.active ? 'Deactivate' : 'Activate'}
                                  </button>
                                  <button
                                    type="button"
                                    disabled={busyId === u.id}
                                    onClick={() => setConfirmDelete(u)}
                                    className="inline-flex h-7 w-7 items-center justify-center text-muted hover:text-crit transition-colors rounded-lg border border-border/80 bg-surface hover:bg-crit-tint/30 shadow-2xs disabled:opacity-50 cursor-pointer"
                                    aria-label={`Delete ${u.username}`}
                                  >
                                    <Trash2 size={12} aria-hidden />
                                  </button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 border-t border-line/60 pt-3">
                <p className="text-[12px] text-muted leading-relaxed">
                  Every user signs in with their own credentials and can change their password from the sidebar menu. Restrict a user to specific campaigns/accounts from Edit — empty means no access. Administrators have full access. Deactivating or resetting a password signs that user out everywhere.
                </p>
              </div>
            </>
          ) : (
            <div className="py-6">
              <EmptyState
                icon={<ShieldCheck size={22} aria-hidden />}
                title="No users yet"
                body="Create a user to grant access."
              />
            </div>
          )}
        </Card>
      )}

      {/* Delete User Confirmation Modal */}
      <Modal
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        title="Delete User"
      >
        {confirmDelete && (
          <div className="flex flex-col gap-4">
            <div className="flex items-start gap-3 rounded-xl border border-rose-500/25 bg-rose-500/10 p-3.5">
              <AlertTriangle className="h-5 w-5 shrink-0 text-rose-500" />
              <div className="text-[13px] text-foreground/90">
                <p className="font-semibold text-rose-500 dark:text-rose-400">
                  Are you sure you want to delete user "{confirmDelete.display_name || confirmDelete.username}"?
                </p>
                <p className="mt-1 text-[12px] text-muted">
                  Their access will be immediately revoked and historical logs become admin-only.
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 pt-2">
              <Button variant="secondary" onClick={() => setConfirmDelete(null)} isStatic>
                Cancel
              </Button>
              <Button
                variant="danger"
                disabled={busyId === confirmDelete.id}
                onClick={async () => {
                  const targetUser = confirmDelete;
                  setConfirmDelete(null);
                  await remove(targetUser);
                }}
                isStatic
              >
                Delete User
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <UserDialog
        open={creating || !!editing}
        user={editing}
        campaigns={campaigns.data ?? []}
        accounts={accounts.data ?? []}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
        onSaved={() => {
          setCreating(false);
          setEditing(null);
          void users.reload();
        }}
      />
    </div>
  );
}

function UserDialog({
  open,
  user,
  campaigns,
  accounts,
  onClose,
  onSaved,
}: {
  open: boolean;
  user: UserRow | null;
  campaigns: { id: number; name: string }[];
  accounts: IdName[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [seededFor, setSeededFor] = useState<number | 'new' | null>(null);
  const [form, setForm] = useState({
    username: '',
    password: '',
    display_name: '',
    role: 'campaign_manager',
    can_manage_licenses: false,
  });
  const [campaignIds, setCampaignIds] = useState<number[]>([]);
  const [accountIds, setAccountIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);

  const target = user?.id ?? 'new';
  if (open && seededFor !== target) {
    setSeededFor(target);
    setForm({
      username: user?.username ?? '',
      password: '',
      display_name: user?.display_name ?? '',
      role: user?.role ?? 'campaign_manager',
      can_manage_licenses: user?.can_manage_licenses ?? false,
    });
    setCampaignIds(user?.allowed_campaign_ids ?? []);
    setAccountIds(user?.allowed_account_ids ?? []);
  }
  if (!open && seededFor !== null) setSeededFor(null);

  const isAdminRole = form.role === 'admin';

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={user ? `Edit ${user.username}` : 'New user'}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} isStatic>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="user-form" disabled={busy} isStatic>
            {busy ? 'Saving…' : user ? 'Save user' : 'Create user'}
          </Button>
        </>
      }
    >
      <form
        id="user-form"
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            if (user) {
              await apiPut(`/api/users/${user.id}`, {
                display_name: form.display_name.trim(),
                role: form.role,
                can_manage_licenses: isAdminRole ? true : form.can_manage_licenses,
                allowed_campaign_ids: campaignIds,
                allowed_account_ids: accountIds,
                ...(form.password ? { password: form.password } : {}),
              });
            } else {
              await apiPost('/api/users', {
                username: form.username.trim(),
                password: form.password,
                display_name: form.display_name.trim(),
                role: form.role,
                can_manage_licenses: isAdminRole ? true : form.can_manage_licenses,
                allowed_campaign_ids: campaignIds,
                allowed_account_ids: accountIds,
              });
            }
            toast(user ? 'User saved' : 'User created', 'ok');
            onSaved();
          } catch (ex) {
            toast(ex instanceof Error ? ex.message : String(ex), 'crit');
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Username">
            <Input required disabled={!!user} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          </Field>
          <Field label="Display name">
            <Input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col">
            <Field label={user ? 'Reset password' : 'Password'}>
              <Input
                type="password"
                autoComplete="new-password"
                minLength={user ? undefined : 8}
                required={!user}
                placeholder={user ? '••••••••' : 'Min 8 characters'}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </Field>
            <p className="mt-1 text-[11.5px] text-muted">
              {user ? 'Leave blank to keep current password.' : 'Minimum 8 characters.'}
            </p>
          </div>
          <Field label="Role">
            <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="campaign_manager">Campaign manager</option>
              <option value="admin">Administrator</option>
            </Select>
          </Field>
        </div>

        <div className="rounded-xl border border-line bg-surface-2/40 p-3.5 flex items-start gap-3">
          <input
            type="checkbox"
            id="can-manage-licenses"
            checked={isAdminRole || form.can_manage_licenses}
            disabled={isAdminRole}
            onChange={(e) => setForm({ ...form, can_manage_licenses: e.target.checked })}
            className="mt-0.5 h-4 w-4 rounded border-border text-primary focus:ring-primary cursor-pointer disabled:opacity-50"
          />
          <label htmlFor="can-manage-licenses" className="flex flex-col cursor-pointer select-none">
            <span className="text-[13px] font-semibold text-foreground">
              Licences Manager access {isAdminRole && <span className="text-[11px] font-normal text-muted">(Granted by Admin role)</span>}
            </span>
            <span className="text-[11.5px] text-muted">
              Allow user to view and manage enterprise Sales Navigator licences and seat assignments.
            </span>
          </label>
        </div>

        {isAdminRole ? (
          <p className="rounded-[12px] bg-inset p-3 text-[13px] text-muted">
            Administrators see every campaign and account. No explicit selections are stored.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <fieldset className="rounded-[12px] bg-inset p-3">
              <legend className="px-1 text-[13px] font-medium">Campaigns</legend>
              <div className="scroll-y flex max-h-[180px] flex-col gap-1.5">
                {campaigns.length ? (
                  campaigns.map((c) => (
                    <label key={c.id} className="flex items-center gap-2 text-[13px]">
                      <input
                        type="checkbox"
                        className="h-4 w-4"
                        checked={campaignIds.includes(c.id)}
                        onChange={(e) =>
                          setCampaignIds((prev) => (e.target.checked ? [...prev, c.id] : prev.filter((x) => x !== c.id)))
                        }
                      />
                      <span className="truncate">{c.name}</span>
                    </label>
                  ))
                ) : (
                  <p className="text-[13px] text-muted">No campaigns yet.</p>
                )}
              </div>
            </fieldset>
            <fieldset className="rounded-[12px] bg-inset p-3">
              <legend className="px-1 text-[13px] font-medium">Accounts</legend>
              <div className="scroll-y flex max-h-[180px] flex-col gap-1.5">
                {accounts.length ? (
                  accounts.map((a) => (
                    <label key={a.id} className="flex items-center gap-2 text-[13px]">
                      <input
                        type="checkbox"
                        className="h-4 w-4"
                        checked={accountIds.includes(a.id)}
                        onChange={(e) =>
                          setAccountIds((prev) => (e.target.checked ? [...prev, a.id] : prev.filter((x) => x !== a.id)))
                        }
                      />
                      <span className="truncate">{a.name}</span>
                    </label>
                  ))
                ) : (
                  <p className="text-[13px] text-muted">No accounts yet.</p>
                )}
              </div>
            </fieldset>
          </div>
        )}
      </form>
    </Modal>
  );
}
