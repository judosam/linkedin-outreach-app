/* Outreach Command Center — views part 2.
   Loaded after app.js: Accounts (quota balancing), Campaigns, Campaign detail,
   Leads (contact dates), Threads, Workers, Logs & History, Jobs & Scheduler,
   Settings. Declares the view functions referenced by the router in app.js. */
'use strict';

/* ------------------------------------------------------------------ *
 *  VIEW: Accounts & Quota Balancing
 * ------------------------------------------------------------------ */
let accountsViewRevision = 0;
let visibleAccountHealth = '';
let accountHealthRefreshing = false;
const accountHealthSignature = accounts => JSON.stringify(accounts.map(a =>
  [a.id, a.status, a.session_state, a.session_configured, a.last_cookie_refresh_at]));

async function refreshVisibleAccountHealth() {
  if (accountHealthRefreshing || APP.hidden || currentRoute !== 'accounts' ||
      $('#modalHost .modal') || $('[data-verifying="true"]', MAIN)) return;
  accountHealthRefreshing = true;
  const revision = accountsViewRevision;
  try {
    const accounts = await apiGet('/api/accounts');
    if (revision === accountsViewRevision && currentRoute === 'accounts' &&
        !$('#modalHost .modal') && !$('[data-verifying="true"]', MAIN) &&
        accountHealthSignature(accounts) !== visibleAccountHealth) {
      await viewAccounts();
    }
  } finally { accountHealthRefreshing = false; }
}

async function viewAccounts() {
  const revision = ++accountsViewRevision;
  const viewHash = location.hash;
  const [accounts, campaigns] = await Promise.all([
    apiGet('/api/accounts'),
    apiGet('/api/campaigns').catch(() => [])
  ]);
  const needsAuth = accounts.filter(a => ['warn','crit'].includes(accountHealth(a)[0]));

  if (APP.hidden || location.hash !== viewHash || revision !== accountsViewRevision) return;
  visibleAccountHealth = accountHealthSignature(accounts);
  MAIN.innerHTML = `<div class="page accounts-page">
    <div class="page-head">
      <div>
        <h1>LinkedIn Accounts <span class="pill pill-primary" style="vertical-align:4px">${accounts.length} managed</span></h1>
        <p class="page-sub">Multi-account load balancing &amp; session auto-rotation · daily quotas per account</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary" id="accVerifyAll" ${accounts.some(a => a.session_configured) ? '' : 'disabled'} title="Verify every account's session one by one"><span class="msym">done_all</span>Verify All</button>
        <button class="btn btn-secondary" id="accReload"><span class="msym">refresh</span>Refresh</button>
        <button class="btn btn-primary" id="accAdd"><span class="msym">add</span>Add LinkedIn Account</button>
      </div>
    </div>

    ${needsAuth.length ? `<div class="banner banner-warn banner-compact">
      <p class="banner-line" title="${esc(needsAuth.map(a => `${a.name} — ${accountHealth(a)[1]}`).join(' · '))}"><span class="msym" aria-hidden="true">warning</span><b>${needsAuth.length} account${needsAuth.length > 1 ? 's' : ''} need attention:</b>&nbsp;${needsAuth.map(a => `${esc(a.name)} (${esc(accountHealth(a)[1])})`).join(' · ')}. Restore Sales Navigator access or upload fresh cookies, then verify.</p>
      <a class="btn btn-secondary btn-sm" href="#/dashboard?history=1">View run logs</a>
    </div>` : ''}

    <div class="card table-wrap">
      <table class="data compact" style="min-width:860px">
        <thead><tr>
          <th>Account</th><th>Session</th><th>Refreshed</th>
          <th class="q-num" style="width:72px">InMail</th><th class="q-num" style="width:72px">Invites</th>
          <th class="q-num" style="width:100px">Invites / week</th><th class="q-num" style="width:72px">Messages</th><th class="q-runs" style="width:44px">Runs</th><th>Campaigns</th><th style="text-align:right">Actions</th>
        </tr></thead>
        <tbody>
          ${accounts.length ? accounts.map(a => {
            const paused = a.status === 'paused';
            const u = a.usage_today || { invites: 0, inmails: 0, messages: 0 };
            const statePill = pill(...accountHealth(a));
            return `<tr>
              <td><button class="account-open" data-account-details="${a.id}" aria-haspopup="dialog" aria-label="View ${esc(a.name)} details">${who(a.name, '')}</button></td>
              <td>${statePill}</td>
              <td class="date-cell">${a.last_cookie_refresh_at ? ago(a.last_cookie_refresh_at) : 'never'}</td>
              <td class="q-num">${quotaBar(u.inmails, a.daily_inmail_cap)}</td>
              <td class="q-num">${quotaBar(u.invites, a.daily_invite_cap)}</td>
              <td class="q-num">${quotaBar(a.weekly_invites?.used ?? 0, a.weekly_invite_cap ?? 100)}<small class="muted">${a.weekly_invites?.remaining ?? 100} left</small></td>
              <td class="q-num">${quotaBar(u.messages, a.daily_message_cap)}</td>
              <td class="q-runs"><span class="runs-num"><b data-live-runs="${a.id}">${a.total_runs ?? 0}</b></span></td>
              <td>
                ${a.campaigns.length ? `<button class="camp-dd-btn" data-campdd="${a.id}" aria-haspopup="dialog"><span>${a.campaigns.length} campaign${a.campaigns.length > 1 ? 's' : ''}</span><span class="msym">open_in_new</span></button>` : '<span class="muted">—</span>'}
              </td>
              <td>
                <div class="cell-actions row-actions">
                  <button class="btn btn-ghost btn-sm icon-only" data-caps="${a.id}" title="Settings &amp; assigned campaigns" aria-label="Settings for ${esc(a.name)}"><span class="msym">tune</span></button>
                  <button class="btn btn-ghost btn-sm icon-only" data-upload="${a.id}" title="Upload cookies JSON" aria-label="Upload cookies for ${esc(a.name)}"><span class="msym">upload_file</span></button>
                  <button class="btn btn-secondary btn-sm act-pause" data-toggle="${a.id}" ${['needs_reauth','seat_required'].includes(a.status) ? 'disabled' : ''} title="${paused ? 'Resume' : 'Pause'} automation" aria-label="${paused ? 'Resume' : 'Pause'} ${esc(a.name)}"><span class="msym">${paused ? 'play_arrow' : 'pause'}</span>${paused ? 'Resume' : 'Pause'}</button>
                  <button class="btn btn-secondary btn-sm act-verify" data-verify="${a.id}" ${a.session_configured ? '' : 'disabled'} title="Verify session" aria-label="Verify session for ${esc(a.name)}"><span class="msym">autorenew</span>Verify</button>
                  <button class="btn btn-ghost btn-sm icon-only" data-remove="${a.id}" title="Remove account" aria-label="Remove ${esc(a.name)}"><span class="msym">delete</span></button>
                </div>
              </td>
            </tr>`;
          }).join('') : `<tr class="empty-row"><td colspan="10">No accounts configured yet. Run the migration script or add one above.</td></tr>`}
        </tbody>
      </table>
    </div>
    <p class="muted small">Sessions are stored as files on the server and are never returned by the API. Session health reflects the last real access check (verify or job run) — cookie age is shown for reference only. The effective per-campaign send budget is the lower of the campaign limit and the account cap.</p>
  </div>`;

  $('#accReload').onclick = () => viewAccounts().catch(e => toast(errText(e), 'crit'));
  $('#accAdd').onclick = () => accountEditor(null, campaigns).catch(e => toast(errText(e), 'crit'));

  /* Verify All: one at a time (LinkedIn rate limits), with per-row progress. */
  $('#accVerifyAll').onclick = async () => {
    const targets = accounts.filter(a => a.session_configured);
    if (!targets.length) { toast('No accounts have a cookies session configured yet.', 'warn'); return; }
    if (!window.confirm(`Verify ${targets.length} account session${targets.length > 1 ? 's' : ''} one by one? This takes a few seconds per account.`)) return;
    const btn = $('#accVerifyAll');
    btn.disabled = true;
    let ok = 0, failed = 0;
    for (const a of targets) {
      const rowBtn = $(`[data-verify="${a.id}"]`, MAIN);
      if (rowBtn) { rowBtn.disabled = true; rowBtn.innerHTML = '<span class="msym">hourglass_top</span>'; }
      btn.innerHTML = `<span class="msym">hourglass_top</span>Verifying ${esc(a.name)} (${ok + failed + 1}/${targets.length})`;
      try {
        await apiPost(`/api/accounts/${a.id}/verify-session`);
        a.status = 'active'; ok++;
      } catch (e) { failed++; toast(`${a.name}: ${errText(e)}`, 'crit'); }
    }
    leadV2._accounts = null; threadV2._accounts = null;
    toast(`Verify All finished: ${ok} verified${failed ? `, ${failed} failed` : ''}`, failed ? 'warn' : 'ok');
    if (currentRoute === 'accounts') await viewAccounts().catch(e => quietToast(e));
    else { btn.disabled = false; btn.innerHTML = '<span class="msym">done_all</span>Verify All'; }
  };

  $$('[data-account-details]', MAIN).forEach(b => b.onclick = () => accountDetails(accounts.find(a => a.id === Number(b.dataset.accountDetails))));
  $$('[data-campdd]', MAIN).forEach(b => b.onclick = () => accountDetails(accounts.find(a => a.id === Number(b.dataset.campdd)), true));
  $$('[data-caps]', MAIN).forEach(b => b.onclick = () => {
    const a = accounts.find(x => x.id === Number(b.dataset.caps));
    accountEditor(a, campaigns).catch(e => toast(errText(e), 'crit'));
  });
  $$('[data-upload]', MAIN).forEach(b => b.onclick = () => {
    const id = Number(b.dataset.upload);
    const a = accounts.find(x => x.id === id);
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      b.disabled = true; b.innerHTML = '<span class="msym">hourglass_top</span>Uploading…';
      try {
        const fd = new FormData();
        fd.append('file', file);
        const res = await apiPost(`/api/accounts/${id}/upload-cookies`, fd);
        if (res.session_ok === true) toast(`Cookies uploaded for ${a ? a.name : 'account'} - session verified, account active`, 'ok');
        else if (res.status === 'seat_required') toast(`Cookies uploaded - account has no Sales Navigator seat (not a cookies problem)`, 'warn');
        else if (res.session_ok === false) toast(`Cookies uploaded but LinkedIn rejected them (401/403) - re-capture with get_cookies.py`, 'crit');
        else toast(`Cookies uploaded for ${a ? a.name : 'account'} - could not live-check just now; run Verify session`, 'warn');
        viewAccounts().catch(e => quietToast(e));
      } catch (e) {
        toast(errText(e), 'crit');
        b.disabled = false; b.innerHTML = '<span class="msym">upload_file</span>';
      }
    };
    input.click();
  });
  $$('[data-toggle]', MAIN).forEach(b => b.onclick = async () => {
    const a = accounts.find(x => x.id === Number(b.dataset.toggle));
    const status = a.status === 'paused' ? 'active' : 'paused';
    if (!window.confirm(`${status === 'paused' ? 'Pause' : 'Resume'} ${a.name}? This changes automated outreach for its assigned campaigns.`)) return;
    b.disabled = true;
    try {
      await apiPut(`/api/accounts/${a.id}`, { name: a.name, status, daily_invite_cap: a.daily_invite_cap, daily_inmail_cap: a.daily_inmail_cap, daily_message_cap: a.daily_message_cap });
      toast(`${a.name} ${status === 'paused' ? 'paused' : 'resumed'}`, 'ok');
      viewAccounts().catch(e => quietToast(e));
    } catch (e) { toast(errText(e), 'crit'); b.disabled = false; }
  });
  $$('[data-remove]', MAIN).forEach(b => b.onclick = async () => {
    const a = accounts.find(x => x.id === Number(b.dataset.remove));
    const campN = a.campaigns.length;
    const msg = `Remove ${a.name}?

` +
      (campN ? `It will be unlinked from ${campN} campaign${campN > 1 ? 's' : ''}. ` : '') +
      `Its cookie file will be deleted from the server. Leads it contacted keep their history but become unowned.

This cannot be undone.`;
    if (!window.confirm(msg)) return;
    b.disabled = true; b.innerHTML = '<span class="msym">hourglass_top</span>';
    try {
      await apiDelete(`/api/accounts/${a.id}`);
      toast(`${a.name} removed`, 'ok');
      viewAccounts().catch(e => quietToast(e));
    } catch (e) {
      toast(errText(e), 'crit');
      b.disabled = false; b.innerHTML = '<span class="msym">delete</span>';
    }
  });
  $$('[data-verify]', MAIN).forEach(b => b.onclick = async () => {
    const id = Number(b.dataset.verify);
    const account = accounts.find(x => x.id === id);
    // Block every concurrent renderer for the whole request: the poller must
    // not repaint stale (pre-verify) health, and this row keeps its own DOM.
    ++accountsViewRevision; b.dataset.verifying = 'true';
    b.disabled = true; b.innerHTML = '<span class="msym">hourglass_top</span>';
    try {
      await apiPost(`/api/accounts/${id}/verify-session`);
      // Trust the endpoint: it reports the post-verify status it persisted.
      if (account) account.status = 'active';
      toast('Session verified', 'ok');
    } catch (e) {
      toast(errText(e), 'crit');
    } finally {
      leadV2._accounts = null; threadV2._accounts = null;
      // Drop the verifying flag only after the repaint, so the health poller
      // can't slip a stale snapshot in between (the old "shown wrongly" bug).
      if (currentRoute === 'accounts' && location.hash === viewHash) {
        await viewAccounts().catch(e => quietToast(e));
      }
      delete b.dataset.verifying;
      if (b.isConnected) {
        b.disabled = false;
        const acc = accounts.find(x => x.id === id);
        b.innerHTML = `<span class="msym">autorenew</span>Verify`;
        b.title = 'Verify session';
        void acc;
      }
    }
  });
}

async function accountEditor(a, initialCampaigns) {
  const isNew = !a;
  const campaigns = initialCampaigns || await apiGet('/api/campaigns').catch(() => []);
  const assignedCids = new Set(
    a?.campaign_ids || (a ? campaigns.filter(c => c.accounts?.some(l => l.account_id === a.id)).map(c => c.id) : [])
  );

  openModal(isNew ? 'Add LinkedIn Account' : `Account settings — ${a.name}`, `
    <form id="accForm" class="grid-2-col">
      <label class="field">
        <span>Account name</span>
        <input class="input" name="name" required value="${esc(a?.name || '')}" ${isNew ? '' : 'readonly'}>
      </label>
      <label class="field"><span>Status</span>
        <select class="input" name="status" ${['needs_reauth','seat_required'].includes(a?.status)?'disabled':''}>${accountStatusOptions(a?.status)}</select>
      </label>

      <div class="field span2">
        <span>Cookies Session File (.json)</span>
        <div style="display:flex;gap:8px;align-items:center">
          <input type="file" id="accCookieFile" class="input" accept=".json" style="padding:5px;flex:1;min-width:0">
          ${!isNew && a.session_configured ? `<button type="button" class="btn btn-secondary btn-sm" id="modalVerifyBtn"><span class="msym">autorenew</span>Verify</button>` : ''}
        </div>
        <small class="muted">Upload exported cookies JSON — saved on the server and linked automatically.</small>
      </div>

      <div class="field span2">
        <span>Assign Campaigns</span>
        ${campaigns.length ? `
        <span class="dd-wrap" style="display:flex">
          <button type="button" class="dd-btn" id="accCampDD" aria-expanded="false" aria-haspopup="true" style="width:100%;justify-content:space-between">
            <span id="accCampDDLabel">${assignedCids.size ? `${assignedCids.size} campaign${assignedCids.size > 1 ? 's' : ''} assigned` : 'Select campaigns…'}</span>
            <span class="msym">expand_more</span>
          </button>
          <span class="dd-panel" id="accCampPanel" style="width:100%;max-width:none" hidden>
            <span class="dd-head">
              <button type="button" class="dd-btn" id="accCampAll" style="flex:1;height:28px;font-size:12px">All</button>
              <button type="button" class="dd-btn" id="accCampNone" style="flex:1;height:28px;font-size:12px">None</button>
            </span>
            ${campaigns.map(c => `
              <label class="dd-item"><input type="checkbox" name="assigned_campaigns" value="${c.id}" ${assignedCids.has(c.id) ? 'checked' : ''}>
                <span>${esc(c.name)} <small class="muted">· ${c.status}</small></span></label>
            `).join('')}
          </span>
        </span>` : '<span class="muted small">No campaigns created yet.</span>'}
        <small class="muted">Only mapped accounts run outreach for a campaign. Selected campaigns will be linked to this account.</small>
      </div>

      <label class="field"><span>Invite cap / day</span><input class="input mono" name="daily_invite_cap" type="number" min="0" value="${a?.daily_invite_cap ?? 30}"></label>
      <label class="field"><span>InMail cap / day</span><input class="input mono" name="daily_inmail_cap" type="number" min="0" value="${a?.daily_inmail_cap ?? 10}"></label>
      <label class="field span2"><span>Message cap / day</span><input class="input mono" name="daily_message_cap" type="number" min="0" value="${a?.daily_message_cap ?? 60}"></label>
      <div class="field span2 weekly-invite-limit">
        <div class="weekly-limit-heading"><label for="weeklyInviteCap">Weekly invitation limit</label><output id="weeklyInviteValue" for="weeklyInviteCap">${a?.weekly_invite_cap ?? 100}</output></div>
        <input id="weeklyInviteCap" name="weekly_invite_cap" type="range" min="0" max="150" step="1" value="${a?.weekly_invite_cap ?? 100}" aria-describedby="weeklyInviteHelp">
        <div class="weekly-limit-scale"><span>0 · Invitations off</span><span>150 maximum</span></div>
        <small id="weeklyInviteHelp" class="muted">Resets every Monday, shared across all campaigns. ${a?.weekly_invites?.used ?? 0} sent this week by this app. Daily limits still apply. Invitations sent outside this app are not tracked.</small>
      </div>
      <p class="muted small span2" style="margin:0">Invites stop at the lowest remaining campaign, daily or weekly limit.</p>
    </form>`,
    `<button class="btn btn-secondary" data-close2>Cancel</button><button class="btn btn-primary" id="accSave">${isNew ? 'Add account' : 'Save account'}</button>`);

  $('#modalHost [data-close2]').onclick = closeModal;
  $('#modalHost .modal').classList.add('account-editor-modal');
  $('#weeklyInviteCap').oninput = e => { $('#weeklyInviteValue').value = e.target.value; };

  /* Assign-Campaigns dropdown: toggle panel, All/None shortcuts, live label */
  const campDD = $('#accCampDD'), campPanel = $('#accCampPanel');
  if (campDD && campPanel) {
    const campLabel = $('#accCampDDLabel');
    const updateCampLabel = () => {
      const n = campPanel.querySelectorAll('input[name="assigned_campaigns"]:checked').length;
      campLabel.textContent = n ? `${n} campaign${n > 1 ? 's' : ''} assigned` : 'Select campaigns…';
      campDD.classList.toggle('active', n > 0);
    };
    campDD.onclick = (e) => {
      e.stopPropagation();
      const open = campPanel.hidden;
      campPanel.hidden = !open;
      campDD.setAttribute('aria-expanded', String(open));
    };
    campPanel.addEventListener('click', (e) => e.stopPropagation());
    campPanel.addEventListener('change', updateCampLabel);
    $('#accCampAll').onclick = () => {
      campPanel.querySelectorAll('input[name="assigned_campaigns"]').forEach(cb => cb.checked = true);
      updateCampLabel();
    };
    $('#accCampNone').onclick = () => {
      campPanel.querySelectorAll('input[name="assigned_campaigns"]').forEach(cb => cb.checked = false);
      updateCampLabel();
    };
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#accCampDD') && !e.target.closest('#accCampPanel')) {
        campPanel.hidden = true; campDD.setAttribute('aria-expanded', 'false');
      }
    });
    updateCampLabel();
  }

  const modalVerifyBtn = $('#modalVerifyBtn');
  if (modalVerifyBtn && a?.id) {
    modalVerifyBtn.onclick = async () => {
      const verifyForm = $('#accForm');
      modalVerifyBtn.disabled = true;
      modalVerifyBtn.innerHTML = '<span class="msym">hourglass_top</span>Verifying…';
      try {
        await apiPost(`/api/accounts/${a.id}/verify-session`);
        toast('Session verified successfully', 'ok');
      } catch (e) {
        toast(errText(e), 'crit');
      } finally {
        leadV2._accounts = null; threadV2._accounts = null;
        try {
          const updated = (await apiGet('/api/accounts')).find(row=>row.id===a.id);
          if (updated) {
            Object.assign(a, updated);
            if (verifyForm.isConnected) {
              verifyForm.status.innerHTML = accountStatusOptions(a.status);
              verifyForm.status.disabled = ['needs_reauth','seat_required'].includes(a.status);
            }
          }
          if (currentRoute === 'accounts') await viewAccounts();
        } catch (e) { quietToast(e); }
        modalVerifyBtn.disabled = false;
        modalVerifyBtn.innerHTML = '<span class="msym">autorenew</span>Verify Session';
      }
    };
  }

  $('#accSave').onclick = async () => {
    const f = $('#accForm');
    const selectedCampIds = Array.from(f.querySelectorAll('input[name="assigned_campaigns"]:checked')).map(cb => Number(cb.value));
    const body = {
      name: f.name.value.trim(),
      status: f.status.value,
      daily_invite_cap: Math.max(0, Number(f.daily_invite_cap.value) || 0),
      weekly_invite_cap: Number(f.weekly_invite_cap.value),
      daily_inmail_cap: Math.max(0, Number(f.daily_inmail_cap.value) || 0),
      daily_message_cap: Math.max(0, Number(f.daily_message_cap.value) || 0),
      campaign_ids: selectedCampIds,
    };
    if (!body.name) { toast('Enter an account name', 'warn'); return; }
    try {
      let accId = a?.id;
      if (isNew) {
        const res = await apiPost('/api/accounts', body);
        accId = res.id;
      } else {
        await apiPut(`/api/accounts/${a.id}`, body);
      }
      const cookieFileInput = $('#accCookieFile');
      if (cookieFileInput?.files?.[0] && accId) {
        const fd = new FormData();
        fd.append('file', cookieFileInput.files[0]);
        await apiPost(`/api/accounts/${accId}/upload-cookies`, fd);
      }
      closeModal();
      toast(isNew ? 'Account added successfully' : 'Account updated successfully', 'ok');
      viewAccounts().catch(e => quietToast(e));
    } catch (e) { toast(errText(e), 'crit'); }
  };
}

/* ------------------------------------------------------------------ *
 *  VIEW: Campaigns list
 * ------------------------------------------------------------------ */
async function viewCampaigns() {
  const viewHash = location.hash;
  const rows = await apiGet('/api/campaigns');
  const totalLeads = rows.reduce((s, c) => s + (c.leads || 0), 0);
  const totalContacted = rows.reduce((s, c) => s + (c.contacted || 0), 0);
  const totalReplies = rows.reduce((s, c) => s + (c.replied || 0), 0);
  const active = rows.filter(c => c.status === 'active').length;
  const rate = totalContacted ? ((totalReplies / totalContacted) * 100).toFixed(1) : '0.0';

  if (APP.hidden || location.hash !== viewHash) return;
  MAIN.innerHTML = `<div class="page campaigns-page">
    <div class="camp-hero">
      <div>
        <h1 class="ch-title">Outreach Campaigns</h1>
        <div class="ch-sub">Load balancing, budgets and reply performance per campaign</div>
      </div>
      <div class="ch-stats">
        <div class="ch-stat"><b>${rows.length}</b><span>Campaigns</span></div>
        <div class="ch-stat"><b>${active}</b><span>Active</span></div>
        <div class="ch-stat"><b>${totalLeads.toLocaleString()}</b><span>Leads</span></div>
        <div class="ch-stat"><b>${rate}%</b><span>Reply rate</span></div>
      </div>
      <a class="btn btn-secondary camp-new-btn" href="#/campaign/new"><span class="msym">add</span>New Campaign</a>
    </div>

    ${rows.length ? `<div class="camp-grid">
      ${rows.map((c, i) => {
        const rr = c.reply_rate || 0;
        const rrCls = rr >= 8 ? 'rr-ok' : rr > 0 ? 'rr-warn' : '';
        return `<div class="camp-card" style="animation-delay:${Math.min(i * 40, 240)}ms">
          <div class="camp-card-top">
            <div style="flex:1;min-width:0">
              <a class="cc-name" href="#/campaign/${c.id}">${esc(c.name)}</a>
              <div class="cc-key">key: ${esc(c.campaign_key)}</div>
            </div>
            ${pill(c.status === 'active' ? 'ok' : 'warn', c.status, false)}
          </div>
          <div class="camp-nums">
            <div><b>${c.leads}</b><span>Leads</span></div>
            <div><b>${c.contacted}</b><span>Contacted</span></div>
            <div class="${rrCls}"><b>${rr}%</b><span>Replies</span></div>
          </div>
          <div class="camp-accounts">
            ${c.accounts.length ? c.accounts.map(a => `<span class="tag" title="invite/inmail/msg per day: ${a.invite_limit}/${a.inmail_limit}/${a.message_limit}"><span class="mono">${a.order_index + 1}</span> ${esc(a.account_name)}</span>`).join('') : '<span class="muted small">No accounts assigned</span>'}
          </div>
          <div class="camp-actions">
            <a class="btn btn-secondary btn-sm" href="#/campaign/${c.id}"><span class="msym">edit</span>Edit</a>
            <button class="btn btn-secondary btn-sm" data-copy-campaign="${c.id}" aria-label="Copy ${esc(c.name)}"><span class="msym">content_copy</span>Copy</button>
            <button class="btn btn-secondary btn-sm act-camp-pause" data-pause-campaign="${c.id}" title="${c.status === 'active' ? 'Pause' : 'Resume'} all automation for this campaign" aria-label="${c.status === 'active' ? 'Pause' : 'Resume'} ${esc(c.name)}"><span class="msym">${c.status === 'active' ? 'pause' : 'play_arrow'}</span>${c.status === 'active' ? 'Pause' : 'Resume'}</button>
            <span class="spacer"></span>
            <button class="btn btn-ghost btn-sm icon-only" data-del-campaign="${c.id}" data-name="${esc(c.name)}" title="Delete campaign" aria-label="Delete ${esc(c.name)}"><span class="msym">delete</span></button>
          </div>
        </div>`;
      }).join('')}
    </div>` : `<div class="card card-pad" style="text-align:center;padding:40px">
      <span class="msym" style="font-size:40px;color:var(--faint)">rocket_launch</span>
      <h2 style="margin:8px 0 4px">No campaigns yet</h2>
      <p class="muted" style="margin:0 0 14px">Create your first campaign to start assigning accounts and budgets.</p>
      <a class="btn btn-primary" href="#/campaign/new"><span class="msym">add</span>New Campaign</a>
    </div>`}
  </div>`;

  $$('[data-copy-campaign]', MAIN).forEach(b => b.onclick = () => {
    const campaign = rows.find(c => c.id === Number(b.dataset.copyCampaign));
    if (campaign) copyCampaignDialog(campaign);
  });

  $$('[data-pause-campaign]', MAIN).forEach(b => b.onclick = async () => {
    const c = rows.find(x => x.id === Number(b.dataset.pauseCampaign));
    if (!c) return;
    const next = c.status === 'active' ? 'paused' : 'active';
    b.disabled = true;
    try {
      await apiPut(`/api/campaigns/${c.id}/pause`, { status: next });
      toast(`${c.name} ${next === 'paused' ? 'paused' : 'resumed'}`, 'ok');
      viewCampaigns().catch(e => quietToast(e));
    } catch (e) { toast(errText(e), 'crit'); b.disabled = false; }
  });

  $$('[data-del-campaign]', MAIN).forEach(b => b.onclick = async () => {
    const name = b.dataset.name;
    if (!window.confirm(`Delete campaign “${name}”?\n\nIts leads are kept but become untagged — history is not lost. This cannot be undone.`)) return;
    b.disabled = true;
    try {
      const res = await apiDelete(`/api/campaigns/${b.dataset.delCampaign}`);
      toast(`Campaign deleted${res?.leads_untagged ? ` — ${res.leads_untagged} lead${res.leads_untagged > 1 ? 's' : ''} kept as untagged` : ''}`, 'ok');
      viewCampaigns().catch(e => quietToast(e));
    } catch (e) { toast(errText(e), 'crit'); b.disabled = false; }
  });
}

/* ------------------------------------------------------------------ *
 *  VIEW: Campaign detail (create/edit with per-campaign account limits)
 * ------------------------------------------------------------------ */
function copyCampaignDialog(campaign) {
  const name = (campaign.name || '').slice(0, 115) + ' copy';
  const key = (campaign.campaign_key || campaign.name || '').slice(0, 115) + '-copy';
  openModal('Copy campaign', `<p class="muted">Copy saved templates, account mappings and daily limits into a new paused campaign. Leads, schedules and history stay with the original.</p>
    <form id="campaignCopyForm" class="dialog-grid">
      <label class="field"><span>New campaign name</span><input class="input" id="copyName" maxlength="120" value="${esc(name)}" required></label>
      <label class="field"><span>Unique campaign key</span><input class="input" id="copyKey" maxlength="120" value="${esc(key)}" required></label>
    </form>`, '<button class="btn btn-secondary" id="copyCancel">Cancel</button><button class="btn btn-primary" id="copySave"><span class="msym">content_copy</span>Create copy</button>');
  $('#copyCancel').onclick = closeModal;
  $('#copySave').onclick = async e => {
    if (!$('#campaignCopyForm').reportValidity()) return;
    const button = e.currentTarget;
    const body = {name: $('#copyName').value.trim(), campaign_key: $('#copyKey').value.trim()};
    button.disabled = true;
    try {
      const copied = await apiPost(`/api/campaigns/${campaign.id}/copy`, body);
      closeModal(); toast('Campaign copied and paused', 'ok');
      location.hash = `#/campaign/${copied.id}`;
    } catch (error) { toast(errText(error), 'crit'); button.disabled = false; }
  };
  $('#campaignCopyForm').onsubmit = e => { e.preventDefault(); $('#copySave').click(); };
}

const CAMPAIGN_TABS = [
  ['invite', 'Connection Invite', 'person_add'],
  ['invite_seq', 'Invite Follow-ups', 'cached'],
  ['inmail', 'InMail', 'send'],
  ['inmail_seq', 'InMail Follow-ups', 'forum'],
];

async function viewCampaignDetail(id) {
  const viewHash = location.hash;
  const isNew = !id || id === 'new';
  const [accounts, detail] = await Promise.all([
    apiGet('/api/accounts'),
    isNew ? Promise.resolve(null) : apiGet(`/api/campaigns/${id}`),
  ]);
  if (APP.hidden || location.hash !== viewHash) return;
  if (!isNew && !detail) { MAIN.innerHTML = '<div class="page"><div class="banner banner-crit">Campaign not found.</div></div>'; return; }
  const d = detail ?? {
    id: 0, campaign_key: '', name: '', status: 'active', search_url: '',
    invite_text: '', invite_track: ['', '', '', ''], inmail_subject: '', inmail_text: '',
    inmail_track: [{ subject: '', body: '' }, { subject: '', body: '' }, { subject: '', body: '' }],
    accounts: [],
  };
  let tab = 'invite';

  function render() {
    if (APP.hidden || location.hash !== viewHash) return;
  MAIN.innerHTML = `<div class="page">
      <div class="page-head">
        <div>
          <h1>${isNew ? 'New Campaign' : esc(d.name)}</h1>
          <p class="page-sub">${isNew ? 'Create a campaign and assign accounts with daily budgets' : `key: ${esc(d.campaign_key)} (immutable — it tags every lead row)`}</p>
        </div>
        <div class="page-actions">
          ${pill(d.status === 'active' ? 'ok' : 'warn', d.status)}
          ${!isNew ? '<button class="btn btn-secondary" id="cCopy"><span class="msym">content_copy</span>Copy</button>' : ''}
          <button class="btn btn-primary" id="cSave"><span class="msym">save</span>${isNew ? 'Create' : 'Save'}</button>
          <a class="btn btn-secondary" href="#/campaigns">Back</a>
        </div>
      </div>
      <div class="grid" style="grid-template-columns:minmax(300px,1fr) 2fr;align-items:start">
        <div class="grid" style="gap:14px">
          <div class="card card-pad">
            <h2>Campaign</h2>
            <label class="field"><span>Name</span><input class="input" id="cName" value="${esc(d.name)}" required></label>
            <label class="field"><span>Campaign key ${isNew ? '' : '(immutable)'}</span><input class="input mono" id="cKey" value="${esc(d.campaign_key)}" ${isNew ? '' : 'disabled'} placeholder="e.g. SCM Podcast"></label>
            <label class="field"><span>Status</span>
              <select class="input" id="cStatus">
                <option value="active" ${d.status === 'active' ? 'selected' : ''}>active</option>
                <option value="paused" ${d.status === 'paused' ? 'selected' : ''}>paused</option>
              </select>
            </label>
            <p class="muted small">Import SavedSearch runs manually from Workers with an account + Search ID. Assign imported leads from the Leads page.</p>
          </div>

          <div class="card card-pad">
            <div class="section-title"><h2>Accounts &amp; quota balancing</h2><button class="btn btn-secondary btn-sm" id="cAddAcc"><span class="msym">add</span>Add</button></div>
            <p class="card-sub">Leads fill the first account until its daily budget is exhausted, then roll to the next. Effective budget = min(campaign limit, account cap).</p>
            <div class="grid" style="gap:10px" id="cAccounts">
              ${d.accounts.map((a, i) => accountLimitRow(a, i, accounts)).join('') || '<p class="muted small" style="text-align:center;padding:8px">No accounts assigned yet.</p>'}
            </div>
          </div>
        </div>

        <div class="card">
          <div class="tabs" role="tablist">
            ${CAMPAIGN_TABS.map(([key, label, icon]) => `<button class="tab ${tab === key ? 'on' : ''}" data-tab="${key}" role="tab"><span class="msym">${icon}</span>${label}</button>`).join('')}
          </div>
          <div class="card-pad">${tabBody(tab, d)}</div>
        </div>
      </div>
    </div>`;

    $$('[data-tab]', MAIN).forEach(b => b.onclick = () => { collect(); tab = b.dataset.tab; render(); });
    $('#cAddAcc').onclick = () => {
      collect();
      /* Always open the compact add-account popup: it lists remaining free
         accounts AND offers inline creation when none are left. */
      quickAddAccountDialog(accounts, d, () => render());
    };
    $$('.acc-select', MAIN).forEach(select => select.onchange = () => { collect(); render(); });
    $$('.acc-remove', MAIN).forEach(b => b.onclick = () => { collect(); d.accounts.splice(Number(b.dataset.i), 1); render(); });
    const collect = () => {
      d.name = $('#cName').value.trim();
      if (isNew) d.campaign_key = $('#cKey').value.trim();
      d.status = $('#cStatus').value;
      $$('#cAccounts .acc-row', MAIN).forEach((row, i) => {
        if (!d.accounts[i]) return;
        const acc = d.accounts[i];
        acc.account_id = Number(row.querySelector('.acc-select').value);
        acc.invite_limit = Math.max(0, Number(row.querySelector('.acc-invite').value) || 0);
        acc.inmail_limit = Math.max(0, Number(row.querySelector('.acc-inmail').value) || 0);
        acc.message_limit = Math.max(0, Number(row.querySelector('.acc-msg').value) || 0);
        acc.calendar_url = row.querySelector('.acc-cal').value || '';
      });
      collectTemplates();
    };
    if ($('#cCopy')) $('#cCopy').onclick = () => copyCampaignDialog(detail);
    $('#cSave').onclick = async () => {
      collect();
      d.name = $('#cName').value.trim();
      if (isNew) d.campaign_key = $('#cKey').value.trim();
      d.status = $('#cStatus').value;
      if (!d.name || !d.accounts.length) { toast('Enter a campaign name and add at least one account', 'warn'); return; }
      if (new Set(d.accounts.map(a => a.account_id)).size !== d.accounts.length) { toast('Each account can appear only once in this campaign.', 'warn'); return; }
      const templates = [d.invite_text, d.inmail_subject, d.inmail_text, ...d.invite_track, ...d.inmail_track.flatMap(t => [t.subject, t.body])];
      if (templates.some(t => /[{}]/.test((t || '').replace(/\{(first_name|company|calendar_url)\}/g, '')))) { toast('Use only {first_name}, {company} and {calendar_url} placeholders', 'warn'); return; }
      const payload = {
        name: d.name,
        campaign_key: isNew ? d.campaign_key : undefined,
        status: d.status,
        invite_text: d.invite_text,
        invite_track: (d.invite_track || []).map(x => x ?? ''),
        inmail_subject: d.inmail_subject, inmail_text: d.inmail_text,
        inmail_track: (d.inmail_track || []).map(t => ({ subject: t.subject ?? '', body: t.body ?? '' })),
        accounts: d.accounts.map((a, i) => ({
          account_id: a.account_id, order_index: i,
          invite_limit: a.invite_limit, inmail_limit: a.inmail_limit, message_limit: a.message_limit,
          calendar_url: a.calendar_url || null, search_url_override: a.search_url_override || null,
        })),
      };
      try {
        if (isNew) { const created = await apiPost('/api/campaigns', payload); location.hash = `#/campaign/${created.id}`; }
        else {
          await apiPut(`/api/campaigns/${d.id}`, payload);
          // A rename must reach the Leads/Threads pages: drop their cached
          // campaign lists so the next render refetches fresh names.
          if (typeof invalidateCampaignCaches === 'function') invalidateCampaignCaches();
          toast('Campaign saved', 'ok');
        }
      } catch (e) { toast(errText(e), 'crit'); }
    };
  }

  function accountLimitRow(a, i, accounts) {
    return `<div class="acc-row" style="border:1px solid var(--hairline);border-radius:8px;padding:10px;display:grid;gap:8px">
      <div style="display:flex;gap:8px;align-items:center">
        <span class="mono muted">#${i + 1}</span>
        <select class="input acc-select" style="flex:1">${accounts.map(acc => `<option value="${acc.id}" ${acc.id === a.account_id ? 'selected' : ''} ${d.accounts.some((other, index) => index !== i && other.account_id === acc.id) ? 'disabled' : ''}>${esc(acc.name)}</option>`).join('')}</select>
        <button type="button" class="icon-btn acc-remove" data-i="${i}" aria-label="Remove account"><span class="msym">close</span></button>
      </div>
      <div class="grid" style="grid-template-columns:repeat(3,1fr);gap:8px">
        <label class="field" style="margin:0"><span>Invite/day</span><input class="input mono acc-invite" type="number" min="0" value="${a.invite_limit}"></label>
        <label class="field" style="margin:0"><span>InMail/day</span><input class="input mono acc-inmail" type="number" min="0" value="${a.inmail_limit}"></label>
        <label class="field" style="margin:0"><span>Msg/day</span><input class="input mono acc-msg" type="number" min="0" value="${a.message_limit}"></label>
      </div>
      <label class="field" style="margin:0"><span>Calendar URL (optional)</span><input class="input mono acc-cal" style="font-size:11px" value="${esc(a.calendar_url ?? '')}" placeholder="https://calendly.com/…"></label>
    </div>`;
  }

  function tabBody(key, d) {
    const hint = '<p class="muted small">Placeholders: <code class="mono">{first_name}</code> · <code class="mono">{company}</code> · <code class="mono">{calendar_url}</code></p>';
    if (key === 'invite') return `${hint}<label class="field"><span>First-touch invite note (with connection request)</span><textarea class="input" data-t="invite_text" rows="7">${esc(d.invite_text || '')}</textarea></label>`;
    if (key === 'invite_seq') return hint + [0, 1, 2, 3].map(i => `
      <label class="field"><span>${i === 0 ? 'After acceptance (sent by Check Replies)' : `Follow-up ${i} (+${i === 1 ? 3 : i === 2 ? 5 : 7} days)`}</span>
      <textarea class="input" data-t="invite_track_${i}" rows="4">${esc(d.invite_track[i] ?? '')}</textarea></label>`).join('');
    if (key === 'inmail') return `${hint}
      <label class="field"><span>InMail subject</span><input class="input" data-t="inmail_subject" value="${esc(d.inmail_subject || '')}"></label>
      <label class="field"><span>First-touch InMail body</span><textarea class="input" data-t="inmail_text" rows="7">${esc(d.inmail_text || '')}</textarea></label>`;
    return hint + [0, 1, 2].map(i => `
      <fieldset style="border:1px solid var(--hairline);border-radius:8px;padding:10px;margin:0 0 10px">
        <legend style="font:600 11px/14px Geist;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);padding:0 4px">InMail Follow-up ${i + 1} (+${i === 0 ? 3 : i === 1 ? 5 : 7} days)</legend>
        <input class="input" data-t="inmail_track_${i}_subject" placeholder="Subject" value="${esc(d.inmail_track[i]?.subject ?? '')}" style="margin-bottom:8px">
        <textarea class="input" data-t="inmail_track_${i}_body" rows="3" placeholder="Body">${esc(d.inmail_track[i]?.body ?? '')}</textarea>
      </fieldset>`).join('');
  }

  function collectTemplates() {
    $$('[data-t]', MAIN).forEach(el => {
      const key = el.dataset.t;
      const m = key.match(/^(invite_track|inmail_track)_(\d+)(_subject|_body)?$/);
      if (!m) { d[key] = el.value; return; }
      if (m[1] === 'invite_track') { while ((d.invite_track || []).length < 4) d.invite_track.push(''); d.invite_track[Number(m[2])] = el.value; }
      else { while ((d.inmail_track || []).length < 3) d.inmail_track.push({ subject: '', body: '' }); const i = Number(m[2]); d.inmail_track[i][m[3] === '_subject' ? 'subject' : 'body'] = el.value; }
    });
  }

  /* Compact popup for adding a LinkedIn account without leaving the campaign
     editor. Two modes: pick an existing free account, or create a new one
     inline (auto-assigned to this campaign on save). */
  function quickAddAccountDialog(allAccounts, campaignState, onDone) {
    const used = new Set(campaignState.accounts.map(a => a.account_id));
    const free = allAccounts.filter(a => !used.has(a.id));
    openModal('Add account to campaign', `
      <div class="qa-add-wrap">
        ${free.length ? `
        <div class="qa-section">
          <div class="qa-label">Pick an existing account</div>
          <div class="qa-picklist">
            ${free.map(a => `<button type="button" class="qa-pick" data-pick="${a.id}">
              <span class="who-avatar" style="background:${avatarColor(a.name)};width:26px;height:26px;font-size:10px">${esc(initials(a.name))}</span>
              <span class="qa-pick-name">${esc(a.name)}</span>
              <span class="muted small">caps ${a.daily_invite_cap ?? 30}/${a.daily_inmail_cap ?? 10}/${a.daily_message_cap ?? 60}</span>
              <span class="msym">add</span>
            </button>`).join('')}
          </div>
        </div>` : '<p class="muted small" style="margin:0 0 4px">Every existing account is already assigned to this campaign.</p>'}
        <div class="qa-section">
          <div class="qa-label">…or create a new account</div>
          <form id="qaAccForm" class="grid-2-col">
            <label class="field span2"><span>Account name</span>
              <input class="input" name="name" placeholder="e.g. Ranganathan A">
            </label>
            <label class="field"><span>Invite cap / day</span><input class="input mono" name="daily_invite_cap" type="number" min="0" value="30"></label>
            <label class="field"><span>InMail cap / day</span><input class="input mono" name="daily_inmail_cap" type="number" min="0" value="10"></label>
            <label class="field span2"><span>Cookies Session File (.json) — optional</span>
              <input type="file" id="qaCookieFile" class="input" accept=".json" style="padding:5px">
              <small class="muted">Upload later from Accounts; outreach needs it before the first run.</small>
            </label>
          </form>
        </div>
      </div>`,
      `<button class="btn btn-secondary" data-close2>Cancel</button><button class="btn btn-primary" id="qaSave" ${free.length ? '' : ''}><span class="msym">add</span>Create &amp; assign</button>`);
    $('#modalHost [data-close2]').onclick = closeModal;

    const assign = (accountId, accountName) => {
      campaignState.accounts.push({ account_id: accountId, account_name: accountName, order_index: campaignState.accounts.length, invite_limit: 10, inmail_limit: 10, message_limit: 30, calendar_url: '', search_url_override: '' });
      closeModal();
      toast(`${accountName} added to ${campaignState.name || 'campaign'} at position ${campaignState.accounts.length}`, 'ok');
      onDone();
    };

    $$('.qa-pick', $('#modalHost')).forEach(btn => btn.onclick = () => assign(Number(btn.dataset.pick), free.find(a => a.id === Number(btn.dataset.pick))?.name || 'account'));

    $('#qaSave').onclick = async () => {
      const f = $('#qaAccForm');
      const name = f.name.value.trim();
      if (!name) { toast('Enter an account name (or pick an existing account above)', 'warn'); return; }
      const btn = $('#qaSave');
      btn.disabled = true;
      try {
        const res = await apiPost('/api/accounts', {
          name,
          status: 'active',
          daily_invite_cap: Math.max(0, Number(f.daily_invite_cap.value) || 0),
          daily_inmail_cap: Math.max(0, Number(f.daily_inmail_cap.value) || 0),
          daily_message_cap: Math.max(0, Number(f.daily_message_cap?.value) || 60),
          campaign_ids: campaignState.id ? [campaignState.id] : [],
        });
        const cookieFile = $('#qaCookieFile');
        if (cookieFile?.files?.[0] && res.id) {
          const fd = new FormData(); fd.append('file', cookieFile.files[0]);
          await apiPost(`/api/accounts/${res.id}/upload-cookies`, fd);
        }
        allAccounts.push({ id: res.id, name, daily_invite_cap: 30, daily_inmail_cap: 10, daily_message_cap: 60, campaigns: [] });
        assign(res.id, name);
      } catch (e) { toast(errText(e), 'crit'); btn.disabled = false; }
    };
  }

  render();
}

/* ------------------------------------------------------------------ *
 *  VIEW: Workers (three send workers — run individually with scope)
 * ------------------------------------------------------------------ */
/* Workers: full page (still reachable from dashboard strip popup) + the
   compact strip injected at the top of the dashboard. */
const WORKER_ICONS = { send_connections: 'person_add', check_replies: 'forum', send_followups: 'cached' };

function workerStripHTML(jobs, live) {
  const running = live && live.status === 'running';
  return `<div class="workers-strip" role="group" aria-label="Workers">
    ${jobs.map(job => {
      const last = job.last_run;
      const isRun = job.running_now || (running && live.job === job.key);
      const cls = isRun ? 'wp-running' : last && last.status === 'error' ? 'wp-error' : '';
      const sub = isRun ? `Running · started ${ago(live.started_at)}`
        : last ? `Last: ${last.status}${last.dry_run ? ' (dry)' : ''} · ${ago(last.started_at)}`
        : 'Never run';
      return `<button class="worker-pill ${cls}" data-wpop="${job.key}" aria-haspopup="dialog"
        title="${esc(job.description)}">
        <span class="wp-ic"><span class="msym">${WORKER_ICONS[job.key] || 'play_arrow'}</span></span>
        <span class="wp-body">
          <span class="wp-name">${esc(JOB_LABELS[job.key])}</span>
          <span class="wp-sub">${esc(sub)}</span>
        </span>
        <span class="wp-status">${isRun ? pill('primary', 'running', false) : last && last.status === 'error' ? pill('crit', 'error', false) : last && last.status === 'success' ? pill('ok', 'ok', false) : pill('idle', 'idle', false)}</span>
      </button>`;
    }).join('')}
  </div>`;
}

function wireWorkerStrip(j, campaigns, accounts) {
  const running = j.live && j.live.status === 'running';
  $$('[data-wpop]', MAIN).forEach(btn => btn.onclick = () => {
    const job = j.jobs.find(x => x.key === btn.dataset.wpop);
    if (!job) return;
    const last = job.last_run;
    openModal(`${JOB_LABELS[job.key]}`, `
      <p class="muted" style="margin:0 0 4px">${esc(job.description)}</p>
      <div class="worker-pop-row">
        <span>Last run: ${last ? `${runStatus(last.status, last.dry_run)} <span class="mono small">${fmtDT(last.started_at)}</span>` : 'no runs yet'}</span>
        ${job.schedule && job.schedule.length ? `<span class="muted small">Schedule: ${esc(job.schedule.join(' · '))}</span>` : '<span class="muted small">Schedule: manual</span>'}
      </div>
      ${running ? `<div class="banner banner-info" style="margin-top:10px"><div><div class="banner-title">A worker is running</div><p>${esc(JOB_LABELS[j.live.job] || '')} started ${esc(ago(j.live.started_at))} — you can start another run using different accounts.</p></div></div>` : ''}`,
      `<button class="btn btn-secondary" data-close2>Close</button>
       ${last ? `<button class="btn btn-secondary" id="wpLog"><span class="msym">receipt_long</span>Last log</button>` : ''}
       <button class="btn btn-primary" id="wpRun"><span class="msym">play_arrow</span>Run now</button>`);
    $('#modalHost [data-close2]').onclick = closeModal;
    const logBtn = $('#wpLog');
    if (logBtn) logBtn.onclick = () => { closeModal(); openRunLog(last.id); };
    $('#wpRun').onclick = () => { closeModal(); runWorkerDialog(job.key, campaigns, accounts); };
  });
}

function workerStateSignature(j) { return JSON.stringify([(j.running || []).map(r=>[r.execution_id,r.job,r.status]), j.jobs.map(r=>[r.key,r.last_run?.id,r.last_run?.status])]); }
async function viewWorkers() {
  const viewHash = location.hash;
  const [j, campaigns, accounts] = await Promise.all([
    apiGet('/api/jobs'),
    apiGet('/api/campaigns'),
    apiGet('/api/accounts'),
  ]);
  const jobs = j.jobs.filter(x => WORKERS.includes(x.key));
  const running = j.live && j.live.running;

  if (APP.hidden || location.hash !== viewHash) return;
  window.__workersSignature = workerStateSignature(j);
  MAIN.innerHTML = `<div class="page">
    <div class="page-head">
      <div><h1>Workers</h1><p class="page-sub">Run campaigns across different accounts at the same time. Each account handles one job at a time.</p></div>
      <div class="page-actions">
        <span class="engine-chip">${running ? `<span class="dot dot-ok pulse"></span><span>Running: ${esc(JOB_LABELS[j.live.job] || '')}</span>` : `<span class="dot dot-ok"></span><span>Idle — ready</span>`}</span>
        <a class="btn btn-secondary" href="#/jobs">Scheduler</a>
        <a class="btn btn-secondary" href="#/dashboard?history=1">Run history</a>
      </div>
    </div>

    ${workerStripHTML(jobs, j.live)}

    ${running ? `<div class="banner banner-info"><div><div class="banner-title">A worker is running</div><p>${esc(JOB_LABELS[j.live.job] || j.live.job || '')} started ${esc(ago(j.live.started_at))}. You can start another run using different accounts.</p></div><div style="display:flex;gap:8px;align-items:center"><button class="btn btn-danger btn-sm" id="bannerStopBtn"><span class="msym">stop</span>Stop worker</button><a class="btn btn-secondary btn-sm" href="#/dashboard?history=1">Watch in logs</a></div></div>` : ''}

    <div class="card card-pad" style="margin-bottom:16px">
      <div class="section-title" style="margin-bottom:8px"><h2 style="margin:0;font-size:15px">Account run counts</h2><span class="muted small">Successful sends &amp; imports per account · live while a job runs</span></div>
      ${accounts.length ? `<div class="runs-strip">${accounts.map(a => `
        <div class="runs-chip${running ? ' live' : ''}" title="Lifetime completed actions for ${esc(a.name)}">
          <span class="runs-name">${esc(a.name)}</span>
          <span class="runs-num"><span class="msym" aria-hidden="true">bolt</span><b data-live-runs="${a.id}">${a.total_runs ?? 0}</b></span>
        </div>`).join('')}</div>` : '<p class="muted small" style="margin:0">No accounts yet.</p>'}
    </div>

    <div class="grid grid-3">
      ${jobs.map(job => {
        const last = job.last_run;
        return `<div class="card card-pad worker-card">
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
            <h2 style="margin:0">${esc(JOB_LABELS[job.key])}</h2>
            ${job.running_now ? pill('primary', 'running', false) : pill('idle', 'worker', false)}
          </div>
          <p class="desc">${esc(job.description)}</p>
          <div class="worker-meta">
            <span style="display:flex;gap:6px;align-items:center">Last run: ${last ? `${runStatus(last.status, last.dry_run)} ${fmtDT(last.started_at)}` : 'no runs yet'}</span>
            ${job.schedule && job.schedule.length ? `<span>Schedule: ${esc(job.schedule.join(' · '))}</span>` : '<span>Schedule: manual</span>'}
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn btn-primary" data-run="${job.key}"><span class="msym">play_arrow</span>Run now</button>
            ${last ? `<button class="btn btn-secondary" data-log="${last.id}"><span class="msym">receipt_long</span>Last log</button>` : ''}
          </div>
        </div>`;
      }).join('')}
    </div>
  </div>`;

  $$('[data-run]', MAIN).forEach(b => b.onclick = () => runWorkerDialog(b.dataset.run, campaigns, accounts));
  $$('[data-log]', MAIN).forEach(b => b.onclick = () => openRunLog(Number(b.dataset.log)));
  wireWorkerStrip(j, campaigns, accounts);
  const bannerStopBtn = $('#bannerStopBtn');
  if (bannerStopBtn) {
    bannerStopBtn.onclick = async () => {
      if ((j.running || []).length > 1) { openFloatingConsole(); return; }
      await requestStopJob(j.live.run_id, j.live.execution_id);
      viewWorkers().catch(e => quietToast(e));
    };
  }
}

function runWorkerDialog(jobKey, campaigns, accounts, savedScope = {}, onSave = null) {
  const eligibleCampaigns = campaigns.filter(c => c.status === 'active');
  const selectedCampaigns = new Set(savedScope.campaign_ids || []);
  const selectedAccounts = new Set(savedScope.account_ids || []);
  openModal(onSave ? `Configure ${JOB_LABELS[jobKey]}` : `Run ${JOB_LABELS[jobKey]}`, `
    <form id="wf" class="scope-form">
      <p class="scope-intro">Choose your campaigns. Only their mapped accounts can run.</p>
      <div class="scope-columns">
        <fieldset class="scope-section"><legend><span class="msym">rocket_launch</span>Campaigns</legend>
          <div class="scope-modes"><label><input type="radio" name="camp" value="all" ${!savedScope.campaign_ids ? 'checked' : ''}> All active</label><label><input type="radio" name="camp" value="pick" ${savedScope.campaign_ids ? 'checked' : ''}> Select campaigns</label></div>
          <div id="campPick" class="scope-pick">${eligibleCampaigns.map(c => `<label class="scope-option"><input type="checkbox" value="${c.id}" ${selectedCampaigns.has(c.id) ? 'checked' : ''}><span><strong>${esc(c.name)}</strong><small>${c.accounts.length} mapped account${c.accounts.length === 1 ? '' : 's'}</small></span></label>`).join('') || '<p class="scope-empty">No active campaigns. Activate a campaign first.</p>'}</div>
        </fieldset>
        <fieldset class="scope-section"><legend><span class="msym">manage_accounts</span>Mapped accounts</legend>
          <div class="scope-modes"><label><input type="radio" name="acct" value="all" ${!savedScope.account_ids ? 'checked' : ''}> All mapped</label><label><input type="radio" name="acct" value="pick" ${savedScope.account_ids ? 'checked' : ''}> Select accounts</label></div>
          <div id="acctPick" class="scope-pick"></div>
        </fieldset>
      </div>
      <section class="scope-preview"><div class="scope-preview-head"><strong>Run preview</strong><span id="scopeCount"></span></div><div id="scopeMap"></div></section>
      <p id="scopeError" class="form-error" role="status" hidden></p>
      <label class="scope-dry"><input type="checkbox" id="wDry" class="checkbox"> Dry run <span>Simulate without sending</span></label>
    </form>`, `<button class="btn btn-secondary" data-close2>Cancel</button><button class="btn btn-primary" id="wGo"><span class="msym">play_arrow</span>${onSave ? 'Save scope' : 'Run now'}</button>`);
  $('#modalHost .modal').classList.add('scope-modal');
  $('#modalHost [data-close2]').onclick = closeModal;
  const mode = name => $(`#modalHost input[name="${name}"]:checked`).value;
  const chosenCampaigns = () => eligibleCampaigns.filter(c => mode('camp') === 'all' || selectedCampaigns.has(c.id));
  function updateScope() {
    const focusedAccount = document.activeElement?.closest('#acctPick') ? document.activeElement.value : null;
    const chosen = chosenCampaigns();
    const mappedIds = new Set(chosen.flatMap(c => c.accounts.map(a => a.account_id)));
    const mapped = accounts.filter(a => mappedIds.has(a.id));
    for (const id of selectedAccounts) if (!mappedIds.has(id)) selectedAccounts.delete(id);
    const allAccounts = mode('acct') === 'all';
    $('#campPick').classList.toggle('scope-all', mode('camp') === 'all');
    $$('#campPick input').forEach(cb => { cb.disabled = mode('camp') === 'all'; cb.checked = mode('camp') === 'all' || selectedCampaigns.has(Number(cb.value)); });
    $('#acctPick').innerHTML = mapped.map(a => {
      const ready = a.status === 'active';
      const names = chosen.filter(c => c.accounts.some(link => link.account_id === a.id)).map(c => c.name).join(', ');
      return `<label class="scope-option ${!ready ? 'scope-unavailable' : ''}"><input type="checkbox" value="${a.id}" ${allAccounts || selectedAccounts.has(a.id) ? 'checked' : ''} ${allAccounts || !ready ? 'disabled' : ''}><span><strong>${esc(a.name)}${!ready ? ` <em>${esc(a.status.replaceAll('_', ' '))}</em>` : ''}</strong><small>${esc(names)}</small></span></label>`;
    }).join('') || '<p class="scope-empty">No mapped accounts in this selection. Edit the campaign to assign accounts.</p>';
    $$('#acctPick input').forEach(cb => cb.onchange = () => { const id = Number(cb.value); cb.checked ? selectedAccounts.add(id) : selectedAccounts.delete(id); updateScope(); });
    const activeIds = new Set(mapped.filter(a => a.status === 'active' && (allAccounts || selectedAccounts.has(a.id))).map(a => a.id));
    const pairs = chosen.map(c => ({campaign:c, links:c.accounts.filter(a => activeIds.has(a.account_id))}));
    const pairCount = pairs.reduce((n, p) => n + p.links.length, 0);
    $('#scopeCount').textContent = `${chosen.length} campaign${chosen.length === 1 ? '' : 's'} · ${activeIds.size} account${activeIds.size === 1 ? '' : 's'}`;
    $('#scopeMap').innerHTML = pairs.map(p => `<div class="scope-map-row"><span>${esc(p.campaign.name)}</span><span class="msym">arrow_forward</span><strong>${p.links.map(a => esc(a.account_name)).join(', ') || '<span class="scope-skipped">Skipped · no selected active account</span>'}</strong></div>`).join('') || '<p class="scope-empty">Select a campaign to preview its accounts.</p>';
    $('#scopeError').hidden = pairCount > 0;
    $('#scopeError').textContent = !chosen.length ? 'Select at least one campaign.' : 'Select an active mapped account, or update the campaign mapping.';
    $('#wGo').disabled = pairCount === 0;
    if (focusedAccount) $(`#acctPick input[value="${focusedAccount}"]`)?.focus({preventScroll:true});
  }
  $$('#campPick input').forEach(cb => cb.onchange = () => { const id = Number(cb.value); cb.checked ? selectedCampaigns.add(id) : selectedCampaigns.delete(id); updateScope(); });
  $$('input[name="camp"],input[name="acct"]', $('#modalHost')).forEach(r => r.onchange = updateScope);
  $('#wGo').onclick = async () => {
    const body = {dry_run:$('#wDry').checked};
    if (mode('camp') === 'pick') body.campaign_ids = chosenCampaigns().map(c => c.id);
    if (mode('acct') === 'pick') body.account_ids = accounts.filter(a => a.status === 'active' && selectedAccounts.has(a.id)).map(a => a.id);
    if (body.campaign_ids?.length === 0 || body.account_ids?.length === 0) { updateScope(); return; }
    try {
      if (onSave) { onSave({campaign_ids:body.campaign_ids || null,account_ids:body.account_ids || null}); return; }
      const res = await apiPost(`/api/jobs/${jobKey}/run`, body);
      toast(`${JOB_LABELS[jobKey]} started`, 'ok'); showStartedJob(res);
      if (res?.warnings?.length) res.warnings.forEach(w => toast(w, 'warn'));
    } catch(e) { toast(errText(e), 'crit'); }
  };
  if (onSave) $('#wDry').closest('label').hidden = true;
  updateScope();
}

/* ------------------------------------------------------------------ *
 *  VIEW: Logs & History (every run + full console log per run)
 * ------------------------------------------------------------------ */
const logsState = { job: '', status: '', page: 1, dry: false, since: 0 };
const LOG_PAGE = 25;
let logsTimer = null, logsRequest = 0;
function stopLogsPolling() { clearTimeout(logsTimer); logsTimer = null; logsRequest++; }
function reloadLogs() { return renderLogs().catch(e => {
  if (currentRoute !== 'logs' || APP.hidden) return;
  toast(`History refresh failed: ${errText(e)}. Retrying…`, 'crit');
  logsTimer = setTimeout(reloadLogs, 5000);
}); }

async function viewLogs() {
  const viewHash = location.hash;
  await renderLogs();
}
async function renderLogs() {
  const viewHash = location.hash;
  clearTimeout(logsTimer);
  const request = ++logsRequest;
  const usp = new URLSearchParams();
  if (logsState.job) usp.set('job', logsState.job);
  if (logsState.status) usp.set('status', logsState.status);
  if (logsState.dry) usp.set('dry_run', 'true');
  if (logsState.since) usp.set('since_days', String(logsState.since));
  usp.set('limit', String(LOG_PAGE)); usp.set('offset', String((logsState.page - 1) * LOG_PAGE)); usp.set('paginated', 'true');
  const data = await apiGet(`/api/runs?${usp}`);
  if (request !== logsRequest || APP.hidden || currentRoute !== 'logs') return;
  const lastPage = Math.max(1, Math.ceil(data.total / LOG_PAGE));
  if (logsState.page > lastPage) { logsState.page = lastPage; return renderLogs(); }
  const start = (logsState.page - 1) * LOG_PAGE;
  const pageRuns = data.items;

  if (APP.hidden || location.hash !== viewHash) return;
  MAIN.innerHTML = `<div class="page logs-page">
    <div class="page-head">
      <div><h1>Logs &amp; Run History</h1><p class="page-sub">Every worker run with full console output, stats and errors</p></div>
      <button class="btn btn-secondary" id="lgReload"><span class="msym">refresh</span>Refresh</button>
    </div>
    <div class="logs-filters" role="group" aria-label="Run history filters">
        <label class="log-filter"><span>Worker</span><select class="input" id="lgJob"><option value="">All workers</option>${Object.entries(JOB_LABELS).map(([k, v]) => `<option value="${k}" ${k === logsState.job ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
        <label class="log-filter"><span>Status</span><select class="input" id="lgStatus"><option value="">All statuses</option>
          ${[['success', 'Success'], ['partial', 'Partial'], ['error', 'Error'], ['running', 'Running'], ['stopped', 'Stopped'], ['skipped', 'Skipped']].map(([k, v]) => `<option value="${k}" ${k === logsState.status ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
        <label class="log-filter"><span>Time range</span><select class="input" id="lgSince"><option value="">All time</option>
          ${[['1', 'Last 24 hours'], ['7', 'Last 7 days'], ['30', 'Last 30 days']].map(([k, v]) => `<option value="${k}" ${Number(k) === logsState.since ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
        <div class="log-filter"><span>Run mode</span><button class="btn btn-secondary" aria-pressed="${logsState.dry}" id="lgDry">${logsState.dry ? 'Dry runs only' : 'All runs'}</button></div>
      <button class="btn btn-ghost" id="lgReset">Reset filters</button>
    </div>
    <div class="logs-summary"><span><b>${data.total.toLocaleString()}</b> matching runs</span><span>Updates every 5 seconds</span></div>
    <div class="card table-wrap">
      <table class="data" style="min-width:1000px">
        <thead><tr>
          <th>Run</th><th>Worker</th><th>Target</th><th>Schedule</th><th>Started</th><th style="text-align:right">Duration</th><th style="text-align:right">Status</th><th style="text-align:right">Log</th>
        </tr></thead>
        <tbody>
          ${pageRuns.length ? pageRuns.map(r => `<tr>
            <td class="mono">#${r.id}</td>
            <td class="cell-main">${esc(JOB_LABELS[r.job] || r.job)}</td>
            <td class="small">${esc(r.target || '—')}</td>
            <td class="small mono">${r.schedule_id ? `#${r.schedule_id}` : '<span class="muted">manual</span>'}</td>
            <td class="date-cell">${fmtDT(r.started_at)}</td>
            <td class="cell-num">${r.duration_s != null ? fmtDur(r.duration_s) : '—'}</td>
            <td style="text-align:right">${runStatus(r.status, r.dry_run)}</td>
            <td style="text-align:right"><button class="btn btn-secondary btn-sm" data-log="${r.id}"><span class="msym">receipt_long</span>View log</button></td>
          </tr>`).join('') : `<tr class="empty-row"><td colspan="8">No runs recorded${logsState.job || logsState.status ? ' for this filter' : ' yet'}.</td></tr>`}
        </tbody>
      </table>
    </div>
    ${data.total > LOG_PAGE ? `<div style="display:flex;align-items:center;justify-content:space-between">
      <span class="mono muted">Showing ${start + 1}–${Math.min(start + LOG_PAGE, data.total)} of ${data.total}</span>
      <div style="display:flex;gap:8px">
        <button class="btn btn-secondary" id="lgPrev" ${logsState.page <= 1 ? 'disabled' : ''}><span class="msym">chevron_left</span>Prev</button>
        <button class="btn btn-secondary" id="lgNext" ${start + LOG_PAGE >= data.total ? 'disabled' : ''}>Next<span class="msym">chevron_right</span></button>
      </div>
    </div>` : ''}
  </div>`;

  $('#lgJob').onchange = (e) => { logsState.job = e.target.value; logsState.page = 1; reloadLogs(); };
  $('#lgStatus').onchange = (e) => { logsState.status = e.target.value; logsState.page = 1; reloadLogs(); };
  $('#lgSince').onchange = (e) => { logsState.since = e.target.value ? Number(e.target.value) : 0; logsState.page = 1; reloadLogs(); };
  const dryBtn = $('#lgDry');
  if (dryBtn) dryBtn.onclick = () => { logsState.dry = !logsState.dry; logsState.page = 1; reloadLogs(); };
  $('#lgReload').onclick = () => reloadLogs();
  if ($('#lgPrev')) $('#lgPrev').onclick = () => { logsState.page--; reloadLogs(); };
  if ($('#lgNext')) $('#lgNext').onclick = () => { logsState.page++; reloadLogs(); };
  $('#lgReset').onclick = () => { Object.assign(logsState, { job: '', status: '', since: 0, dry: false, page: 1 }); reloadLogs(); };
  const poll = () => {
    if (currentRoute !== 'logs' || APP.hidden) return;
    if ($('#modalHost .modal') || document.activeElement?.matches('.logs-filters select, .logs-filters input')) { logsTimer = setTimeout(poll, 5000); return; }
    reloadLogs();
  };
  logsTimer = setTimeout(poll, 5000);
  $$('[data-log]', MAIN).forEach(b => b.onclick = () => openRunLog(Number(b.dataset.log)));
}

/* ------------------------------------------------------------------ *
 *  VIEW: Jobs & Scheduler
 * ------------------------------------------------------------------ */
function fmtScheduleDT(value) {
  if (!value) return '—';
  const d = new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z');
  if (isNaN(d)) return '—';
  return d.toLocaleString('en-IN', {timeZone:'Asia/Kolkata',year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
}

async function viewJobs() {
  const viewHash = location.hash;
  const [j, schedules, campaigns, accounts] = await Promise.all([
    apiGet('/api/jobs'), apiGet('/api/schedules'), apiGet('/api/campaigns'), apiGet('/api/accounts'),
  ]);

  if (APP.hidden || location.hash !== viewHash) return;
  const enabled = schedules.filter(s => s.active);
  MAIN.innerHTML = `<div class="page jobs-page">
    <div class="page-head">
      <div><h1>Jobs &amp; Scheduler</h1></div>
      <div class="page-actions"><button class="btn btn-secondary" id="jsRun"><span class="msym">play_arrow</span>Run now</button><button class="btn btn-primary" id="jsNew"><span class="msym">add</span>New schedule</button></div>
    </div>
    <section class="scheduler-overview" aria-label="Scheduler overview">
      <div class="scheduler-engine"><span class="scheduler-symbol msym">schedule</span><div><h2>Scheduler</h2></div>${pill(j.scheduler_running ? 'ok' : 'warn', j.scheduler_running ? 'Online' : 'Offline')}</div>
      <div class="schedule-overview-stats"><span><b>${enabled.length}</b> active</span><span><b>${schedules.length-enabled.length}</b> paused</span><span class="schedule-zone">IST · UTC+05:30</span></div>
    </section>
    <section aria-labelledby="scheduleHeading"><div class="section-title"><h2 id="scheduleHeading">Your schedules <span class="tag">${schedules.length}</span></h2><a href="#/dashboard?history=1">Run history <span class="msym">arrow_forward</span></a></div>
      <div class="schedule-grid">${schedules.length ? schedules.map((s,i) => `<article class="schedule-card ${s.active ? 'is-active' : 'is-paused'}" style="--enter-delay:${Math.min(i,6)*45}ms">
        <header><span class="schedule-card-icon msym">${s.active ? 'schedule' : 'pause'}</span><h3>${esc(s.name)}</h3>${pill(s.active ? 'ok' : 'idle',s.active ? 'Active' : 'Paused')}</header>
        <div class="schedule-timing"><div class="schedule-time"><strong>${esc(s.run_time)}</strong><span>IST</span></div><div class="schedule-days" aria-label="Scheduled days">${DAYS.map(d=>`<span class="${!s.days_of_week.length || s.days_of_week.includes(d) ? 'selected' : ''}" aria-label="${d}${!s.days_of_week.length || s.days_of_week.includes(d) ? ', scheduled' : ', off'}">${d}</span>`).join('')}</div></div>
        <div class="schedule-workers">${s.job_keys.map(k=>`<span class="tag">${esc(JOB_LABELS[k] || k)}</span>`).join('')}</div>
        <details class="schedule-run-details"><summary>${s.active ? `Next: ${fmtScheduleDT(s.next_run_at)}` : 'Run details'}<span class="msym">expand_more</span></summary><dl class="schedule-dates"><div><dt>Last run</dt><dd>${fmtScheduleDT(s.last_run_at)}</dd></div>${s.jitter_minutes > 0 ? `<div><dt>Time variation</dt><dd>+0–${s.jitter_minutes} min</dd></div>` : ''}${s.window_end ? `<div><dt>Window end</dt><dd>${esc(s.window_end)} IST</dd></div>` : ''}</dl></details>
        <footer><button class="btn btn-secondary btn-sm" data-edit="${s.id}"><span class="msym">edit</span>Edit</button><button class="btn btn-secondary btn-sm" data-active="${s.id}"><span class="msym">${s.active ? 'pause' : 'play_arrow'}</span>${s.active ? 'Pause' : 'Resume'}</button><button class="btn btn-ghost btn-sm schedule-delete" data-del="${s.id}" aria-label="Delete ${esc(s.name)}"><span class="msym">delete</span>Delete</button></footer>
      </article>`).join('') : '<div class="schedule-empty"><span class="msym">calendar_today</span><h3>Make room for your next campaign</h3><p>Create a named schedule, choose your days and time, and select the campaigns to run.</p><button class="btn btn-secondary" id="jsEmptyNew">Create schedule</button></div>'}</div>
    </section>
  </div>`;

  $('#jsRun').onclick = batchDialog;
  if ($('#jsEmptyNew')) $('#jsEmptyNew').onclick = () => scheduleEditor(null, campaigns, accounts);
  $('#jsNew').onclick = () => scheduleEditor(null, campaigns, accounts);

  $$('[data-edit]', MAIN).forEach(b => b.onclick = () => scheduleEditor(schedules.find(s => s.id === Number(b.dataset.edit)), campaigns, accounts));
  $$('[data-active]', MAIN).forEach(b => b.onclick = async () => {
    const s = schedules.find(x => x.id === Number(b.dataset.active));
    try { await apiPut(`/api/schedules/${s.id}`, { active: !s.active }); toast(s.active ? 'Schedule paused' : 'Schedule resumed', 'ok'); viewJobs().catch(e => quietToast(e)); }
    catch (e) { toast(errText(e), 'crit'); }
  });
  $$('[data-del]', MAIN).forEach(b => b.onclick = async () => {
    const s = schedules.find(x => x.id === Number(b.dataset.del));
    if (!window.confirm(`Delete schedule “${s.name}”? Future runs will stop. Run history remains available.`)) return;
    try { await apiDelete(`/api/schedules/${s.id}`); toast('Schedule deleted', 'ok'); viewJobs().catch(e => quietToast(e)); }
    catch (e) { toast(errText(e), 'crit'); }
  });
}

function scheduleEditor(s, campaigns, accounts, newOverride) {
  const isNew = newOverride ?? !s;
  const draft = s ? { ...s, scopes: s.scopes || {} } : { name: '', run_time: '09:00', days_of_week: [], job_keys: [], scopes: {}, active: true, timezone: 'Asia/Kolkata', jitter_minutes: 0, window_end: null };
  draft.timezone = 'Asia/Kolkata';
  openModal(isNew ? 'New schedule' : `Edit schedule — ${draft.name}`, `
    <form id="sf">
      <div class="grid" style="grid-template-columns:1fr 160px;gap:10px;margin-bottom:12px">
        <label class="field" style="margin:0"><span>Schedule name</span><input class="input" id="sName" required maxlength="120" value="${esc(draft.name)}" placeholder="Morning outreach"></label>
        <label class="field" style="margin:0"><span>Time (IST · India)</span><input class="input" id="sTime" type="time" required value="${esc(draft.run_time)}"></label>
      </div>
      <fieldset style="border:none;padding:0;margin:0 0 12px"><legend style="font:600 11px/14px Geist;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Days · none selected means every day</legend>
        <div class="seg" id="sDays" style="flex-wrap:wrap">${DAYS.map(d => `<button type="button" class="${draft.days_of_week.includes(d) ? 'on' : ''}" data-day="${d}">${d}</button>`).join('')}</div>
      </fieldset>
      <fieldset style="border:none;padding:0;margin:0 0 12px"><legend style="font:600 11px/14px Geist;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-bottom:6px">Workers · run in the order shown</legend>
        <div class="seg" id="sJobs" style="flex-wrap:wrap">${WORKERS.map(k => `<button type="button" class="${draft.job_keys.includes(k) ? 'on' : ''}" data-job="${k}">${JOB_LABELS[k]}</button>`).join('')}</div>
      </fieldset>
      <details style="margin-bottom:12px"><summary style="cursor:pointer;color:var(--muted)">Timing options · IST (UTC+05:30)</summary>
        <div class="grid" style="grid-template-columns:repeat(2,1fr);gap:8px;padding-top:8px">
          <label class="field" style="margin:0"><span>Jitter (minutes)</span><input class="input mono" id="sJitter" type="number" min="0" max="60" value="${draft.jitter_minutes}"></label>
          <label class="field" style="margin:0"><span>Window end (optional)</span><input class="input" id="sWindow" type="time" value="${esc(draft.window_end || '')}"></label>
        </div>
      </details>
      <label style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="sActive" class="checkbox" ${draft.active ? 'checked' : ''}> Active</label>
      <p class="form-error" id="sErr" role="alert" hidden></p>
    </form>`,
    `<button class="btn btn-secondary" data-close2>Cancel</button><button class="btn btn-primary" id="sSave">${isNew ? 'Create schedule' : 'Save changes'}</button>`);
  $('#modalHost [data-close2]').onclick = closeModal;
  $$('#sDays [data-day]').forEach(b => b.onclick = () => { const d = b.dataset.day; draft.days_of_week = draft.days_of_week.includes(d) ? draft.days_of_week.filter(x => x !== d) : [...draft.days_of_week, d]; b.classList.toggle('on'); });
  const scopeHost = document.createElement('div');
  $('#sJobs').after(scopeHost);
  const capture = () => {
    draft.name = $('#sName').value.trim(); draft.run_time = $('#sTime').value;
    draft.jitter_minutes = Number($('#sJitter').value) || 0;
    draft.window_end = $('#sWindow').value || null; draft.active = $('#sActive').checked;
  };
  const renderScopes = () => {
    scopeHost.innerHTML = draft.job_keys.map(k => `<button class="btn btn-secondary" type="button" data-scope="${k}" style="margin:8px 8px 0 0">Configure ${JOB_LABELS[k]}</button>`).join('');
    $$('[data-scope]', scopeHost).forEach(b => b.onclick = () => {
      capture(); const key = b.dataset.scope;
      runWorkerDialog(key, campaigns, accounts, draft.scopes[key], scope => {
        draft.scopes = { ...draft.scopes, [key]: scope }; scheduleEditor(draft, campaigns, accounts, isNew);
      });
      $('#modalHost [data-close2]').onclick = () => scheduleEditor(draft, campaigns, accounts, isNew);
    });
  };
  renderScopes();
  $$('#sJobs [data-job]').forEach(b => b.onclick = () => {
    const k = b.dataset.job;
    draft.job_keys = draft.job_keys.includes(k) ? draft.job_keys.filter(x => x !== k) : [...WORKERS.filter(w => draft.job_keys.includes(w) || w === k)];
    b.classList.toggle('on');
    draft.scopes = Object.fromEntries(Object.entries(draft.scopes).filter(([key]) => draft.job_keys.includes(key)));
    renderScopes();
  });
  $('#sSave').onclick = async () => {
    draft.name = $('#sName').value.trim();
    draft.run_time = $('#sTime').value;
    draft.jitter_minutes = Math.max(0, Number($('#sJitter').value) || 0);
    draft.window_end = $('#sWindow').value || null;
    draft.active = $('#sActive').checked;
    if (!draft.job_keys.length) { const el = $('#sErr'); el.textContent = 'Select at least one worker to create a schedule.'; el.hidden = false; return; }
    try {
      const body = (({ name, run_time, days_of_week, job_keys, scopes, active, timezone, jitter_minutes, window_end }) => ({ name, run_time, days_of_week, job_keys, scopes, active, timezone, jitter_minutes, window_end }))(draft);
      if (isNew) await apiPost('/api/schedules', body);
      else await apiPut(`/api/schedules/${draft.id}`, body);
      closeModal(); toast(isNew ? 'Schedule created' : 'Schedule updated', 'ok'); viewJobs().catch(e => quietToast(e));
    } catch (e) { const el = $('#sErr'); el.textContent = errText(e); el.hidden = false; }
  };
}

/* ------------------------------------------------------------------ *
 *  VIEW: Settings
 * ------------------------------------------------------------------ */
async function viewSettings(initialTab) {
  const viewHash = location.hash;
  const s = await apiGet('/api/settings/notifications');
  const alerts = [
    ['alert_critical', 'Critical errors', 'Urgent escalation', 'Instant alert if a session expires or an account is rate-limited.'],
    ['alert_run_summary', 'Per-account run summary', 'End of every run', 'Digest of sent quotas, InMails and invite rates per account.'],
    ['alert_send_errors', 'Send-error digest', 'Throttled batch', 'Immediate notification when a message fails or hits a rate limit.'],
    ['alert_reply_digest', 'New-reply email digest', 'Real-time', 'Formatted email when a prospect responds to any campaign sequence.'],
  ];
  if (APP.hidden || location.hash !== viewHash) return;

  const urlParams = new URLSearchParams((location.hash.split('?')[1] || '').split('#')[0]);
  let activeTab = initialTab || urlParams.get('tab') || (location.hash.includes('activity') ? 'activity' : 'notifications');
  const isAdmin = window.ME?.role === 'admin';

  MAIN.innerHTML = `<div class="page settings-page">
    <div class="page-head"><div><h1>System Configuration</h1><p class="page-sub">Notifications, alert routing, user activity and team access</p></div></div>

    <div class="settings-tabs-wrap">
      <div class="seg settings-tabs" role="tablist" aria-label="Settings navigation">
        <button type="button" class="settings-tab-btn ${activeTab === 'notifications' ? 'on' : ''}" data-stab="notifications" role="tab" aria-selected="${activeTab === 'notifications'}"><span class="msym">notifications</span>Alerts &amp; Notifications</button>
        <button type="button" class="settings-tab-btn ${activeTab === 'activity' ? 'on' : ''}" data-stab="activity" role="tab" aria-selected="${activeTab === 'activity'}"><span class="msym">history</span>User Activity</button>
        ${isAdmin ? `<button type="button" class="settings-tab-btn ${activeTab === 'users' ? 'on' : ''}" data-stab="users" role="tab" aria-selected="${activeTab === 'users'}"><span class="msym">manage_accounts</span>Users &amp; Access</button>` : ''}
      </div>
    </div>

    <div id="settingsNotificationsPanel" ${activeTab !== 'notifications' ? 'style="display:none"' : ''}>
      <div class="settings-cols">
      <form class="card card-pad" id="nfForm">
        <h2 style="margin:0;font-size:15px">Alerts &amp; Notifications</h2>
        <p class="card-sub" style="margin:2px 0 10px">Webhook routing and operational dispatches</p>

        <div class="settings-grid" style="grid-template-columns:1fr">
          <div class="panel-box">
            <div class="panel-head">
              <b><span class="msym" style="font-size:16px;color:var(--primary)">forum</span> Google Chat webhook</b>
              <span class="mono muted small">SSL POST</span>
            </div>
            <div class="email-add-row">
              <input class="input mono" type="url" id="nfWebhook" placeholder="${s.webhook_configured ? esc(s.gchat_webhook_url) : 'https://chat.googleapis.com/v1/spaces/…'}">
              <button type="button" class="btn btn-secondary btn-sm" id="nfTest"><span class="msym">send</span>Test</button>
            </div>
            <p class="muted small" style="margin:0">${s.webhook_configured ? `Configured (ends “${esc(s.gchat_webhook_url)}”)` : 'Not configured yet'}</p>
          </div>

          <div class="panel-box">
            <div class="panel-head">
              <b><span class="msym" style="font-size:16px;color:var(--muted)">mail</span> Email recipients</b>
              <span class="mono muted small">${s.email_recipients.length} active</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:5px;min-height:26px" id="nfChips">
              ${s.email_recipients.map(r => `<span class="tag"><span class="dot" style="background:var(--ok-dot)"></span>${esc(r)}<button type="button" class="icon-btn" style="width:18px;height:18px" data-rm="${esc(r)}" aria-label="Remove"><span class="msym" style="font-size:13px">close</span></button></span>`).join('')}
            </div>
            <div class="email-add-row">
              <input class="input" type="email" id="nfEmail" placeholder="name@company.com">
              <button type="button" class="btn btn-secondary btn-sm" id="nfEmailAdd"><span class="msym">add</span>Add</button>
            </div>
            <p class="muted small" style="margin:0">Digests and critical failure alerts.</p>
          </div>
        </div>

        <b style="font-size:12px;display:block;margin:10px 0 5px">Trigger categories</b>
        <div class="trigger-grid" style="grid-template-columns:1fr">
          ${alerts.map(([key, label, badge, desc]) => `
            <label style="display:flex;justify-content:space-between;gap:10px;align-items:center;background:var(--inset);border-radius:8px;padding:10px 12px;cursor:pointer;margin:0">
              <span style="min-width:0">
                <span style="display:flex;gap:6px;align-items:center;flex-wrap:wrap"><b style="font-size:12.5px">${label}</b><span class="tag">${badge}</span></span>
                <span class="muted small" style="display:block;margin-top:1px">${desc}</span>
              </span>
              <input type="checkbox" class="checkbox" data-alert="${key}" ${s[key] ? 'checked' : ''}>
            </label>`).join('')}
        </div>
        <div style="margin-top:10px;display:flex;justify-content:flex-end">
          <button type="submit" class="btn btn-primary"><span class="msym">save</span>Save configuration</button>
        </div>
      </form>

      ${isAdmin ? `<div class="card card-pad" id="usersSection"><div class="loading"><span class="spinner"></span>Loading users…</div></div>` : ''}
      </div>
    </div>

    <div id="settingsActivityPanel" ${activeTab !== 'activity' ? 'style="display:none"' : ''}>
      <div id="settingsActivityHost"><div class="loading"><span class="spinner"></span>Loading user activity…</div></div>
    </div>

    ${isAdmin ? `<div id="settingsUsersPanel" ${activeTab !== 'users' ? 'style="display:none"' : ''}>
      <div class="card card-pad" id="usersSectionStandalone"><div class="loading"><span class="spinner"></span>Loading users…</div></div>
    </div>` : ''}
  </div>`;

  const usersHost = $('#usersSection');
  if (usersHost) renderUsersSection(usersHost).catch(e => {
    usersHost.innerHTML = `<div class="banner banner-warn"><div><div class="banner-title">Couldn't load users</div><p>${esc(errText(e))}</p></div></div>`;
  });

  async function switchTab(tab) {
    activeTab = tab;
    $$('[data-stab]').forEach(b => {
      const isCurrent = b.dataset.stab === tab;
      b.classList.toggle('on', isCurrent);
      b.setAttribute('aria-selected', isCurrent ? 'true' : 'false');
    });
    const notifP = $('#settingsNotificationsPanel');
    const actP = $('#settingsActivityPanel');
    const userP = $('#settingsUsersPanel');
    if (notifP) notifP.style.display = tab === 'notifications' ? '' : 'none';
    if (actP) actP.style.display = tab === 'activity' ? '' : 'none';
    if (userP) userP.style.display = tab === 'users' ? '' : 'none';

    if (tab === 'activity') {
      const host = $('#settingsActivityHost');
      if (typeof renderUserActivityCompact === 'function') {
        await renderUserActivityCompact(host);
      }
    } else if (tab === 'users' && isAdmin) {
      const host = $('#usersSectionStandalone');
      if (host && !host.dataset.loaded) {
        await renderUsersSection(host);
        host.dataset.loaded = 'true';
      }
    }
  }

  $$('[data-stab]').forEach(btn => {
    btn.onclick = () => switchTab(btn.dataset.stab);
  });

  if (activeTab === 'activity') {
    switchTab('activity');
  }

  const recipients = [...s.email_recipients];
  $('#nfChips').addEventListener('click', (e) => {
    const rm = e.target.closest('[data-rm]');
    if (rm) { const i = recipients.indexOf(rm.dataset.rm); if (i >= 0) recipients.splice(i, 1); rm.closest('.tag').remove(); }
  });
  const addRecipient = () => {
    const input = $('#nfEmail');
    const v = input.value.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) { toast('Enter a valid email address', 'warn'); return; }
    if (!recipients.includes(v)) {
      recipients.push(v);
      $('#nfChips').insertAdjacentHTML('beforeend', `<span class="tag"><span class="dot" style="background:var(--ok-dot)"></span>${esc(v)}<button type="button" class="icon-btn" style="width:18px;height:18px" data-rm="${esc(v)}" aria-label="Remove"><span class="msym" style="font-size:13px">close</span></button></span>`);
    }
    input.value = '';
  };
  $('#nfEmailAdd').onclick = addRecipient;
  $('#nfEmail').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addRecipient(); } });
  $('#nfTest').onclick = async () => {
    try { const r = await apiPost('/api/settings/test-webhook'); toast(r.ok ? 'Test notification sent — check Google Chat' : 'Webhook test failed (see server log)', r.ok ? 'ok' : 'warn'); }
    catch (e) { toast(errText(e), 'crit'); }
  };
  $('#nfForm').onsubmit = async (e) => {
    e.preventDefault();
    try {
      await apiPut('/api/settings/notifications', {
        gchat_webhook_url: $('#nfWebhook').value.trim() || s.gchat_webhook_url,
        email_recipients: recipients,
        alert_critical: $('[data-alert="alert_critical"]').checked,
        alert_run_summary: $('[data-alert="alert_run_summary"]').checked,
        alert_send_errors: $('[data-alert="alert_send_errors"]').checked,
        alert_reply_digest: $('[data-alert="alert_reply_digest"]').checked,
      });
      toast('Configuration saved — webhook routing updated', 'ok');
      viewSettings().catch(e => quietToast(e));
    } catch (ex) { toast(errText(ex), 'crit'); }
  };
}

/* ------------------------------------------------------------------ *
 *  Users & Access — shared renderer (used by Settings page and #/users)
 * ------------------------------------------------------------------ */
const ROLE_LABEL = { admin: 'Administrator', campaign_manager: 'Campaign manager' };
const ROLE_DESC = {
  admin: 'Full access — accounts, campaigns, scheduling, logs, users & settings.',
  campaign_manager: 'Runs the campaigns & accounts you assign. No user management.',
};

async function renderUsersSection(container, { standalone = false } = {}) {
  const data = await apiGet('/api/users');
  const users = data.users || [];
  const scopeLine = (u) => {
    const nc = (u.allowed_campaign_ids || []).length, na = (u.allowed_account_ids || []).length;
    if (u.role === 'admin') return 'All campaigns & accounts';
    return `${nc} campaign${nc === 1 ? '' : 's'} · ${na} account${na === 1 ? '' : 's'}`;
  };
  container.innerHTML = `
    ${standalone ? `<div class="page-head">
      <div>
        <h1>Users &amp; Access <span class="pill pill-primary" style="vertical-align:4px">${users.length} user${users.length === 1 ? '' : 's'}</span></h1>
        <p class="page-sub">Web-application logins with per-user campaign &amp; account access</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary" id="uReload"><span class="msym">refresh</span>Refresh</button>
        <button class="btn btn-primary" id="uAdd"><span class="msym">person_add</span>Add user</button>
      </div>
    </div>` : `<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px">
      <div><h2 style="margin:0">Users &amp; Access</h2><p class="card-sub" style="margin:2px 0 0">Logins with per-user campaign &amp; account access</p></div>
      <button class="btn btn-primary btn-sm" id="uAdd"><span class="msym">person_add</span>Add user</button>
    </div>`}
    <div class="card table-wrap" style="${standalone ? '' : 'box-shadow:none'}">
      <table class="data compact" style="min-width:640px">
        <thead><tr>
          <th>User</th><th>Role &amp; access</th><th>Status</th><th>Last login</th><th style="text-align:right">Actions</th>
        </tr></thead>
        <tbody>
          ${users.length ? users.map(u => {
            const isYou = u.is_you;
            const admin = u.role === 'admin';
            return `<tr>
              <td>${who(u.display_name || u.username, isYou ? `${u.username} · you` : u.username)}</td>
              <td>
                <span class="tag" title="${esc(ROLE_DESC[u.role] || '')}"><span class="msym" style="font-size:13px;vertical-align:-2px;${admin ? 'color:var(--primary)' : ''}">${admin ? 'shield' : 'work'}</span> ${ROLE_LABEL[u.role] || esc(u.role)}</span>
                <div class="cell-sub">${esc(scopeLine(u))}</div>
              </td>
              <td>${u.active ? pill('ok', 'Active') : pill('crit', 'Deactivated')}</td>
              <td class="date-cell">${u.last_login_at ? ago(u.last_login_at) : '<span class="muted">never</span>'}</td>
              <td>
                <div class="cell-actions" style="justify-content:flex-end">
                  <button class="btn btn-ghost btn-sm" data-uedit="${u.id}"><span class="msym">tune</span>Edit</button>
                  ${isYou ? '' : `<button class="btn btn-secondary btn-sm" data-udeactivate="${u.id}" ${u.active ? '' : 'disabled'}>${u.active ? 'Deactivate' : '—'}</button>`}
                  ${isYou ? `<span class="muted small" style="padding:0 6px">you</span>` : `<button class="btn btn-ghost btn-sm icon-only" data-udel="${u.id}" title="Delete user" aria-label="Delete ${esc(u.username)}"><span class="msym">delete</span></button>`}
                </div>
              </td>
            </tr>`;
          }).join('') : `<tr class="empty-row"><td colspan="5">No users yet.</td></tr>`}
        </tbody>
      </table>
    </div>
    <p class="muted small">Every user signs in with their own credentials and can change their password from the sidebar menu. Restrict a user to specific campaigns/accounts from Edit — empty means no access. Administrators have full access. Deactivating or resetting a password signs that user out everywhere.</p>`;

  container.querySelector('#uAdd').onclick = () => userEditor(null).catch(e => toast(errText(e), 'crit'));
  const reload = standalone
    ? () => viewUsers().catch(e => quietToast(e))
    : () => { const host = $('#usersSection'); if (host) renderUsersSection(host).catch(e => toast(errText(e), 'crit')); };
  const rl = container.querySelector('#uReload');
  if (rl) rl.onclick = reload;

  $$('[data-uedit]', container).forEach(b => b.onclick = () => {
    const u = users.find(x => x.id === Number(b.dataset.uedit));
    userEditor(u).catch(e => toast(errText(e), 'crit'));
  });

  $$('[data-udeactivate]', container).forEach(b => b.onclick = async () => {
    const u = users.find(x => x.id === Number(b.dataset.udeactivate));
    const verb = u.active ? 'deactivate' : 'activate';
    if (!window.confirm(`${verb.charAt(0).toUpperCase() + verb.slice(1)} ${u.display_name || u.username}?${u.active ? ' They will be signed out everywhere.' : ''}`)) return;
    b.disabled = true;
    try {
      await apiPut(`/api/users/${u.id}`, { active: !u.active });
      toast(`${u.display_name || u.username} ${u.active ? 'deactivated' : 'reactivated'}`, 'ok');
      reload();
    } catch (e) { toast(errText(e), 'crit'); b.disabled = false; }
  });

  $$('[data-udel]', container).forEach(b => b.onclick = async () => {
    const u = users.find(x => x.id === Number(b.dataset.udel));
    if (!window.confirm(`Delete ${u.display_name || u.username} permanently? This cannot be undone.`)) return;
    b.disabled = true;
    try {
      await apiDelete(`/api/users/${u.id}`);
      toast(`${u.display_name || u.username} deleted`, 'ok');
      reload();
    } catch (e) { toast(errText(e), 'crit'); b.disabled = false; }
  });
}

async function viewUsers() {
  const viewHash = location.hash;
  if (window.ME?.role !== 'admin') {
    if (APP.hidden || location.hash !== viewHash) return;
  MAIN.innerHTML = `<div class="page"><div class="banner banner-warn"><div><div class="banner-title">Administrator access required</div><p>Your account (${esc(window.ME?.user || '?')}) is a campaign manager. Ask an administrator for user management.</p></div><a class="btn btn-secondary" href="#/dashboard">Back to dashboard</a></div></div>`;
    return;
  }
  MAIN.innerHTML = `<div class="page" id="usersSection"></div>`;
  await renderUsersSection(MAIN.querySelector('#usersSection'), { standalone: true });
}

/* Create / edit a user (admin) — with campaign & account access scoping */
async function userEditor(u) {
  const isNew = !u;
  const [campaigns, accounts] = await Promise.all([apiGet('/api/campaigns'), apiGet('/api/accounts')]);
  const selCamps = new Set(u?.allowed_campaign_ids || []);
  const selAccts = new Set(u?.allowed_account_ids || []);

  const scopeDD = (id, label, items, selected) => `
    <div class="field span2">
      <span>${label}</span>
      <button type="button" class="dd-btn ${selected.size ? 'active' : ''}" id="${id}Btn" aria-haspopup="dialog" style="width:100%;justify-content:space-between">
        <span id="${id}Label">${selected.size ? `${selected.size} selected` : 'None selected — no access'}</span>
        <span class="msym">tune</span>
      </button>
      <small class="muted">Click to choose specific ${label.toLowerCase().includes('campaign') ? 'campaigns' : 'accounts'}; select none to grant no access. Administrators have full access.</small>
    </div>`;

  openModal(isNew ? 'Add user' : `Edit user — ${u.display_name || u.username}`, `
    <form id="userForm" class="grid-2-col">
      <label class="field"><span>Username</span>
        <input class="input mono" name="username" required minlength="3" maxlength="80" value="${esc(u?.username || '')}" ${isNew ? '' : 'readonly'} placeholder="e.g. jane.ops">
        <small class="muted">${isNew ? 'Used to sign in. Cannot be changed later.' : 'Usernames are permanent.'}</small>
      </label>
      <label class="field"><span>Display name <small class="muted" style="font-weight:400">(optional)</small></span>
        <input class="input" name="display_name" maxlength="120" value="${esc(u?.display_name || '')}" placeholder="e.g. Jane Ops"></label>
      <label class="field span2"><span>Role</span>
        <select class="input" name="role">
          <option value="campaign_manager" ${u?.role !== 'admin' ? 'selected' : ''}>Campaign manager — campaigns &amp; accounts, no user management</option>
          <option value="admin" ${u?.role === 'admin' ? 'selected' : ''}>Administrator — full access including users</option>
        </select>
      </label>
      ${isNew ? `<label class="field span2"><span>Password <small class="muted" style="font-weight:400">(min 8 characters)</small></span>
        <input class="input" name="password" type="password" autocomplete="new-password" minlength="8" required></label>`
      : `<label class="field span2"><span>Reset password <small class="muted" style="font-weight:400">(optional — signs them out everywhere)</small></span>
        <input class="input" name="password" type="password" autocomplete="new-password" minlength="8" placeholder="Leave blank to keep current password"></label>`}
      ${scopeDD('uCamps', 'Campaign access', campaigns, selCamps, 'id', 'name')}
      ${scopeDD('uAccts', 'Account access', accounts, selAccts, 'id', 'name')}
      <p class="form-error span2" id="userErr" role="alert" hidden></p>
    </form>`,
    `<button class="btn btn-secondary" data-close2>Cancel</button><button class="btn btn-primary" id="userSave"><span class="msym">save</span>${isNew ? 'Create user' : 'Save changes'}</button>`);
  $('#modalHost [data-close2]').onclick = closeModal;

  /* Scope pickers open as proper popup dialogs (layered above this modal),
     with search + All/None. Selections land in selCamps / selAccts. */
  const scopePopup = (id, title, items, selectedSet, nameKey) => {
    const btn = $(`#${id}Btn`);
    if (!btn) return;
    btn.onclick = () => {
      const working = new Set(selectedSet);
      const host = document.createElement('div');
      host.className = 'scope-pop-backdrop';
      host.innerHTML = `
        <div class="scope-pop" role="dialog" aria-modal="true" aria-label="${esc(title)}">
          <div class="scope-pop-head"><h3>${esc(title)}</h3><button class="icon-btn" data-x aria-label="Close"><span class="msym">close</span></button></div>
          <div class="scope-pop-search"><input class="input" data-search placeholder="Search…" aria-label="Search ${esc(title)}"></div>
          <div class="scope-pop-list">
            ${items.map(it => `<label class="dd-item" data-name="${esc(it[nameKey]).toLowerCase()}"><input type="checkbox" value="${it.id}" ${working.has(it.id) ? 'checked' : ''}>
              <span>${esc(it[nameKey])}${it.status && it.status !== 'active' ? ` <small class="muted">· ${it.status}</small>` : ''}</span></label>`).join('') || '<p class="muted small" style="padding:8px">None available.</p>'}
          </div>
          <div class="scope-pop-foot">
            <button class="btn btn-secondary btn-sm" data-all>All</button>
            <button class="btn btn-secondary btn-sm" data-none>None</button>
            <span class="muted small" data-count></span>
            <button class="btn btn-primary btn-sm" data-ok>Done</button>
          </div>
        </div>`;
      document.body.appendChild(host);
      const list = host.querySelector('.scope-pop-list');
      const count = host.querySelector('[data-count]');
      const updateCount = () => {
        const n = list.querySelectorAll('input:checked').length;
        count.textContent = n ? `${n} of ${items.length} selected` : 'None selected — no access';
      };
      list.addEventListener('change', updateCount);
      host.querySelector('[data-search]').addEventListener('input', (e) => {
        const q = e.target.value.trim().toLowerCase();
        list.querySelectorAll('.dd-item').forEach(row => {
          row.style.display = !q || row.dataset.name.includes(q) ? '' : 'none';
        });
      });
      host.querySelector('[data-all]').onclick = () => { list.querySelectorAll('input').forEach(cb => cb.checked = true); updateCount(); };
      host.querySelector('[data-none]').onclick = () => { list.querySelectorAll('input').forEach(cb => cb.checked = false); updateCount(); };
      const close = () => host.remove();
      host.querySelector('[data-x]').onclick = close;
      host.addEventListener('click', (e) => { if (e.target === host) close(); });
      host.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
      host.querySelector('[data-ok]').onclick = () => {
        selectedSet.clear();
        list.querySelectorAll('input:checked').forEach(cb => selectedSet.add(Number(cb.value)));
        const label = $(`#${id}Label`), trigger = $(`#${id}Btn`);
        const n = selectedSet.size;
        label.textContent = n ? `${n} selected` : 'None selected — no access';
        trigger.classList.toggle('active', n > 0);
        close();
      };
      updateCount();
      setTimeout(() => host.querySelector('[data-search]')?.focus(), 40);
    };
  };
  scopePopup('uCamps', 'Campaign access', campaigns, selCamps, 'name');
  scopePopup('uAccts', 'Account access', accounts, selAccts, 'name');

  $('#userSave').onclick = async () => {
    const f = $('#userForm'), err = $('#userErr');
    err.hidden = true;
    const campBoxes = [...selCamps];
    const acctBoxes = [...selAccts];
    const body = {
      role: f.role.value,
      allowed_campaign_ids: campBoxes,
      allowed_account_ids: acctBoxes,
    };
    if (f.display_name) body.display_name = f.display_name.value.trim();
    if (f.password && f.password.value) body.password = f.password.value;
    const b = $('#userSave'); b.disabled = true;
    try {
      if (isNew) {
        body.username = f.username.value.trim();
        await apiPost('/api/users', body);
        toast(`User ${body.username} created`, 'ok');
      } else {
        await apiPut(`/api/users/${u.id}`, body);
        toast('User updated', 'ok');
      }
      closeModal();
      const host = $('#usersSection');
      if (host) renderUsersSection(host).catch(e => quietToast(e));
      if (currentRoute === 'users') viewUsers().catch(e => quietToast(e));
    } catch (ex) {
      err.textContent = errText(ex); err.hidden = false; b.disabled = false;
    }
  };
  setTimeout(() => $('#userForm [name=username]')?.focus(), 30);
}
