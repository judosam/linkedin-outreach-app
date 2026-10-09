/* Outreach Command Center — views part 3 (v2 views).
   Overrides viewLeads/viewThreads from views.js with the extended versions:
   - Leads: column sorting and campaign/account/pipeline filters,
     page sizes, select-all-matching with frozen server count, bulk delete.
   - Threads: server-side campaign/account/category/review
     filters + sorting (dropdown-pickers), reply categories, comments.
   NOTE: uses fresh const names to avoid collisions with views.js globals. */
'use strict';

/* ==================== LEADS (v2) ==================== */
const leadV2 = {
  campaign: '', status: '', q: '', page: 1,
  sort: 'newest', pageSize: 50, account: '', otm: '', error: '',
  contactFrom: '', contactTo: '', createdFrom: '', createdTo: '', followupFrom: '', followupTo: '',
  _campaigns: null, _accounts: null,
};
const leadSel = { ids: new Set(), allMatching: false, snapshot: null, count: null, excluded: new Set() };
/* Latest leads payload for the current page — used by row actions (reply modal). */
let leadDataCache = { items: [] };

/* Display name for a lead's campaign: prefer the live `campaign_name` the API
   now sends (reflects renames instantly), fall back to the cached campaign
   list, then to the immutable campaign_key. */
function campaignName(campaigns, l) {
  if (l.campaign_name) return l.campaign_name;
  const hit = campaigns.find(c => String(c.id) === String(l.campaign_id ?? l.campaign) || c.campaign_key === l.campaign);
  return hit?.name || l.campaign || '—';
}

/* Drop the Leads/Threads cached campaign lists so the next render refetches
   them — otherwise a campaign rename shows the old name until reload. */
function invalidateCampaignCaches() {
  leadV2._campaigns = null;
  threadV2._campaigns = null;
}

function leadSnapshot() {
  const s = leadV2;
  return JSON.stringify([s.campaign, s.status, s.q, s.sort, s.account, s.otm, s.error,
                         s.contactFrom, s.contactTo, s.createdFrom, s.createdTo, s.followupFrom, s.followupTo]);
}
function leadSelClear() {
  leadSel.ids.clear(); leadSel.allMatching = false; leadSel.snapshot = null; leadSel.count = null; leadSel.excluded.clear();
}
/* Date inputs are plain <input type=date> (YYYY-MM-DD). Convert to a local-
   time ISO instant so '2026-09-12' means that day in THIS machine's timezone,
   matching what the user sees in the table, not server-UTC. */
function localDayISO(v, end = false) {
  if (!v) return '';
  // Parsing without a timezone gives local midnight / end-of-day;
  // toISOString() is the correct UTC instant for that local moment.
  const d = new Date(`${v}T${end ? '23:59:59.999' : '00:00:00'}`);
  return Number.isNaN(d.getTime()) ? '' : d.toISOString();
}
function leadQS(forExport = false) {
  const s = leadV2;
  const u = new URLSearchParams();
  if (s.campaign) u.set('campaign_id', s.campaign);
  if (s.status) u.set('status', s.status);
  if (s.q) u.set('q', s.q);
  if (s.account) u.set('account_id', s.account);
  if (s.otm) u.set('opentomsg', s.otm);
  if (s.error) u.set('error', s.error);
  if (s.contactFrom) u.set('contact_from', localDayISO(s.contactFrom));
  if (s.contactTo) u.set('contact_to', localDayISO(s.contactTo, true));
  if (s.createdFrom) u.set('created_from', localDayISO(s.createdFrom));
  if (s.createdTo) u.set('created_to', localDayISO(s.createdTo, true));
  if (s.followupFrom) u.set('followup_from', localDayISO(s.followupFrom));
  if (s.followupTo) u.set('followup_to', localDayISO(s.followupTo, true));
  if (s.sort !== 'newest' || forExport) u.set('sort', s.sort);
  return u;
}
function leadFilterCount() {
  const s = leadV2;
  return [s.campaign, s.status, s.q, s.account, s.otm, s.error,
          s.contactFrom || s.contactTo, s.createdFrom || s.createdTo, s.followupFrom || s.followupTo].filter(Boolean).length;
}

/* Removable filter chips under the toolbar */
function leadChips(campaigns, accounts) {
  const s = leadV2;
  const chips = [];
  const push = (k, label, val) => chips.push({ k, label, val });
  if (s.q) push('q', 'Search', `“${s.q}”`);
  if (s.campaign === '__none__') push('campaign', 'Campaign', 'No campaign (unassigned)');
  else if (s.campaign) push('campaign', 'Campaign', campaigns.find(c => String(c.id) === s.campaign)?.name || `#${s.campaign}`);
  if (s.account) push('account', 'Account', accounts.find(a => String(a.id) === s.account)?.name || `#${s.account}`);
  if (s.status) push('status', 'Stage', s.status === '__untouched__' ? 'Untouched' : (STATUS_META[s.status]?.label || s.status));
  if (s.otm) push('otm', 'OpenToMsg', s.otm === 'yes' ? 'Open to messages' : s.otm === 'no' ? 'Not open' : 'Not checked');
  if (s.error) push('error', 'Errors', s.error === 'only' ? 'With send errors' : 'Without errors');
  const range = (key, label, a, b) => { if (a || b) push(key, label, `${a || '…'} → ${b || '…'}`); };
  range('contactDate', 'Contacted', s.contactFrom, s.contactTo);
  range('createdDate', 'Added', s.createdFrom, s.createdTo);
  range('followupDate', 'Follow-up', s.followupFrom, s.followupTo);
  if (!chips.length) return '';
  return `<div class="chip-row" role="list" aria-label="Active filters">
    <span class="chip-label">Filters</span>
    ${chips.map(c => `<span class="chip" role="listitem">${esc(c.label)}: <b>${esc(c.val)}</b>
      <button class="chip-x" data-chip-x="${c.k}" aria-label="Remove ${esc(c.label)} filter"><span class="msym">close</span></button></span>`).join('')}
  </div>`;
}

function leadSortHead(label, key) {
  const on = leadV2.sort === key || leadV2.sort === key + '_desc';
  const dir = leadV2.sort.endsWith('_desc') ? 'desc' : 'asc';
  const next = !on ? key : (dir === 'asc' ? key + '_desc' : 'newest');
  const cls = on ? (dir === 'asc' ? 'sort-asc' : 'sort-desc') : '';
  return `<button class="th-sort ${cls}" data-sort="${next}" aria-label="Sort by ${esc(label)}">${esc(label)}<span class="sort-ic msym">${on ? (dir === 'asc' ? 'arrow_upward' : 'arrow_downward') : 'unfold_more'}</span></button>`;
}

async function viewLeads() {
  const m = location.hash.match(/\?q=([^&]+)/);
  if (m) { leadV2.q = decodeURIComponent(m[1]); leadV2.page = 1; history.replaceState(null, '', '#/leads'); }
  await renderLeads2();
}

/* Keep a popover on-screen: panels anchor to their trigger's left edge, so a
   trigger near the right side of the filter bar pushed the panel off-screen.
   After unhiding, flip to right-anchored when it would overflow. */
function placePanel(btn, panel) {
  if (!btn || !panel || panel.hidden) return;
  panel.style.left = ''; panel.style.right = '';
  const r = panel.getBoundingClientRect();
  if (r.right > innerWidth - 8) { panel.style.left = 'auto'; panel.style.right = '0'; }
  if (panel.getBoundingClientRect().left < 8) { panel.style.left = '0'; panel.style.right = 'auto'; }
}

/* Compact pagination for page headers (top of view) */
function pagerHTML(prefix, page, totalPages, total, extra = '') {
  return `<div class="pager-top" role="navigation" aria-label="Pagination">
    <span class="mono muted small">Page ${page} of ${totalPages}${total != null ? ` · ${Number(total).toLocaleString()}` : ''}${extra}</span>
    <div style="display:flex;gap:6px">
      <button class="btn btn-secondary btn-sm icon-btn-pair" id="${prefix}Prev" ${page <= 1 ? 'disabled' : ''} aria-label="Previous page"><span class="msym">chevron_left</span></button>
      <button class="btn btn-secondary btn-sm icon-btn-pair" id="${prefix}Next" ${page >= totalPages ? 'disabled' : ''} aria-label="Next page"><span class="msym">chevron_right</span></button>
    </div>
  </div>`;
}

/* One delegated outside-click closer for ALL popovers (More filters, Dates,
   Threads popovers). Re-rendering used to attach a fresh document listener
   per panel per render — dozens of stale listeners after a few clicks. */
document.addEventListener('click', (e) => {
  $$('.dd-panel', MAIN).forEach(p => {
    if (!p.hidden && !p.contains(e.target) && !(e.target.closest('.dd-btn')?.nextElementSibling === p)) {
      p.hidden = true;
      const btn = p.parentElement?.querySelector('.dd-btn[aria-expanded="true"]');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    }
  });
});

/* Request generation: the newest filter/sort/page click always wins — a slow
   older response can never overwrite fresh results (the "stale freeze"). */
let __leadsReq = 0;
async function renderLeads2(opts = {}) {
  if (currentRoute !== 'leads' || APP.hidden) return;
  const gen = ++__leadsReq;
  const isUpdate = !!MAIN.querySelector('.filterbar');
  if (isUpdate) {
    MAIN.classList.add('is-refreshing');
    /* Watchdog: never leave the UI pointer-locked if a request hangs. */
    setTimeout(() => MAIN.classList.remove('is-refreshing'), 15000);
  }
  if (opts.cached && leadV2._last) {
    MAIN.classList.remove('is-refreshing');
    return drawLeads2(leadV2._last.data, leadV2._last.campaigns, leadV2._last.accounts);
  }
  const u = leadQS();
  u.set('page', String(leadV2.page)); u.set('page_size', String(leadV2.pageSize));
  let data, campaigns, accounts;
  try {
    [data, campaigns, accounts] = await Promise.all([
      apiGet(`/api/leads?${u}`),
      leadV2._campaigns || apiGet('/api/campaigns').then(c => (leadV2._campaigns = c)),
      leadV2._accounts || apiGet('/api/accounts').then(a => (leadV2._accounts = a)),
    ]);
  } catch (e) { MAIN.classList.remove('is-refreshing'); throw e; }
  if (gen !== __leadsReq) return; // superseded by a newer request
  leadV2._last = { data, campaigns, accounts };
  leadDataCache = data;
  MAIN.classList.remove('is-refreshing');
  return drawLeads2(data, campaigns, accounts);
}

/* Lead name cell: avatar + name (links to LinkedIn when a URL is known) + title.
   Leads confirmed "Open to messages" get an InMail badge next to the name. */
function leadWho(l) {
  const name = l.linkedin_url
    ? `<a class="lead-link" href="${esc(l.linkedin_url)}" target="_blank" rel="noopener noreferrer" title="Open LinkedIn profile">${esc(l.full_name)}<span class="msym">open_in_new</span></a>`
    : esc(l.full_name);
  const badge = l.opentomsg === true ? ' <span class="otm-badge" title="Open to messages — InMail eligible"><span class="msym">mail</span>InMail</span>'
    : l.opentomsg === false ? ' <span class="otm-badge otm-no" title="Checked — not open to messages"><span class="msym">mail</span>Not open</span>' : '';
  return `<div class="who">
    <div class="who-avatar" style="background:${avatarColor(l.full_name)}">${esc(initials(l.full_name))}</div>
    <div class="who-meta"><span class="who-name">${name}${badge}</span>${l.title ? `<span class="who-sub">${esc(l.title)}</span>` : ''}</div>
  </div>`;
}

function drawLeads2(data, campaigns, accounts) {
  const s = leadV2;
  const totalPages = Math.max(1, Math.ceil(data.total / s.pageSize));
  const activeFilters = leadFilterCount();

  MAIN.innerHTML = `<div class="page leads-page">
    <div class="page-head">
      <div><h1>Leads &amp; Prospect Pipeline</h1><p class="page-sub">${data.total.toLocaleString()} leads matching current filters${activeFilters ? ` · ${activeFilters} filter(s) active` : ''}</p></div>
      <div class="page-actions">
        ${pagerHTML('l', data.page, totalPages, null)}
        <button class="btn btn-secondary" id="lImport"><span class="msym">upload</span>Import CSV</button>
        <button class="btn btn-secondary" id="lImportSaved"><span class="msym">download</span>Import SavedSearch/List</button>
        <button class="btn btn-secondary" id="lExport"><span class="msym">download</span>Export CSV</button>
        ${activeFilters ? '<button class="btn btn-secondary" id="lClear"><span class="msym">filter_alt_off</span>Clear</button>' : ''}
        <button class="btn btn-secondary" id="lReload"><span class="msym">refresh</span>Refresh</button>
      </div>
    </div>

    <div class="filterbar compact">
      <div class="search"><span class="msym">search</span><input class="input" id="lq" placeholder="Search name, company, ID…" value="${esc(s.q)}" aria-label="Search leads">${s.q ? '<button class="search-clear" id="lqClear" aria-label="Clear search"><span class="msym">close</span></button>' : ''}</div>
      <select class="filter-select" id="leadCampaign" aria-label="Campaign">${optionsHTML([['__none__','— No campaign (unassigned) —'],...campaigns.map(c=>[c.id,c.name])],s.campaign,'All campaigns')}</select>
      <select class="filter-select" id="leadAccount" aria-label="Account">${optionsHTML(accounts.map(a=>[a.id,a.name]),s.account,'All accounts')}</select>
      <select class="filter-select" id="leadStage" aria-label="Stage">${optionsHTML([['__untouched__','Untouched'],...Object.entries(STATUS_META).filter(([k])=>k).map(([k,v])=>[k,v.label])],s.status,'All stages')}</select>
      <select class="filter-select" id="leadOtm" aria-label="Open to messages">${optionsHTML([['yes','Open to messages'],['no','Not open'],['unchecked','Not checked']],s.otm,'OpenToMsg: all')}</select>
      <select class="filter-select" id="leadError" aria-label="Send errors">${optionsHTML([['only','With send errors'],['none','Without errors']],s.error,'Errors: all')}</select>
      <span class="dd-wrap">
        <button class="dd-btn${(s.contactFrom || s.contactTo || s.createdFrom || s.createdTo || s.followupFrom || s.followupTo) ? ' active' : ''}" id="leadDates" aria-haspopup="dialog" aria-expanded="false"><span class="msym">calendar_month</span>Dates${(s.contactFrom||s.contactTo||s.createdFrom||s.createdTo||s.followupFrom||s.followupTo) ? ' <b>•</b>' : ''}</button>
        <div class="dd-panel dd-dates" id="leadDatesPanel" hidden>
          <div class="dd-head"><span class="dd-title">Date ranges</span><button class="btn btn-ghost btn-sm" id="lfReset">Clear all</button></div>
          <div class="dd-row"><label for="lfContactFrom">Contacted</label><input type="date" id="lfContactFrom" value="${esc(s.contactFrom)}"><input type="date" id="lfContactTo" value="${esc(s.contactTo)}" aria-label="Contacted until"></div>
          <div class="dd-row"><label for="lfCreatedFrom">Added</label><input type="date" id="lfCreatedFrom" value="${esc(s.createdFrom)}"><input type="date" id="lfCreatedTo" value="${esc(s.createdTo)}" aria-label="Added until"></div>
          <div class="dd-row"><label for="lfFollowupFrom">Follow-up</label><input type="date" id="lfFollowupFrom" value="${esc(s.followupFrom)}"><input type="date" id="lfFollowupTo" value="${esc(s.followupTo)}" aria-label="Follow-up until"></div>
          <div class="dd-actions"><button class="btn btn-secondary btn-sm" id="lfDone">Done</button><button class="btn btn-primary btn-sm" id="lfApply">Apply</button></div>
        </div>
      </span>
      <div style="flex:1"></div>
      <select class="filter-select" id="lPageSize" aria-label="Rows per page" style="min-width:92px">${[25, 50, 100].map(n => `<option value="${n}" ${s.pageSize === n ? 'selected' : ''}>${n} / page</option>`).join('')}</select>
    </div>

    ${leadChips(campaigns, accounts)}

    ${(leadSel.ids.size > 0 || leadSel.allMatching) ? `<div class="bulkbar">
      <span class="bulkbar-count">${leadSel.allMatching
        ? `<b>${(leadSel.ids.size - leadSel.excluded.size).toLocaleString()} matching records selected</b> · across all pages`
        : `<b>${leadSel.ids.size} selected</b>`}</span>
      ${leadSel.allMatching ? '' : `<button class="btn btn-secondary btn-sm" id="lSelAll">Select all ${data.total.toLocaleString()} matching records</button>`}
      <div style="flex:1"></div>
      <button class="btn btn-secondary btn-sm" id="lReassign">Reassign selected</button>
      <button class="btn btn-secondary btn-sm" id="lRetry" title="Remove errors and restore previous stages"><span class="msym">restart_alt</span>Remove errors</button>
      <button class="btn btn-secondary btn-sm" id="lSelClear">Clear selection</button>
      <button class="btn btn-danger btn-sm" id="lDel"><span class="msym">delete</span>Delete selected</button>
    </div>` : ''}

    <div class="card table-wrap">
      <table class="data compact leads-table">
        <colgroup><col style="width:3%"><col style="width:15%"><col style="width:11%"><col style="width:9%"><col style="width:10%"><col style="width:9%"><col style="width:8%"><col style="width:8%"><col style="width:7%"><col style="width:9%"><col style="width:6%"></colgroup>
        <thead><tr>
          <th style="width:34px"><input type="checkbox" id="lAll" class="checkbox" aria-label="Select all rows on this page"></th>
          <th>${leadSortHead('Lead', 'lead_name')}</th>
          <th>${leadSortHead('Company', 'company')}</th>
          <th>${leadSortHead('Location', 'location')}</th>
          <th>${leadSortHead('Campaign', 'campaign')}</th>
          <th>${leadSortHead('Owner Account', 'account')}</th>
          <th>${leadSortHead('Stage', 'stage')}</th>
          <th>${leadSortHead('Added Date', 'created')}</th>
          <th>${leadSortHead('Initial Contact', 'contact')}</th>
          <th>${leadSortHead('Last Follow-up', 'followup')}</th>
          <th>Reply</th>
        </tr></thead>
        <tbody>
          ${data.items.length ? data.items.map(l => {
            const checked = leadSel.ids.has(l.id) && !leadSel.excluded.has(l.id);
            return `<tr>
            <td><input type="checkbox" class="checkbox" data-sel="${l.id}" ${checked ? 'checked' : ''} aria-label="Select ${esc(l.full_name)}"></td>
            <td data-label="Lead">${leadWho(l)}</td>
            <td data-label="Company" class="small">${esc(l.company || '—')}</td>
            <td data-label="Location" class="small">${esc(l.location || '—')}</td>
            <td data-label="Campaign" class="small">${esc(campaignName(campaigns, l))}</td>
            <td data-label="Owner Account" class="small">${esc(l.associate_account ?? '—')}</td>
            <td data-label="Stage">${statusPill(l.status)}${l.status === 'BLOCKED_ERROR' ? `<button class="err-clear" data-err-clear="${l.id}" title="Remove error and restore previous stage"><span class="msym">restart_alt</span>Remove error</button>${l.last_error ? `<div class="err-sub" title="${esc(l.last_error)}">${esc(l.last_error)}</div>` : ''}` : ''}</td>
            <td data-label="Added Date" class="date-cell" title="${esc(fmtDT(l.created_at))}">${fmtD(l.created_at)}</td>
            <td data-label="Initial Contact" class="date-cell">${l.first_contacted_at ? `<div>${fmtD(l.first_contacted_at)}</div><div class="sub">${l.contact_channel === 'inmail' ? 'InMail' : l.contact_channel === 'invite' ? 'Invite' : 'contacted'} · ${ago(l.first_contacted_at)}</div>` : '<span class="muted">not contacted</span>'}</td>
            <td data-label="Last Follow-up" class="date-cell">${l.last_followup_at ? `<div>${fmtD(l.last_followup_at)}</div><div class="sub">${esc((l.last_followup_stage || '').replaceAll('_', ' ').toLowerCase() || 'follow-up')}</div>` : '<span class="muted">—</span>'}</td>
            <td data-label="Reply">${l.received_replies
              ? `<button class="reply-chip${l.reply_message ? '' : ' reply-chip-empty'}" data-reply="${l.id}" title="${l.reply_message ? 'View reply message' : 'No message text stored'}">${pill('ok', 'Replied')}</button>`
              : '<span class="muted">—</span>'}</td>
          </tr>`;
          }).join('') : `<tr class="empty-row"><td colspan="11">No leads match these filters. Widen the filters, import a CSV, or run Import SavedSearch.</td></tr>`}
        </tbody>
      </table>
    </div>

  </div>`;

  const apply = () => { leadSelClear(); leadV2.page = 1; renderLeads2().catch(e => toast(errText(e), 'crit')); };
  /* Reply chip -> modal with the stored reply message + recent timeline. */
  $$('[data-reply]', MAIN).forEach(b => b.onclick = async () => {
    const lead = (leadDataCache.items || []).find(x => String(x.id) === b.dataset.reply);
    if (!lead) return;
    openModal(`Reply · ${lead.full_name}`, `
      <div class="reply-modal">
        <div style="display:flex;gap:12px;align-items:center;padding-bottom:12px;border-bottom:1px solid var(--hairline)">
          <div class="who-avatar" style="background:${avatarColor(lead.full_name)};width:36px;height:36px">${esc(initials(lead.full_name))}</div>
          <div style="flex:1;min-width:0">
            <b>${esc(lead.full_name)}</b>
            <div class="muted small">${esc(lead.title || '')}${lead.title && lead.company ? ' · ' : ''}${esc(lead.company || '')}</div>
          </div>
          ${lead.linkedin_url ? `<a class="btn btn-secondary btn-sm" href="${esc(lead.linkedin_url)}" target="_blank" rel="noopener noreferrer"><span class="msym">open_in_new</span>LinkedIn</a>` : ''}
        </div>
        <div class="reply-quote" style="margin-top:12px">${lead.reply_message
          ? `<p style="white-space:pre-wrap;margin:0;line-height:1.6">${esc(lead.reply_message)}</p>`
          : '<span class="muted small">No reply text was captured for this lead — only the replied flag.</span>'}</div>
        <div class="muted small" style="margin-top:10px;display:flex;gap:14px;flex-wrap:wrap">
          <span><span class="msym" style="font-size:14px;vertical-align:-2px">rocket_launch</span> ${esc(lead.campaign_name || lead.campaign || '—')}</span>
          <span><span class="msym" style="font-size:14px;vertical-align:-2px">person</span> ${esc(lead.associate_account ?? '—')}</span>
          <span><span class="msym" style="font-size:14px;vertical-align:-2px">category</span> ${esc(REPLY_CATEGORIES[lead.reply_category] ?? 'Unclassified')}</span>
        </div>
        <div id="replyTimeline" style="margin-top:14px"><div class="loading"><span class="spinner"></span>Loading activity…</div></div>
      </div>`);
    try {
      const tl = await apiGet(`/api/leads/${lead.id}/timeline`);
      const host = $('#replyTimeline');
      if (!host) return;
      const events = (tl.events || []).slice(-6).reverse();
      host.innerHTML = events.length
        ? `<div class="section-title" style="margin:0 0 8px"><h2>Recent activity</h2></div>` + events.map(ev =>
          `<div class="tl-row"><span class="tl-dot tl-${esc(ev.kind)}"></span><div><div class="small">${esc(ev.detail || ev.kind)}</div><div class="muted" style="font-size:11px">${ago(ev.at)}</div></div></div>`).join('')
        : '';
    } catch (ex) { const h = $('#replyTimeline'); if (h) h.innerHTML = ''; }
  });
  let qTimer;
  $('#lq').oninput = (e) => { clearTimeout(qTimer); qTimer = setTimeout(() => { leadV2.q = e.target.value.trim(); apply(); }, 350); };
  $('#leadCampaign').onchange=e=>{leadV2.campaign=e.target.value;apply();};
  $('#leadAccount').onchange=e=>{leadV2.account=e.target.value;apply();};
  /* Dates: compact popover, applied together. Stage filters instantly. */
  $('#leadStage').onchange = (e) => { leadV2.status = e.target.value; apply(); };
  $('#leadOtm').onchange = (e) => { leadV2.otm = e.target.value; apply(); };
  $('#leadError').onchange = (e) => { leadV2.error = e.target.value; apply(); };
  /* Per-row Clear-error action. */
  $$('[data-err-clear]', MAIN).forEach(b => b.onclick = () => retryLeads([Number(b.dataset.errClear)], b));
  const lfBtn = $('#leadDates'), lfPanel = $('#leadDatesPanel');
  lfBtn.onclick = () => {
    const open = lfPanel.hidden;
    lfPanel.hidden = !open;
    lfBtn.setAttribute('aria-expanded', String(open));
    if (open) {
      /* Clamp the panel inside the viewport (it anchors to a mid-bar wrap). */
      lfPanel.style.transform = '';
      const pr = lfPanel.getBoundingClientRect();
      let shift = 0;
      if (pr.right > innerWidth - 8) shift = innerWidth - 8 - pr.right;
      if (pr.left + shift < 8) shift = 8 - pr.left;
      if (shift) lfPanel.style.transform = `translateX(${Math.round(shift)}px)`;
    }
  };
  $('#lfDone').onclick = $('#lfApply').onclick = () => {
    Object.assign(leadV2, {
      contactFrom: $('#lfContactFrom').value, contactTo: $('#lfContactTo').value,
      createdFrom: $('#lfCreatedFrom').value, createdTo: $('#lfCreatedTo').value,
      followupFrom: $('#lfFollowupFrom').value, followupTo: $('#lfFollowupTo').value,
    });
    lfPanel.hidden = true; lfBtn.setAttribute('aria-expanded', 'false');
    apply();
  };
  $('#lfReset').onclick = () => {
    Object.assign(leadV2, { contactFrom: '', contactTo: '', createdFrom: '', createdTo: '', followupFrom: '', followupTo: '' });
    apply();
  };
  lfPanel.addEventListener('keydown', e => { if (e.key === 'Escape') { lfPanel.hidden = true; lfBtn.setAttribute('aria-expanded', 'false'); lfBtn.focus(); } });
  $('#lPageSize').onchange = (e) => { leadV2.pageSize = Number(e.target.value); apply(); };
  /* Top pager */
  const lPrevBtn = $('#lPrev'), lNextBtn = $('#lNext');
  if (lPrevBtn) lPrevBtn.onclick = () => { leadV2.page--; renderLeads2().catch(e => quietToast(e)); };
  if (lNextBtn) lNextBtn.onclick = () => { leadV2.page++; renderLeads2().catch(e => quietToast(e)); };
  const qClear = $('#lqClear'); if (qClear) qClear.onclick = () => { leadV2.q = ''; apply(); };
  // Remove one visible filter at a time (date ranges clear both bounds).
  $$('[data-chip-x]', MAIN).forEach(b => b.onclick = () => {
    const k = b.dataset.chipX;
    const ranges = { contactDate: ['contactFrom', 'contactTo'], createdDate: ['createdFrom', 'createdTo'], followupDate: ['followupFrom', 'followupTo'] };
    if (k === 'error') leadV2.error = '';
    if (ranges[k]) ranges[k].forEach(key => { leadV2[key] = ''; });
    else if (k in leadV2) leadV2[k] = '';
    apply();
  });
  $$('[data-sort]', MAIN).forEach(b => b.onclick = () => { leadV2.sort = b.dataset.sort; renderLeads2().catch(e => toast(errText(e), 'crit')); });
  $('#lReload').onclick = () => renderLeads2().catch(e => toast(errText(e), 'crit'));
  const clearBtn = $('#lClear');
  if (clearBtn) clearBtn.onclick = () => {
    leadSelClear();
    Object.assign(leadV2, { campaign: '', status: '', q: '', account: '', otm: '', error: '',
                            contactFrom: '', contactTo: '', createdFrom: '', createdTo: '', followupFrom: '', followupTo: '', page: 1 });
    renderLeads2().catch(e => quietToast(e));
  };


  // ---- Selection (instant: re-renders from cached data, no refetch) ----
  const rerender = () => renderLeads2({ cached: true }).catch(e => quietToast(e));
  $$('[data-sel]', MAIN).forEach(cb => cb.onchange = () => {
    const id = Number(cb.dataset.sel);
    if (leadSel.allMatching) { if (cb.checked) {leadSel.ids.add(id);leadSel.excluded.delete(id);} else leadSel.excluded.add(id); }
    else if (cb.checked) leadSel.ids.add(id); else leadSel.ids.delete(id);
    rerender();
  });
  const allBox = $('#lAll');
  if (allBox) {
    const selected = data.items.filter(l => leadSel.ids.has(l.id) && !leadSel.excluded.has(l.id)).length;
    allBox.checked = data.items.length > 0 && selected === data.items.length;
    allBox.indeterminate = selected > 0 && selected < data.items.length;
  }
  if (allBox) allBox.onchange = () => {
    if (leadSel.allMatching) {
      if (allBox.checked) data.items.forEach(l => {leadSel.ids.add(l.id);leadSel.excluded.delete(l.id);}); else data.items.forEach(l => {if(leadSel.ids.has(l.id))leadSel.excluded.add(l.id);});
    } else {
      if (allBox.checked) data.items.forEach(l => leadSel.ids.add(l.id));
      else data.items.forEach(l => leadSel.ids.delete(l.id));
    }
    rerender();
  };
  const selAll = $('#lSelAll');
  if (selAll) selAll.onclick = async () => {
    const snapshot = leadSnapshot(); selAll.disabled = true;
    try {
      const result = await apiGet(`/api/leads?${leadQS()}&ids_only=true`);
      if (currentRoute !== 'leads' || snapshot !== leadSnapshot()) return;
      leadSel.ids = new Set(result.ids); leadSel.allMatching = true; leadSel.snapshot = snapshot;
      leadSel.excluded.clear(); leadSel.count = result.total;
      rerender(); toast(`All ${result.total.toLocaleString()} matching records selected across all pages.`, 'ok');
    } catch(e) {toast(errText(e),'crit'); if(selAll.isConnected)selAll.disabled=false;}
  };
  const selClear = $('#lSelClear');
  if (selClear) selClear.onclick = () => { leadSelClear(); rerender(); };

  // ---- Bulk retry: clear BLOCKED_ERROR so the next run re-queues them ----
  const moveBtn = $('#lReassign');
  if (moveBtn) moveBtn.onclick = () => reassignLeadsDialog([...leadSel.ids].filter(id => !leadSel.excluded.has(id)), campaigns, accounts);
  const retryBtn = $('#lRetry');
  if (retryBtn) retryBtn.onclick = () => retryLeads([...leadSel.ids].filter(id => !leadSel.excluded.has(id)), retryBtn);
  /* Shared by the bulk bar and the per-row Clear-error action. */
  async function retryLeads(ids, btn) {
    if (!ids.length) { toast('No selected leads carry a send error. Filter “Errors: with send errors” first.', 'warn'); return; }
    if (btn) btn.disabled = true;
    try {
      const res = await apiPost('/api/leads/reset-errors', { ids });
      toast(`${res.reset} lead(s) restored to their previous stage${res.skipped ? ` · ${res.skipped} skipped` : ''}`, 'ok');
      leadSelClear();
      renderLeads2().catch(e => quietToast(e));
    } catch (e) { toast(errText(e), 'crit'); if (btn && btn.isConnected) btn.disabled = false; }
  }

  // ---- Bulk delete with exact preview ----
  const delBtn = $('#lDel');
  if (delBtn) delBtn.onclick = async () => {
    openModal('Delete selected leads', `
      <div id="delPrev"><div class="loading"><span class="spinner"></span>Building exact preview…</div></div>`,
      `<button class="btn btn-secondary" data-close2>Cancel</button><button class="btn btn-danger" id="delGo" disabled><span class="msym">delete</span>Delete permanently</button>`);
    const dialog = $('#modalHost .modal');
    $('#modalHost [data-close2]').onclick = closeModal;
    try {
      const selectedIds = [...leadSel.ids].filter(id => !leadSel.excluded.has(id));
      const preview = await apiPost('/api/leads/delete-preview', {ids: selectedIds});
      if (!dialog.isConnected) return;
      $('#delPrev').innerHTML = `
        <p><b>${Number(preview.existing).toLocaleString()}</b> lead(s) will be deleted${preview.missing ? ` · <b>${preview.missing}</b> already deleted (skipped)` : ''}.</p>
        <div class="card" style="box-shadow:none;padding:10px;background:var(--inset)">
          ${preview.campaigns.slice(0, 6).map(c => `<div style="display:flex;justify-content:space-between"><span>${esc(c.campaign)}</span><b class="mono">${c.count}</b></div>`).join('')}
          ${preview.campaigns.length > 6 ? `<div class="muted small">+ ${preview.campaigns.length - 6} more campaigns</div>` : ''}
        </div>
        <p class="muted small" style="margin:10px 0 0">Also removed: <b>${preview.comments_to_remove}</b> internal comments, <b>${preview.events_to_remove}</b> timeline events. Run logs are kept.</p>
        <div class="banner banner-warn" style="padding:8px 12px;margin-top:10px"><p style="margin:0">Deleted leads lose their local suppression history — if re-imported later, automated outreach may contact them again.</p></div>`;
      const go = $('#delGo'); go.disabled = false;
      go.onclick = async () => {
        go.disabled = true; go.innerHTML = '<span class="msym">hourglass_top</span>Deleting…';
        try {
          const deleted = (await apiPost('/api/leads/bulk-delete-v2', {ids: selectedIds})).deleted;
          closeModal(); leadSelClear();
          toast(`Deleted ${deleted} lead(s).`, 'ok');
          renderLeads2().catch(e => quietToast(e));
        } catch (e) {
          go.disabled = false; go.innerHTML = '<span class="msym">delete</span>Delete permanently';
          if (!dialog.isConnected) return;
          $('#delPrev').insertAdjacentHTML('beforeend', `<p class="form-error" role="alert">${esc(errText(e))}</p>`);
        }
      };
    } catch (e) {
      if (!dialog.isConnected) return;
      $('#delPrev').innerHTML = `<p class="form-error" role="alert">${esc(errText(e))}</p>`;
    }
  };

  $('#lImportSaved').onclick = () => {
    openModal('Import leads from Sales Nav', `
      <p class="muted small">Pick what to import from. The Sales Nav account and optional campaign assignment are chosen in the next step.</p>
      <div class="imp-chooser">
        <button class="btn btn-secondary" id="impChooseSearch"><span class="msym">manage_search</span>${JOB_LABELS.sync_leads || 'Import SavedSearch'}</button>
        <button class="btn btn-secondary" id="impChooseList"><span class="msym">list_alt</span>${JOB_LABELS.import_list || 'Import SavedList'}</button>
      </div>`);
    $('#impChooseSearch').onclick = () => importDialog('sync_leads', campaigns, accounts);
    $('#impChooseList').onclick = () => importDialog('import_list', campaigns, accounts);
  };
  $('#lExport').onclick = async () => {
    try {
      const res = await fetch(`/api/leads/export?${leadQS(true)}`, { credentials: 'include' });
      if (!res.ok) throw new Error('Export failed');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `leads_export_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) { toast(errText(e), 'crit'); }
  };
  $('#lImport').onclick = () => {
    openModal('Import leads from CSV', `
      <p class="muted small">Leads arrive <b>untagged</b> — assign them to a campaign from the table afterwards. You can also import directly into a campaign by choosing one here.</p>
      <label class="field"><span>Campaign (optional)</span>
        <select class="input" id="impCamp"><option value="">Untagged pool</option>${campaigns.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select>
      </label>
      <div class="card" style="background:var(--inset);padding:10px;font-size:11.5px;color:var(--muted)">
        <b>Required column:</b> <code class="mono">full_name</code> (or <code class="mono">first_name</code> + <code class="mono">last_name</code>)<br>
        <b>Optional columns</b> — leave any of them empty:<br>
        <span style="display:inline-block;margin:4px 0 0 12px">• <code class="mono">sales_nav_id</code> — ACw or ACo token; required for outreach</span><br>
        <span style="display:inline-block;margin:2px 0 0 12px">• <code class="mono">sales_nav_urn</code> — decorated <code class="mono">urn:li:fs_salesProfile:(…)</code> sent verbatim as the message recipient</span><br>
        <span style="display:inline-block;margin:2px 0 0 12px">• <code class="mono">linkedin_url</code>, <code class="mono">title</code>, <code class="mono">company</code>, <code class="mono">location</code></span><br>
        <span style="display:inline-block;margin:2px 0 0 12px">• <code class="mono">opentomsg</code> — true, false or unknown</span><br>
        <a href="#" id="impTemplate" class="link" style="display:inline-flex;align-items:center;gap:4px;margin-top:6px"><span class="msym" style="font-size:14px">download</span>Download CSV template (with sample data)</a><br><span>Replace the sample people with your leads and their real profile IDs. Sample IDs are blank; leave opentomsg unknown unless verified.</span>
      </div>
      <div class="dialog-actions" style="margin-top:12px">
        <button class="btn btn-secondary" id="impPick"><span class="msym">upload_file</span>Upload CSV</button>
        <button class="btn btn-ghost" id="impClear" disabled>Clear file</button>
      </div>
      <p id="impFileStatus" class="muted small" role="status">No file selected. Upload a CSV, choose its campaign, then click Import leads.</p>
      <div id="impResult" role="status" hidden></div>
      <input type="file" id="impFile" accept=".csv,text/csv" hidden>`,
      '<button class="btn btn-secondary" id="impClose">Close</button><button class="btn btn-primary" id="impStart" disabled><span class="msym">download_done</span>Import leads</button>');
    const picker = $('#impFile'), upload = $('#impPick'), clear = $('#impClear');
    const start = $('#impStart'), campaign = $('#impCamp'), status = $('#impFileStatus'), result = $('#impResult');
    let selectedFile = null, importing = false;
    $('#impClose').onclick = closeModal;
    upload.onclick = () => picker.click();
    $('#impTemplate').onclick = e => {
      e.preventDefault();
      fetch('/api/leads/import-template', { credentials: 'include' })
        .then(res => { if (!res.ok) throw new Error('Template download failed'); return res.blob(); })
        .then(blob => {
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url; a.download = 'leads_import_template.csv';
          document.body.appendChild(a); a.click(); a.remove();
          URL.revokeObjectURL(url);
        })
        .catch(ex => toast(errText(ex), 'crit'));
    };
    const setFile = file => {
      selectedFile = file;
      result.hidden = true; result.replaceChildren();
      start.disabled = !file; clear.disabled = !file;
      status.textContent = file
        ? `${file.name} · ${Math.max(1, Math.ceil(file.size / 1024))} KB · Ready to import. No leads added yet.`
        : 'No file selected. Upload a CSV, choose its campaign, then click Import leads.';
    };
    clear.onclick = () => { picker.value = ''; setFile(null); };
    picker.onchange = () => {
      const file = picker.files?.[0];
      if (!file) return;
      if (!/\.csv$/i.test(file.name) || !file.size) {
        picker.value = ''; setFile(null);
        status.textContent = 'Choose a non-empty .csv file.';
        return;
      }
      setFile(file);
    };
    start.onclick = async () => {
      if (importing || !selectedFile) return;
      importing = true;
      const file = selectedFile, camp = campaign.value;
      start.disabled = upload.disabled = clear.disabled = campaign.disabled = true;
      start.textContent = 'Importing…';
      status.textContent = `Importing ${file.name}…`;
      try {
        const fd = new FormData();
        fd.append('file', file);
        const j = await apiPost(`/api/leads/import-csv${camp ? `?campaign_id=${camp}` : ''}`, fd);
        selectedFile = null; picker.value = '';
        status.textContent = `${file.name} · Import complete`;
        result.hidden = false;
        result.innerHTML = `<p><b>${Number(j.added) || 0} added</b> · ${Number(j.skipped) || 0} skipped</p>${j.errors?.length ? `<ul class="muted small">${j.errors.map(error => `<li>${esc(error)}</li>`).join('')}</ul>` : ''}`;
        toast(`Imported ${j.added} lead(s)${j.skipped ? `, skipped ${j.skipped}` : ''}`, 'ok');
        if (currentRoute === 'leads') renderLeads2().catch(e => quietToast(e));
      } catch (ex) {
        status.textContent = `Import failed: ${errText(ex)}. Your selected file is retained.`;
        toast(errText(ex), 'crit');
      } finally {
        importing = false; upload.disabled = campaign.disabled = false;
        start.disabled = clear.disabled = !selectedFile;
        start.innerHTML = '<span class="msym">download_done</span>Import leads';
      }
    };
  };
}

/* ==================== THREADS (v2) ==================== */
const threadV2 = {
  q: '', channel: 'all', campaignIds: '', accountIds: '', category: '',
  review: '', sort: 'newest', page: 1, sel: null,
  _campaigns: null, _accounts: null,
};
const REPLY_CATEGORIES = {
  positive: 'Positive / Interested', meeting: 'Meeting requested', followup_later: 'Follow up later',
  referral: 'Referral', declined: 'Declined / Not interested', unsubscribe: 'Unsubscribe / Do not contact',
  ooo: 'Out of office', unclassified: 'Unclassified',
};
const REPLY_TONES = { positive: 'ok', meeting: 'ok', followup_later: 'warn', referral: 'primary', declined: 'crit', unsubscribe: 'crit', ooo: 'idle', unclassified: 'idle' };

let __threadsReq = 0;
async function viewThreads() {
  if (currentRoute !== 'threads' || APP.hidden) return;
  const gen = ++__threadsReq;
  const isUpdate = !!MAIN.querySelector('.chip-row, .thread-grid, #thReload');
  if (isUpdate) MAIN.classList.add('is-refreshing');
  let campaigns, accounts, data;
  try {
    [campaigns, accounts] = await Promise.all([
      threadV2._campaigns || apiGet('/api/campaigns').then(c => (threadV2._campaigns = c)),
      threadV2._accounts || apiGet('/api/accounts').then(a => (threadV2._accounts = a)),
    ]);
    const u = new URLSearchParams();
    u.set('page_size', '50'); u.set('page', String(threadV2.page));
    if (threadV2.q) u.set('q', threadV2.q);
    if (threadV2.channel) u.set('channel', threadV2.channel);
    if (threadV2.campaignIds) u.set('campaign_ids', threadV2.campaignIds);
    if (threadV2.accountIds) u.set('account_ids', threadV2.accountIds);
    if (threadV2.category) u.set('category', threadV2.category);
    if (threadV2.review) u.set('review', threadV2.review);
    if (threadV2.sort !== 'newest') u.set('sort', threadV2.sort);
    data = await apiGet(`/api/threads?${u}`);
  } catch (e) { MAIN.classList.remove('is-refreshing'); throw e; }
  if (gen !== __threadsReq) return; // superseded by a newer click
  MAIN.classList.remove('is-refreshing');
  const rows = data.items;
  const sel = threadV2.sel ? rows.find(r => r.id === threadV2.sel) : null;
  const totalPages = Math.max(1, Math.ceil(data.total / 50));
  const activeFilters = [threadV2.q, threadV2.campaignIds, threadV2.accountIds, threadV2.category, threadV2.review].filter(Boolean).length;

  // Dropdown labels reflect the current pick
  const campLabel = threadV2.campaignIds
    ? `${threadV2.campaignIds.split(',').length} campaign(s)`
    : 'All campaigns';
  const acctLabel = threadV2.accountIds
    ? `${threadV2.accountIds.split(',').length} account(s)`
    : 'All accounts';

  // Removable filter chips
  const chips = [];
  const cpush = (k, label, val) => chips.push({ k, label, val });
  if (threadV2.q) cpush('q', 'Search', `“${threadV2.q}”`);
  if (threadV2.campaignIds) cpush('campaignIds', 'Campaign', campLabel.replace(' campaign(s)', ' campaign(s)'));
  if (threadV2.accountIds) cpush('accountIds', 'Account', acctLabel);
  if (threadV2.category) cpush('category', 'Category', REPLY_CATEGORIES[threadV2.category] || threadV2.category);
  if (threadV2.review) cpush('review', 'Review', threadV2.review === 'needs_review' ? 'Needs review' : 'Reviewed');
  const chipRow = chips.length ? `<div class="chip-row" role="list" aria-label="Active filters">
    <span class="chip-label">Filters</span>
    ${chips.map(c => `<span class="chip" role="listitem">${esc(c.label)}: <b>${esc(c.val)}</b>
      <button class="chip-x" data-chip-x="${c.k}" aria-label="Remove ${esc(c.label)} filter"><span class="msym">close</span></button></span>`).join('')}
  </div>` : '';

  MAIN.innerHTML = `<div class="page">
    <div class="page-head">
      <div><h1>Inbox &amp; Reply Matrix</h1><p class="page-sub">${data.total} reply conversation(s)${activeFilters ? ` · ${activeFilters} filter(s) active` : ''}</p></div>
      <div class="page-actions">
        ${data.total > 50 ? pagerHTML('th', data.page, totalPages, null) : ''}
        <button class="btn btn-secondary" id="thReload"><span class="msym">refresh</span>Refresh</button>
      </div>
    </div>

    <div class="filterbar">
      <div class="search"><span class="msym">search</span><input class="input" id="thQ" placeholder="Search replies, names, companies…" value="${esc(threadV2.q)}" aria-label="Search replies">${threadV2.q ? '<button class="search-clear" id="thQClear" aria-label="Clear search"><span class="msym">close</span></button>' : ''}</div>
      ${scopePickerHTML('campaignIds','Campaigns',campaigns)}
      ${scopePickerHTML('accountIds','Accounts',accounts)}
      <select class="filter-select" id="thCategory" aria-label="Reply category">${optionsHTML(Object.entries(REPLY_CATEGORIES),threadV2.category,'All reply categories')}</select>
      <select class="filter-select" id="thReview" aria-label="Review status">${optionsHTML([['needs_review','Needs review'],['reviewed','Reviewed']],threadV2.review,'All reviews')}</select>
      <div style="flex:1"></div>
      <select class="filter-select" id="thSort" aria-label="Sort conversations">
        ${[['newest', 'Newest reply'], ['oldest', 'Oldest reply'], ['lead_name', 'Lead A–Z'], ['campaign', 'Campaign'], ['account', 'Account'], ['reviewed', 'Recently reviewed']].map(([k, v]) => `<option value="${k}" ${k === threadV2.sort ? 'selected' : ''}>${v}</option>`).join('')}
      </select>
      ${activeFilters ? '<button class="btn btn-secondary" id="thClear"><span class="msym">filter_alt_off</span>Clear</button>' : ''}
    </div>
    ${chipRow}
    <div class="seg">${[['all', 'All replies'], ['booked', 'Mentions booking']].map(([k, l]) => `<button class="${threadV2.channel === k ? 'on' : ''}" data-ch="${k}">${l}</button>`).join('')}</div>

    ${rows.length === 0 ? `<div class="card card-pad" style="text-align:center;padding:40px"><div class="stat-ic" style="margin:0 auto 10px"><span class="msym">forum</span></div><h2>No replies here yet</h2><p class="muted small">When Check Replies finds lead responses, they appear here with campaign and account attribution.</p></div>` : `
    <div class="grid" style="grid-template-columns:2fr 3fr;align-items:start">
      <div class="card" style="max-height:70vh;overflow-y:auto">
        ${rows.map(r => `<button class="notif-item" data-thread="${r.id}" style="border-bottom:1px solid var(--hairline);align-items:flex-start">
          <div class="who-avatar" style="background:${avatarColor(r.full_name)}">${esc(initials(r.full_name))}</div>
          <div style="flex:1;min-width:0">
            <div style="display:flex;justify-content:space-between;gap:8px"><b style="font-size:13px">${r.linkedin_url
                ? `<a class="lead-link" href="${esc(r.linkedin_url)}" target="_blank" rel="noopener noreferrer" title="Open LinkedIn profile">${esc(r.full_name)}<span class="msym">open_in_new</span></a>`
                : esc(r.full_name)}</b><span class="mono muted" style="font-size:10.5px">${r.reply_received_at ? fmtD(r.reply_received_at) : ''}</span></div>
            <p class="muted small" style="margin:2px 0">“${esc((r.reply_message ?? '').slice(0, 80))}”</p>
            <div style="display:flex;gap:4px;flex-wrap:wrap">
              ${pill(REPLY_TONES[r.reply_category] || 'idle', REPLY_CATEGORIES[r.reply_category] || r.reply_category)}
              ${r.comment_count ? `<span class="tag"><span class="msym" style="font-size:12px;vertical-align:-2px">comment</span>${r.comment_count}</span>` : ''}
              ${r.review_status === 'needs_review' ? pill('warn', 'Needs review', false) : ''}
              ${r.campaign_name || r.campaign ? `<span class="tag">${esc(r.campaign_name || r.campaign)}</span>` : ''}${r.account ? `<span class="tag">${esc(r.account)}</span>` : ''}
            </div>
          </div>
        </button>`).join('')}
      </div>
      <div class="card card-pad" style="min-height:260px" id="threadDetail">
        ${sel ? threadDetailHTML(sel) : '<p class="muted" style="text-align:center;padding:60px 0">Select a reply from the list.</p>'}
      </div>
    </div>`}

  </div>`;

  const apply = () => { threadV2.page = 1; viewThreads().catch(e => toast(errText(e), 'crit')); };
  $$('[data-ch]', MAIN).forEach(b => b.onclick = () => { threadV2.channel = b.dataset.ch; apply(); });
  $$('[data-thread]', MAIN).forEach(b => b.onclick = () => { threadV2.sel = Number(b.dataset.thread); viewThreads().catch(e => quietToast(e)); });
  $('#thReload').onclick = () => viewThreads().catch(e => quietToast(e));
  let tq;
  $('#thQ').oninput = (e) => { clearTimeout(tq); tq = setTimeout(() => { threadV2.q = e.target.value.trim(); apply(); }, 350); };
  const thQClear = $('#thQClear');
  if (thQClear) thQClear.onclick = () => { threadV2.q = ''; apply(); };
  // Chip removal
  $$('[data-chip-x]', MAIN).forEach(b => b.onclick = () => {
    const k = b.dataset.chipX;
    if (k in threadV2) threadV2[k] = '';
    apply();
  });
  $('#thCategory').onchange = e => { threadV2.category = e.target.value; apply(); };
  $('#thReview').onchange = e => { threadV2.review = e.target.value; apply(); };
  wireScopePickers(apply);
  $('#thSort').onchange = e => { threadV2.sort = e.target.value; apply(); };
  const clearBtn = $('#thClear');
  if (clearBtn) clearBtn.onclick = () => { Object.assign(threadV2, { q: '', campaignIds: '', accountIds: '', category: '', review: '', sort: 'newest', page: 1 }); viewThreads().catch(e => quietToast(e)); };
  if ($('#thPrev')) $('#thPrev').onclick = () => { threadV2.page--; viewThreads().catch(e => quietToast(e)); };
  if ($('#thNext')) $('#thNext').onclick = () => { threadV2.page++; viewThreads().catch(e => quietToast(e)); };

  if (sel) bindThreadDetail(sel);
}

function threadDetailHTML(sel) {
  const srcLabel = sel.reply_category_source === 'manual' ? 'Manually selected'
    : sel.reply_category_source === 'auto' ? 'Automatically detected' : 'Not classified';
  return `
    <div style="display:flex;gap:12px;align-items:flex-start;border-bottom:1px solid var(--hairline);padding-bottom:12px">
      <div class="who-avatar" style="background:${avatarColor(sel.full_name)};width:40px;height:40px">${esc(initials(sel.full_name))}</div>
      <div style="flex:1"><b style="font-size:15px">${sel.linkedin_url
          ? `<a class="lead-link" href="${esc(sel.linkedin_url)}" target="_blank" rel="noopener noreferrer" title="Open LinkedIn profile">${esc(sel.full_name)}<span class="msym">open_in_new</span></a>`
          : esc(sel.full_name)}</b><div class="muted small">${esc(sel.title || '')} ${sel.company ? '· ' + esc(sel.company) : ''}</div></div>
      ${sel.linkedin_url ? `<a class="btn btn-secondary btn-sm" href="${esc(sel.linkedin_url)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${esc(sel.full_name)} on LinkedIn"><span class="msym">open_in_new</span>Profile</a>` : ''}
      ${pill('ok', 'Replied')}
    </div>
    <div style="margin-top:14px;background:var(--inset);border-left:4px solid var(--primary);border-radius:8px;padding:14px">
      <p style="white-space:pre-wrap;margin:0;line-height:1.6">${esc(sel.reply_message || '')}</p>
    </div>
    <div class="muted small" style="margin-top:12px;display:flex;gap:16px;flex-wrap:wrap">
      <span><span class="msym" style="font-size:14px;vertical-align:-2px">rocket_launch</span> ${esc(sel.campaign_name || sel.campaign || '—')}</span>
      <span><span class="msym" style="font-size:14px;vertical-align:-2px">person</span> ${esc(sel.account ?? '—')}</span>
      ${sel.reply_received_at ? `<span><span class="msym" style="font-size:14px;vertical-align:-2px">schedule</span> ${fmtDT(sel.reply_received_at)}</span>` : ''}
    </div>
    <div style="margin-top:14px;display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      <label class="field" style="margin:0"><span>Category · ${srcLabel}</span>
        <select class="input" id="tCat" style="width:230px">
          ${Object.entries(REPLY_CATEGORIES).map(([k, v]) => `<option value="${k}" ${k === sel.reply_category ? 'selected' : ''}>${v}</option>`).join('')}
        </select>
      </label>
      ${sel.review_status === 'reviewed'
        ? `<button class="btn btn-secondary" id="tUnreview"><span class="msym">undo</span>Mark needs review</button>`
        : `<button class="btn btn-primary" id="tReview"><span class="msym">task_alt</span>Mark reviewed</button>`}
    </div>
    <div class="section-title" style="margin-top:18px"><h2>Internal comments</h2></div>
    <div id="tComments"><div class="loading"><span class="spinner"></span>Loading…</div></div>
    <div style="display:flex;gap:8px;margin-top:8px">
      <input class="input" id="tNewComment" placeholder="Add an internal comment… (Enter)" maxlength="4000">
      <button class="btn btn-secondary" id="tAddComment"><span class="msym">add_comment</span>Add</button>
    </div>`;
}

function bindThreadDetail(sel) {
  $('#tCat').onchange = async (e) => {
    try {
      await apiPut(`/api/leads/${sel.id}/category`, { category: e.target.value });
      toast('Category saved — manual picks are never overwritten', 'ok');
      viewThreads().catch(e => quietToast(e));
    } catch (ex) { toast(errText(ex), 'crit'); }
  };
  const reviewBtn = $('#tReview') || $('#tUnreview');
  if (reviewBtn) reviewBtn.onclick = async () => {
    const to = reviewBtn.id === 'tReview' ? 'reviewed' : 'needs_review';
    try {
      await apiPost(`/api/leads/${sel.id}/review`, { review_status: to });
      toast(to === 'reviewed' ? 'Marked reviewed' : 'Marked needs review', 'ok');
      viewThreads().catch(e => quietToast(e));
    } catch (ex) { toast(errText(ex), 'crit'); }
  };
  $('#tComments').dataset.leadId = String(sel.id);
  loadThreadComments(sel.id);
  let savingComment = false;
  const addComment = async () => {
    if (savingComment) return;
    const input = $('#tNewComment');
    const body = input.value.trim();
    if (!body) { toast('Comment cannot be empty', 'warn'); return; }
    savingComment = true;
    try {
      await apiPost(`/api/leads/${sel.id}/comments`, { body });
      input.value = '';
      loadThreadComments(sel.id);
      toast('Comment added', 'ok');
    } catch (ex) { toast(errText(ex), 'crit'); }
    finally { savingComment = false; }
  };
  $('#tAddComment').onclick = addComment;
  $('#tNewComment').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); addComment(); } };
}

async function loadThreadComments(leadId) {
  const host = $('#tComments');
  if (!host || host.dataset.leadId !== String(leadId)) return;
  let comments;
  try { comments = await apiGet(`/api/leads/${leadId}/comments`); } catch { return; }
  if (!host.isConnected) return;
  host.innerHTML = comments.length ? comments.map(c => `
    <div class="card" style="box-shadow:none;padding:10px;margin-bottom:8px" data-cid="${c.id}">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span class="tag">${esc(c.author)}</span>
        <span class="muted small">${fmtDT(c.created_at)}${c.updated_at ? ' · edited' : ''}</span>
      </div>
      <p class="c-body" style="margin:6px 0 8px;white-space:pre-wrap">${esc(c.body)}</p>
      <div style="display:flex;gap:6px">
        <button class="btn btn-ghost btn-sm" data-cedit="${c.id}" title="Edit"><span class="msym">edit</span></button>
        <button class="btn btn-ghost btn-sm" data-cdel="${c.id}" title="Delete" style="color:var(--crit-text)"><span class="msym">delete</span></button>
      </div>
    </div>`).join('') : '<p class="muted small">No comments yet — internal notes only; the LinkedIn reply text is never modified.</p>';
  $$('[data-cdel]', host).forEach(b => b.onclick = async () => {
    if (!window.confirm('Delete this comment? This cannot be undone.')) return;
    try { await apiDelete(`/api/comments/${b.dataset.cdel}`); loadThreadComments(leadId); toast('Comment deleted', 'ok'); }
    catch (e) { toast(errText(e), 'crit'); }
  });
  $$('[data-cedit]', host).forEach(b => b.onclick = () => {
    const card = b.closest('[data-cid]');
    const bodyEl = card.querySelector('.c-body');
    if (!bodyEl) return;
    const current = bodyEl.textContent;
    bodyEl.outerHTML = `<textarea class="input c-edit" rows="3" maxlength="4000">${esc(current)}</textarea>
      <div style="display:flex;gap:6px;margin-top:6px"><button class="btn btn-secondary btn-sm" data-csave="${b.dataset.cedit}">Save</button></div>`;
    card.querySelector('[data-csave]').onclick = async () => {
      const v = card.querySelector('.c-edit').value.trim();
      if (!v) { toast('Comment cannot be empty', 'warn'); return; }
      try { await apiPut(`/api/comments/${b.dataset.cedit}`, { body: v }); loadThreadComments(leadId); toast('Comment updated', 'ok'); }
      catch (e) { toast(errText(e), 'crit'); }
    };
  });
}

