/* Enterprise licences: server-confirmed roster, protected admin seat. */
const salesNavState = { data: null, busy: false, loading: false, error: '', results: null,
  selected: new Set(), request: 0, updated: null };
const SALESNAV_HOLDING = ['ACTIVATED', 'ACTIVE', 'INVITED', 'PENDING'];
function parseSalesNavEmails(raw) {
  return [...new Set(String(raw || '').split(/[\s,;]+/).map(s => s.trim().toLowerCase()).filter(Boolean))];
}
function salesNavStatusTone(status) {
  return ({ ACTIVATED: 'ok', ACTIVE: 'ok', INVITED: 'primary', PENDING: 'warn', DECLINED: 'crit' })[status] || 'idle';
}
function salesNavProtected(row) { return row.protected || String(row.name || '').trim().toLowerCase() === 'anne davis'; }
function salesNavRows() { return [...(salesNavState.data?.licenses || []), ...(salesNavState.data?.others || [])]; }
function salesNavConfirmRemove(emails) {
  if (salesNavState.busy || !emails.length) return;
  openModal('Remove Sales Navigator access?', `<p>This will request removal for ${emails.length} account${emails.length === 1 ? '' : 's'}.</p>
    <ul class="sn-confirm-list">${emails.map(email => `<li>${esc(email)}</li>`).join('')}</ul>
    <p class="muted small">Anne Davis’s admin access is protected. Refresh the roster after removal to confirm LinkedIn’s final status.</p>`,
    '<button class="btn btn-secondary" id="snCancel">Cancel</button><button class="btn btn-danger" id="snConfirm">Remove access</button>');
  $('#modalHost .modal').setAttribute('role', 'alertdialog');
  $('#snCancel').onclick = closeModal;
  $('#snConfirm').onclick = () => { closeModal(); salesNavRun('remove', emails); };
  $('#snCancel').focus();
}
function salesNavAddDialog() {
  openModal('Add accounts', `<p class="muted small">Add email addresses to your organisation. You can assign available licences from the roster afterwards.</p>
    <label class="field"><span>Email addresses</span><textarea class="input" id="snEmails" rows="5" placeholder="name@company.com"></textarea></label>
    <p class="muted small">Separate addresses with a new line, comma or semicolon.</p><p id="snEmailError" class="form-error" role="alert"></p>`,
    '<button class="btn btn-secondary" id="snCancel">Cancel</button><button class="btn btn-primary" id="snAdd">Add accounts</button>');
  $('#snCancel').onclick = closeModal;
  $('#snAdd').onclick = () => {
    const emails = parseSalesNavEmails($('#snEmails').value);
    if (!emails.length || emails.some(e => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e))) {
      $('#snEmailError').textContent = 'Enter valid email addresses.'; return;
    }
    closeModal(); salesNavRun('add', emails);
  };
}
async function salesNavRun(kind, emails) {
  if (salesNavState.busy || !emails.length) return;
  if (kind === 'remove' && salesNavRows().some(r => emails.includes(r.email) && salesNavProtected(r))) {
    salesNavState.error = 'Anne Davis’s admin access cannot be removed.'; salesNavRender(); return;
  }
  salesNavState.busy = true;
  salesNavState.loading = false;
  salesNavState.error = '';
  ++salesNavState.request; // Ignore any roster request started before this action.
  salesNavRender();
  try {
    const response = await apiPost(`/api/salesnav/${kind}`, { emails });
    salesNavState.results = response.results || [];
    salesNavState.selected.clear();
    // Bulk tasks settle asynchronously. Never change a roster status or free
    // a seat based only on an accepted request, including partial failures.
  } catch (e) { salesNavState.error = errText(e); }
  finally {
    salesNavState.busy = false;
    if (!APP.hidden && currentRoute === 'salesnav') salesNavRender();
  }
}
function salesNavRoster(rows, holding) {
  if (!rows.length) return `<div class="sn-empty"><span class="msym">${holding ? 'workspace_premium' : 'group'}</span>
    <strong>${holding ? 'No licences assigned' : 'No accounts waiting for a licence'}</strong>
    <p>${holding ? 'Assign a licence to an available account below.' : 'Add accounts when you are ready to grow your team.'}</p></div>`;
  return `<div class="sn-table-scroll" tabindex="0" role="region" aria-label="${holding ? 'Current licences' : 'Available accounts'}">
    <table class="data sn-table"><thead><tr>${holding ? '<th class="sn-check"><input id="snSelectAll" type="checkbox" aria-label="Select all removable accounts"></th>' : ''}
    <th>Account</th><th>Status</th><th>Access</th><th class="sn-actions-heading">Actions</th></tr></thead><tbody>${rows.map(row => {
      const protectedSeat = salesNavProtected(row), selected = salesNavState.selected.has(row.email);
      return `<tr data-sn-email="${esc(row.email)}" class="${protectedSeat ? 'sn-protected-row' : ''}">
        ${holding ? `<td class="sn-check">${protectedSeat ? '<span class="msym sn-lock" title="Protected administrator" aria-label="Protected administrator">lock</span>' : `<input type="checkbox" data-sn-check value="${esc(row.email)}" aria-label="Select ${esc(row.email)}" ${selected ? 'checked' : ''} ${!row.email ? 'disabled' : ''}>`}</td>` : ''}
        <td><div class="sn-person"><span class="sn-avatar" aria-hidden="true">${esc((row.name || row.email || '?').slice(0, 1).toUpperCase())}</span><div><strong>${esc(row.name || row.email || 'Unnamed account')}</strong><span>${esc(row.email || 'Email unavailable')}</span></div></div></td>
        <td>${pill(salesNavStatusTone(row.status), ({ACTIVATED:'Active', ACTIVE:'Active', INVITED:'Invited', PENDING:'Pending', NONE:'Not assigned', DECLINED:'Declined'})[row.status] || row.status)}</td>
        <td>${protectedSeat ? '<span class="sn-protected-label">Protected admin</span>' : '<span class="muted small">Team member</span>'}</td>
        <td><div class="sn-row-actions">${['INVITED','PENDING'].includes(row.status) && row.email ? `<button class="btn btn-secondary btn-sm" data-sn-link="${esc(row.email)}">Get invite link</button>` : ''}
          ${protectedSeat ? '<span class="muted small">Removal locked</span>' : holding ? `<button class="btn btn-ghost btn-sm" data-sn-remove="${esc(row.email)}" ${!row.email ? 'disabled' : ''}>Remove access</button>` : `<button class="btn btn-secondary btn-sm" data-sn-activate="${esc(row.email)}" ${!row.email || !salesNavState.data?.remaining ? 'disabled' : ''}>Assign licence</button>`}</div></td>
      </tr>`;
    }).join('')}</tbody></table></div>`;
}
function salesNavResultsHTML() {
  if (!salesNavState.results) return '';
  return `<section class="card sn-results" aria-label="Last action results"><div class="sn-section-head"><div><h2>Action results</h2><p>Requests may take a moment to appear in the roster. Refresh to confirm.</p></div><button class="icon-btn" id="snDismissResults" aria-label="Dismiss action results"><span class="msym">close</span></button></div>
    <ul>${salesNavState.results.map(r => `<li><div><strong>${esc(r.email)}</strong><p>${esc(r.detail || r.action)}</p></div>${pill(r.action === 'failed' ? 'crit' : 'idle', r.action === 'activated' || r.action === 'removed' ? 'Request accepted' : r.action)}${r.link ? `<button class="btn btn-secondary btn-sm" data-sn-copy="${esc(r.link)}">Copy invite link</button>` : ''}</li>`).join('')}</ul></section>`;
}
function salesNavRender() {
  if (APP.hidden || currentRoute !== 'salesnav' || window.ME?.role !== 'admin') return;
  const s = salesNavState, d = s.data, rows = d?.licenses || [], others = d?.others || [];
  const removable = rows.filter(r => !salesNavProtected(r) && r.email);
  s.selected = new Set([...s.selected].filter(email => removable.some(r => r.email === email)));
  MAIN.innerHTML = `<div class="page salesnav-page" aria-busy="${s.busy || s.loading}">
    <div class="page-head"><div><h1>Sales Navigator licences</h1><p class="page-sub">One place to manage your team’s access.</p></div><div class="page-actions">
    <button class="btn btn-secondary" id="snRefresh" ${s.busy || s.loading ? 'disabled' : ''}><span class="msym">refresh</span>${s.loading ? 'Refreshing…' : 'Refresh'}</button>
    <button class="btn btn-primary" id="snOpenAdd" ${!d || s.busy ? 'disabled' : ''}><span class="msym">person_add</span>Add accounts</button></div></div>
    <div class="sn-admin-note"><span class="msym">lock</span><div><strong>Anne Davis · Licence administrator</strong><p>Her admin access is protected and cannot be removed.</p></div><span class="sn-protected-label">Protected</span></div>
    ${s.error ? `<div class="banner banner-crit" role="alert">${esc(s.error)}</div>` : ''}
    ${s.busy ? '<p class="sn-working" role="status">Processing your request…</p>' : ''}
    ${d ? `<div class="sn-summary"><div><span>Licences in use</span><strong>${d.used}<small> / ${d.max_licenses}</small></strong><div class="sn-meter" role="meter" aria-label="Licences used" aria-valuemin="0" aria-valuemax="${Math.max(d.max_licenses,d.used)}" aria-valuenow="${d.used}"><i style="width:${Math.min(100,d.used / Math.max(1,d.max_licenses)*100)}%"></i></div></div>
      <div><span>Available seats</span><strong>${d.remaining}</strong><small>${d.remaining ? 'Ready to assign' : 'All seats are in use'}</small></div>
      <div><span>Awaiting assignment</span><strong>${others.length}</strong><small>Accounts without a licence</small></div></div>
      ${salesNavResultsHTML()}
      <section class="card sn-roster"><div class="sn-section-head"><div><h2>Current licences <span>${rows.length}</span></h2><p>Active seats and invitations awaiting acceptance.</p></div>
      <button class="btn btn-secondary btn-sm" id="snRemoveSelected" ${!s.selected.size || s.busy ? 'disabled' : ''}>Remove selected${s.selected.size ? ` (${s.selected.size})` : ''}</button></div>${salesNavRoster(rows, true)}</section>
      <section class="card sn-roster"><div class="sn-section-head"><div><h2>Available accounts <span>${others.length}</span></h2><p>${d.remaining ? 'Assign a licence when an account is ready.' : 'Free a team member’s seat before assigning another licence.'}</p></div></div>${salesNavRoster(others, false)}</section>
      <p class="sn-sync-note">Last refreshed ${esc(s.updated?.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) || '—')} · Roster and seat counts confirmed by LinkedIn.</p>` : '<div class="card sn-empty" role="status">Refresh the roster to load accounts and available seats.</div>'}
    </div>`;
  $('#snRefresh').onclick = () => viewSalesNav();
  $('#snOpenAdd').onclick = salesNavAddDialog;
  if (s.busy) $$('.salesnav-page button,.salesnav-page input', MAIN).forEach(el => el.disabled = true);
  const all = $('#snSelectAll'), checks = $$('[data-sn-check]:not(:disabled)', MAIN);
  if (all) {
    all.disabled = s.busy || !checks.length;
    all.checked = !!checks.length && checks.every(c => c.checked);
    all.indeterminate = checks.some(c => c.checked) && !all.checked;
    all.onchange = () => { s.selected = new Set(all.checked ? removable.map(r => r.email) : []); salesNavRender(); $('#snSelectAll')?.focus(); };
  }
  checks.forEach(c => c.onchange = () => { c.checked ? s.selected.add(c.value) : s.selected.delete(c.value); const email=c.value; salesNavRender(); $$('[data-sn-check]', MAIN).find(el => el.value === email)?.focus(); });
  if ($('#snRemoveSelected')) $('#snRemoveSelected').onclick = () => salesNavConfirmRemove([...s.selected]);
  $$('[data-sn-remove]', MAIN).forEach(b => b.onclick = () => salesNavConfirmRemove([b.dataset.snRemove]));
  $$('[data-sn-activate]', MAIN).forEach(b => b.onclick = () => salesNavRun('activate', [b.dataset.snActivate]));
  $$('[data-sn-link]', MAIN).forEach(b => b.onclick = () => salesNavRun('link', [b.dataset.snLink]));
  $$('[data-sn-copy]', MAIN).forEach(b => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.snCopy); toast('Invite link copied', 'ok'); }
    catch { toast('Unable to copy the invite link', 'warn'); }
  });
  if ($('#snDismissResults')) $('#snDismissResults').onclick = () => { s.results = null; salesNavRender(); };
}
async function viewSalesNav() {
  if (window.ME?.role !== 'admin') {
    salesNavState.data = null; salesNavState.results = null;
    MAIN.innerHTML = '<div class="page"><h1>Sales Navigator licences</h1><p>Administrator access is required to manage licences.</p></div>'; return;
  }
  if (salesNavState.busy) { salesNavRender(); return; }
  const request = ++salesNavState.request;
  salesNavState.loading = true; salesNavState.error = ''; salesNavRender();
  try {
    const data = await apiGet('/api/salesnav/licenses');
    if (request !== salesNavState.request || APP.hidden || currentRoute !== 'salesnav') return;
    salesNavState.data = data; salesNavState.updated = new Date();
  } catch (e) { if (request === salesNavState.request) salesNavState.error = errText(e); }
  finally { if (request === salesNavState.request) { salesNavState.loading = false; salesNavRender(); } }
}
