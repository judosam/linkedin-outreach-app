import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui';
import { Field, Input, Select } from '@/components/form';
import { Modal } from '@/components/Modal';
import { apiPost } from '@/lib/api';
import { useToast } from '@/lib/toast';
import { useLiveConsole } from '@/lib/console';
import { requestNotifyPermission } from '@/lib/notify';

export interface ImportCampaign {
  id: number;
  name: string;
}

export interface ImportAccount {
  id: number;
  name: string;
  status: string;
}

/* Saved-search and list imports belong with the pipeline they create, so this
   dialog is shared by the Leads page (primary home) and the scheduler. The
   server requires a numeric saved_search_id / list_id plus an import account. */
export function ImportDialog({
  job,
  campaigns,
  accounts,
  onClose,
  onStarted,
}: {
  job: 'sync_leads' | 'import_list' | null;
  campaigns: ImportCampaign[];
  accounts: ImportAccount[];
  onClose: () => void;
  onStarted: () => void;
}) {
  const toast = useToast();
  const console = useLiveConsole();
  const [importAccount, setImportAccount] = useState('');
  const [externalId, setExternalId] = useState('');
  const [tagCampaign, setTagCampaign] = useState('');
  const [outreachAccount, setOutreachAccount] = useState('');
  const [busy, setBusy] = useState(false);

  const [seeded, setSeeded] = useState(false);
  if (job && !seeded) {
    setSeeded(true);
    setImportAccount('');
    setExternalId('');
    setTagCampaign('');
    setOutreachAccount('');
    setBusy(false);
  }
  if (!job && seeded) setSeeded(false);
  if (!job) return null;
  const isSync = job === 'sync_leads';
  const active = accounts.filter((a) => a.status === 'active');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!importAccount || !externalId.trim()) return;
    if (!tagCampaign) {
      toast('Tag leads to a campaign is required. Please select a campaign.', 'warn');
      return;
    }
    setBusy(true);
    requestNotifyPermission();
    try {
      const body: Record<string, unknown> = {
        account_id: Number(importAccount),
        campaign_id: Number(tagCampaign),
        outreach_account_id: outreachAccount ? Number(outreachAccount) : null,
      };
      if (isSync) body.saved_search_id = externalId.trim();
      else body.list_id = externalId.trim();
      const res = await apiPost<{ message?: string; execution_id?: string; warnings?: string[] }>(
        `/api/jobs/${job}/run`,
        body,
      );
      toast(res.message || 'Job started', 'ok');
      res.warnings?.forEach((w) => toast(w, 'warn'));
      onClose();
      console.open(res.execution_id);
      onStarted();
    } catch (ex) {
      toast(ex instanceof Error ? ex.message : String(ex), 'crit');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={isSync ? 'Import from Saved Search' : 'Import from List'}
      size="md"
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose} isStatic>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            form="import-form"
            disabled={busy || !importAccount || !externalId.trim() || !tagCampaign || campaigns.length === 0}
            isStatic
          >
            {busy ? 'Starting…' : 'Start import'}
          </Button>
        </>
      }
    >
      <form id="import-form" className="flex flex-col gap-3.5" onSubmit={submit}>
        <p className="rounded-lg bg-inset px-3 py-2 text-[12px] text-muted">
          This import creates real leads. Verify the Sales Nav account and ID before launching.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Import account" hint="Session account to run import">
            <Select required value={importAccount} onChange={(e) => setImportAccount(e.target.value)}>
              <option value="">Choose account…</option>
              {active.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </Field>

          <Field label={isSync ? 'Saved search ID' : 'List ID'} hint="Numeric ID only">
            <Input
              required
              inputMode="numeric"
              pattern="[0-9]+"
              value={externalId}
              onChange={(e) => setExternalId(e.target.value)}
              placeholder="e.g. 123456789"
            />
          </Field>

          <Field
            label={
              <>
                Tag leads to campaign <span className="text-crit font-bold" title="Required">*</span>
              </>
            }
            hint={
              campaigns.length === 0
                ? 'Create a campaign first'
                : 'Required destination'
            }
          >
            <Select
              required
              value={tagCampaign}
              onChange={(e) => setTagCampaign(e.target.value)}
            >
              <option value="" disabled>
                Select campaign (Required)…
              </option>
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Outreach account" hint="Optional assigned sender">
            <Select value={outreachAccount} onChange={(e) => setOutreachAccount(e.target.value)}>
              <option value="">None assigned</option>
              {active.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </form>
    </Modal>
  );
}
