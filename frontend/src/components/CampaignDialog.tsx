import { useEffect, useRef, useState } from 'react';
import {
  Calendar,
  Check,
  ChevronDown,
  Clock,
  FileText,
  Info,
  MessageSquare,
  Pause,
  Play,
  Plus,
  Search,
  Users,
  X,
} from 'lucide-react';
import { Button, IconButton, Pill, cn } from '@/components/ui';
import { Field, Input, Select, Textarea } from '@/components/form';
import { Modal } from '@/components/Modal';
import { apiGet, apiPost, apiPut } from '@/lib/api';
import { useToast } from '@/lib/toast';

export interface CampaignListItem {
  id: number;
  campaign_key: string;
  name: string;
  status: string;
  accounts: {
    account_id: number;
    account_name: string;
    invite_limit: number;
    inmail_limit: number;
    message_limit: number;
    calendar_url?: string | null;
  }[];
  leads: number;
  contacted: number;
  replied: number;
  reply_rate: number;
}

export interface AccountOption {
  id: number;
  name: string;
  status: string;
}

interface CampaignDetailData {
  id: number;
  campaign_key: string;
  name: string;
  status: string;
  invite_text: string;
  invite_track: string[];
  inmail_subject: string;
  inmail_text: string;
  inmail_track: { subject?: string; body?: string }[];
  accounts: {
    account_id: number;
    account_name?: string;
    order_index: number;
    invite_limit: number;
    inmail_limit: number;
    message_limit: number;
    calendar_url?: string | null;
  }[];
  invite_fu_days?: number[];
  inmail_fu_days?: number[];
}

export interface AssignedAccountSlot {
  uid: string;
  account_id: number | null;
  invite: number;
  inmail: number;
  messages: number;
  calendar_url: string;
}

const AVATAR_COLORS = [
  'bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30',
  'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  'bg-purple-500/15 text-purple-600 dark:text-purple-400 border-purple-500/30',
  'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
  'bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 border-indigo-500/30',
  'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30',
];

function getAvatarStyle(id: number) {
  return AVATAR_COLORS[Math.abs(id) % AVATAR_COLORS.length];
}

function getInitials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '—';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function AccountSelectDropdown({
  accounts,
  assignedSlots,
  currentSlotUid,
  selectedAccountId,
  onSelect,
}: {
  accounts: AccountOption[];
  assignedSlots: AssignedAccountSlot[];
  currentSlotUid: string;
  selectedAccountId: number | null;
  onSelect: (accountId: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const chosenAccount = selectedAccountId != null ? accounts.find((a) => a.id === selectedAccountId) : null;

  const filtered = accounts.filter((a) =>
    a.name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="relative flex-1 max-w-md" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          'flex h-9 w-full items-center justify-between gap-2 rounded-lg border bg-white dark:bg-[#111b2f] px-2.5 text-left text-[13px] shadow-2xs transition-all cursor-pointer',
          open
            ? 'border-primary ring-2 ring-primary/15'
            : 'border-border/90 hover:border-primary/50',
        )}
        aria-expanded={open}
      >
        {chosenAccount ? (
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <span
              className={cn(
                'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[10.5px] font-bold shadow-2xs',
                getAvatarStyle(chosenAccount.id),
              )}
            >
              {getInitials(chosenAccount.name)}
            </span>
            <span className="font-semibold text-foreground truncate text-[13px]">
              {chosenAccount.name}
            </span>
            <Pill tone={chosenAccount.status === 'active' ? 'ok' : chosenAccount.status === 'paused' ? 'idle' : 'crit'} dot>
              {chosenAccount.status.replace(/_/g, ' ')}
            </Pill>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-muted">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-dashed border-border bg-slate-50 dark:bg-slate-800 text-muted/60">
              <Users size={12} />
            </span>
            <span className="text-[13px]">Select an account…</span>
          </div>
        )}
        <ChevronDown
          size={15}
          className={cn('text-muted transition-transform shrink-0 ml-1', open && 'rotate-180')}
          aria-hidden
        />
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1.5 w-full min-w-[290px] max-w-sm rounded-xl border border-lineStrong/80 bg-white dark:bg-[#111b2f] p-1.5 shadow-2xl z-50 ring-1 ring-black/5">
          {accounts.length > 5 && (
            <div className="relative mb-1.5">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search accounts…"
                className="h-8 w-full rounded-md border border-border bg-slate-50 dark:bg-slate-800/80 pl-7 pr-2.5 text-[12px] text-foreground placeholder:text-muted focus:border-primary focus:outline-hidden"
                autoFocus
              />
            </div>
          )}

          <div className="max-h-56 overflow-y-auto flex flex-col gap-0.5">
            {filtered.length === 0 ? (
              <p className="py-3 text-center text-[12px] text-muted">No accounts found</p>
            ) : (
              filtered.map((acc) => {
                const usedElsewhere = assignedSlots.some(
                  (s) => s.uid !== currentSlotUid && s.account_id === acc.id,
                );
                const isSelected = selectedAccountId === acc.id;

                return (
                  <button
                    key={acc.id}
                    type="button"
                    disabled={usedElsewhere}
                    onClick={() => {
                      onSelect(acc.id);
                      setOpen(false);
                      setSearch('');
                    }}
                    className={cn(
                      'flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition-colors',
                      usedElsewhere
                        ? 'opacity-40 cursor-not-allowed bg-transparent'
                        : isSelected
                          ? 'bg-primary-tint/50 text-primary font-medium cursor-pointer'
                          : 'hover:bg-slate-100 dark:hover:bg-slate-800/80 text-foreground cursor-pointer',
                    )}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className={cn(
                          'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold',
                          getAvatarStyle(acc.id),
                        )}
                      >
                        {getInitials(acc.name)}
                      </span>
                      <span className="truncate font-medium">{acc.name}</span>
                      <Pill tone={acc.status === 'active' ? 'ok' : acc.status === 'paused' ? 'idle' : 'crit'} dot>
                        {acc.status.replace(/_/g, ' ')}
                      </Pill>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0 ml-2">
                      {usedElsewhere && (
                        <span className="text-[10.5px] text-muted italic">Assigned</span>
                      )}
                      {isSelected && <Check size={14} className="text-primary" />}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

type MsgTab = 'invite' | 'invite-fu' | 'inmail' | 'inmail-fu';
const MSG_TABS: [MsgTab, string][] = [
  ['invite', 'Connection Invite'],
  ['invite-fu', 'Invite Follow-ups'],
  ['inmail', 'InMail'],
  ['inmail-fu', 'InMail Follow-ups'],
];

const inviteStageLabel = (i: number, days: number[]) =>
  i === 0
    ? 'After acceptance message (sent as soon as they accept)'
    : `Follow-up ${i} (+${days[i - 1] ?? 0} days after previous stage)`;

const FU_HINT =
  'Sent after the delay set in Follow-up timing (default +3/+5/+7 days). Empty stages are automatically skipped.';

export function CampaignDialog({
  open,
  editId,
  source,
  accounts,
  onClose,
  onSaved,
  initialTab,
  fuDays: _fuDays = { invite: [3, 5, 7], inmail: [3, 5, 7] },
}: {
  open: boolean;
  editId?: number | null;
  source?: CampaignListItem | null;
  accounts: AccountOption[];
  onClose: () => void;
  onSaved: () => void | Promise<void>;
  initialTab?: 'details' | 'messages' | 'accounts' | 'timing';
  fuDays?: { invite: number[]; inmail: number[] };
}) {
  const toast = useToast();
  const [name, setName] = useState('');
  const [key, setKey] = useState('');
  const [status, setStatus] = useState('active');
  const [inviteText, setInviteText] = useState('');
  const [track, setTrack] = useState<string[]>(['', '', '', '']); // [0]=after-accept, [1..3]=FU
  const [inmailSubject, setInmailSubject] = useState('');
  const [inmailText, setInmailText] = useState('');
  const [inmailTrack, setInmailTrack] = useState<{ subject: string; body: string }[]>([
    { subject: '', body: '' },
    { subject: '', body: '' },
    { subject: '', body: '' },
  ]);
  const [assigned, setAssigned] = useState<AssignedAccountSlot[]>([]);
  const [inviteFuDays, setInviteFuDays] = useState<[number, number, number]>([3, 5, 7]);
  const [inmailFuDays, setInmailFuDays] = useState<[number, number, number]>([3, 5, 7]);
  const [busy, setBusy] = useState(false);
  const [loadingEdit, setLoadingEdit] = useState(false);
  const [seeded, setSeeded] = useState(false);
  const [tab, setTab] = useState<'details' | 'messages' | 'timing' | 'accounts'>('details');
  const [msgTab, setMsgTab] = useState<MsgTab>('invite');

  // Initial seed when opening for New / Copy
  if (open && !seeded && !editId) {
    setSeeded(true);
    setName(source ? `${source.name} (Copy)` : '');
    setKey(source ? `${source.campaign_key}-copy` : '');
    setStatus(source ? 'paused' : 'active');
    setInviteText('');
    setTrack(['', '', '', '']);
    setInmailSubject('');
    setInmailText('');
    setInmailTrack([
      { subject: '', body: '' },
      { subject: '', body: '' },
      { subject: '', body: '' },
    ]);
    if (source && source.accounts) {
      setAssigned(
        source.accounts.map((a, i) => ({
          uid: `copy-${a.account_id}-${i}`,
          account_id: a.account_id,
          invite: a.invite_limit ?? 10,
          inmail: a.inmail_limit ?? 10,
          messages: a.message_limit ?? 30,
          calendar_url: a.calendar_url || '',
        })),
      );
    } else {
      setAssigned([]);
    }
    setInviteFuDays([3, 5, 7]);
    setInmailFuDays([3, 5, 7]);
    setBusy(false);
    setTab(initialTab || 'details');
    setMsgTab('invite');
  }

  // Load campaign for Edit
  useEffect(() => {
    if (open && editId) {
      setLoadingEdit(true);
      setTab(initialTab || 'details');
      setMsgTab('invite');
      apiGet<CampaignDetailData>(`/api/campaigns/${editId}`)
        .then((data) => {
          setName(data.name || '');
          setKey(data.campaign_key || '');
          setStatus(data.status || 'active');
          setInviteText(data.invite_text || '');
          setTrack([
            data.invite_track?.[0] || '',
            data.invite_track?.[1] || '',
            data.invite_track?.[2] || '',
            data.invite_track?.[3] || '',
          ]);
          setInmailSubject(data.inmail_subject || '');
          setInmailText(data.inmail_text || '');
          setInmailTrack([
            { subject: data.inmail_track?.[0]?.subject || '', body: data.inmail_track?.[0]?.body || '' },
            { subject: data.inmail_track?.[1]?.subject || '', body: data.inmail_track?.[1]?.body || '' },
            { subject: data.inmail_track?.[2]?.subject || '', body: data.inmail_track?.[2]?.body || '' },
          ]);
          if (data.invite_fu_days?.length === 3) {
            setInviteFuDays([data.invite_fu_days[0], data.invite_fu_days[1], data.invite_fu_days[2]]);
          }
          if (data.inmail_fu_days?.length === 3) {
            setInmailFuDays([data.inmail_fu_days[0], data.inmail_fu_days[1], data.inmail_fu_days[2]]);
          }
          setAssigned(
            (data.accounts || []).map((a, i) => ({
              uid: `edit-${a.account_id}-${i}`,
              account_id: a.account_id,
              invite: a.invite_limit ?? 10,
              inmail: a.inmail_limit ?? 10,
              messages: a.message_limit ?? 30,
              calendar_url: a.calendar_url || '',
            })),
          );
        })
        .catch((err) => {
          toast(err instanceof Error ? err.message : String(err), 'crit');
        })
        .finally(() => {
          setLoadingEdit(false);
        });
    }
  }, [open, editId]);

  if (!open && seeded) setSeeded(false);

  const isCopy = !editId && !!source;
  const isEdit = !!editId;
  const validAssigned = assigned.filter((a) => a.account_id !== null);
  const valid = name.trim().length > 0;

  const addAccountSlot = () => {
    setAssigned((prev) => [
      ...prev,
      {
        uid: `slot-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        account_id: null,
        invite: 10,
        inmail: 10,
        messages: 30,
        calendar_url: '',
      },
    ]);
  };

  const updateAccountSlot = (uid: string, updates: Partial<AssignedAccountSlot>) => {
    setAssigned((prev) => prev.map((item) => (item.uid === uid ? { ...item, ...updates } : item)));
  };

  const removeAccountSlot = (uid: string) => {
    setAssigned((prev) => prev.filter((item) => item.uid !== uid));
  };

  const toggleCampaignStatus = async () => {
    if (!editId) return;
    setBusy(true);
    try {
      const next = status === 'active' ? 'paused' : 'active';
      await apiPut(`/api/campaigns/${editId}/pause`, { status: next });
      setStatus(next);
      toast(next === 'paused' ? 'Campaign paused' : 'Campaign resumed', 'ok');
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'crit');
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!valid || busy || loadingEdit) return;
    setBusy(true);
    try {
      if (isCopy && source) {
        await apiPost(`/api/campaigns/${source.id}/copy`, {
          name: name.trim(),
          campaign_key: key.trim() || undefined,
        });
        toast('Campaign copied (paused)', 'ok');
      } else if (isEdit && editId) {
        await apiPut(`/api/campaigns/${editId}`, {
          name: name.trim(),
          status,
          invite_text: inviteText,
          invite_track: track.map((s) => s.trim()).filter(Boolean),
          inmail_subject: inmailSubject,
          inmail_text: inmailText,
          inmail_track: inmailTrack
            .map((s) => ({ subject: s.subject.trim(), body: s.body.trim() }))
            .filter((s) => s.subject || s.body),
          invite_fu_days: inviteFuDays,
          inmail_fu_days: inmailFuDays,
          accounts: validAssigned.map((a, i) => ({
            account_id: a.account_id!,
            order_index: i,
            invite_limit: a.invite ?? 10,
            inmail_limit: a.inmail ?? 10,
            message_limit: a.messages ?? 30,
            calendar_url: a.calendar_url?.trim() || null,
          })),
        });
        toast('Campaign changes saved', 'ok');
      } else {
        await apiPost('/api/campaigns', {
          name: name.trim(),
          campaign_key: key.trim() || undefined,
          status,
          invite_text: inviteText,
          invite_track: track.map((s) => s.trim()).filter(Boolean),
          inmail_subject: inmailSubject,
          inmail_text: inmailText,
          inmail_track: inmailTrack
            .map((s) => ({ subject: s.subject.trim(), body: s.body.trim() }))
            .filter((s) => s.subject || s.body),
          invite_fu_days: inviteFuDays,
          inmail_fu_days: inmailFuDays,
          accounts: validAssigned.map((a, i) => ({
            account_id: a.account_id!,
            order_index: i,
            invite_limit: a.invite ?? 10,
            inmail_limit: a.inmail ?? 10,
            message_limit: a.messages ?? 30,
            calendar_url: a.calendar_url?.trim() || null,
          })),
        });
        toast('Campaign created', 'ok');
      }
      await onSaved();
    } catch (ex) {
      toast(ex instanceof Error ? ex.message : String(ex), 'crit');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? `Edit ${name || 'campaign'}` : isCopy ? `Copy ${source?.name}` : 'New campaign'}
      size="xl"
      footer={
        <div className="flex w-full items-center justify-between">
          {isEdit ? (
            <Button
              variant="secondary"
              size="sm"
              icon={status === 'active' ? <Pause size={13} aria-hidden /> : <Play size={13} aria-hidden />}
              disabled={busy || loadingEdit}
              onClick={() => void toggleCampaignStatus()}
              className={status === 'active' ? 'text-muted' : 'text-primary font-medium'}
              isStatic
            >
              {status === 'active' ? 'Pause Campaign' : 'Resume Campaign'}
            </Button>
          ) : (
            <div />
          )}
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose} isStatic>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void submit()}
              disabled={busy || !valid || loadingEdit}
              isStatic
            >
              {busy ? 'Saving…' : isEdit ? 'Save changes' : isCopy ? 'Create copy' : 'Create campaign'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {/* Navigation tabs */}
        {!isCopy && (
          <div className="flex items-center justify-between border-b border-line pb-1">
            <div className="seg" role="tablist" aria-label="Campaign sections">
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'details'}
                aria-pressed={tab === 'details'}
                onClick={() => setTab('details')}
                className="flex items-center gap-1.5"
              >
                <FileText size={14} aria-hidden />
                <span>Details</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'messages'}
                aria-pressed={tab === 'messages'}
                onClick={() => setTab('messages')}
                className="flex items-center gap-1.5"
              >
                <MessageSquare size={14} aria-hidden />
                <span>Messages</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'accounts'}
                aria-pressed={tab === 'accounts'}
                onClick={() => setTab('accounts')}
                className="flex items-center gap-1.5"
              >
                <Users size={14} aria-hidden />
                <span>Accounts</span>
                {validAssigned.length > 0 && (
                  <span className="rounded-full bg-primary-tint px-1.5 py-0.2 text-[10.5px] font-semibold text-primary">
                    {validAssigned.length}
                  </span>
                )}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'timing'}
                aria-pressed={tab === 'timing'}
                onClick={() => setTab('timing')}
                className="flex items-center gap-1.5"
              >
                <Clock size={14} aria-hidden />
                <span>Follow-up timing</span>
              </button>
            </div>
          </div>
        )}

        {/* Copy mode view */}
        {isCopy && (
          <div className="flex flex-col gap-4">
            <div className="rounded-[14px] border border-border bg-surface-2 p-4 shadow-xs">
              <div className="flex flex-col gap-4">
                <Field label="Campaign Name">
                  <Input
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Sales Outreach Q4 (Copy)"
                    className="font-medium"
                  />
                </Field>
                <div className="border-t border-line/60 pt-3">
                  <Field label="Campaign Key">
                    <Input
                      value={key}
                      onChange={(e) => setKey(e.target.value)}
                      placeholder={name ? name.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').slice(0, 32) : 'unique-key'}
                      className="font-mono text-[13px]"
                    />
                  </Field>
                  <p className="mt-1 text-[11.5px] text-muted">
                    Must be unique. Defaults automatically to the campaign name.
                  </p>
                </div>
              </div>
            </div>
            <p className="rounded-[10px] bg-inset/70 p-3 text-[12.5px] text-muted">
              Templates, accounts, and timing configurations from <strong>{source?.name}</strong> will be duplicated. The copied campaign will start paused.
            </p>
          </div>
        )}

        {/* Tab 1: Details */}
        {!isCopy && tab === 'details' && (
          <div className="flex flex-col gap-4">
            <div className="rounded-[14px] border border-border bg-surface-2 p-4 shadow-xs">
              <div className="grid gap-4 sm:grid-cols-12 sm:items-end">
                <div className="sm:col-span-8">
                  <Field label="Campaign Name">
                    <Input
                      required
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="e.g. Enterprise Outreach Q4"
                      className="font-medium"
                    />
                  </Field>
                </div>
                <div className="sm:col-span-4">
                  <Field label="Status">
                    <Select
                      value={status}
                      onChange={(e) => setStatus(e.target.value)}
                      className="font-medium"
                    >
                      <option value="active">Active (Sending)</option>
                      <option value="paused">Paused</option>
                    </Select>
                  </Field>
                </div>
              </div>
              <div className="mt-4 border-t border-line/60 pt-3">
                <Field label="Campaign Key">
                  <Input
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    disabled={isEdit}
                    placeholder={name ? name.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').slice(0, 32) : 'unique-key'}
                    className="font-mono text-[13px]"
                  />
                </Field>
                <p className="mt-1 text-[11.5px] text-muted">
                  Immutable identifier stamped on leads for tracking. {isEdit ? 'Set at campaign creation.' : 'Defaults automatically from campaign name if left blank.'}
                </p>
              </div>
            </div>

            <div className="flex items-start gap-2.5 rounded-[12px] bg-inset/70 p-3.5 text-[12.5px] text-muted">
              <Info size={16} className="mt-0.5 shrink-0 text-primary" aria-hidden />
              <div>
                <span className="font-semibold text-foreground">Setup workflow:</span> Configure message templates in Messages, assign sender accounts with volume quotas in Accounts, then customize follow-up delay slider bars.
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Messages */}
        {!isCopy && tab === 'messages' && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2 rounded-[10px] bg-inset/70 px-3 py-2 text-[12.5px] text-muted">
              <span className="font-semibold text-foreground">Placeholders:</span>
              <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-[11.5px] text-primary">{'{first_name}'}</code>
              <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-[11.5px] text-primary">{'{company}'}</code>
              <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-[11.5px] text-primary">{'{calendar_url}'}</code>
            </div>

            {/* Template track sub-tabs */}
            <div className="msg-tabs" role="tablist" aria-label="Message templates">
              {(MSG_TABS as readonly [MsgTab, string][]).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={msgTab === value}
                  aria-pressed={msgTab === value}
                  onClick={() => setMsgTab(value)}
                >
                  {label}
                </button>
              ))}
            </div>

            {msgTab === 'invite' && (
              <Field label="First-touch invite note (with connection request)" hint="Optional note sent alongside connection invite (under 300 chars).">
                <Textarea
                  rows={6}
                  placeholder="Hi {first_name}, I noticed your work at {company} and would love to connect..."
                  value={inviteText}
                  onChange={(e) => setInviteText(e.target.value)}
                />
              </Field>
            )}

            {msgTab === 'invite-fu' && (
              <div className="flex flex-col gap-3">
                <p className="card-sub text-[12px]">{FU_HINT}</p>
                {track.map((stage, i) => (
                  <Field key={i} label={inviteStageLabel(i, inviteFuDays)}>
                    <Textarea
                      rows={2.5}
                      placeholder={i === 0 ? 'Thanks for connecting, {first_name}!' : `Follow-up ${i}...`}
                      value={stage}
                      onChange={(e) => setTrack((prev) => prev.map((s, j) => (j === i ? e.target.value : s)))}
                    />
                  </Field>
                ))}
              </div>
            )}

            {msgTab === 'inmail' && (
              <div className="grid gap-3 sm:grid-cols-[1fr_2fr]">
                <Field label="InMail subject">
                  <Input
                    placeholder="Quick question..."
                    value={inmailSubject}
                    onChange={(e) => setInmailSubject(e.target.value)}
                  />
                </Field>
                <Field label="InMail message">
                  <Textarea
                    rows={3}
                    placeholder="Hi {first_name}..."
                    value={inmailText}
                    onChange={(e) => setInmailText(e.target.value)}
                  />
                </Field>
              </div>
            )}

            {msgTab === 'inmail-fu' && (
              <div className="flex flex-col gap-3">
                {inmailTrack.map((stage, i) => (
                  <div key={i} className="grid gap-3 rounded-[10px] border border-border bg-surface-2 p-3 sm:grid-cols-[1fr_2fr]">
                    <Field label={`InMail follow-up ${i + 1} (+${inmailFuDays[i]}d) subject`}>
                      <Input
                        placeholder="Re: Previous message..."
                        value={stage.subject}
                        onChange={(e) =>
                          setInmailTrack((prev) => prev.map((s, j) => (j === i ? { ...s, subject: e.target.value } : s)))
                        }
                      />
                    </Field>
                    <Field label={`InMail follow-up ${i + 1} message`}>
                      <Textarea
                        rows={2.5}
                        placeholder="Following up on my previous note..."
                        value={stage.body}
                        onChange={(e) =>
                          setInmailTrack((prev) => prev.map((s, j) => (j === i ? { ...s, body: e.target.value } : s)))
                        }
                      />
                    </Field>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Accounts (Add account button + individual card dropdowns) */}
        {!isCopy && tab === 'accounts' && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-[14.5px] font-semibold text-foreground">Sender Accounts &amp; Capacity</h3>
                <p className="card-sub text-[12px]">
                  Select the accounts that run this campaign with custom daily sending limits.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-primary-tint px-2.5 py-0.5 text-[12px] font-semibold text-primary">
                  {validAssigned.length} of {accounts.length} mapped
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="primary"
                  icon={<Plus size={14} aria-hidden />}
                  onClick={addAccountSlot}
                  isStatic
                >
                  Add account
                </Button>
              </div>
            </div>

            {/* Active sender cards */}
            {assigned.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border/80 bg-surface/50 p-8 text-center text-muted flex flex-col items-center justify-center gap-3">
                <Users size={28} className="text-muted/60" aria-hidden />
                <div>
                  <p className="font-semibold text-[13.5px] text-foreground">No sender accounts assigned yet</p>
                  <p className="text-[12px] text-muted mt-0.5">Click &ldquo;Add account&rdquo; to assign a sender account and set daily quotas.</p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  icon={<Plus size={14} aria-hidden />}
                  onClick={addAccountSlot}
                  isStatic
                >
                  Add account
                </Button>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between text-[12px] text-muted font-medium">
                  <span>Assigned Accounts ({assigned.length})</span>
                  <span>Daily Quotas</span>
                </div>
                {assigned.map((item, idx) => {
                  return (
                    <div
                      key={item.uid}
                      className="flex flex-col gap-2.5 rounded-xl border border-border/80 bg-surface-2/40 p-3 shadow-2xs transition-all hover:border-primary/40"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2.5 flex-1 min-w-0">
                          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[11px] font-bold text-primary">
                            {idx + 1}
                          </span>
                          <AccountSelectDropdown
                            accounts={accounts}
                            assignedSlots={assigned}
                            currentSlotUid={item.uid}
                            selectedAccountId={item.account_id}
                            onSelect={(accId) => updateAccountSlot(item.uid, { account_id: accId })}
                          />
                        </div>

                        <IconButton
                          label="Remove account"
                          size="sm"
                          className="h-7 w-7 text-muted hover:text-crit hover:bg-crit-tint/30"
                          onClick={() => removeAccountSlot(item.uid)}
                        >
                          <X size={13} />
                        </IconButton>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 pt-1">
                        <div className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-2">
                          <div className="flex items-center justify-between text-[11px] font-medium text-muted">
                            <span>Invites / day</span>
                            <span className="font-mono font-bold text-foreground tabular-nums">{item.invite}</span>
                          </div>
                          <input
                            type="range"
                            min={0}
                            max={50}
                            step={1}
                            value={item.invite}
                            onChange={(e) => updateAccountSlot(item.uid, { invite: Number(e.target.value) })}
                            className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-line accent-primary"
                          />
                        </div>

                        <div className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-2">
                          <div className="flex items-center justify-between text-[11px] font-medium text-muted">
                            <span>InMails / day</span>
                            <span className="font-mono font-bold text-foreground tabular-nums">{item.inmail}</span>
                          </div>
                          <input
                            type="range"
                            min={0}
                            max={30}
                            step={1}
                            value={item.inmail}
                            onChange={(e) => updateAccountSlot(item.uid, { inmail: Number(e.target.value) })}
                            className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-line accent-info"
                          />
                        </div>

                        <div className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-2">
                          <div className="flex items-center justify-between text-[11px] font-medium text-muted">
                            <span>Messages / day</span>
                            <span className="font-mono font-bold text-foreground tabular-nums">{item.messages}</span>
                          </div>
                          <input
                            type="range"
                            min={0}
                            max={100}
                            step={5}
                            value={item.messages}
                            onChange={(e) => updateAccountSlot(item.uid, { messages: Number(e.target.value) })}
                            className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-line accent-primary"
                          />
                        </div>
                      </div>

                      {/* Calendar booking link */}
                      <div className="flex flex-col gap-1 border-t border-line/60 pt-2">
                        <div className="flex items-center justify-between text-[11.5px] font-medium text-muted">
                          <span className="flex items-center gap-1.5 text-foreground">
                            <Calendar size={12} className="text-primary" aria-hidden />
                            Calendar booking link
                          </span>
                          <span className="text-[10.5px] text-muted">Replaces {'{calendar_url}'} placeholder</span>
                        </div>
                        <Input
                          value={item.calendar_url || ''}
                          onChange={(e) => updateAccountSlot(item.uid, { calendar_url: e.target.value })}
                          placeholder="https://calendly.com/your-name/30min"
                          className="h-8 text-[12px] bg-surface"
                        />
                      </div>
                    </div>
                  );
                })}

                <div className="flex items-center justify-between pt-1">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    icon={<Plus size={13} aria-hidden />}
                    onClick={addAccountSlot}
                    isStatic
                  >
                    Add another account
                  </Button>
                  {assigned.some((a) => a.account_id != null) && (
                    <div className="rounded-lg bg-inset/80 px-3 py-1.5 text-[11.5px] text-muted">
                      <span className="font-semibold text-foreground">Priority:</span>{' '}
                      {assigned
                        .map((slot) => accounts.find((a) => a.id === slot.account_id)?.name)
                        .filter(Boolean)
                        .join(' → ')}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab 4: Follow-up timing with interactive slide bars */}
        {!isCopy && tab === 'timing' && (
          <div className="flex flex-col gap-4">
            <div className="rounded-[10px] bg-inset/70 px-3 py-2 text-[12px] text-muted">
              Configure delays (in days) before each follow-up stage for this campaign. Use the slide bars below to set timing (up to 7 days).
            </div>

            <div className="flex flex-col gap-4">
              {/* Connection Invite Track */}
              <div className="rounded-[14px] border border-border bg-surface-2 p-4 shadow-xs flex flex-col gap-3">
                <div className="flex items-center gap-2.5">
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-tint text-[12px] font-bold text-primary">
                    1
                  </span>
                  <div>
                    <h3 className="text-[14px] font-semibold text-foreground">Connection Invite Track</h3>
                    <p className="text-[12px] text-muted">Days to wait after acceptance / previous follow-up</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="flex min-w-0 flex-col gap-2 rounded-xl border border-line/80 bg-surface p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-[11.5px] font-semibold uppercase tracking-wider text-muted truncate">
                          Follow-Up {i + 1}
                        </span>
                        <div className="flex items-center gap-1 rounded-md border border-border/70 bg-surface-2 px-1.5 py-0.5 shrink-0">
                          <span className="font-mono text-[12.5px] font-bold text-primary tabular-nums">
                            {inviteFuDays[i]}
                          </span>
                          <span className="text-[11px] text-muted font-medium">d</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 pt-1 min-w-0">
                        <span className="text-[10.5px] font-medium text-muted shrink-0 w-3">1d</span>
                        <input
                          type="range"
                          min={1}
                          max={7}
                          step={1}
                          value={inviteFuDays[i]}
                          onChange={(e) => {
                            const v = Math.max(1, Math.min(7, Number(e.target.value) || 1));
                            const next = [...inviteFuDays] as [number, number, number];
                            next[i] = v;
                            setInviteFuDays(next);
                          }}
                          className="h-2 w-full min-w-0 flex-1 cursor-pointer appearance-none rounded-lg bg-line accent-primary"
                          aria-label={`Invite follow-up ${i + 1} delay in days`}
                        />
                        <span className="text-[10.5px] font-medium text-muted shrink-0 w-3 text-right">7d</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* InMail Outreach Track */}
              <div className="rounded-[14px] border border-border bg-surface-2 p-4 shadow-xs flex flex-col gap-3">
                <div className="flex items-center gap-2.5">
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-info-tint text-[12px] font-bold text-info">
                    2
                  </span>
                  <div>
                    <h3 className="text-[14px] font-semibold text-foreground">InMail Outreach Track</h3>
                    <p className="text-[12px] text-muted">Days to wait after initial InMail / previous follow-up</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="flex min-w-0 flex-col gap-2 rounded-xl border border-line/80 bg-surface p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-[11.5px] font-semibold uppercase tracking-wider text-muted truncate">
                          Follow-Up {i + 1}
                        </span>
                        <div className="flex items-center gap-1 rounded-md border border-border/70 bg-surface-2 px-1.5 py-0.5 shrink-0">
                          <span className="font-mono text-[12.5px] font-bold text-info tabular-nums">
                            {inmailFuDays[i]}
                          </span>
                          <span className="text-[11px] text-muted font-medium">d</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 pt-1 min-w-0">
                        <span className="text-[10.5px] font-medium text-muted shrink-0 w-3">1d</span>
                        <input
                          type="range"
                          min={1}
                          max={7}
                          step={1}
                          value={inmailFuDays[i]}
                          onChange={(e) => {
                            const v = Math.max(1, Math.min(7, Number(e.target.value) || 1));
                            const next = [...inmailFuDays] as [number, number, number];
                            next[i] = v;
                            setInmailFuDays(next);
                          }}
                          className="h-2 w-full min-w-0 flex-1 cursor-pointer appearance-none rounded-lg bg-line accent-info"
                          aria-label={`InMail follow-up ${i + 1} delay in days`}
                        />
                        <span className="text-[10.5px] font-medium text-muted shrink-0 w-3 text-right">7d</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
