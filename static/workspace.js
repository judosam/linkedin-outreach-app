/* Shared workspace dialogs and the persistent, backend-driven job console. */
'use strict';

function optionsHTML(items, value, empty = 'All') {
  return `<option value="">${esc(empty)}</option>` + items.map(([id, label]) => `<option value="${esc(id)}" ${String(id) === String(value) ? 'selected' : ''}>${esc(label)}</option>`).join('');
}

function scopePickerHTML(key, label, items) {
  const selected = new Set((threadV2[key] || '').split(',').filter(Boolean));
  return `<details class="scope-picker" data-scope="${key}"><summary>${label}${selected.size ? ` <b>${selected.size}</b>` : ''}<span class="msym">expand_more</span></summary><div class="scope-pop"><div class="scope-pop-title">${label}<button class="btn btn-ghost btn-sm" data-scope-clear>Clear</button></div><div class="filter-checks">${items.map(it=>`<label><input class="checkbox" type="checkbox" value="${it.id}" ${selected.has(String(it.id))?'checked':''}>${esc(it.name)}</label>`).join('')}</div><button class="btn btn-primary btn-sm" data-scope-apply>Apply</button></div></details>`;
}
function wireScopePickers(apply) {
  $$('.scope-picker',MAIN).forEach(picker=>{
    picker.addEventListener('toggle',()=>{if(picker.open){
      $$('.scope-picker',MAIN).forEach(other=>{if(other!==picker)other.open=false;});
      const panel=$('.scope-pop',picker);panel.style.left='0';
      const rect=panel.getBoundingClientRect();
      if(rect.right>innerWidth-12)panel.style.left=`${innerWidth-12-rect.right}px`;
    }});
    $('[data-scope-clear]',picker).onclick=()=>$$('input',picker).forEach(el=>el.checked=false);
    $('[data-scope-apply]',picker).onclick=()=>{threadV2[picker.dataset.scope]=$$('input:checked',picker).map(el=>el.value).join(',');picker.open=false;apply();};
  });
}
document.addEventListener('click',e=>$$('.scope-picker[open]').forEach(el=>{if(!el.contains(e.target))el.open=false;}));
document.addEventListener('keydown',e=>{if(e.key==='Escape')$$('.scope-picker[open]').forEach(el=>{el.open=false;$('summary',el).focus();});});

function filtersDialog() {
  const state = leadV2;
  const select = (key, label, items) => `<label class="field"><span>${label}</span><select class="input" name="${key}">${optionsHTML(items, state[key])}</select></label>`;
  openModal('Filter leads', `<form id="workspaceFilters"><div class="dialog-grid">
    ${select('status','Stage',[['__untouched__','Untouched'],...Object.entries(STATUS_META).filter(([k])=>k).map(([k,v])=>[k,v.label])])}
    ${select('source','Source',[['campaign_search','SavedSearch'],['list_import','SavedList']])}
    ${select('replied','Reply state',[['true','Replied'],['false','No reply']])}
    ${select('category','Reply category',Object.entries(REPLY_CATEGORIES))}
    ${select('review','Review state',[['needs_review','Needs review'],['reviewed','Reviewed']])}
    </div></form>`,
    '<button class="btn btn-ghost" id="filterReset">Clear filters</button><button class="btn btn-secondary" id="filterClose">Close</button><button class="btn btn-primary" id="filterApply">Apply filters</button>');
  $('#modalHost .modal').classList.add('compact-filter-modal');
  const form = $('#workspaceFilters');
  $('#filterClose').onclick = closeModal;
  $('#filterReset').onclick = () => { for (const el of form.elements) if (el.matches('select')) el.value = ''; };
  $('#filterApply').onclick = () => {
    for (const el of form.elements) if (el.name) state[el.name] = el.value;
    state.page = 1; leadSelClear(); closeModal();
    renderLeads2().catch(e=>toast(errText(e),'crit'));
  };
}

async function batchDialog() {
  try {
    const campaigns = (await apiGet('/api/campaigns')).filter(c=>c.status==='active');
    openModal('Run Job Now', `<p class="card-sub">Choose workers and campaigns. Runs execute in sequence.</p>
      <fieldset class="filter-section"><legend>Workers</legend><div class="dialog-grid"><label class="choice-tile"><input class="checkbox" type="checkbox" id="batchConnections" checked>Run Connections</label><label class="choice-tile"><input class="checkbox" type="checkbox" id="batchFollowups">Run Follow-ups</label></div></fieldset>
      <fieldset class="filter-section"><legend>Campaigns</legend><input class="input" id="batchSearch" placeholder="Search campaigns…" aria-label="Search campaigns"><div class="dialog-actions"><button class="btn btn-ghost" id="batchAll">Select all</button><button class="btn btn-ghost" id="batchNone">Clear selection</button></div><div class="filter-checks" id="batchCampaigns">${campaigns.map(c=>`<label data-name="${esc(c.name.toLowerCase())}"><input class="checkbox" type="checkbox" value="${c.id}">${esc(c.name)}</label>`).join('') || '<p>No active campaigns. Create or activate a campaign first.</p>'}</div></fieldset>
      <label class="choice-tile"><input class="checkbox" id="batchDry" type="checkbox">Dry run · no outreach</label><p class="batch-summary" id="batchSummary" role="status"></p>`,
      '<button class="btn btn-secondary" id="batchCancel">Cancel</button><button class="btn btn-primary" id="batchStart">Run Job</button>');
    $('#modalHost .modal').classList.add('compact-run-modal');
    const selected=()=>$$('#batchCampaigns input:checked').map(el=>Number(el.value));
    const update=()=>{ $('#batchSummary').textContent=`Connections: ${$('#batchConnections').checked?'Enabled':'Disabled'} · Follow-ups: ${$('#batchFollowups').checked?'Enabled':'Disabled'} · Campaigns: ${selected().length} selected`; $('#batchStart').disabled=!selected().length || !($('#batchConnections').checked || $('#batchFollowups').checked); };
    $$('#modalHost input[type=checkbox]').forEach(el=>el.onchange=update);
    $('#batchAll').onclick=()=>{$$('#batchCampaigns input').forEach(el=>el.checked=true);update();};
    $('#batchNone').onclick=()=>{$$('#batchCampaigns input').forEach(el=>el.checked=false);update();};
    $('#batchSearch').oninput=e=>{$$('#batchCampaigns label').forEach(el=>el.hidden=!el.dataset.name.includes(e.target.value.toLowerCase()));};
    $('#batchCancel').onclick=closeModal;
    $('#batchStart').onclick=async()=>{
      const body={connections:$('#batchConnections').checked,followups:$('#batchFollowups').checked,campaign_ids:selected(),dry_run:$('#batchDry').checked};
      try { const result=await apiPost('/api/jobs/batch',body); showStartedJob(result); (result.warnings||[]).forEach(w=>toast(w,'warn')); } catch(e) {toast(errText(e),'crit');}
    };
    update();
  } catch(e) {toast(errText(e),'crit');}
}

function importDialog(key, campaigns, accounts, selectedAccountId = null) {
  const search=key==='sync_leads';
  const active=accounts.filter(a=>a.status==='active');
  const initial=selectedAccountId || (active.length===1 ? active[0].id : '');
  openModal(JOB_LABELS[key], `<p class="card-sub">Import leads from a saved ${search?'search':'list'} using one active LinkedIn account.</p><form id="importForm" class="dialog-grid">
    <label class="field"><span>Import account (required)</span><select class="input" name="account" required>${optionsHTML(active.map(a=>[a.id,a.name]),initial,'Choose an account')}</select></label>
    <label class="field"><span>${search?'Saved Search':'Saved List'} ID</span><input class="input mono" name="savedId" inputmode="numeric" pattern="[0-9]+" placeholder="Enter numeric ID" required></label>
    <label class="field"><span>Outreach account (optional)</span><select class="input" name="outreachAccount">${optionsHTML(active.map(a=>[a.id,a.name]),'','No account assigned')}</select></label>
    <label class="field"><span>Campaign tag (required)</span><select class="input" name="campaign" required></select></label>
    <label class="choice-tile"><input class="checkbox" name="dry" type="checkbox">Dry run</label></form><p id="importAssignmentHint" class="muted small"></p><p class="muted small">Existing leads keep their account assignments and engagement history.</p>`,
    '<button class="btn btn-secondary" id="importCancel">Cancel</button><button class="btn btn-primary" id="importStart">Start Import</button>');
  const form=$('#importForm');
  form.onsubmit=e=>{e.preventDefault();$('#importStart').click();};
  const updateCampaigns=()=>{
    const aid=Number(form.elements.outreachAccount.value);
    const assigned=!!form.elements.outreachAccount.value;
    const eligible=campaigns.filter(c=>!assigned || (c.accounts || []).some(a=>a.account_id===aid));
    const previous=form.elements.campaign.value;
    form.elements.campaign.innerHTML=optionsHTML(eligible.map(c=>[c.id,c.name]),previous,'Choose a campaign');
    $('#importAssignmentHint').textContent=assigned
      ? 'New leads will be assigned to the selected outreach account. Only campaigns mapped to that account are available. The import account is used only to fetch leads.'
      : 'No account will be assigned during import. Campaign outreach will use its mapped accounts and available budgets.';
  };
  form.elements.outreachAccount.onchange=updateCampaigns;
  updateCampaigns();
  $('#importCancel').onclick=closeModal;
  $('#importStart').onclick=async e=>{
    if(!form.reportValidity()) return;
    const body={account_id:Number(form.elements.account.value),campaign_id:form.elements.campaign.value?Number(form.elements.campaign.value):null,
      outreach_account_id:form.elements.outreachAccount.value?Number(form.elements.outreachAccount.value):null,dry_run:form.elements.dry.checked,[search?'saved_search_id':'list_id']:form.elements.savedId.value.trim()};
    const button=e.currentTarget;button.disabled=true;
    try {const result=await apiPost(`/api/jobs/${key}/run`,body);showStartedJob(result);} catch(e){toast(errText(e),'crit');button.disabled=false;}
  };
}

let consoleTimer=null, consoleBusy=false, consoleSnapshot=null, consoleCleared=null, consoleExecution=null, consoleGeneration=0;
function selectConsoleExecution(id) { consoleExecution=id || null; consoleGeneration++; }
function resetJobConsole() {
  minimizeFloatingConsole();
  consoleGeneration++; consoleExecution=null; consoleSnapshot=null; consoleCleared=null;
  clearTimeout(consoleTimer); $('#floatingConsole')?.remove();
}
function ensureFloatingConsole() {
  if ($('#floatingConsole')) return;
  const host=document.createElement('aside');host.id='floatingConsole';host.setAttribute('aria-label','Live job console');
  host.innerHTML=`<section class="floating-panel expanded" id="floatingPanel" hidden aria-label="Live job output"><header><span class="console-emblem msym">terminal</span><div><strong>Live job console</strong><span id="floatingStatus" role="status">Connecting…</span></div><button class="icon-btn" id="floatingClose" aria-label="Close live job console"><span class="msym">close</span></button></header><div class="floating-content"><label class="console-run-picker" id="consoleRunPicker" hidden><span>Running jobs</span><select class="input" id="consoleRunSelect" aria-label="Select running job"></select></label><p id="floatingContext" class="card-sub"></p><div id="floatingProgress" class="progress-metrics"></div><p id="floatingAction" class="card-sub"></p><pre class="runlog" id="floatingOutput" tabindex="0" aria-label="Live logs"></pre></div><footer><button class="btn btn-danger btn-sm" id="floatingStop" hidden>Stop Run</button><button class="btn btn-secondary btn-sm" id="floatingAuto" aria-pressed="true">Auto-scroll on</button><button class="btn btn-ghost btn-sm" id="floatingClear">Clear completed</button><a href="#/dashboard?history=1">History</a></footer></section><button class="floating-ball" id="floatingBall" aria-controls="floatingPanel" aria-expanded="false" aria-label="Open live job console"><span class="msym">schedule</span><span id="floatingCount">0</span></button>`;
  APP.append(host);
  $('#floatingBall').onclick=()=>$('#floatingPanel').hidden ? openFloatingConsole() : minimizeFloatingConsole();
  $('#floatingClose').onclick = minimizeFloatingConsole;
  $('#floatingStop').onclick=()=>requestStopJob(consoleSnapshot?.run_id, consoleSnapshot?.execution_id);
  $('#consoleRunSelect').onchange=e=>{selectConsoleExecution(e.target.value);pollFloatingConsole();};
  $('#floatingAuto').onclick=e=>{const on=e.currentTarget.getAttribute('aria-pressed')!=='true';e.currentTarget.setAttribute('aria-pressed',String(on));e.currentTarget.textContent=on?'Auto-scroll on':'Auto-scroll paused';};
  $('#floatingClear').onclick=()=>{if(!consoleSnapshot?.active){consoleCleared=consoleSnapshot?.run_id;$('#floatingOutput').textContent='Completed output cleared from this panel. History is retained.';}};
  host.addEventListener('keydown', e => {
    if ($('#floatingPanel').hidden) return;
    if (e.key === 'Escape') { e.preventDefault(); minimizeFloatingConsole(); }
    if (e.key === 'Tab') {
      const items = [...host.querySelectorAll('button:not(:disabled), a, select, [tabindex="0"]')].filter(el => el.getClientRects().length);
      const first = items[0], last = items[items.length-1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
}
let consoleBackground = null, consoleOverflow = '';
function minimizeFloatingConsole() {
  if (!$('#floatingPanel')) return;
  $('#floatingPanel').hidden = true;
  $('#floatingConsole').removeAttribute('role'); $('#floatingConsole').removeAttribute('aria-modal');
  $('#floatingBall').setAttribute('aria-expanded', 'false');
  $('#floatingBall').setAttribute('aria-label', 'Open live job console');
  if (consoleBackground) {
    consoleBackground.forEach(([el, inert]) => el.inert = inert);
    consoleBackground = null; document.body.style.overflow = consoleOverflow;
  }
  $('#floatingBall').focus();
}
function openFloatingConsole() {
  ensureFloatingConsole();
  if ($('#modalHost .modal')) closeModal();
  const host = $('#floatingConsole');
  if (!consoleBackground) {
    consoleOverflow = document.body.style.overflow;
    consoleBackground = [...APP.children].filter(el => el !== host).map(el => [el, el.inert]);
    consoleBackground.forEach(([el]) => el.inert = true); document.body.style.overflow = 'hidden';
  }
  host.setAttribute('role', 'dialog'); host.setAttribute('aria-modal', 'true');
  $('#floatingPanel').classList.add('expanded'); $('#floatingPanel').hidden = false;
  $('#floatingBall').setAttribute('aria-expanded', 'true');
  $('#floatingBall').setAttribute('aria-label', 'Minimize live job console');
  $('#floatingOutput').focus(); pollFloatingConsole();
}
async function pollFloatingConsole(){
  clearTimeout(consoleTimer);
  if(consoleBusy) return;
  if(APP.hidden){consoleTimer=setTimeout(pollFloatingConsole,2000);return;}
  ensureFloatingConsole();consoleBusy=true; const generation=consoleGeneration;
  try{
    const j=await apiGet('/api/runs/live'+(consoleExecution?'?execution_id='+encodeURIComponent(consoleExecution):''));
    if(generation!==consoleGeneration || APP.hidden) return;
    consoleSnapshot=j;
    const runs=j.running || [];
    const picker=$('#consoleRunSelect');
    const selected=j.execution_id || '';
    const choices=[...runs];
    if(selected && !choices.some(r=>r.execution_id===selected)) choices.unshift({execution_id:selected,job:j.job,target:j.target,status:j.status});
    const options=choices.map(r=>`<option value="${esc(r.execution_id)}">${esc(JOB_LABELS[r.job] || r.job)} · ${esc(r.target || 'Starting')} · ${esc(r.status)}</option>`).join('');
    if(picker.innerHTML!==options)picker.innerHTML=options;
    picker.value=selected; $('#consoleRunPicker').hidden=choices.length<2;
    $('#consoleRunPicker span').textContent=`${runs.length} running ${runs.length===1?'job':'jobs'}`;
    $('#floatingBall').classList.toggle('running',!!j.running_count);$('#floatingCount').textContent=String(j.running_count || 0);
    const displayStatus=j.batch_status || j.status;
    $('#floatingPanel').dataset.status=displayStatus || 'idle';
    $('#floatingStatus').textContent=({success:'Completed',error:'Failed',partial:'Completed with warnings',running:'Running',stopping:'Stopping',stopped:'Stopped',idle:'Idle'})[displayStatus] || displayStatus;

    const wasActiveInConsole = window.__floatingConsoleWasActive ?? false;
    window.__floatingConsoleWasActive = !!j.active;
    if (wasActiveInConsole && !j.active && j.run_id && typeof notifyRunFinished === 'function') {
      notifyRunFinished({ run_id: j.run_id, job: j.job, execution_id: j.execution_id });
    }

    const elapsed=j.active && j.started_at ? Math.max(0,Math.floor((Date.now()-new Date(j.started_at+'Z').getTime())/1000)):j.duration_s;
    $('#floatingContext').textContent=[j.target,j.started_at?'Started '+fmtDT(j.started_at):'',elapsed!=null?fmtDur(elapsed):''].filter(Boolean).join(' · ');
    const p=j.progress||{};
    $('#floatingAction').textContent=j.active ? p.action || 'Starting worker…' : ''; 
    $('#floatingProgress').innerHTML=p.page?`<span>Page <b>${esc(p.page)}${p.total_pages!=null?' / '+esc(p.total_pages):''}</b></span><span>This page <b>${esc(p.page_extracted)}</b></span><span>Extracted <b>${esc(p.extracted)}</b></span><span>New <b>${esc(p.added)}</b></span>${p.percent!=null?`<progress max="100" value="${p.percent}" aria-label="Extraction progress"></progress><span>${p.percent}%</span>`:''}`:'';
    const output=$('#floatingOutput'); const text=j.log_text||(j.active?'Starting worker…':'No job output yet.');
    if(consoleCleared!==j.run_id || j.active){if(output.textContent!==text){const scroll=output.scrollTop;output.textContent=text;output.scrollTop=$('#floatingAuto').getAttribute('aria-pressed')==='true'?output.scrollHeight:scroll;}}
    $('#floatingStop').hidden=!j.active;$('#floatingStop').disabled=j.status==='stopping';$('#floatingStop').textContent=j.status==='stopping'?'Stopping…':'Stop Run';$('#floatingClear').disabled=!!j.active;
  }catch(e){if(generation===consoleGeneration){ if(consoleExecution && /not found/i.test(errText(e)))selectConsoleExecution(null); if($('#floatingStatus'))$('#floatingStatus').textContent='Disconnected · retrying…'; }}
  finally{consoleBusy=false;consoleTimer=setTimeout(pollFloatingConsole,2000);}
}
window.addEventListener('DOMContentLoaded',()=>{ $('#runBatchNow').onclick=batchDialog;pollFloatingConsole(); });

/* Account summaries live outside the scrolling table and share modal focus handling. */
function accountHealth(account) {
  // A stale derived session flag must never override persisted access failure.
  const state = ['seat_required','needs_reauth','paused'].includes(account.status)
    ? account.status : account.session_state || account.status;
  if (state === 'seat_required') return ['warn','Sales Nav required'];
  if (state === 'needs_reauth') return ['crit','Needs re-auth'];
  if (!account.session_configured) return ['warn','Session missing'];
  if (account.status === 'paused') return ['idle','Paused'];
  return account.status === 'active' ? ['ok','Active'] : ['warn','Verification required'];
}
function accountStatusOptions(status) {
  const labels = {active:'Active', paused:'Paused', needs_reauth:'Needs re-auth', seat_required:'Sales Nav required'};
  const blocked = ['needs_reauth','seat_required'].includes(status);
  return Object.entries(labels).filter(([key])=>blocked ? key===status : ['active','paused'].includes(key)).map(([key,label])=>`<option value="${key}" ${key===(status || 'active')?'selected':''}>${label}</option>`).join('');
}

function accountDetails(account, campaignsOnly = false) {
  if (!account) return;
  const usage = account.usage_today || {};
  const state = accountHealth(account);
  const campaigns = `<section class="account-assignments"><h3>Assigned campaigns <span class="tag">${account.campaigns.length}</span></h3>${account.campaigns.length ? `<ul>${account.campaigns.map(name => `<li><span class="msym">rocket_launch</span>${esc(name)}</li>`).join('')}</ul>` : '<p class="muted">No campaigns assigned yet.</p>'}</section>`;
  openModal(campaignsOnly ? `Campaigns · ${account.name}` : 'Account details', `
    <div class="account-profile"><span class="profile-avatar">${esc(initials(account.name))}</span><div><h2>${esc(account.name)}</h2>${pill(...state)}</div></div>
    ${campaignsOnly ? campaigns : `<div class="account-facts"><div><span>Last session refresh</span><strong>${account.last_cookie_refresh_at ? fmtDT(account.last_cookie_refresh_at) : 'Not refreshed yet'}</strong></div><div><span>Total runs</span><strong>${account.total_runs ?? 0}</strong></div></div>
    <section class="account-limits"><h3>Today's usage <span class="muted">used / daily limit</span></h3>${[['Invites','invites','daily_invite_cap'],['InMails','inmails','daily_inmail_cap'],['Messages','messages','daily_message_cap']].map(([label,key,cap]) => `<div class="account-limit"><span>${label}</span>${quotaBar(usage[key] || 0, account[cap])}</div>`).join('')}</section>${campaigns}`}`,
    '<button class="btn btn-secondary" id="accountDetailClose">Close</button><button class="btn btn-primary" id="accountDetailSettings"><span class="msym">tune</span>Account settings</button>');
  $('#modalHost .modal').classList.add('account-detail-modal');
  $('#accountDetailClose').onclick = closeModal;
  $('#accountDetailSettings').onclick = () => accountEditor(account).catch(e=>toast(errText(e),'crit'));
}
