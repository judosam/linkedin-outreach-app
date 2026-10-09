import { useEffect, useRef, useState, type FormEvent, type SelectHTMLAttributes } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  ChevronRight,
  Download,
  ExternalLink,
  FileSpreadsheet,
  FileSearch,
  History,
  ListFilter,
  ListPlus,
  Mail,
  MessageSquare,
  Search,
  Send,
  Trash2,
  TriangleAlert,
  Upload,
  UploadCloud,
  UserCheck,
  X,
} from 'lucide-react';
import { Avatar, Button, Card, EmptyState, ErrorState, Loading, Pill, SortHeader, cn } from '@/components/ui';
import { Field, Input, PageHeader, Select } from '@/components/form';
import { Modal } from '@/components/Modal';
import { ImportDialog } from '@/components/ImportDialog';
import { ColumnFilter, FilterFields, localDayISO, type FilterSpec } from '@/components/colfilter';
import { apiGet, apiPut, apiPost, apiDelete } from '@/lib/api';
import { useAsync, useDebounced } from '@/lib/hooks';
import { useToast } from '@/lib/toast';
import { REPLY_CATEGORIES, STATUS_META, type Tone } from '@/lib/constants';
import { fmtDate, fmtDT, ago, nf } from '@/lib/format';

interface Lead {
  id: number;
  linkedin_url: string;
  sales_nav_id: string;
  opentomsg: boolean | null;
  full_name: string;
  title: string | null;
  company: string | null;
  location: string | null;
  source: string;
  campaign: string | null;
  campaign_id: number | null;
  campaign_name: string | null;
  associate_account: string | null;
  status: string;
  last_error: string;
  received_replies: boolean;
  reply_message: string;
  reply_category: string;
  review_status: string;
  created_at: string | null;
  first_contacted_at: string | null;
  last_followup_at: string | null;
  last_followup_stage: string;
  comment_count: number;
}

interface LeadPage {
  total: number;
  page: number;
  page_size: number;
  items: Lead[];
}

interface CampaignRow {
  id: number;
  name: string;
  status: string;
}

interface AccountRow {
  id: number;
  name: string;
  status: string;
}

const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  REPLY_CATEGORIES.map((c) => [c.value, c.label]),
);

/* The outreach channel a lead is currently on, derived from its stage. Drives
   the chip shown under the name so the marketing channel is scannable. */
function channel(status: string): { label: string; tone: string } | null {
  if (status === 'INVITE_AFTER_ACCEPT') return { label: 'Accepted', tone: 'accepted' };
  if (status.startsWith('INVITE')) return { label: 'Invite', tone: 'invite' };
  if (status.startsWith('INMAIL')) return { label: 'InMail', tone: 'inmail' };
  if (status === 'BLOCKED_ERROR') return { label: 'Error', tone: 'error' };
  return null;
}

/* The channel chip carries an icon so it still reads without colour. */
function ChannelIcon({ tone }: { tone: string }) {
  const Icon =
    tone === 'inmail'
      ? Mail
      : tone === 'invite'
        ? Send
        : tone === 'accepted'
          ? UserCheck
          : tone === 'error'
            ? TriangleAlert
            : null;
  return Icon ? <Icon size={10} aria-hidden /> : null;
}

/* Filter selects carry their own label for assistive tech while the visible
   option text does the describing — no separate label row needed. */
function FilterSelect({
  label,
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  return <Select aria-label={label} title={label} className={cn('w-auto min-w-0 flex-1 sm:w-[166px] sm:flex-none', className)} {...props} />;
}

type FilterKey =
  | 'q'
  | 'company'
  | 'location'
  | 'campaign_id'
  | 'account_id'
  | 'status'
  | 'created'
  | 'contact'
  | 'followup'
  | 'reply'
  | 'opentomsg';
type Filters = Record<FilterKey, string[]>;
const emptyFilters = (): Filters => ({
  q: [],
  company: [],
  location: [],
  campaign_id: [],
  account_id: [],
  status: [],
  created: [],
  contact: [],
  followup: [],
  reply: [],
  opentomsg: [],
});
const LABELS: Record<FilterKey, string> = {
  q: 'Lead',
  company: 'Company',
  location: 'Location',
  campaign_id: 'Campaign',
  account_id: 'Owner account',
  status: 'Stage',
  created: 'Added',
  contact: 'Contacted',
  followup: 'Follow-up',
  reply: 'Reply',
  opentomsg: 'OpenToMsg',
};
function profileUrl(lead: Lead) {
  try {
    const url = new URL(lead.linkedin_url);
    if (
      url.protocol === 'https:' &&
      (url.hostname === 'linkedin.com' || url.hostname.endsWith('.linkedin.com'))
    )
      return url.href;
  } catch {
    /* Try a valid Sales Nav identity below. */
  }
  return /^AC[wo]/.test(lead.sales_nav_id || '')
    ? 'https://www.linkedin.com/sales/lead/' + encodeURIComponent(lead.sales_nav_id)
    : '';
}
function leadParams(filters: Filters) {
  const params = new URLSearchParams();
  for (const key of ['q', 'company'] as FilterKey[])
    if (filters[key][0]?.trim()) params.set(key, filters[key][0].trim());

  if (filters.campaign_id.length > 0) {
    if (filters.campaign_id.length === 1) {
      params.set('campaign_id', filters.campaign_id[0]);
    } else {
      const ids = filters.campaign_id.filter((x) => x !== '__none__');
      if (ids.length) params.set('campaign_ids', ids.join(','));
      if (filters.campaign_id.includes('__none__')) params.set('campaign_id', '__none__');
    }
  }

  if (filters.account_id.length > 0) {
    if (filters.account_id.length === 1) {
      params.set('account_id', filters.account_id[0]);
    } else {
      params.set('account_ids', filters.account_id.join(','));
    }
  }

  if (filters.status.length > 0) {
    if (filters.status.length === 1) {
      params.set('status', filters.status[0]);
    } else {
      params.set('statuses', filters.status.join(','));
    }
  }

  for (const key of ['created', 'contact', 'followup'] as const) {
    const [from, to] = filters[key];
    if (from) params.set(key + '_from', localDayISO(from));
    if (to) params.set(key + '_to', localDayISO(to, true));
  }
  const reply = filters.reply[0];
  if (reply === 'replied') params.set('replied', 'true');
  else if (reply?.startsWith('error:')) params.set('error', reply.slice(6));
  else if (reply) {
    params.set('category', reply);
    params.set('replied', 'true');
  }
  return params;
}

export default function Leads() {
  const toast = useToast(),
    [urlParams] = useSearchParams();
  const [filters, setFilters] = useState<Filters>(() => ({
    ...emptyFilters(),
    q: [urlParams.get('q') || ''],
    campaign_id: [urlParams.get('campaign_id') || ''],
  }));
  const debouncedQ = useDebounced(filters.q[0] || '');
  /* Dashboard → “View leads” deep-links filter by campaign. Re-apply when the
     param changes while already on this page; a param-less URL never clobbers
     a selection the user made in the dropdown. */
  const urlCampaign = urlParams.get('campaign_id') || '';
  useEffect(() => {
    if (!urlCampaign) return;
    setFilters((prev) =>
      prev.campaign_id[0] === urlCampaign ? prev : { ...prev, campaign_id: [urlCampaign] },
    );
    setPage(1);
  }, [urlCampaign]);
  const [sort, setSort] = useState('newest'),
    [page, setPage] = useState(1),
    [pageSize, setPageSize] = useState(50);
  const [selected, setSelected] = useState<number[]>([]),
    [selectedAllMatching, setSelectedAllMatching] = useState(false),
    [matchTotal, setMatchTotal] = useState(0),
    [idsBusy, setIdsBusy] = useState(false),
    [detail, setDetail] = useState<Lead | null>(null),
    [reassigning, setReassigning] = useState(false);
  const [importJob, setImportJob] = useState<'sync_leads' | 'import_list' | null>(null),
    [csv, setCsv] = useState(false);
  const [openFilter, setOpenFilter] = useState<FilterKey | null>(null),
    [more, setMore] = useState(false);
  const [deletePreview, setDeletePreview] = useState<(DeletePreview & { ids: number[] }) | null>(null),
    [actionBusy, setActionBusy] = useState(false);
  const campaigns = useAsync<CampaignRow[]>(() => apiGet('/api/campaigns'), []),
    accounts = useAsync<AccountRow[]>(() => apiGet('/api/accounts'), []);
  const params = leadParams({ ...filters, q: [debouncedQ] });
  params.set('page', String(page));
  params.set('page_size', String(pageSize));
  params.set('sort', sort);
  const query = params.toString();
  const leads = useAsync<LeadPage>(() => apiGet('/api/leads?' + query), [query]);
  const allRows = leads.data?.items ?? [];
  const rows = allRows.filter(
    (l) =>
      (!filters.location[0] ||
        (l.location || '').toLowerCase().includes(filters.location[0].toLowerCase())) &&
      (!filters.opentomsg[0] ||
        (filters.opentomsg[0] === 'yes'
          ? l.opentomsg === true
          : filters.opentomsg[0] === 'no'
            ? l.opentomsg === false
            : l.opentomsg == null)),
  );
  const pages = Math.max(1, Math.ceil((leads.data?.total || 0) / pageSize)),
    allSelected = rows.length > 0 && rows.every((l) => selected.includes(l.id));
  const activeKeys = (Object.keys(filters) as FilterKey[]).filter((k) => filters[k].some(Boolean));
  const pageFiltered = !!(filters.location[0] || filters.opentomsg[0]);
  const update = (key: FilterKey, value: string[]) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(1);
    setSelected([]);
    setSelectedAllMatching(false);
  };
  const resetFilters = () => {
    setFilters(emptyFilters());
    setPage(1);
    setSelected([]);
    setSelectedAllMatching(false);
  };
  /* Cross-page select-all (legacy parity): the server can hand back every
     matching id in one snapshot via ids_only, so bulk actions reach beyond
     the current page while page-only filters stay page-scoped. */
  const selectAllMatching = async () => {
    setIdsBusy(true);
    try {
      const q = leadParams({ ...filters, q: [debouncedQ] });
      q.set('ids_only', 'true');
      const r = await apiGet<{ ids: number[]; total: number }>('/api/leads?' + q.toString());
      setMatchTotal(r.total);
      setSelected(r.ids);
      setSelectedAllMatching(true);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setIdsBusy(false);
    }
  };
  const specs: Record<FilterKey, FilterSpec> = {
    q: {
      kind: 'text',
      placeholder: 'Name, company, title or ID',
      hint: 'Searches name, company, title and ID',
    },
    company: {
      kind: 'text',
      placeholder: 'Company contains…',
      suggestions: [...new Set(allRows.map((l) => l.company || '').filter(Boolean))],
    },
    location: {
      kind: 'text',
      placeholder: 'Location contains…',
      hint: 'This page only',
      suggestions: [...new Set(allRows.map((l) => l.location || '').filter(Boolean))],
    },
    campaign_id: {
      kind: 'values',
      multi: true,
      options: [
        { value: '__none__', label: 'Unassigned' },
        ...(campaigns.data || []).map((c) => ({ value: String(c.id), label: c.name })),
      ],
    },
    account_id: {
      kind: 'values',
      multi: true,
      options: (accounts.data || []).map((a) => ({ value: String(a.id), label: a.name })),
    },
    status: {
      kind: 'values',
      multi: true,
      options: Object.entries(STATUS_META).map(([k, m]) => ({ value: k || '__untouched__', label: m.label })),
    },
    created: { kind: 'range', fromLabel: 'From', toLabel: 'To' },
    contact: { kind: 'range', fromLabel: 'From', toLabel: 'To' },
    followup: { kind: 'range', fromLabel: 'From', toLabel: 'To' },
    reply: {
      kind: 'values',
      multi: false,
      options: [
        { value: 'replied', label: 'Replied' },
        ...REPLY_CATEGORIES,
        { value: 'error:only', label: 'With send errors' },
        { value: 'error:none', label: 'Without errors' },
      ],
    },
    opentomsg: {
      kind: 'values',
      multi: false,
      options: [
        { value: 'yes', label: 'Open' },
        { value: 'no', label: 'Not open' },
        { value: 'unchecked', label: 'Unchecked' },
      ],
    },
  };
  const filterControl = (key: FilterKey) => (
    <ColumnFilter
      label={LABELS[key]}
      spec={specs[key]}
      value={filters[key]}
      open={openFilter === key}
      onOpen={(v) => setOpenFilter(v ? key : null)}
      onApply={(v) => update(key, v)}
    />
  );
  const header = (key: FilterKey, asc: string, desc: string, sortLabel?: string) => (
    <SortHeader
      label={LABELS[key]}
      sortLabel={sortLabel}
      active={sort === asc || sort === desc}
      direction={sort === asc ? 'asc' : sort === desc ? 'desc' : null}
      onClick={() => {
        setSort(sort === asc ? desc : asc);
        setPage(1);
        setSelected([]);
      }}
      filter={filterControl(key)}
    />
  );
  const chipText = (key: FilterKey) => {
    const spec = specs[key];
    const values = filters[key];
    return (
      (spec.kind === 'values'
        ? values.map((v) => spec.options.find((o) => o.value === v)?.label || v).join(', ')
        : spec.kind === 'range'
          ? (values[0] || 'Any start') + ' → ' + (values[1] || 'Any end')
          : values[0]) + (key === 'location' || key === 'opentomsg' ? ' (page)' : '')
    );
  };
  const removeErrors = async () => {
    if (!selected.length || actionBusy) return;
    setActionBusy(true);
    try {
      const r = await apiPost<{ reset: number; skipped: number }>('/api/leads/reset-errors', {
        ids: selected,
      });
      toast(r.reset + ' errors removed · ' + r.skipped + ' unchanged', 'ok');
      setSelected([]);
      await leads.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setActionBusy(false);
    }
  };
  const previewDelete = async () => {
    if (!selected.length || actionBusy) return;
    setActionBusy(true);
    try {
      const ids = [...selected];
      const r = await apiPost<DeletePreview>('/api/leads/delete-preview', { ids });
      setDeletePreview({ ...r, ids });
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setActionBusy(false);
    }
  };
  const confirmDelete = async () => {
    if (!deletePreview || actionBusy) return;
    setActionBusy(true);
    try {
      const r = await apiPost<{ deleted: number; skipped: number }>('/api/leads/bulk-delete-v2', {
        ids: deletePreview.ids,
      });
      toast(r.deleted + ' leads deleted · ' + r.skipped + ' skipped', 'ok');
      setDeletePreview(null);
      setSelected([]);
      await leads.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setActionBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Leads"
        subtitle="Your outreach pipeline"
        actions={
          <>
            <Button
              size="sm"
              variant="secondary"
              icon={<Upload size={14} />}
              onClick={() => setCsv(true)}
              isStatic
            >
              Import CSV
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<FileSearch size={14} />}
              onClick={() => setImportJob('sync_leads')}
              isStatic
            >
              Import Saved Search
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<ListPlus size={14} />}
              onClick={() => setImportJob('import_list')}
              isStatic
            >
              Import List
            </Button>
            <a
              href={'/api/leads/export?' + leadParams(filters)}
              target="_blank"
              rel="noopener noreferrer"
              title={
                pageFiltered
                  ? 'Exports server matches; page-only filters are not included'
                  : 'Export all matching leads'
              }
              className="inline-flex h-8 items-center gap-1.5 rounded-control border border-border/80 bg-surface px-3 text-[13px] font-medium text-ink shadow-2xs hover:border-primary/50 hover:bg-surface-2 hover:text-primary active:scale-[0.98] transition-all"
            >
              <Download size={13} />
              Export CSV{pageFiltered ? ' (server matches)' : ''}
            </a>
          </>
        }
      />
      {!!selected.length && (
        <Card className="flex flex-wrap items-center gap-2 p-2.5">
          <span className="mr-2 text-xs font-medium">
            {selectedAllMatching
              ? `All ${nf.format(matchTotal || leads.data?.total || 0)} matching leads selected (across pages)`
              : `${selected.length} selected on this page`}
          </span>
          {!selectedAllMatching && (leads.data?.total ?? 0) > rows.length && (
            <Button
              size="sm"
              variant="secondary"
              disabled={idsBusy}
              onClick={() => void selectAllMatching()}
              isStatic
            >
              {idsBusy
                ? 'Selecting all…'
                : `Select all ${nf.format(leads.data?.total ?? 0)} matching leads across all pages`}
            </Button>
          )}
          {selectedAllMatching && (
            <Button size="sm" variant="ghost" onClick={() => { setSelectedAllMatching(false); setSelected([]); }} isStatic>
              Clear select-all
            </Button>
          )}
          <Button size="sm" variant="primary" onClick={() => setReassigning(true)} isStatic>
            Reassign
          </Button>
          <Button
            size="sm"
            disabled={actionBusy}
            title="Remove errors and restore previous stages"
            onClick={() => void removeErrors()}
            isStatic
          >
            Remove errors
          </Button>
          <Button
            size="sm"
            variant="danger"
            disabled={actionBusy}
            onClick={() => void previewDelete()}
            isStatic
          >
            Delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected([])} isStatic>
            Clear selection
          </Button>
        </Card>
      )}
      <Card className="p-2 sm:px-3 sm:py-2.5 shadow-2xs">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[200px] flex-1 basis-full sm:basis-auto">
            <Search
              size={14}
              aria-hidden
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted"
            />
            <Input
              aria-label="Search leads"
              placeholder="Search name, company, title…"
              value={filters.q[0] || ''}
              onChange={(e) => update('q', [e.target.value])}
              className="h-8 pl-8 text-[12.5px] rounded-lg"
            />
          </div>
          <FilterSelect
            label="Campaign"
            value={filters.campaign_id[0] || ''}
            onChange={(e) => update('campaign_id', [e.target.value])}
            className="h-8 text-[12.5px] rounded-lg sm:w-[170px]"
          >
            <option value="">All campaigns</option>
            <option value="__none__">Unassigned</option>
            {(campaigns.data || []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </FilterSelect>
          <Button
            size="sm"
            variant="secondary"
            className="h-8 px-2.5 text-xs font-medium"
            icon={<ListFilter size={13} />}
            onClick={() => {
              setOpenFilter(null);
              setMore(true);
            }}
            isStatic
          >
            Filters ({activeKeys.length})
          </Button>

          {/* Desktop inline lead counter */}
          <div className="ml-auto hidden lg:flex items-center gap-1.5 text-[12px] text-muted font-medium whitespace-nowrap pl-2">
            <span className="font-semibold text-foreground">{nf.format(leads.data?.total || 0)}</span>
            <span>leads match</span>
            {activeKeys.length > 0 && <span className="text-muted/70">· {activeKeys.length} active</span>}
            {pageFiltered && <span className="text-muted/70">· {rows.length}/{allRows.length} on page</span>}
          </div>
        </div>

        {activeKeys.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-line/60 pt-2">
            {activeKeys.map((k) => (
              <span key={k} className="filter-chip text-[11px] py-0.5 px-2">
                <span>
                  {LABELS[k]}: {chipText(k)}
                </span>
                <button
                  type="button"
                  aria-label={'Remove ' + LABELS[k] + ' filter'}
                  onClick={() => update(k, [])}
                >
                  <X size={11} />
                </button>
              </span>
            ))}
            {activeKeys.length >= 2 && (
              <button
                type="button"
                className="px-1.5 text-[11px] font-medium text-primary hover:underline"
                onClick={resetFilters}
              >
                Clear all
              </button>
            )}
          </div>
        )}

        <p aria-live="polite" className="mt-1.5 text-[11.5px] text-muted lg:hidden">
          {nf.format(leads.data?.total || 0)} leads match · {activeKeys.length} filter
          {activeKeys.length === 1 ? '' : 's'} active
          {pageFiltered
            ? ' · ' + rows.length + ' of ' + allRows.length + ' on this page match page-only filters'
            : ''}
        </p>
      </Card>
      {leads.loading && !leads.data ? (
        <Loading label="Loading leads…" />
      ) : leads.error ? (
        <ErrorState message={leads.error} onRetry={leads.reload} />
      ) : (
        <Card className="overflow-hidden">
          <div className="dt-wrap">
            <table className="dt leads-table">
              <colgroup>
                {[3, 17, 12, 11, 9, 11, 8, 8, 7, 7, 4, 3].map((w, i) => (
                  <col key={i} style={{ width: w + '%' }} />
                ))}
              </colgroup>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="Select all leads on this page"
                      checked={allSelected}
                      onChange={(e) => {
                        setSelectedAllMatching(false);
                        setSelected(e.target.checked ? rows.map((r) => r.id) : []);
                      }}
                    />
                  </th>
                  {header('q', 'lead_name', 'lead_name_desc')}
                  {header('company', 'company', 'company_desc')}
                  {header('location', 'location', 'location_desc')}
                  {header('campaign_id', 'campaign', 'campaign_desc')}
                  {header('account_id', 'account', 'account_desc')}
                  {header('status', 'stage', 'stage_desc')}
                  {header('created', 'created', 'created_desc', 'Added date')}
                  {header('contact', 'contact', 'contact_desc', 'Initial contact')}
                  {header('followup', 'followup', 'followup_desc', 'Last follow-up')}
                  <th className="reply-head">
                    <span className="th-inner">
                      <span>Reply</span>
                      {filterControl('reply')}
                    </span>
                  </th>
                  <th>
                    <span className="sr-only">Details</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((l) => {
                  const meta = STATUS_META[l.status] || {
                    label: l.status || 'Untouched',
                    tone: 'idle' as Tone,
                  };
                  const ch = channel(l.status),
                    url = profileUrl(l);
                  return (
                    <tr key={l.id} data-open onClick={() => setDetail(l)}>
                      <td onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          aria-label={'Select ' + l.full_name}
                          checked={selected.includes(l.id)}
                          onChange={(e) =>
                            setSelected((prev) =>
                              e.target.checked ? [...prev, l.id] : prev.filter((id) => id !== l.id),
                            )
                          }
                        />
                      </td>
                      <td>
                        {url ? (
                          <a
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={'Open ' + l.full_name + ' on LinkedIn'}
                            aria-label={'Open ' + l.full_name + ' on LinkedIn'}
                            onClick={(e) => e.stopPropagation()}
                            className="block truncate font-medium hover:text-primary hover:underline"
                          >
                            {l.full_name}
                            <ExternalLink size={11} className="ml-1 inline opacity-60" aria-hidden />
                          </a>
                        ) : (
                          <button
                            type="button"
                            className="block max-w-full truncate text-left font-medium hover:text-primary"
                            onClick={() => setDetail(l)}
                          >
                            {l.full_name}
                          </button>
                        )}
                        <span className="lead-subline">
                          {ch && (
                            <span className="chip" data-tone={ch.tone}>
                              <ChannelIcon tone={ch.tone} />
                              {ch.label}
                            </span>
                          )}
                          {l.title && (
                            <span className="truncate" title={l.title}>
                              {l.title}
                            </span>
                          )}
                        </span>
                      </td>
                      <td>
                        <span className="block truncate" title={l.company || undefined}>
                          {l.company || '—'}
                        </span>
                      </td>
                      <td>
                        <span className="block truncate" title={l.location || undefined}>
                          {l.location || '—'}
                        </span>
                      </td>
                      <td>
                        <span className="block truncate" title={l.campaign_name || l.campaign || undefined}>
                          {l.campaign_name || l.campaign || 'Unassigned'}
                        </span>
                      </td>
                      <td>
                        {l.associate_account ? (
                          <span className="flex min-w-0 items-center gap-1.5">
                            <Avatar name={l.associate_account} size="sm" />
                            <span className="truncate" title={l.associate_account}>
                              {l.associate_account}
                            </span>
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td title={meta.label}>
                        <Pill tone={meta.tone}>{meta.label}</Pill>
                      </td>
                      <td title={fmtDT(l.created_at)}>
                        <span className="block truncate">{fmtDate(l.created_at)}</span>
                        <span className="sub truncate">{ago(l.created_at)}</span>
                      </td>
                      <td title={fmtDT(l.first_contacted_at)}>
                        <span className="block truncate">
                          {l.first_contacted_at ? fmtDate(l.first_contacted_at) : 'Not yet'}
                        </span>
                      </td>
                      <td title={fmtDT(l.last_followup_at)}>
                        <span className="block truncate">
                          {l.last_followup_at ? fmtDate(l.last_followup_at) : '—'}
                        </span>
                      </td>
                      <td
                        title={
                          l.received_replies ? CATEGORY_LABELS[l.reply_category] || 'Replied' : 'No reply'
                        }
                      >
                        {l.received_replies ? (
                          <span
                            className="block truncate text-[10.5px] text-ok"
                            aria-label={CATEGORY_LABELS[l.reply_category] || 'Replied'}
                          >
                            {CATEGORY_LABELS[l.reply_category] || 'Replied'}
                          </span>
                        ) : (
                          '—'
                        )}
                        {l.comment_count > 0 && (
                          <span
                            className="sub flex items-center gap-0.5"
                            title={`${l.comment_count} comments`}
                          >
                            <MessageSquare size={10} aria-hidden />
                            {l.comment_count}
                          </span>
                        )}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="lead-detail-button"
                          aria-label={'View details for ' + l.full_name}
                          onClick={(e) => {
                            e.stopPropagation();
                            setDetail(l);
                          }}
                        >
                          <ChevronRight size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {!rows.length && (
                  <tr>
                    <td colSpan={12}>
                      <EmptyState
                        icon={<ListFilter size={20} />}
                        title="No leads match"
                        body="Adjust the filters, or import leads."
                      />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2">
            <label className="flex items-center gap-2 text-xs text-muted">
              Rows per page
              <select
                aria-label="Rows per page"
                className="rounded border border-line bg-surface px-2 py-1"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                  setSelected([]);
                  setSelectedAllMatching(false);
                }}
              >
                {[25, 50, 100, 200].map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                disabled={page <= 1}
                onClick={() => {
                  setPage(page - 1);
                  setSelected([]);
                  setSelectedAllMatching(false);
                }}
                isStatic
              >
                Previous
              </Button>
              <span className="text-xs text-muted">
                Page {page} of {pages}
              </span>
              <Button
                size="sm"
                disabled={page >= pages}
                onClick={() => {
                  setPage(page + 1);
                  setSelected([]);
                  setSelectedAllMatching(false);
                }}
                isStatic
              >
                Next
              </Button>
            </div>
          </div>
        </Card>
      )}
      <MoreFilters
        open={more}
        onClose={() => setMore(false)}
        filters={filters}
        specs={specs}
        onApply={(f) => {
          setFilters(f);
          setPage(1);
          setSelected([]);
          setMore(false);
        }}
      />
      <CsvImport
        open={csv}
        campaigns={campaigns.data || []}
        onClose={() => setCsv(false)}
        onDone={() => void leads.reload()}
      />
      <Modal
        open={!!deletePreview}
        title="Delete selected leads"
        onClose={() => {
          if (!actionBusy) setDeletePreview(null);
        }}
        footer={
          <>
            <Button onClick={() => setDeletePreview(null)} disabled={actionBusy} isStatic>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={actionBusy || !deletePreview?.existing}
              onClick={() => void confirmDelete()}
              isStatic
            >
              {actionBusy ? 'Deleting…' : 'Delete ' + (deletePreview?.existing || 0) + ' leads'}
            </Button>
          </>
        }
      >
        {deletePreview && (
          <div className="flex flex-col gap-3 text-sm">
            <p>
              {deletePreview.existing} leads will be permanently deleted; {deletePreview.missing} selected
              leads are already missing or inaccessible.
            </p>
            <ul>
              {deletePreview.campaigns.map((c) => (
                <li key={c.campaign}>
                  {c.campaign}: {c.count}
                </li>
              ))}
            </ul>
            <p className="text-muted">
              {deletePreview.comments_to_remove} comments and {deletePreview.events_to_remove} lead events
              will be removed. Run logs are retained.
            </p>
          </div>
        )}
      </Modal>
      <LeadDetail
        lead={detail}
        campaigns={campaigns.data || []}
        onClose={() => setDetail(null)}
        onChanged={() => void leads.reload()}
      />
      <ReassignDialog
        open={reassigning}
        ids={selected}
        campaigns={campaigns.data || []}
        accounts={accounts.data || []}
        onClose={() => setReassigning(false)}
        onDone={() => {
          setReassigning(false);
          setSelected([]);
          void leads.reload();
        }}
      />
      <ImportDialog
        job={importJob}
        campaigns={campaigns.data || []}
        accounts={accounts.data || []}
        onClose={() => setImportJob(null)}
        onStarted={() => {
          setImportJob(null);
          void leads.reload();
        }}
      />
    </div>
  );
}
interface DeletePreview {
  existing: number;
  missing: number;
  campaigns: { campaign: string; count: number }[];
  comments_to_remove: number;
  events_to_remove: number;
}
function MoreFilters({
  open,
  onClose,
  filters,
  specs,
  onApply,
}: {
  open: boolean;
  onClose: () => void;
  filters: Filters;
  specs: Record<FilterKey, FilterSpec>;
  onApply: (f: Filters) => void;
}) {
  const [draft, setDraft] = useState(filters),
    [seeded, setSeeded] = useState(false);
  if (open && !seeded) {
    setSeeded(true);
    setDraft(filters);
  }
  if (!open && seeded) setSeeded(false);
  const invalid = (['created', 'contact', 'followup'] as const).some(
    (k) => draft[k][0] && draft[k][1] && draft[k][0] > draft[k][1],
  );
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Lead filters"
      size="lg"
      footer={
        <>
          <Button onClick={() => setDraft(emptyFilters())} isStatic>
            Clear all
          </Button>
          <Button onClick={onClose} isStatic>
            Cancel
          </Button>
          <Button variant="primary" disabled={invalid} onClick={() => onApply(draft)} isStatic>
            Apply filters
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {(Object.keys(specs) as FilterKey[]).map((k) => (
          <section key={k} className="rounded-panel border border-line p-3">
            <h3 className="mb-2 text-sm">{LABELS[k]}</h3>
            {k === 'opentomsg' && <p className="mb-2 text-xs text-muted">This page only</p>}
            <FilterFields
              label={LABELS[k]}
              spec={specs[k]}
              value={draft[k]}
              onChange={(v) => setDraft((prev) => ({ ...prev, [k]: v }))}
            />
          </section>
        ))}
      </div>
      {invalid && (
        <p role="alert" className="mt-2 text-xs text-crit">
          End dates must follow start dates.
        </p>
      )}
    </Modal>
  );
}
function CsvImport({
  open,
  onClose,
  campaigns,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  campaigns: CampaignRow[];
  onDone: () => void;
}) {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [campaign, setCampaign] = useState(''),
    [file, setFile] = useState<File | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [result, setResult] = useState<{ added: number; skipped: number; errors: string[] } | null>(null),
    [seeded, setSeeded] = useState(false),
    [version, setVersion] = useState(0);
  if (open && !seeded) {
    setSeeded(true);
    setCampaign('');
    setFile(null);
    setBusy(false);
    setError('');
    setResult(null);
    setVersion((v) => v + 1);
  }
  if (!open && seeded) setSeeded(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file || busy) return;
    if (!campaign) {
      setError('Destination campaign is required. Please select a campaign before importing.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const body = new FormData();
      body.append('file', file);
      const r = await apiPost<{ added: number; skipped: number; errors: string[] }>(
        '/api/leads/import-csv?campaign_id=' + encodeURIComponent(campaign),
        body,
      );
      setResult(r);
      toast(r.added + ' leads imported · ' + r.skipped + ' skipped', 'ok');
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      title="Import CSV"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose} isStatic>
            Close
          </Button>
          {!result && (
            <Button
              variant="primary"
              form="csv-form"
              type="submit"
              disabled={!file || !campaign || busy || campaigns.length === 0}
              isStatic
            >
              {busy ? 'Importing…' : 'Import CSV'}
            </Button>
          )}
        </>
      }
    >
      <form id="csv-form" onSubmit={submit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label className="text-[13px] font-medium text-ink">CSV file</label>
          <p className="-mt-1 text-[12px] text-muted">
            Required: full_name, or first_name and last_name. Optional: sales_nav_id, linkedin_url, sales_nav_urn, title, company, location, opentomsg.
          </p>
          <div
            className={cn(
              'relative flex flex-col items-center justify-center rounded-[14px] border-2 border-dashed p-6 text-center transition-all cursor-pointer',
              file
                ? 'border-primary/50 bg-primary-tint/25'
                : 'border-border/80 bg-surface-2/60 hover:border-primary/40 hover:bg-surface-2',
            )}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              const f = e.dataTransfer.files?.[0];
              if (f) setFile(f);
            }}
          >
            <input
              ref={fileInputRef}
              key={version}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            {file ? (
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary-tint text-primary shadow-xs">
                  <FileSpreadsheet size={24} aria-hidden />
                </div>
                <div className="text-left">
                  <div className="font-semibold text-[13.5px] text-foreground">{file.name}</div>
                  <div className="text-[12px] text-muted">{(file.size / 1024).toFixed(1)} KB · Ready to import</div>
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setFile(null);
                  }}
                  className="ml-3 rounded-lg p-1.5 text-muted hover:bg-crit-tint/50 hover:text-crit transition-colors"
                  title="Remove file"
                >
                  <X size={16} aria-hidden />
                </button>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-primary/20 bg-primary-tint/50 text-primary shadow-xs">
                  <UploadCloud size={22} aria-hidden />
                </div>
                <div>
                  <span className="font-semibold text-[13.5px] text-primary hover:underline">Choose a file</span>
                  <span className="text-[13px] text-muted"> or drag &amp; drop it here</span>
                </div>
                <p className="text-[11.5px] text-muted">Supports standard CSV files with header row</p>
              </div>
            )}
          </div>
        </div>
        <p className="text-xs text-muted">
          Column headers must match the{' '}
          <a
            href="/api/leads/import-template"
            download="leads_import_template.csv"
            className="font-medium text-primary hover:underline"
          >
            CSV template
          </a>. Select the destination campaign before importing.
        </p>
        <Field
          label={
            <>
              Destination campaign <span className="text-crit font-bold" title="Required">*</span>
            </>
          }
          hint={campaigns.length === 0 ? 'No campaigns available. Please create a campaign first.' : undefined}
        >
          <Select
            required
            value={campaign}
            onChange={(e) => {
              setCampaign(e.target.value);
              if (error) setError('');
            }}
          >
            <option value="" disabled>
              Select destination campaign (Required)…
            </option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
        <p className="text-xs text-muted">
          CSV leads start without an outreach account. Use Reassign after importing to choose one.
        </p>
        {error && (
          <p role="alert" className="text-sm text-crit">
            {error}
          </p>
        )}
        {result && (
          <div role="status" className="text-sm">
            <strong>
              {result.added} imported · {result.skipped} skipped
            </strong>
            {!!result.errors?.length && (
              <pre className="mt-2 max-h-[180px] overflow-auto whitespace-pre-wrap text-xs text-crit">
                {result.errors.join('\n')}
              </pre>
            )}
          </div>
        )}
      </form>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/* Bulk reassign                                                              */
/* -------------------------------------------------------------------------- */

/* The server treats "field present in the body" as "change this field", so the
   chosen destination is sent explicitly (a null value is a real unassignment). */
function ReassignDialog({
  open,
  ids,
  campaigns,
  accounts,
  onClose,
  onDone,
}: {
  open: boolean;
  ids: number[];
  campaigns: CampaignRow[];
  accounts: AccountRow[];
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [target, setTarget] = useState<'campaign' | 'account'>('campaign');
  const [campaignId, setCampaignId] = useState('');
  const [accountId, setAccountId] = useState('');
  const [busy, setBusy] = useState(false);

  const [seeded, setSeeded] = useState(false);
  if (open && !seeded) {
    setSeeded(true);
    setTarget('campaign');
    setCampaignId('');
    setAccountId('');
    setBusy(false);
  }
  if (!open && seeded) setSeeded(false);
  if (!open) return null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const body: Record<string, unknown> = { ids };
      if (target === 'campaign') body.campaign_id = campaignId ? Number(campaignId) : null;
      else body.account_id = accountId ? Number(accountId) : null;
      await apiPost('/api/leads/reassign', body);
      toast(`${ids.length} lead(s) reassigned`, 'ok');
      setCampaignId('');
      setAccountId('');
      onDone();
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
      title={`Reassign ${ids.length} lead(s)`}
      size="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} isStatic>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="reassign-form" disabled={busy} isStatic>
            {busy ? 'Reassigning…' : 'Reassign'}
          </Button>
        </>
      }
    >
      <form id="reassign-form" className="flex flex-col gap-4" onSubmit={submit}>
        <p className="rounded-panel bg-inset p-3 text-[12.5px] text-muted">
          Stage, history and replies are preserved. Only the campaign or sending account changes.
        </p>

        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium">What to change</span>
          <div className="seg" role="group" aria-label="What to change">
            <button type="button" aria-pressed={target === 'campaign'} onClick={() => setTarget('campaign')}>
              Campaign
            </button>
            <button type="button" aria-pressed={target === 'account'} onClick={() => setTarget('account')}>
              Sending account
            </button>
          </div>
        </div>

        {target === 'campaign' ? (
          <Field
            label="Campaign"
            hint="Choose “No campaign” to move these leads back to the unassigned pool."
          >
            <Select required value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
              <option value="">No campaign (unassign)</option>
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
        ) : (
          <Field label="Sending account" hint="Choose “No account” to clear the sending account.">
            <Select required value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">No account (clear)</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                  {a.status !== 'active' ? ` — ${a.status.replace(/_/g, ' ')}` : ''}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </form>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/* Lead detail popup — metadata, assignment, review, comments and history      */
/* -------------------------------------------------------------------------- */

interface TimelinePayload {
  lead: {
    id: number;
    full_name: string;
    company: string | null;
    title: string | null;
    status: string;
    received_replies: boolean;
    reply_message: string | null;
  };
  events: { kind: string; detail: string; job: string | null; at: string | null }[];
}

interface CommentRow {
  id: number;
  author: string;
  body: string;
  created_at: string | null;
  updated_at: string | null;
}

function LeadDetail({
  lead,
  campaigns,
  onClose,
  onChanged,
}: {
  lead: Lead | null;
  campaigns: CampaignRow[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const leadId = lead?.id ?? null;

  const timeline = useAsync<TimelinePayload>(
    () =>
      leadId ? apiGet(`/api/leads/${leadId}/timeline`) : Promise.resolve(null as unknown as TimelinePayload),
    [leadId],
  );
  const comments = useAsync<CommentRow[]>(
    () => (leadId ? apiGet(`/api/leads/${leadId}/comments`) : Promise.resolve([])),
    [leadId],
  );

  const [category, setCategory] = useState('');
  const [assignTo, setAssignTo] = useState('');
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);

  // Re-seed local controls whenever a different lead opens.
  const [seeded, setSeeded] = useState<number | null>(null);
  if (lead && seeded !== lead.id) {
    setSeeded(lead.id);
    setCategory(lead.reply_category || '');
    setAssignTo(lead.campaign_id != null ? String(lead.campaign_id) : '');
    setComment('');
  }
  if (!lead && seeded !== null) setSeeded(null);

  if (!lead || leadId == null) return null;

  const meta = STATUS_META[lead.status] ?? { label: lead.status || 'Untouched', tone: 'idle' as Tone };

  const run = async (fn: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await fn();
      toast(message, 'ok');
      onChanged();
      void timeline.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={lead.full_name} size="lg">
      {profileUrl(lead) && (
        <a
          href={profileUrl(lead)}
          target="_blank"
          rel="noopener noreferrer"
          className="mb-3 inline-flex items-center gap-2 rounded-control border border-line px-3 py-1.5 text-xs text-primary"
        >
          Open LinkedIn
          <ExternalLink size={12} />
        </a>
      )}
      {timeline.loading && !timeline.data ? (
        <Loading label="Loading history…" />
      ) : timeline.error ? (
        <ErrorState message={timeline.error} onRetry={timeline.reload} />
      ) : (
        <div className="flex flex-col gap-5">
          {/* Header */}
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={meta.tone}>{meta.label}</Pill>
            {lead.received_replies && (
              <Pill tone="ok" dot>
                Replied
              </Pill>
            )}
            {lead.review_status && <Pill tone="idle">{lead.review_status.replace(/_/g, ' ')}</Pill>}
            {lead.reply_category && (
              <Pill tone="info">
                {REPLY_CATEGORIES.find((c) => c.value === lead.reply_category)?.label ?? lead.reply_category}
              </Pill>
            )}
            <span className="text-[12px] text-muted">
              {[lead.title, lead.company].filter(Boolean).join(' · ') || '—'}
            </span>
          </div>

          {lead.reply_message && (
            <div className="rounded-panel bg-inset p-3">
              <h3 className="label">Reply received</h3>
              <p className="mt-1.5 whitespace-pre-wrap text-[13px] text-ink2">{lead.reply_message}</p>
            </div>
          )}

          {lead.last_error && (
            <p role="alert" className="rounded-panel bg-[var(--crit-tint)] p-3 text-[13px] text-crit">
              {lead.last_error}
            </p>
          )}

          {/* Metadata */}
          <section>
            <h3 className="label">Details</h3>
            <dl className="mt-2 grid gap-x-4 gap-y-2.5 sm:grid-cols-2">
              <Fact
                k="Source"
                v={
                  lead.source === 'list_import'
                    ? 'List import / CSV'
                    : lead.source === 'campaign_search'
                      ? 'Saved search'
                      : lead.source || '—'
                }
              />
              <Fact k="Sending account" v={lead.associate_account || '—'} />
              <Fact k="Location" v={lead.location || '—'} />
              <Fact k="Added" v={lead.created_at ? fmtDT(lead.created_at) : '—'} />
              <Fact
                k="First contacted"
                v={lead.first_contacted_at ? fmtDT(lead.first_contacted_at) : 'Never'}
              />
              <Fact
                k="Last follow-up"
                v={
                  lead.last_followup_at
                    ? `${fmtDT(lead.last_followup_at)}${lead.last_followup_stage ? ` · ${lead.last_followup_stage}` : ''}`
                    : '—'
                }
              />
            </dl>
          </section>

          {/* Assignment + categorisation */}
          <section className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium">Campaign</span>
              <Select
                aria-label="Assign campaign"
                value={assignTo}
                disabled={busy}
                onChange={(e) => {
                  const next = e.target.value;
                  setAssignTo(next);
                  void run(
                    () => apiPut(`/api/leads/${lead.id}/assign`, { campaign_id: next ? Number(next) : null }),
                    'Campaign updated',
                  );
                }}
              >
                <option value="">Unassigned</option>
                {campaigns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium">Reply category</span>
              <Select
                aria-label="Reply category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="">Choose a category…</option>
                {REPLY_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </label>
            <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={busy || !category || category === lead.reply_category}
                onClick={() =>
                  void run(() => apiPut(`/api/leads/${lead.id}/category`, { category }), 'Category saved')
                }
                isStatic
              >
                Save category
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy || lead.review_status === 'reviewed'}
                onClick={() =>
                  void run(
                    () => apiPost(`/api/leads/${lead.id}/review`, { review_status: 'reviewed' }),
                    'Marked reviewed',
                  )
                }
                isStatic
              >
                Mark reviewed
              </Button>
            </div>
          </section>

          {/* Comments */}
          <section>
            <h3 className="flex items-center gap-1.5 text-[14px]">
              <MessageSquare size={15} aria-hidden />
              Comments
              {(comments.data?.length ?? 0) > 0 && (
                <span className="num text-[12px] text-muted">({comments.data!.length})</span>
              )}
            </h3>
            <div className="mt-2 flex flex-col gap-2">
              <div className="flex items-end gap-2">
                <Input
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Add a note for your team…"
                  aria-label="New comment"
                />
                <Button
                  variant="secondary"
                  disabled={busy || !comment.trim()}
                  onClick={() =>
                    void run(async () => {
                      await apiPost(`/api/leads/${lead.id}/comments`, { body: comment.trim() });
                      setComment('');
                      await comments.reload();
                    }, 'Comment added')
                  }
                  isStatic
                >
                  Post
                </Button>
              </div>
              {comments.loading && !comments.data ? (
                <p className="text-[13px] text-muted">Loading comments…</p>
              ) : comments.data?.length ? (
                <ul className="flex flex-col gap-1.5">
                  {comments.data.map((c) => (
                    <li key={c.id} className="group flex items-start gap-3 rounded-[10px] bg-inset p-2.5">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-[12.5px] font-medium">{c.author}</span>
                          <time className="shrink-0 text-[11px] text-muted" title={fmtDT(c.created_at)}>
                            {ago(c.created_at)}
                          </time>
                        </div>
                        <p className="mt-0.5 whitespace-pre-wrap text-[13px] text-ink2">{c.body}</p>
                      </div>
                      <button
                        type="button"
                        aria-label="Delete comment"
                        title="Delete comment"
                        className="shrink-0 rounded-md p-1 text-muted opacity-0 transition-opacity duration-150 ease-out hover:bg-[var(--crit-tint)] hover:text-crit focus-visible:opacity-100 group-hover:opacity-100"
                        onClick={() => {
                          if (!window.confirm('Delete this comment?')) return;
                          void run(async () => {
                            await apiDelete(`/api/comments/${c.id}`);
                            await comments.reload();
                          }, 'Comment deleted');
                        }}
                      >
                        <Trash2 size={14} aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-muted">No comments yet.</p>
              )}
            </div>
          </section>

          {/* Event history */}
          <section>
            <h3 className="flex items-center gap-1.5 text-[14px]">
              <History size={15} aria-hidden />
              Event history
            </h3>
            {timeline.data?.events.length ? (
              <ol className="mt-2 flex flex-col gap-2">
                {timeline.data.events.map((ev, i) => (
                  <li key={i} className="flex gap-3 rounded-[10px] bg-inset p-2.5">
                    <span className="mt-0.5 shrink-0 text-[11px] uppercase tracking-wide text-muted">
                      {ev.kind}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px]">{ev.detail || '—'}</span>
                      <span className="block text-[11.5px] text-muted">
                        {fmtDT(ev.at)}
                        {ev.job ? ` · ${ev.job}` : ''}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="mt-1 text-[13px] text-muted">No events recorded for this lead yet.</p>
            )}
          </section>
        </div>
      )}
    </Modal>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[11px] uppercase tracking-wide text-muted">{k}</dt>
      <dd className="truncate text-[13px]">{v}</dd>
    </div>
  );
}
