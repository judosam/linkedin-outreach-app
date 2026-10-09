import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Copy, MessageSquareReply, Pause, Pencil, Play, Plus, Rocket, Trash2, Users } from 'lucide-react';
import { CampaignDialog, type AccountOption } from '@/components/CampaignDialog';
import { Avatar, Button, Card, EmptyState, ErrorState, IconButton, Loading, Pill, Progress, Ring } from '@/components/ui';
import { PageHeader } from '@/components/form';
import { Modal } from '@/components/Modal';
import { apiDelete, apiGet, apiPut } from '@/lib/api';
import { useAsync } from '@/lib/hooks';
import { useToast } from '@/lib/toast';
import { nf } from '@/lib/format';

export interface CampaignListItem {
  id: number;
  campaign_key: string;
  name: string;
  status: string;
  accounts: { account_id: number; account_name: string; invite_limit: number; inmail_limit: number; message_limit: number }[];
  leads: number;
  contacted: number;
  replied: number;
  reply_rate: number;
}

export default function Campaigns() {
  const toast = useToast();
  const { data, error, loading, reload } = useAsync<CampaignListItem[]>(() => apiGet('/api/campaigns'), []);
  const accounts = useAsync<AccountOption[]>(() => apiGet('/api/accounts'), []);
  const fuDays = useAsync<{ invite: number[]; inmail: number[] }>(
    () => apiGet('/api/settings/fu-delays'),
    [],
  );
  const [detailId, setDetailId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  /* ?create=1 creates immediately; ?templates=1 opens the template editor;
     ?edit=<id> opens the edit popup (the /campaign/:id route redirects here). */
  const [urlParams, setUrlParams] = useSearchParams();
  const [copyOf, setCopyOf] = useState<CampaignListItem | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const createParam = urlParams.get('create');
  const templatesParam = urlParams.get('templates');
  const editParam = Number(urlParams.get('edit') || '');
  useEffect(() => {
    if (createParam === '1' || templatesParam === '1') setCreating(true);
    if (Number.isFinite(editParam) && editParam > 0) setEditingId(editParam);
  }, [createParam, templatesParam, editParam]);
  /* Drop the deep-link params once a dialog closes, so it does not spring
     back open on the next render or reload. */
  const clearDeepLink = () => {
    if (createParam || templatesParam || urlParams.get('edit')) {
      setUrlParams({}, { replace: true });
    }
  };
  const [busyId, setBusyId] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<CampaignListItem | null>(null);

  const toggle = async (c: CampaignListItem) => {
    setBusyId(c.id);
    try {
      const next = c.status === 'active' ? 'paused' : 'active';
      await apiPut(`/api/campaigns/${c.id}/pause`, { status: next });
      toast(`${c.name} ${next === 'paused' ? 'paused' : 'resumed'}`, 'ok');
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setBusyId(null);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setBusyId(deleteTarget.id);
    try {
      await apiDelete(`/api/campaigns/${deleteTarget.id}`);
      toast(`Campaign "${deleteTarget.name}" and associated leads permanently deleted`, 'ok');
      setDetailId(null);
      setDeleteTarget(null);
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setBusyId(null);
    }
  };

  const campaigns = data ?? [];
  // Derive from the live list so the popup never shows stale numbers.
  const detail = detailId != null ? campaigns.find((c) => c.id === detailId) ?? null : null;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Campaigns"
        subtitle={data ? `${campaigns.filter((c) => c.status === 'active').length} active of ${campaigns.length}` : 'Outreach campaigns'}
        actions={
          <Button variant="primary" size="sm" icon={<Plus size={13} aria-hidden />} onClick={() => setCreating(true)} isStatic>
            New campaign
          </Button>
        }
      />

      {/* Compact roll-up so the page reads as a workspace, not only a list. */}
      {campaigns.length > 0 && (
        <div className="grid gap-2.5 sm:grid-cols-3">
          {[
            {
              label: 'Active campaigns',
              value: campaigns.filter((c) => c.status === 'active').length,
              sub: `of ${campaigns.length} total`,
              icon: <Rocket size={14} aria-hidden />,
            },
            {
              label: 'Leads in campaigns',
              value: campaigns.reduce((a, c) => a + c.leads, 0),
              sub: `${nf.format(campaigns.reduce((a, c) => a + c.contacted, 0))} contacted`,
              icon: <Users size={14} aria-hidden />,
            },
            {
              label: 'Replies',
              value: campaigns.reduce((a, c) => a + c.replied, 0),
              sub: 'across all campaigns',
              icon: <MessageSquareReply size={14} aria-hidden />,
            },
          ].map((t) => (
            <Card key={t.label} className="surface-hover flex items-center gap-3 px-3.5 py-2.5 shadow-2xs">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-tint text-primary">
                {t.icon}
              </span>
              <div className="min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[16px] font-bold leading-none text-foreground">{nf.format(t.value)}</span>
                  <span className="truncate text-[11px] font-semibold uppercase tracking-wider text-muted">{t.label}</span>
                </div>
                <div className="mt-0.5 truncate text-[11.5px] text-muted">{t.sub}</div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {loading && !data ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : campaigns.length ? (
        <Card className="overflow-hidden">
          <div className="w-full overflow-hidden">
            {/* Fixed layout + colgroup: every column gets an exact percentage
                so the table never overflows and renders cleanly without in-table scroll. */}
            <table className="dt dt-fixed w-full">
              <colgroup>
                {[1, 23, 10, 8, 8, 8, 9, 15, 18].map((w, i) => (
                  <col key={i} style={{ width: w + '%' }} />
                ))}
              </colgroup>
              <thead>
                <tr>
                  <th className="w-[6px] p-0" aria-label="Status" />
                  <th>Campaign</th>
                  <th>Status</th>
                  <th className="text-right">Leads</th>
                  <th className="text-right">Contacted</th>
                  <th className="text-right">Replied</th>
                  <th>Reply rate</th>
                  <th>Accounts</th>
                  <th className="col-actions text-right pr-4">Actions</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => (
                  <tr key={c.id} data-open onClick={() => setDetailId(c.id)}>
                    <td className="w-[6px] px-0 py-2">
                      <span className="accent-bar" data-active={c.status === 'active'} />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="block max-w-full truncate text-left font-medium hover:text-primary hover:underline"
                        onClick={() => setDetailId(c.id)}
                      >
                        {c.name}
                      </button>
                      <span className="sub truncate">{c.campaign_key}</span>
                    </td>
                    <td>
                      <Pill tone={c.status === 'active' ? 'ok' : 'idle'} dot>
                        {c.status === 'active' ? 'Active' : 'Paused'}
                      </Pill>
                    </td>
                    <td className="num text-right">{nf.format(c.leads)}</td>
                    <td className="num text-right">{nf.format(c.contacted)}</td>
                    <td className="num text-right">{nf.format(c.replied)}</td>
                    <td>
                      <Ring value={c.replied} limit={Math.max(1, c.contacted)} size={38} stroke={4}>
                        {c.reply_rate}%
                      </Ring>
                    </td>
                    <td>
                      {c.accounts.length ? (
                        <div className="flex items-center gap-2">
                          <span className="flex -space-x-1.5">
                            {c.accounts.slice(0, 3).map((a) => (
                              <Avatar
                                key={a.account_id}
                                name={a.account_name}
                                size="sm"
                                className="ring-2 ring-[var(--surface-solid)]"
                              />
                            ))}
                          </span>
                          <span
                            className="truncate text-[12.5px] text-ink2"
                            title={c.accounts.map((a) => a.account_name).join(', ')}
                          >
                            {c.accounts.length === 1 ? c.accounts[0].account_name : `${c.accounts.length} accounts`}
                          </span>
                        </div>
                      ) : (
                        <span className="text-[12.5px] text-muted">None</span>
                      )}
                    </td>
                    <td className="col-actions py-2 pr-3" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
                        <IconButton
                          label={c.status === 'active' ? `Pause ${c.name}` : `Resume ${c.name}`}
                          size="sm"
                          className="h-8 w-8 rounded-lg border border-border/80 bg-surface text-ink2 shadow-2xs hover:border-primary/50 hover:bg-primary-tint/30 hover:text-primary active:scale-95 transition-all"
                          disabled={busyId === c.id}
                          onClick={() => void toggle(c)}
                        >
                          {c.status === 'active' ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}
                        </IconButton>
                        <IconButton
                          label={`Edit ${c.name}`}
                          size="sm"
                          className="h-8 w-8 rounded-lg border border-border/80 bg-surface text-ink2 shadow-2xs hover:border-primary/50 hover:bg-primary-tint/30 hover:text-primary active:scale-95 transition-all"
                          onClick={() => setEditingId(c.id)}
                        >
                          <Pencil size={14} aria-hidden />
                        </IconButton>
                        <IconButton
                          label={`Copy ${c.name}`}
                          size="sm"
                          className="h-8 w-8 rounded-lg border border-border/80 bg-surface text-ink2 shadow-2xs hover:border-primary/50 hover:bg-primary-tint/30 hover:text-primary active:scale-95 transition-all"
                          disabled={busyId === c.id}
                          onClick={() => setCopyOf(c)}
                        >
                          <Copy size={14} aria-hidden />
                        </IconButton>
                        <IconButton
                          label={`Delete ${c.name}`}
                          size="sm"
                          className="h-8 w-8 rounded-lg border border-border/80 bg-surface text-ink2 shadow-2xs hover:border-crit/50 hover:bg-crit-tint/40 hover:text-crit active:scale-95 transition-all"
                          disabled={busyId === c.id}
                          onClick={() => setDeleteTarget(c)}
                        >
                          <Trash2 size={14} aria-hidden />
                        </IconButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <Card className="p-6">
          <EmptyState
            icon={<Rocket size={22} aria-hidden />}
            title="No campaigns yet"
            body="A campaign holds your message templates and the accounts that send them."
            action={
              <Button variant="primary" onClick={() => setCreating(true)} isStatic>
                Create a campaign
              </Button>
            }
          />
        </Card>
      )}

      <CampaignDetail
        campaign={detail}
        busyId={busyId}
        onClose={() => setDetailId(null)}
        onOpen={(c) => setEditingId(c.id)}
        onToggle={(c) => void toggle(c)}
        onCopy={(c) => {
          setDetailId(null);
          setCopyOf(c);
        }}
        onDelete={(c) => setDeleteTarget(c)}
      />

      <CampaignDialog
        open={creating || editingId != null}
        editId={editingId}
        accounts={accounts.data ?? []}
        fuDays={fuDays.data ?? undefined}
        initialTab={urlParams.get('templates') === '1' ? 'messages' : 'details'}
        onClose={() => {
          setCreating(false);
          setEditingId(null);
          clearDeepLink();
        }}
        onSaved={async () => {
          setCreating(false);
          setEditingId(null);
          clearDeepLink();
          await reload();
        }}
      />

      <CampaignDialog
        open={!!copyOf}
        source={copyOf}
        accounts={accounts.data ?? []}
        onClose={() => setCopyOf(null)}
        onSaved={() => {
          setCopyOf(null);
          void reload();
        }}
      />

      {/* Delete Campaign Confirmation Modal */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Campaign & Associated Leads"
        size="md"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDeleteTarget(null)} isStatic>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              icon={<Trash2 size={13} aria-hidden />}
              disabled={busyId === deleteTarget?.id}
              onClick={() => void confirmDelete()}
              isStatic
            >
              {busyId === deleteTarget?.id ? 'Deleting…' : 'Delete campaign & leads'}
            </Button>
          </>
        }
      >
        {deleteTarget && (
          <div className="flex flex-col gap-3">
            <div className="rounded-[12px] border border-crit/30 bg-crit/10 p-3.5 text-[13px] text-crit">
              <strong className="block font-semibold">Irreversible action</strong>
              Deleting <strong>&ldquo;{deleteTarget.name}&rdquo;</strong> will permanently delete this campaign and all <strong>{deleteTarget.leads} associated leads</strong>, along with their entire outreach history.
            </div>
            <p className="text-[12.5px] text-muted">
              Are you sure you want to permanently delete this campaign and all its leads? This action cannot be undone.
            </p>
          </div>
        )}
      </Modal>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Detail popup — the per-account breakdown the compact row leaves out        */
/* -------------------------------------------------------------------------- */

function CampaignDetail({
  campaign,
  busyId,
  onClose,
  onOpen,
  onToggle,
  onCopy,
  onDelete,
}: {
  campaign: CampaignListItem | null;
  busyId: number | null;
  onClose: () => void;
  onOpen: (c: CampaignListItem) => void;
  onToggle: (c: CampaignListItem) => void;
  onCopy: (c: CampaignListItem) => void;
  onDelete: (c: CampaignListItem) => void;
}) {
  if (!campaign) return null;

  const stats = [
    ['Leads', campaign.leads],
    ['Contacted', campaign.contacted],
    ['Replied', campaign.replied],
  ] as const;

  return (
    <Modal
      open
      onClose={onClose}
      title={campaign.name}
      size="lg"
      footer={
        <>
          <Button
            variant="danger"
            size="sm"
            icon={<Trash2 size={14} aria-hidden />}
            disabled={busyId === campaign.id}
            onClick={() => onDelete(campaign)}
            isStatic
          >
            Delete
          </Button>
          <Button variant="ghost" size="sm" icon={<Copy size={14} aria-hidden />} onClick={() => onCopy(campaign)} isStatic>
            Copy
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={campaign.status === 'active' ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}
            disabled={busyId === campaign.id}
            onClick={() => onToggle(campaign)}
            isStatic
          >
            {campaign.status === 'active' ? 'Pause' : 'Resume'}
          </Button>
          <Button variant="primary" size="sm" icon={<Pencil size={14} aria-hidden />} onClick={() => onOpen(campaign)} isStatic>
            Edit campaign
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone={campaign.status === 'active' ? 'ok' : 'idle'} dot>
            {campaign.status === 'active' ? 'Active' : 'Paused'}
          </Pill>
          <span className="num text-[12px] text-muted">{campaign.campaign_key}</span>
        </div>

        <div className="grid grid-cols-3 gap-3">
          {stats.map(([label, value]) => (
            <div key={label} className="rounded-panel bg-inset p-3">
              <div className="num text-[20px] font-semibold">{nf.format(value)}</div>
              <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
            </div>
          ))}
        </div>

        <div>
          <div className="flex items-center justify-between text-[12.5px]">
            <span className="label">Reply rate</span>
            <span className="num text-muted">{campaign.reply_rate}%</span>
          </div>
          <Progress value={campaign.replied} limit={Math.max(1, campaign.contacted)} tone="primary" className="mt-1.5" />
          <p className="mt-1.5 text-[12px] text-muted">
            {nf.format(campaign.replied)} replies from {nf.format(campaign.contacted)} contacted leads.
          </p>
        </div>

        <section>
          <h3 className="label">Sending accounts</h3>
          {campaign.accounts.length ? (
            <div className="mt-2 overflow-hidden rounded-panel bg-inset">
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-muted">
                    <th className="px-3 py-1.5 font-medium">Account</th>
                    <th className="px-3 py-1.5 text-right font-medium">Invites</th>
                    <th className="px-3 py-1.5 text-right font-medium">InMails</th>
                    <th className="px-3 py-1.5 text-right font-medium">Messages</th>
                  </tr>
                </thead>
                <tbody>
                  {campaign.accounts.map((a) => (
                    <tr key={a.account_id} className="border-t border-line">
                      <td className="truncate px-3 py-2">{a.account_name}</td>
                      <td className="num px-3 py-2 text-right text-ink2">{a.invite_limit}</td>
                      <td className="num px-3 py-2 text-right text-ink2">{a.inmail_limit}</td>
                      <td className="num px-3 py-2 text-right text-ink2">{a.message_limit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-1.5 text-[13px] text-muted">No account is mapped to this campaign yet.</p>
          )}
        </section>
      </div>
    </Modal>
  );
}
