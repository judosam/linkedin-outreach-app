/* Campaign reporting and history use the existing no-build application shell. */
let dashboardReport = {rows: []};
const outreachMetrics = [
  ['invites', 'Invites sent', 'person_add'],
  ['inmails', 'InMails sent', 'send'],
  ['messages', 'Messages sent', 'forum'],
  ['replies', 'Replies received', 'mark_email_read']
];
const accountSendMetrics = [
  ['invites', 'Invites sent'],
  ['inmails', 'InMails sent'],
  ['messages', 'Messages sent']
];
function sumSends(rows) {
  return rows.reduce((total, row) => {
    for (const [key] of outreachMetrics) total[key] += Number(row[key] || 0);
    return total;
  }, {invites: 0, inmails: 0, messages: 0, replies: 0});
}
function dashboardTotalsHTML(report) {
  const totals = sumSends(report.rows || []);
  return `<section class="outreach-totals" aria-label="Overall outreach counts">${outreachMetrics.map(([key,label,icon]) => `<article class="outreach-total ${key}"><div><span>${label}</span><strong>${totals[key].toLocaleString()}</strong><small>${key === 'replies' ? 'Leads responded' : 'Across active campaigns'}</small></div><span class="metric-symbol msym">${icon}</span></article>`).join('')}</section>`;
}
function campaignStatsHTML(report) {
  dashboardReport = report;
  const campaigns = new Map();
  for (const row of report.rows || []) {
    if (!campaigns.has(row.campaign_id)) campaigns.set(row.campaign_id, []);
    campaigns.get(row.campaign_id).push(row);
  }
  return `<div class="campaign-overview-grid">${[...campaigns].map(([id, rows]) => {
    const totals = sumSends(rows), count = rows.filter(r => r.account_id != null).length;
    return `<button class="campaign-overview" data-campaign-stats="${id}" aria-haspopup="dialog"><div class="campaign-overview-head"><span class="campaign-monogram">${esc(initials(rows[0].campaign))}</span><div class="campaign-head-text"><h3 title="${esc(rows[0].campaign)}">${esc(rows[0].campaign)}</h3><span>${count} ${count === 1 ? 'account' : 'accounts'}</span></div><span class="campaign-active"><span class="dot-pulse"></span>Active</span></div><dl class="campaign-micro-metrics">${outreachMetrics.map(([key,label]) => `<div class="micro-stat ${key}"><dt>${label.replace(' sent','').replace(' received','')}</dt><dd class="${key === 'replies' ? 'metric-replies' : ''}">${totals[key].toLocaleString()}</dd></div>`).join('')}</dl><div class="campaign-overview-foot"><span>View account breakdown</span><span class="msym">arrow_forward</span></div></button>`;
  }).join('') || '<div class="campaign-empty"><span class="msym">rocket_launch</span><h3>No active campaigns</h3><p>Activate a campaign in Campaigns to see its performance here.</p></div>'}</div>`;
}
function bindCampaignStats() {
  $$('[data-campaign-stats]', MAIN).forEach(b => b.onclick = () => openCampaignStats(Number(b.dataset.campaignStats)));
}
function openCampaignStats(id) {
  const rows = dashboardReport.rows.filter(r => r.campaign_id === id);
  if (!rows.length) return;
  const period = dashRange === 1 ? 'Today' : `Last ${dashRange} days`;
  const campName = rows[0].campaign;
  const sumInv = rows.reduce((s, r) => s + Number(r.invites || 0), 0);
  const sumInm = rows.reduce((s, r) => s + Number(r.inmails || 0), 0);
  const sumMsg = rows.reduce((s, r) => s + Number(r.messages || 0), 0);
  const sumRep = rows.reduce((s, r) => s + Number(r.replies || 0), 0);
  const acctCount = rows.filter(r => r.account_id != null).length;

  openModal(campName, `
    <div class="campaign-popup-shell">
      <div class="campaign-popup-meta-strip">
        <span class="campaign-popup-period"><span class="msym">calendar_today</span>${esc(period)}</span>
        <span class="campaign-popup-scope">Confirmed sends · UTC</span>
      </div>

      <div class="campaign-popup-kpi-grid">
        <div class="kpi-cell">
          <span class="kpi-label">Accounts</span>
          <strong class="kpi-val">${acctCount}</strong>
        </div>
        <div class="kpi-cell kpi-invites">
          <span class="kpi-label">Invites</span>
          <strong class="kpi-val">${sumInv.toLocaleString()}</strong>
        </div>
        <div class="kpi-cell kpi-inmails">
          <span class="kpi-label">InMails</span>
          <strong class="kpi-val">${sumInm.toLocaleString()}</strong>
        </div>
        <div class="kpi-cell kpi-messages">
          <span class="kpi-label">Messages</span>
          <strong class="kpi-val">${sumMsg.toLocaleString()}</strong>
        </div>
        <div class="kpi-cell kpi-replies">
          <span class="kpi-label">Replies</span>
          <strong class="kpi-val">${sumRep.toLocaleString()}</strong>
        </div>
      </div>

      <div class="account-performance-list">
        ${rows.map(r => `
          <div class="account-performance">
            <div class="account-performance-head">
              <div class="account-info">
                <span class="account-avatar-sm">${esc(initials(r.account))}</span>
                <strong>${esc(r.account)}</strong>
              </div>
              <div class="account-head-right">
                ${Number(r.replies || 0) > 0 ? `<span class="account-reply-tag"><span class="msym">mark_email_read</span>${r.replies} replies</span>` : ''}
                <span class="active-badge-pill small"><span class="dot-pulse"></span>Active</span>
              </div>
            </div>
            <dl>
              ${accountSendMetrics.map(([key, label]) => `<div class="${key}"><dt>${label}</dt><dd>${Number(r[key] || 0).toLocaleString()}</dd></div>`).join('')}
            </dl>
            <div class="account-performance-foot">
              ${r.last_run ? `<span class="account-last-run">${runStatus(r.last_run.status, false)}<span>${esc(JOB_LABELS[r.last_run.job] || r.last_run.job)} · ${fmtDT(r.last_run.started_at)}</span></span><button class="btn btn-ghost btn-sm" data-pair-log="${r.last_run.id}"><span class="msym">receipt_long</span>View log</button>` : '<span class="muted small">No recorded run in this period.</span>'}
            </div>
          </div>
        `).join('')}
      </div>
    </div>`,
    `<button class="btn btn-secondary" id="campaignStatsClose">Close</button>`
  );
  const dialog = $('#modalHost .modal');
  dialog.classList.remove('modal-compact');
  dialog.classList.add('campaign-breakdown-modal');
  $('#campaignStatsClose').onclick = closeModal;
  $$('[data-pair-log]', $('#modalHost')).forEach(b => b.onclick = () => openRunLog(Number(b.dataset.pairLog)));
}

async function openDashboardHistory() {
  if (typeof minimizeFloatingConsole === 'function') minimizeFloatingConsole();
  openModal('Run history', `<div class="history-controls"><label class="field"><span>Worker</span><select class="input" id="historyWorker"><option value="">All workers</option>${Object.entries(JOB_LABELS).map(([k,v])=>`<option value="${esc(k)}">${esc(v)}</option>`).join('')}</select></label><label class="field"><span>Status</span><select class="input" id="historyStatus"><option value="">All statuses</option>${['running','success','partial','error','stopped'].map(v=>`<option value="${v}">${v}</option>`).join('')}</select></label><button class="btn btn-secondary" id="historyRefresh">Refresh</button></div><div id="dashboardHistoryRows" aria-live="polite"></div>`, '<span id="historyPage" class="muted small"></span><button class="btn btn-secondary" id="historyPrev">Previous</button><button class="btn btn-secondary" id="historyNext">Next</button>');
  const dialog = $('#modalHost .modal'); dialog.classList.remove('modal-compact'); dialog.classList.add('log-dialog', 'history-dialog');
  let page = 1, request = 0;
  async function load() {
    const version = ++request;
    const query = new URLSearchParams({paginated:'true',limit:'25',offset:String((page-1)*25)});
    if ($('#historyWorker').value) query.set('job', $('#historyWorker').value);
    if ($('#historyStatus').value) query.set('status', $('#historyStatus').value);
    try {
      const data = await apiGet('/api/runs?' + query);
      if (!dialog.isConnected || version !== request) return;
      $('#dashboardHistoryRows').innerHTML = data.items.length ? `<div class="history-list">${data.items.map(r => `<button class="history-row" data-history-log="${r.id}"><span class="history-symbol msym">history</span><span><strong>${esc(JOB_LABELS[r.job] || r.job)}</strong><small>${esc(r.target || 'Worker run')} · ${fmtDT(r.started_at)}</small></span>${runStatus(r.status,r.dry_run)}<span class="msym">arrow_forward</span></button>`).join('')}</div>` : '<div class="campaign-empty"><h3>No matching runs</h3><p>Change the filters or start a worker from the dashboard.</p></div>';
      $('#historyPage').textContent = `${data.total} runs · page ${page}`;
      $('#historyPrev').disabled = page <= 1; $('#historyNext').disabled = page * 25 >= data.total;
      $$('[data-history-log]', dialog).forEach(b => b.onclick = () => openRunLog(Number(b.dataset.historyLog)));
    } catch(e) { if (dialog.isConnected && version === request) $('#dashboardHistoryRows').innerHTML = `<p class="form-error" role="alert">${esc(errText(e))}</p>`; }
  }
  $('#historyWorker').onchange = $('#historyStatus').onchange = () => { page = 1; load(); };
  $('#historyRefresh').onclick = load;
  $('#historyPrev').onclick = () => { page--; load(); };
  $('#historyNext').onclick = () => { page++; load(); };
  await load();
}

function reassignLeadsDialog(ids, campaigns, accounts) {
  openModal('Reassign leads', `<p>Move <b>${ids.length}</b> selected lead(s). Contact history, replies and the current stage are preserved. Future actions use the destination account and campaign.</p>
    <label class="field"><span>Campaign</span><select class="input" id="moveCampaign"><option value="keep">Keep current campaign</option><option value="">Untagged pool</option>${campaigns.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label>
    <label class="field"><span>Outreach account</span><select class="input" id="moveAccount"></select></label>
    <p class="muted small">A selected account must be mapped to the destination campaign. Existing Sales Nav IDs in that campaign prevent the move.</p><p id="moveError" class="form-error" role="alert"></p>`,
    '<button class="btn btn-secondary" id="moveCancel">Cancel</button><button class="btn btn-primary" id="moveSave">Reassign leads</button>');
  const campaign = $('#moveCampaign'), account = $('#moveAccount');
  function accountOptions() {
    const previous = account.value || 'keep';
    const c = campaigns.find(c => String(c.id) === campaign.value);
    const allowed = c ? new Set((c.accounts || []).map(a => a.account_id)) : null;
    account.innerHTML = '<option value="keep">Keep current account</option><option value="">No assigned account</option>' + accounts.filter(a => !allowed || allowed.has(a.id)).map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join('');
    account.value = [...account.options].some(o => o.value === previous) ? previous : 'keep';
  }
  accountOptions(); campaign.onchange = accountOptions;
  $('#moveCancel').onclick = closeModal;
  $('#moveSave').onclick = async () => {
    const button = $('#moveSave'), body = {ids};
    if (campaign.value !== 'keep') body.campaign_id = campaign.value ? Number(campaign.value) : null;
    if (account.value !== 'keep') body.account_id = account.value ? Number(account.value) : null;
    if (campaign.value === 'keep' && account.value === 'keep') { $('#moveError').textContent = 'Choose a campaign or account to change.'; return; }
    button.disabled = true;
    try {
      const result = await apiPost('/api/leads/reassign', body);
      closeModal(); leadSelClear(); toast(`${result.changed} lead(s) reassigned. Stages preserved.`, 'ok');
      await renderLeads2();
    } catch (e) { if (button.isConnected) { $('#moveError').textContent = errText(e); button.disabled = false; } }
  };
}

const userActivityState = {page: 1, action: '', username: '', days: '0'};

async function renderUserActivityCompact(host = null) {
  const target = host || $('#settingsTabContent') || MAIN;
  if (!target) return;
  const state = userActivityState;
  const data = await apiGet('/api/user-activity?' + new URLSearchParams(state));
  const admin = window.ME?.role === 'admin';
  const labels = {login: 'Login', logout: 'Logout', run_job: 'Start worker', run_batch: 'Start batch', stop_job: 'Stop worker', reassign_leads: 'Reassign leads', reset_lead_errors: 'Remove lead errors', ...JOB_LABELS};
  const label = key => labels[key] || key.replaceAll('_', ' ');

  target.innerHTML = `<div class="card card-pad compact-activity-card">
    <div class="compact-activity-head">
      <div>
        <h2 style="margin:0;font-size:15px">User Activity &amp; Audit Log</h2>
        <p class="card-sub" style="margin:2px 0 10px">${admin ? 'Activity across all users and scheduled workers' : 'Your sign-ins and application actions'} · recorded from this update onward</p>
      </div>
      <button class="btn btn-secondary btn-sm" id="uaRefresh"><span class="msym">refresh</span>Refresh</button>
    </div>
    <div class="activity-filters compact-filters-bar">
      <label class="field"><span>User</span><input class="input" id="uaUser" placeholder="Search username" value="${esc(state.username)}"></label>
      <label class="field"><span>Activity</span><select class="input" id="uaAction"><option value="">All activity</option>${Object.entries(labels).map(([key,value]) => `<option value="${esc(key)}" ${state.action === key ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select></label>
      <label class="field"><span>Period</span><select class="input" id="uaDays">${[['0','All time'],['1','Past 24 hours'],['7','Past 7 days'],['30','Past 30 days']].map(([key,value]) => `<option value="${key}" ${state.days === key ? 'selected' : ''}>${value}</option>`).join('')}</select></label>
      <button class="btn btn-secondary btn-sm" id="uaApply"><span class="msym">filter_list</span>Apply</button>
    </div>
    <section class="user-activity-timeline" aria-label="Activity timeline">
      <div class="timeline-heading">
        <h2>Activity timeline</h2>
        <span>${data.total.toLocaleString()} matching events</span>
      </div>
      ${data.items.map(a => {
        const failure = ['error','partial','stopped'].includes(a.result) || a.result.startsWith('rejected');
        const tone = failure ? 'warn' : a.result === 'running' ? 'primary' : 'ok';
        const icon = a.action === 'login' || a.action === 'logout' ? 'person' : a.run_id ? 'play_arrow' : 'history';
        return `<article class="user-timeline-event">
          <div class="timeline-marker ${tone}"><span class="msym">${icon}</span></div>
          <div class="timeline-event-content">
            <div class="timeline-event-heading"><strong>${esc(label(a.action))}</strong>${pill(tone, a.result, false)}</div>
            <p>${esc(a.detail)}</p>
            <div class="timeline-event-meta">
              <span class="timeline-user">${esc(initials(a.username))}</span><b>${esc(a.username)}</b>
              <time title="${fmtDT(a.created_at)}">${fmtDT(a.created_at)}</time>
              ${a.run_id ? `<button class="btn btn-ghost btn-sm" data-activity-run="${a.run_id}">View run #${a.run_id}<span class="msym">arrow_forward</span></button>` : ''}
            </div>
          </div>
        </article>`;
      }).join('') || '<div class="campaign-empty"><span class="msym">history</span><h3>No activity matches these filters</h3><p>Try another user, activity type or period.</p></div>'}
    </section>
    <div class="activity-pager">
      <span>${data.total} events · page ${data.page}</span>
      <div style="display:flex;gap:6px">
        <button class="btn btn-secondary btn-sm" id="uaPrev" ${state.page <= 1 ? 'disabled' : ''}>Previous</button>
        <button class="btn btn-secondary btn-sm" id="uaNext" ${state.page * 50 >= data.total ? 'disabled' : ''}>Next</button>
      </div>
    </div>
  </div>`;

  $('#uaApply').onclick = () => {
    state.page = 1; state.username = $('#uaUser').value; state.action = $('#uaAction').value; state.days = $('#uaDays').value;
    renderUserActivityCompact(target).catch(e => toast(errText(e), 'crit'));
  };
  $('#uaUser').onkeydown = e => { if (e.key === 'Enter') $('#uaApply').click(); };
  $('#uaRefresh').onclick = () => renderUserActivityCompact(target).catch(e => toast(errText(e), 'crit'));
  $('#uaPrev').onclick = () => { state.page--; renderUserActivityCompact(target).catch(e => toast(errText(e), 'crit')); };
  $('#uaNext').onclick = () => { state.page++; renderUserActivityCompact(target).catch(e => toast(errText(e), 'crit')); };
  $$('[data-activity-run]', target).forEach(b => b.onclick = () => openRunLog(Number(b.dataset.activityRun)));
}

async function viewUserActivity() {
  if (typeof viewSettings === 'function') {
    await viewSettings('activity');
  } else {
    MAIN.innerHTML = `<div class="page"><div id="settingsTabContent"></div></div>`;
    await renderUserActivityCompact($('#settingsTabContent'));
  }
}
