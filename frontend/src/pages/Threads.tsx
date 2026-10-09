import { useState } from 'react';
import { ExternalLink, MessageSquareReply, MessagesSquare, Search, Send, ChevronDown, ChevronUp, Check } from 'lucide-react';
import { Button, Card, EmptyState, ErrorState, Loading, Segmented, cn } from '@/components/ui';
import { Input, PageHeader, Select, Textarea } from '@/components/form';
import { Modal } from '@/components/Modal';
import { apiGet, apiPost, apiPut } from '@/lib/api';
import { useAsync, useDebounced } from '@/lib/hooks';
import { useToast } from '@/lib/toast';
import { REPLY_CATEGORIES } from '@/lib/constants';
import { fmtDT, ago, initials } from '@/lib/format';

function getCategoryBadge(catValue?: string) {
  const norm = (catValue || 'unclassified').toLowerCase();
  const found = REPLY_CATEGORIES.find((c) => c.value === norm);
  const label = found?.label || catValue || 'Unclassified';

  switch (norm) {
    case 'positive':
      return {
        label,
        badgeClass: 'border-emerald-500/30 bg-emerald-500/12 text-emerald-700 dark:text-emerald-300 dark:bg-emerald-950/40 dark:border-emerald-800',
        dotClass: 'bg-emerald-500',
      };
    case 'declined':
    case 'unsubscribe':
      return {
        label,
        badgeClass: 'border-rose-500/30 bg-rose-500/12 text-rose-700 dark:text-rose-300 dark:bg-rose-950/40 dark:border-rose-800',
        dotClass: 'bg-rose-500',
      };
    case 'meeting':
      return {
        label,
        badgeClass: 'border-indigo-500/30 bg-indigo-500/12 text-indigo-700 dark:text-indigo-300 dark:bg-indigo-950/40 dark:border-indigo-800',
        dotClass: 'bg-indigo-500',
      };
    case 'referral':
      return {
        label,
        badgeClass: 'border-purple-500/30 bg-purple-500/12 text-purple-700 dark:text-purple-300 dark:bg-purple-950/40 dark:border-purple-800',
        dotClass: 'bg-purple-500',
      };
    case 'followup_later':
    case 'ooo':
      return {
        label,
        badgeClass: 'border-amber-500/30 bg-amber-500/12 text-amber-700 dark:text-amber-300 dark:bg-amber-950/40 dark:border-amber-800',
        dotClass: 'bg-amber-500',
      };
    case 'unclassified':
    default:
      return {
        label: 'Unclassified',
        badgeClass: 'border-border/80 bg-surface-2 text-muted dark:bg-slate-800/80 dark:border-slate-700 dark:text-slate-300',
        dotClass: 'bg-muted-foreground/60',
      };
  }
}

interface ThreadItem {
  id: number;
  full_name: string;
  title: string | null;
  company: string | null;
  campaign: string | null;
  campaign_id: number | null;
  campaign_name: string | null;
  account: string | null;
  account_id: number | null;
  reply_message: string | null;
  reply_received_at: string | null;
  status: string;
  reply_category: string;
  reply_category_source: string;
  review_status: string;
  reply_reviewed_at: string | null;
  linkedin_url: string;
  comment_count: number;
}

interface ThreadPage {
  total: number;
  page: number;
  page_size: number;
  items: ThreadItem[];
}

export default function Threads() {
  const [channel, setChannel] = useState<'all' | 'booked'>('all');
  const [sort, setSort] = useState('newest');
  const [category, setCategory] = useState('');
  const [review, setReview] = useState('');
  const [q, setQ] = useState('');
  const debouncedQ = useDebounced(q);
  const [page, setPage] = useState(1);
  const [activeThread, setActiveThread] = useState<ThreadItem | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  const toggleExpanded = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const { data, error, loading, reload } = useAsync<ThreadPage>(() => {
    const params = new URLSearchParams({ channel, sort, page: String(page), page_size: '25' });
    if (debouncedQ.trim()) params.set('q', debouncedQ.trim());
    if (category) params.set('category', category);
    if (review) params.set('review', review);
    return apiGet<ThreadPage>(`/api/threads?${params}`);
  }, [channel, sort, category, review, debouncedQ, page]);

  const items = data?.items ?? [];
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  // Sync active thread with reloaded data if it's currently open
  const openThread = activeThread ? (items.find((i) => i.id === activeThread.id) ?? activeThread) : null;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Threads & replies"
        subtitle={data ? `${data.total} replies received` : 'Reply inbox'}
        actions={
          <Segmented
            label="Channel"
            value={channel}
            onChange={(v) => {
              setChannel(v as 'all' | 'booked');
              setPage(1);
            }}
            options={[
              { value: 'all', label: 'All replies' },
              { value: 'booked', label: 'Booked' },
            ]}
          />
        }
      />

      <Card className="flex min-w-0 flex-col p-4">
        {/* Filters and search toolbar: neat, horizontal, single-row alignment */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2.5 border-b border-line pb-3.5">
          <div className="relative min-w-[240px] flex-1">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <Input
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
              placeholder="Search by name, company, or message content…"
              className="pl-9 h-9 text-[13px] w-full"
              aria-label="Search replies"
            />
          </div>
          <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap shrink-0">
            <Select
              aria-label="Filter by category"
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setPage(1);
              }}
              className="h-9 text-[12.5px] w-auto min-w-[135px]"
            >
              <option value="">All categories</option>
              {REPLY_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>

            <Select
              aria-label="Filter by review"
              value={review}
              onChange={(e) => {
                setReview(e.target.value);
                setPage(1);
              }}
              className="h-9 text-[12.5px] w-auto min-w-[125px]"
            >
              <option value="">Any review</option>
              <option value="needs_review">Needs review</option>
              <option value="reviewed">Reviewed</option>
              <option value="unreviewed">Unreviewed</option>
            </Select>

            <Select
              aria-label="Sort replies"
              value={sort}
              onChange={(e) => {
                setSort(e.target.value);
                setPage(1);
              }}
              className="h-9 text-[12.5px] w-auto min-w-[130px]"
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="lead_name">Name A–Z</option>
              <option value="lead_name_desc">Name Z–A</option>
              <option value="reviewed">Recently reviewed</option>
            </Select>
          </div>
        </div>

        {/* Reply List Table */}
        {loading && !data ? (
          <div className="py-12">
            <Loading />
          </div>
        ) : error ? (
          <div className="py-6">
            <ErrorState message={error} onRetry={reload} />
          </div>
        ) : items.length ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1150px] table-fixed border-collapse text-[13px]">
                <colgroup>
                  <col style={{ width: '18%' }} />
                  <col style={{ width: '28%' }} />
                  <col style={{ width: '14%' }} />
                  <col style={{ width: '17%' }} />
                  <col style={{ width: '11%' }} />
                  <col style={{ width: '6%' }} />
                  <col style={{ width: '6%' }} />
                </colgroup>
                <thead>
                  <tr className="border-b border-line/70 text-left text-[11px] font-semibold uppercase tracking-wider text-muted">
                    <th className="py-3 px-3">LEAD</th>
                    <th className="py-3 px-3">LATEST MESSAGE</th>
                    <th className="py-3 px-3">CAMPAIGN &amp; ACCOUNT</th>
                    <th className="py-3 px-3">CATEGORY</th>
                    <th className="py-3 px-3">REVIEW</th>
                    <th className="py-3 px-3">RECEIVED</th>
                    <th className="py-3 pr-4 text-right">ACTION</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/60">
                  {items.map((t) => {
                    const isExpanded = expandedIds.has(t.id);
                    const isLong = (t.reply_message?.length ?? 0) > 75 || (t.reply_message?.includes('\n') ?? false);
                    return (
                      <tr
                        key={t.id}
                        onClick={() => setActiveThread(t)}
                        className="group cursor-pointer transition-colors hover:bg-surface-2/60"
                      >
                        {/* LEAD */}
                        <td className="py-3 px-3 align-top">
                          <div className="flex items-center gap-2.5">
                            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-[12px] border border-primary/20">
                              {initials(t.full_name)}
                            </div>
                            <div className="min-w-0">
                              <div className="truncate font-semibold text-[13px] text-foreground group-hover:text-primary transition-colors">
                                {t.full_name}
                              </div>
                              <div className="truncate text-[11.5px] text-muted">
                                {[t.company, t.title].filter(Boolean).join(' · ') || '—'}
                              </div>
                            </div>
                          </div>
                        </td>

                        {/* LATEST MESSAGE PREVIEW with Read more option */}
                        <td className="py-3 px-3 align-top">
                          <div className="flex flex-col">
                            <p
                              className={cn(
                                'text-[12.5px] text-foreground/90 italic leading-snug break-words',
                                !isExpanded && 'line-clamp-2',
                              )}
                            >
                              {t.reply_message ? `"${t.reply_message}"` : '—'}
                            </p>
                            {isLong && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  toggleExpanded(t.id);
                                }}
                                className="mt-1 text-[11px] font-semibold text-primary hover:underline flex items-center gap-0.5 cursor-pointer self-start"
                              >
                                {isExpanded ? (
                                  <>Show less <ChevronUp size={11} /></>
                                ) : (
                                  <>Read more <ChevronDown size={11} /></>
                                )}
                              </button>
                            )}
                            {t.comment_count > 0 && (
                              <span className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-primary">
                                <MessagesSquare size={11} /> {t.comment_count} {t.comment_count === 1 ? 'note' : 'notes'}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* CAMPAIGN & ACCOUNT */}
                        <td className="py-3 px-3 align-top">
                          <div className="truncate text-[12px] font-medium text-foreground">
                            {t.campaign_name || t.campaign || '—'}
                          </div>
                          {t.account && <div className="truncate text-[11px] text-muted">via {t.account}</div>}
                        </td>

                        {/* CATEGORY */}
                        <td className="py-3 px-3 align-top">
                          {(() => {
                            const cat = getCategoryBadge(t.reply_category);
                            return (
                              <span
                                className={cn(
                                  'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-medium shadow-2xs',
                                  cat.badgeClass,
                                )}
                              >
                                <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', cat.dotClass)} aria-hidden />
                                <span>{cat.label}</span>
                              </span>
                            );
                          })()}
                        </td>

                        {/* REVIEW */}
                        <td className="py-3 px-3 align-top">
                          {t.review_status === 'reviewed' ? (
                            <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-emerald-500/30 bg-emerald-500/12 px-2.5 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300 shadow-2xs">
                              <Check size={11} className="shrink-0" />
                              Reviewed
                            </span>
                          ) : t.review_status === 'needs_review' ? (
                            <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-amber-500/35 bg-amber-500/15 px-2.5 py-0.5 text-[11px] font-semibold text-amber-700 dark:text-amber-400 shadow-2xs">
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden />
                              Needs review
                            </span>
                          ) : (
                            <span className="inline-flex items-center whitespace-nowrap rounded-full border border-border/70 bg-surface-2/60 px-2.5 py-0.5 text-[11px] font-medium text-muted">
                              Unreviewed
                            </span>
                          )}
                        </td>

                        {/* RECEIVED */}
                        <td className="py-3 px-3 text-[12px] text-muted whitespace-nowrap align-top">
                          {ago(t.reply_received_at)}
                        </td>

                        {/* ACTION */}
                        <td className="py-3 pr-4 text-right align-top" onClick={(e) => e.stopPropagation()}>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => setActiveThread(t)}
                            isStatic
                          >
                            View
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {pages > 1 && (
              <div className="mt-4 flex items-center justify-between border-t border-line/60 pt-3">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="h-8 text-xs"
                  isStatic
                >
                  Previous
                </Button>
                <span className="text-[12px] text-muted">
                  Page {page} of {pages} ({data?.total ?? 0} total)
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={page >= pages}
                  onClick={() => setPage((p) => p + 1)}
                  className="h-8 text-xs"
                  isStatic
                >
                  Next
                </Button>
              </div>
            )}
          </>
        ) : (
          <div className="py-12">
            <EmptyState
              icon={<MessageSquareReply size={24} aria-hidden />}
              title="No replies found"
              body="Replies land here when a lead answers an invite or message."
            />
          </div>
        )}
      </Card>

      {/* Reply Detail Modal Popup */}
      <Modal
        open={!!openThread}
        onClose={() => setActiveThread(null)}
        title={openThread ? `Reply from ${openThread.full_name}` : 'Reply Details'}
        size="lg"
        footer={
          openThread ? (
            <div className="flex w-full items-center justify-between">
              <span className="text-[11.5px] text-muted">
                Lead ID: #{openThread.id}
              </span>
              <Button variant="secondary" size="sm" onClick={() => setActiveThread(null)} isStatic>
                Close
              </Button>
            </div>
          ) : undefined
        }
      >
        {openThread && (
          <ThreadDetailModal
            thread={openThread}
            onChanged={() => {
              void reload();
            }}
          />
        )}
      </Modal>
    </div>
  );
}

function ThreadDetailModal({ thread, onChanged }: { thread: ThreadItem; onChanged: () => void }) {
  const toast = useToast();
  const [category, setCategory] = useState(thread.reply_category);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const comments = useAsync<{ id: number; author: string; body: string; created_at: string | null }[]>(
    () => apiGet(`/api/leads/${thread.id}/comments`),
    [thread.id],
  );

  const run = async (fn: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await fn();
      onChanged();
      toast(message, 'ok');
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'crit');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3.5">
      {/* Header Info */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-3">
        <div className="min-w-0">
          <h3 className="text-[17px] font-bold text-foreground">{thread.full_name}</h3>
          <p className="mt-0.5 text-[12.5px] text-muted">
            {[thread.title, thread.company].filter(Boolean).join(' · ') || 'No title / company'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(() => {
            const cat = getCategoryBadge(thread.reply_category);
            return (
              <span
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium shadow-2xs',
                  cat.badgeClass,
                )}
              >
                <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', cat.dotClass)} aria-hidden />
                <span>{cat.label}</span>
              </span>
            );
          })()}
          {thread.review_status === 'reviewed' ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/12 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-700 dark:text-emerald-300">
              <Check size={11} className="shrink-0" />
              Reviewed
            </span>
          ) : (
            <span
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold border',
                thread.review_status === 'needs_review'
                  ? 'border-amber-500/35 bg-amber-500/15 text-amber-700 dark:text-amber-400'
                  : 'border-border/80 bg-surface-2 text-muted',
              )}
            >
              {thread.review_status === 'needs_review' ? (
                <>
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden />
                  Needs review
                </>
              ) : (
                'Unreviewed'
              )}
            </span>
          )}
        </div>
      </div>

      {/* Meta tags */}
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
        {thread.campaign_name && (
          <span className="inline-flex items-center rounded-md bg-primary/10 border border-primary/20 px-2 py-0.5 font-medium text-primary text-[11.5px]">
            {thread.campaign_name}
          </span>
        )}
        {thread.account && <span>via <strong>{thread.account}</strong></span>}
        {thread.reply_received_at && <span>· Received {fmtDT(thread.reply_received_at)}</span>}
        {thread.linkedin_url && (
          <a
            href={thread.linkedin_url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline"
          >
            Open LinkedIn profile <ExternalLink size={12} aria-hidden />
          </a>
        )}
      </div>

      {/* Reply Message Quote Bubble */}
      <div className="rounded-xl border border-line bg-surface-2/70 p-4">
        <div className="flex items-center justify-between pb-1.5 border-b border-line/60">
          <span className="text-[11px] font-bold uppercase tracking-wider text-muted">
            Latest reply message
          </span>
          {thread.reply_received_at && (
            <span className="text-[11.5px] text-muted font-medium">
              {fmtDT(thread.reply_received_at)}
            </span>
          )}
        </div>
        <blockquote className="mt-2.5 whitespace-pre-wrap text-[13.5px] leading-relaxed text-foreground font-medium">
          {thread.reply_message ? `"${thread.reply_message}"` : 'No reply text captured.'}
        </blockquote>
      </div>

      {/* Perfectly Aligned Controls: Category & Review */}
      <div className="grid gap-3 sm:grid-cols-2 rounded-xl border border-line p-3.5 bg-card">
        {/* Reply Category */}
        <div className="flex flex-col gap-1.5">
          <span className="text-[12.5px] font-semibold text-foreground">Reply category</span>
          <div className="flex items-center gap-2">
            <Select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              aria-label="Reply category"
              className="h-8 flex-1 text-[12px] w-auto"
            >
              {REPLY_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </Select>
            <Button
              variant="secondary"
              size="sm"
              disabled={busy || !category.trim()}
              onClick={() => void run(() => apiPut(`/api/leads/${thread.id}/category`, { category }), 'Category saved')}
              className="h-8 px-2.5 text-xs font-semibold"
              isStatic
            >
              Save
            </Button>
          </div>
          <span className="text-[11px] text-muted">Manual categorization is preserved.</span>
        </div>

        {/* Review Status */}
        <div className="flex flex-col gap-1.5">
          <span className="text-[12.5px] font-semibold text-foreground">Review status</span>
          <div className="flex items-center gap-1.5 h-8">
            {(['needs_review', 'reviewed', ''] as const).map((v) => (
              <Button
                key={v || 'clear'}
                variant={thread.review_status === v ? 'primary' : 'secondary'}
                size="sm"
                disabled={busy}
                onClick={() =>
                  void run(() => apiPost(`/api/leads/${thread.id}/review`, { review_status: v }), 'Review updated')
                }
                className={cn(
                  'h-8 flex-1 text-xs font-semibold',
                  v === 'needs_review' && thread.review_status === v && 'bg-amber-500 hover:bg-amber-600 border-amber-600 text-white',
                  v === 'reviewed' && thread.review_status === v && 'bg-emerald-600 hover:bg-emerald-700 border-emerald-700 text-white',
                )}
                isStatic
              >
                {v === 'needs_review' ? 'Needs review' : v === 'reviewed' ? 'Reviewed' : 'Clear'}
              </Button>
            ))}
          </div>
          <span className="text-[11px] text-muted">Inbox review and triage state.</span>
        </div>
      </div>

      {/* Team Notes Section */}
      <div className="rounded-xl border border-line p-3.5 bg-card">
        <h4 className="text-[13px] font-semibold text-foreground flex items-center gap-1.5">
          <MessagesSquare size={14} className="text-primary" /> Internal team notes
        </h4>

        {comments.loading && !comments.data ? (
          <div className="py-4">
            <Loading label="Loading notes…" />
          </div>
        ) : comments.data?.length ? (
          <ul className="mt-2.5 flex flex-col gap-2 max-h-[160px] overflow-y-auto pr-1">
            {comments.data.map((c) => (
              <li key={c.id} className="rounded-lg border border-line/60 bg-surface-2/40 p-2.5 text-[12.5px]">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold text-foreground text-[12px]">{c.author}</span>
                  <time className="text-[11px] text-muted">{fmtDT(c.created_at)}</time>
                </div>
                <p className="mt-1 whitespace-pre-wrap text-foreground/90">{c.body}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[12px] text-muted">No notes on this reply yet.</p>
        )}

        <div className="mt-3 flex flex-col gap-2">
          <Textarea
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Add an internal note for your team…"
            aria-label="New note"
            className="text-[12.5px]"
          />
          <div className="flex justify-end">
            <Button
              variant="primary"
              size="sm"
              icon={<Send size={13} aria-hidden />}
              disabled={busy || !note.trim()}
              onClick={() =>
                void run(async () => {
                  await apiPost(`/api/leads/${thread.id}/comments`, { body: note.trim() });
                  setNote('');
                  await comments.reload();
                }, 'Note added')
              }
              className="h-8 text-xs font-medium"
              isStatic
            >
              Add note
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
