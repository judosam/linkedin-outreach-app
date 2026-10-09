/* Outreach Command Center — vanilla JS single-page app (hash-routed).
   Mirrors the biometric TimeChamp app architecture: one index.html shell,
   views rendered into <main> by a tiny router, no build step. */

'use strict';

/* ------------------------------------------------------------------ *
 *  Small helpers
 * ------------------------------------------------------------------ */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const MAIN = $('#main');
const APP = $('#app');
const LOGIN = $('#loginView');

const STATUS_META = {
  '': { label: 'Untouched', tone: 'idle' },
  BLOCKED_ERROR: { label: 'Error', tone: 'crit' },
  INVITE_SENT: { label: 'Invite Sent', tone: 'primary' },
  INMAIL_SENT: { label: 'InMail Sent', tone: 'info' },
  INVITE_AFTER_ACCEPT: { label: 'After Accept', tone: 'ok' },
  INVITE_FOLLOWUP_1: { label: 'Invite FU 1', tone: 'primary' },
  INVITE_FOLLOWUP_2: { label: 'Invite FU 2', tone: 'primary' },
  INVITE_FOLLOWUP_3: { label: 'Invite FU 3', tone: 'primary' },
  INMAIL_FOLLOWUP_1: { label: 'InMail FU 1', tone: 'info' },
  INMAIL_FOLLOWUP_2: { label: 'InMail FU 2', tone: 'info' },
  INMAIL_FOLLOWUP_3: { label: 'InMail FU 3', tone: 'info' },
};

const JOB_LABELS = {
  sync_leads: 'Import SavedSearch',
  import_list: 'Import SavedList',
  send_connections: 'Send Connections',
  check_replies: 'Check Replies',
  send_followups: 'Send Follow-ups',
};
const WORKERS = ['send_connections', 'check_replies', 'send_followups'];
const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

function pill(tone, label, dot = true) {
  return `<span class="pill pill-${tone}">${dot ? `<span class="dot"></span>` : ''}${esc(label)}</span>`;
}
function statusPill(status) {
  const m = STATUS_META[status] ?? { label: status || 'Untouched', tone: 'idle' };
  return pill(m.tone, m.label);
}
function fmtDT(value) {
  if (!value) return '—';
  const d = new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z');
  if (isNaN(d)) return '—';
  return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function fmtD(value) {
  if (!value) return '—';
  const d = new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z');
  if (isNaN(d)) return '—';
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}
function ago(value) {
  if (!value) return 'never';
  const d = new Date(/Z$|[+-]\d\d:\d\d$/.test(value) ? value : value + 'Z');
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}
function initials(name) {
  return String(name || '?').split(' ').map(p => p[0]).slice(0, 2).join('').toUpperCase();
}
const AVATAR_COLORS = ['#4F46E5', '#6063EE', '#7C3AED', '#0E7490', '#B45309', '#4D7C0F', '#BE185D', '#334155'];
function avatarColor(name) {
  let h = 0;
  for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}
function who(name, sub) {
  return `<div class="who">
    <div class="who-avatar" style="background:${avatarColor(name)}">${esc(initials(name))}</div>
    <div class="who-meta"><span class="who-name">${esc(name)}</span>${sub ? `<span class="who-sub">${esc(sub)}</span>` : ''}</div>
  </div>`;
}
function quotaBar(used, limit) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const cls = pct >= 100 ? 'crit' : pct >= 80 ? 'warn' : '';
  return `<div class="quota">
    <div class="quota-track"><div class="quota-fill ${cls}" style="width:${pct}%"></div></div>
    <span class="quota-num">${used}/${limit}</span>
  </div>`;
}
function runStatus(status, dryRun) {
  const map = { success: 'ok', partial: 'warn', error: 'crit', running: 'primary', stopping: 'warn', stopped: 'warn', skipped: 'idle' };
  return pill(map[status] ?? 'idle', (status || 'unknown') + (dryRun ? ' · dry' : ''));
}
function errText(e) { return e instanceof Error ? e.message : String(e); }

let stopRequestInFlight = false;
async function requestStopJob(expectedRunId, executionId) {
  if (stopRequestInFlight) return;               // one request at a time
  if (!window.confirm('Are you sure you want to stop the currently running job?')) return;
  // Guard every stop control (topbar, floating console, banners): loading
  // state + disable so rapid clicks cannot stack duplicate stop requests.
  stopRequestInFlight = true;
  const buttons = ['#topbarStopBtn', '#floatingStop', '#bannerStopBtn']
    .map(sel => $(sel)).filter(Boolean);
  const prev = buttons.map(b => ({ b, html: b.innerHTML, dis: b.disabled }));
  buttons.forEach(b => { b.disabled = true; b.innerHTML = '<span class="msym">hourglass_top</span><span>Stopping…</span>'; });
  try {
    const res = await apiPost('/api/jobs/stop', {run_id: typeof expectedRunId === 'number' ? expectedRunId : null, execution_id: typeof executionId === 'string' ? executionId : null});
    toast(res.message || 'Stop requested. Terminating worker…', 'warn');
    if (typeof pollNav === 'function') pollNav();
    if (typeof reloadLogs === 'function') reloadLogs();
  } catch (e) {
    toast(errText(e), 'crit');
    prev.forEach(({b, html, dis}) => { b.innerHTML = html; b.disabled = dis; }); // restore on failure
  } finally {
    setTimeout(() => { stopRequestInFlight = false; }, 1500); // brief latch covers double-click windows
  }
}

/* ------------------------------------------------------------------ *
 *  API client
 * ------------------------------------------------------------------ */
async function apiGet(url) {
  const res = await fetch(url, { credentials: 'include', cache: 'no-store', signal: AbortSignal.timeout(30000) });
  if (res.status === 401) { showLogin(); throw new Error('Not authenticated'); }
  if (!res.ok) throw new Error(await detail(res));
  return res.json();
}
async function apiSend(method, url, body) {
  const host = $('#modalHost');
  if (host.dataset.busy === 'true') throw new Error('A request is already in progress');
  const dialog = host.querySelector('.modal');
  const inModal = !!dialog;
  const button = document.activeElement?.closest('button');
  const label = button?.innerHTML;
  const disabled = button?.disabled;
  if (inModal) host.dataset.busy = 'true';
  if (button) { button.disabled = true; button.textContent = 'Working…'; }
  try {
    const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
    const res = await fetch(url, {
      method, credentials: 'include', signal: AbortSignal.timeout(30000),
      headers: (body !== undefined && !isForm) ? { 'Content-Type': 'application/json' } : undefined,
      body: isForm ? body : (body !== undefined ? JSON.stringify(body) : undefined),
    });
    if (res.status === 401) { showLogin(); throw new Error('Not authenticated'); }
    if (!res.ok) throw new Error(await detail(res));
    return res.json();
  } catch (error) {
    if (inModal && dialog.isConnected && host.querySelector('.modal-body')) {
      let alert = host.querySelector('[data-request-error]');
      if (!alert) { alert = document.createElement('p'); alert.dataset.requestError = ''; alert.className = 'form-error'; alert.setAttribute('role', 'alert'); host.querySelector('.modal-body').append(alert); }
      alert.textContent = error.message;
    } else if (method !== 'GET' && error.message !== 'Not authenticated' && error.message !== 'A request is already in progress') {
      // Safety net: mutations failing outside a modal still pop up a toast,
      // even when the caller swallows the error with a silent catch.
      toast(error.message, 'crit');
    }
    throw error;
  } finally {
    if (inModal && dialog.isConnected) host.dataset.busy = 'false';
    if (button?.isConnected) { button.disabled = disabled; button.innerHTML = label; }
  }
}
const apiPost = (url, body) => apiSend('POST', url, body);
const apiPut = (url, body) => apiSend('PUT', url, body);
const apiDelete = (url) => apiSend('DELETE', url);
async function detail(res) {
  try {
    const j = await res.json();
    return Array.isArray(j.detail) ? j.detail.map(e => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`).join('; ') : (j.detail ? String(j.detail) : JSON.stringify(j));
  } catch { return res.statusText || 'Request failed'; }
}

/* ------------------------------------------------------------------ *
 *  Toast + modal
 * ------------------------------------------------------------------ */
let _lastToast = { msg: '', at: 0 };
function toast(message, tone = 'info') {
  // Dedupe: the API-layer safety net and call-site handlers can produce the
  // same message milliseconds apart — show it once.
  const now = Date.now();
  if (message === _lastToast.msg && now - _lastToast.at < 2000) return;
  _lastToast = { msg: message, at: now };
  const icons = { info: 'info', ok: 'check_circle', warn: 'warning', crit: 'error' };
  const el = document.createElement('div');
  el.className = `toast toast-${tone}`;
  el.innerHTML = `<span class="msym">${icons[tone] || 'info'}</span><span style="flex:1;min-width:0">${esc(message)}</span><button class="icon-btn" style="width:24px;height:24px" aria-label="Dismiss"><span class="msym" style="font-size:14px">close</span></button>`;
  el.querySelector('button').onclick = () => el.remove();
  $('#toastHost').appendChild(el);
  setTimeout(() => el.remove(), 6000);
}
/* Throttled background-refresh failure notice (max 1 per 10s). */
let _quietAt = 0;
function quietToast(e) {
  const now = Date.now();
  if (now - _quietAt < 10000) return;
  _quietAt = now;
  toast(`Refresh failed: ${errText(e)}`, 'warn');
}
/* Desktop popup when the tab is in the background. */
function desktopNotify(title, body) {
  try {
    if (!('Notification' in window) || document.visibilityState !== 'hidden') return;
    if (Notification.permission === 'granted') {
      const n = new Notification(title, { body, tag: 'occ-run' });
      n.onclick = () => { window.focus(); n.close(); };
    }
  } catch { /* notifications unavailable — toasts already cover it */ }
}
function requestNotifyPermission() {
  try { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); } catch {}
}
function runSummaryText(stats) {
  if (!stats || typeof stats !== 'object') return '';
  const parts = Object.entries(stats)
    .filter(([, v]) => typeof v === 'number' || typeof v === 'string')
    .slice(0, 3).map(([k, v]) => `${String(k).replace(/_/g, ' ')}: ${v}`);
  return parts.length ? ` (${parts.join(', ')})` : '';
}
/* Render modal dialog with completed run details */
function showRunCompletedDetails(run) {
  if (!run || !run.id) return;
  if (typeof minimizeFloatingConsole === 'function') minimizeFloatingConsole();

  const label = JOB_LABELS[run.job] || run.job || 'Job';
  const status = run.status || 'unknown';
  const dry = !!run.dry_run;

  const toneMap = { success: 'ok', partial: 'warn', error: 'crit', stopped: 'idle', running: 'primary' };
  const tone = toneMap[status] || 'idle';
  const iconMap = { success: 'check_circle', partial: 'warning', error: 'error', stopped: 'stop_circle' };
  const icon = iconMap[status] || 'info';

  const statusTitleMap = {
    success: 'Run Completed Successfully',
    partial: 'Run Completed with Warnings',
    error: 'Run Failed',
    stopped: 'Run Stopped'
  };
  const title = statusTitleMap[status] || `Run ${status}`;

  // Errors section if any
  let errorsHTML = '';
  const errors = run.errors || [];
  if (errors.length > 0) {
    errorsHTML = `
      <div class="run-completed-section run-completed-errors">
        <div class="errors-header"><span class="msym">error</span><strong>Errors &amp; Warnings (${errors.length})</strong></div>
        <pre class="runlog run-errors" tabindex="0">${esc(errors.join('\n'))}</pre>
      </div>`;
  }

  // Batch breakdown if applicable
  let batchHTML = '';
  if (Array.isArray(run.batch_runs) && run.batch_runs.length > 1) {
    batchHTML = `
      <div class="run-completed-section">
        <h3>Batch Steps (${run.batch_runs.length})</h3>
        <div class="run-batch-steps">
          ${run.batch_runs.map(b => `
            <div class="run-batch-step">
              <span class="msym" style="color:var(--${b.status === 'success' ? 'ok' : b.status === 'error' ? 'crit' : 'warn'})">${b.status === 'success' ? 'check_circle' : b.status === 'error' ? 'error' : 'warning'}</span>
              <strong>${esc(JOB_LABELS[b.job] || b.job)}</strong>
              ${runStatus(b.status, b.dry_run)}
              <span class="muted small" style="margin-left:auto">${b.duration_s != null ? fmtDur(b.duration_s) : ''}</span>
            </div>
          `).join('')}
        </div>
      </div>`;
  }

  // Metadata row
  const metaItems = [
    run.target ? `<span>Target: <strong>${esc(run.target)}</strong></span>` : '',
    run.duration_s != null ? `<span>Duration: <strong>${fmtDur(run.duration_s)}</strong></span>` : '',
    `<span>Mode: <strong>${dry ? 'Dry Run (Simulated)' : 'Live Outreach'}</strong></span>`,
    run.started_at ? `<span>Started: <strong>${fmtDT(run.started_at)}</strong></span>` : '',
    run.finished_at ? `<span>Finished: <strong>${fmtDT(run.finished_at)}</strong></span>` : '',
  ].filter(Boolean).join(' · ');

  const bodyHTML = `
    <div class="run-completed-banner outcome-${tone}">
      <span class="msym banner-icon">${icon}</span>
      <div class="banner-text">
        <div class="banner-title">${title}</div>
        <div class="banner-sub">${esc(label)} · Run #${run.id}</div>
      </div>
    </div>

    <div class="run-completed-meta">
      ${metaItems}
    </div>

    ${batchHTML}
    ${errorsHTML}

    ${run.log_text ? `
      <details class="run-completed-log-preview">
        <summary><span class="msym">code</span><span>Console output preview</span></summary>
        <pre class="runlog" tabindex="0">${esc(run.log_text)}</pre>
      </details>
    ` : ''}
  `;

  const footHTML = `
    <button class="btn btn-secondary" id="runCompletedViewLog"><span class="msym">terminal</span>Full Log Details</button>
    <button class="btn btn-primary" id="runCompletedDismiss">Close</button>
  `;

  openModal(`Run #${run.id} Completed — Details`, bodyHTML, footHTML);
  const dialog = $('#modalHost .modal');
  if (dialog) {
    dialog.classList.remove('modal-compact');
    dialog.classList.add('run-completed-dialog');
  }

  const viewLogBtn = $('#runCompletedViewLog');
  if (viewLogBtn) {
    viewLogBtn.onclick = () => openRunLog(run.id);
  }
  const dismissBtn = $('#runCompletedDismiss');
  if (dismissBtn) {
    dismissBtn.onclick = closeModal;
  }
}
window.showRunCompletedDetails = showRunCompletedDetails;

/* Fetch the just-finished run and popup the outcome with completed details. */
async function notifyRunFinished(active) {
  if (!active) return;
  try {
    let run = null;
    if (active.run_id) {
      try {
        run = await apiGet(`/api/runs/${active.run_id}/log`);
      } catch { /* fallback to list query */ }
    }
    if (!run || !run.id) {
      const runs = await apiGet(`/api/runs?job=${encodeURIComponent(active.job || '')}&limit=1`);
      run = Array.isArray(runs) ? runs[0] : runs?.items?.[0];
    }
    if (!run || !run.id || (active.run_id && run.id !== active.run_id)) return;

    window.__completedRunPopupsShown = window.__completedRunPopupsShown || new Set();
    if (window.__completedRunPopupsShown.has(run.id)) return;
    window.__completedRunPopupsShown.add(run.id);

    const label = JOB_LABELS[run.job] || run.job || 'Job';
    if (run.status === 'success') {
      toast(`${label} finished successfully${runSummaryText(run.stats)}`, 'ok');
      desktopNotify(`${label} finished`, `Completed successfully${runSummaryText(run.stats)}`);
    } else if (run.status === 'partial') {
      const n = run.errors?.length || 0;
      toast(`${label} finished with ${n} error${n === 1 ? '' : 's'}${runSummaryText(run.stats)}`, 'warn');
      desktopNotify(`${label} finished with errors`, `${n} error(s) — check Logs & History`);
    } else if (run.status === 'error') {
      const msg = run.errors?.[0] || 'See Logs & History for details';
      toast(`${label} failed: ${String(msg).slice(0, 140)}`, 'crit');
      desktopNotify(`${label} failed`, String(msg).slice(0, 140));
    } else if (run.status === 'stopped') {
      toast(`${label} was stopped`, 'info');
    }

    const activeModal = $('#modalHost .modal');
    const isEditingForm = activeModal && activeModal.querySelector('form, input:not([readonly]), textarea:not([readonly])') && !activeModal.classList.contains('log-dialog') && !activeModal.classList.contains('run-completed-dialog');
    if (isEditingForm) {
      window.__pendingCompletedRun = run;
    } else {
      showRunCompletedDetails(run);
    }
  } catch { /* polling hiccups must not spam */ }
}
window.notifyRunFinished = notifyRunFinished;

let modalCleanup = null;
function openModal(title, bodyHTML, footHTML = '') {
  closeModal();
  const host = $('#modalHost');
  host.dataset.busy = 'false';
  host.innerHTML = `
    <div class="modal-backdrop" data-backdrop>
      <div class="modal modal-compact" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="modal-head"><h2>${esc(title)}</h2><button class="icon-btn" data-close aria-label="Close"><span class="msym">close</span></button></div>
        <div class="modal-body">${bodyHTML}</div>
        ${footHTML ? `<div class="modal-foot">${footHTML}</div>` : ''}
      </div>
    </div>`;
  host.querySelector('[data-backdrop]').addEventListener('click', (e) => { if (e.target.hasAttribute('data-backdrop')) closeModal(); });
  host.querySelector('[data-close]').addEventListener('click', closeModal);
  const previousFocus = document.activeElement;
  const overflow = document.body.style.overflow;
  document.body.style.overflow = 'hidden';
  APP.inert = true;
  const focusable = () => [...host.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]')].filter(el => el.getClientRects().length);
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); closeModal(); }
    if (e.key === 'Tab') {
      const items = focusable(), first = items[0], last = items[items.length - 1];
      if (!first) { e.preventDefault(); return; }
      if (e.shiftKey && (document.activeElement === first || !items.includes(document.activeElement))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !items.includes(document.activeElement))) { e.preventDefault(); first.focus(); }
    }
  };
  document.addEventListener('keydown', onKey);
  modalCleanup = () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = overflow; APP.inert = false; if (previousFocus?.isConnected) previousFocus.focus(); };
  (focusable().find(el => el.tagName !== 'BUTTON') || focusable()[0])?.focus();
  return host;
}
function closeModal() {
  $('#modalHost').innerHTML = '';
  modalCleanup?.();
  modalCleanup = null;
  if (window.__pendingCompletedRun) {
    const pending = window.__pendingCompletedRun;
    window.__pendingCompletedRun = null;
    setTimeout(() => showRunCompletedDetails(pending), 100);
  }
}

/* ------------------------------------------------------------------ *
 *  Auth + shell
 * ------------------------------------------------------------------ */
function showLogin() {
  if (typeof resetJobConsole === 'function') resetJobConsole();
  stopLogsPolling(); closeModal();
  MAIN.classList.remove('is-refreshing');
  APP.hidden = true; LOGIN.hidden = false;
  sessionStorage.setItem('occ-route', location.hash || '#/dashboard');
}
function showApp() {
  LOGIN.hidden = true; APP.hidden = false;
  if (typeof pollFloatingConsole === 'function') pollFloatingConsole();
}

/* Identity: who is logged in (drives the user menu + admin-only UI). */
window.ME = { user: '', name: '', role: '' };
async function loadIdentity() {
  const me = await apiGet('/api/me').catch(() => null);
  window.ME = me || { user: '', name: '', role: '' };
  applyIdentity();
  return window.ME;
}
function applyIdentity() {
  const name = window.ME.name || window.ME.user || '—';
  const roleLabel = window.ME.role === 'admin' ? 'Administrator' : 'Campaign manager';
  $$('#userName').forEach(el => el.textContent = name);
  $$('#userRole').forEach(el => el.textContent = roleLabel);
  const isAdmin = window.ME.role === 'admin';
  $$('[data-nav="salesnav"]').forEach(el => el.hidden = !isAdmin);
  $$('#navUsers').forEach(el => el.style.display = isAdmin ? '' : 'none');
  $$('#menuManageUsers').forEach(el => el.style.display = isAdmin ? '' : 'none');
}

/* User menu popover (footer of the sidebar) */
const userMenu = $('#userMenu');
$('#userMenuBtn').addEventListener('click', (e) => {
  e.stopPropagation();
  userMenu.hidden = !userMenu.hidden;
});
document.addEventListener('click', (e) => {
  if (!userMenu.hidden && !e.target.closest('#userMenu') && !e.target.closest('#userMenuBtn')) userMenu.hidden = true;
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') userMenu.hidden = true; });
$('#menuChangePw').addEventListener('click', () => { userMenu.hidden = true; passwordDialog(); });
$('#menuManageUsers').addEventListener('click', () => { userMenu.hidden = true; location.hash = '#/users'; });

/* Change-password dialog — available to every logged-in user. */
function passwordDialog() {
  openModal('Change password', `
    <form id="pwForm" class="grid" style="gap:12px">
      <label class="field"><span>Current password</span>
        <input class="input" name="current" type="password" autocomplete="current-password" required></label>
      <label class="field"><span>New password <small class="muted" style="font-weight:400">(min 8 characters)</small></span>
        <input class="input" name="next" type="password" autocomplete="new-password" minlength="8" required></label>
      <label class="field"><span>Confirm new password</span>
        <input class="input" name="confirm" type="password" autocomplete="new-password" minlength="8" required></label>
      <p class="form-error" id="pwErr" role="alert" hidden></p>
      <p class="muted small" style="margin:0">Changing your password signs out your other sessions on all devices.</p>
    </form>`,
    `<button class="btn btn-secondary" data-close2>Cancel</button><button class="btn btn-primary" id="pwSave"><span class="msym">lock_reset</span>Update password</button>`);
  $('#modalHost [data-close2]').onclick = closeModal;
  $('#pwSave').onclick = async () => {
    const f = $('#pwForm'), err = $('#pwErr');
    err.hidden = true;
    if (f.next.value !== f.confirm.value) { err.textContent = 'New passwords do not match.'; err.hidden = false; return; }
    const b = $('#pwSave'); b.disabled = true;
    try {
      await apiPost('/api/me/password', { current_password: f.current.value, new_password: f.next.value });
      closeModal();
      toast('Password updated', 'ok');
    } catch (ex) {
      err.textContent = errText(ex); err.hidden = false; b.disabled = false;
    }
  };
  setTimeout(() => $('#pwForm [name=current]')?.focus(), 30);
}

$('#loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = $('#loginError');
  err.hidden = true;
  try {
    await apiPost('/api/login', { username: $('#loginUser').value.trim(), password: $('#loginPass').value });
    await loadIdentity();
    showApp();
    const saved = sessionStorage.getItem('occ-route');
    const destination = saved && saved !== '#/login' ? saved : '#/dashboard';
    if (location.hash === destination) route(); else location.hash = destination;
  } catch (ex) {
    err.textContent = ex.message.includes('Incorrect') ? 'Incorrect username or password.'
      : ex.message.includes('deactivated') ? ex.message
      : 'Login failed — is the server running?';
    err.hidden = false;
  }
});
$('#logoutBtn').addEventListener('click', async () => {
  try { await apiPost('/api/logout'); } catch {}
  showLogin();
  $('#loginPass').value = '';
});

/* Sidebar (mobile) */
$('#sidebarToggle').addEventListener('click', () => {
  const sb = $('#sidebar');
  const open = sb.classList.toggle('open');
  let scrim = $('.scrim');
  if (open) {
    if (!scrim) { scrim = document.createElement('div'); scrim.className = 'scrim'; document.body.appendChild(scrim); scrim.onclick = () => $('#sidebarToggle').click(); }
  } else if (scrim) scrim.remove();
});

/* Router */
const ROUTES = {
  dashboard: viewDashboard,
  accounts: (...args) => viewAccounts(...args),
  campaigns: (...args) => viewCampaigns(...args),
  campaign: (...args) => viewCampaignDetail(...args),
  leads: (...args) => viewLeads(...args),
  threads: (...args) => viewThreads(...args),
  workers: (...args) => viewWorkers(...args),
  jobs: (...args) => viewJobs(...args),
  salesnav: (...args) => viewSalesNav(...args),
  logs: () => { location.hash = '#/dashboard?history=1'; },
  activity: (...args) => viewSettings('activity', ...args),
  users: (...args) => viewUsers(...args),
  settings: (...args) => viewSettings(...args),
};
let currentRoute = '';

async function route() {
  if (APP.hidden) return;
  const hash = location.hash || '#/dashboard';
  const [name, arg] = hash.replace(/^#\//, '').split('?')[0].split('/');
  const view = ROUTES[name] ? name : 'dashboard';
  if (currentRoute !== view) currentRoute = view;
  $$('.nav-item').forEach(a => a.classList.toggle('on', a.dataset.nav === (view === 'activity' ? 'settings' : view)));
  stopLogsPolling(); closeModal();
  MAIN.classList.remove('is-refreshing');
  $$('.nav-item').forEach(a => a.setAttribute('aria-current', (a.dataset.nav === view || (view === 'activity' && a.dataset.nav === 'settings')) ? 'page' : 'false'));
  /* Invalidate in-flight list requests from the previous page so a slow
     response can never land after the new page renders (stale overwrite). */
  if (typeof __leadsReq === 'number') __leadsReq++;
  if (typeof __threadsReq === 'number') __threadsReq++;
  MAIN.innerHTML = `<div class="loading"><span class="spinner"></span>Loading…</div>`;
  try {
    await ROUTES[view](arg);
  } catch (e) {
    if (currentRoute !== view) return;
    MAIN.innerHTML = `<div class="page"><div class="banner banner-crit"><div><div class="banner-title">Couldn't load this page</div><p>${esc(errText(e))}</p></div><a class="btn btn-secondary" href="#/dashboard">Go to dashboard</a></div></div>`;
  }
  const openSb = $('#sidebar'); openSb.classList.remove('open'); $('.scrim')?.remove();
}
window.addEventListener('hashchange', route);

/* Live badge polling (nav badges + notification dot) */
let pollTimer = null;
let lastObservedRun = null;
function showStartedJob(result) {
  closeModal();
  if (result?.execution_id) {
    window.__activeExecMap = window.__activeExecMap || new Map();
    window.__activeExecMap.set(result.execution_id, {
      execution_id: result.execution_id,
      job: result.job || result.job_key || '',
      started_at: new Date().toISOString()
    });
  }
  if (typeof selectConsoleExecution === 'function') selectConsoleExecution(result?.execution_id);
  location.hash = '#/dashboard';
  openFloatingConsole();
  requestNotifyPermission();
  pollNav();
}
window.addEventListener('DOMContentLoaded', async () => {
  try { await apiGet('/api/me'); await loadIdentity(); showApp(); await route(); }
  catch { showLogin(); }
  startPolling();
});
function patchLiveRuns(accountRuns) {
  if (!accountRuns) return;
  $$('[data-live-runs]').forEach(el => {
    const v = accountRuns[el.dataset.liveRuns];
    if (v != null && String(v) !== el.textContent) {
      el.textContent = v;
      el.classList?.remove('bump');
      void el.offsetWidth;            // restart the animation
      el.classList?.add('bump');
    }
  });
}

async function pollNav() {
  if (APP.hidden) return;
  try {
    const j = await apiGet('/api/jobs');
    const nav = j.nav || {};
    setBadge('#navAccounts', nav.accounts_active ?? '', '');
    setBadge('#navCampaigns', nav.campaigns_active ? `${nav.campaigns_active} active` : '', '');
    setBadge('#navUnread', nav.unread_replies > 0 ? nav.unread_replies : '', 'hot');
    setBadge('#navScheduler', nav.scheduler_healthy ? 'Active' : 'Off', nav.scheduler_healthy ? 'ok' : 'warn');
    setBadge('#navJobsHealth', '', '');
    const running = j.live && j.live.running;
    const runIdentity = running ? `${j.live.started_at || ''}:${j.live.job || ''}` : null;
    const isNewRun = running && runIdentity !== lastObservedRun;
    if (!running || !$('#modalHost .modal') || currentRoute === 'dashboard') lastObservedRun = runIdentity;
    if (isNewRun && currentRoute !== 'dashboard' && !$('#modalHost .modal')) {
      // Background jobs never change the user's current page.
    }
    /* Run lifecycle → popup notifications: remember the active run and popup
       its outcome the moment it disappears from the live slot. */
    const prevActive = window.__activeRun || null;
    if (running) {
      window.__activeRun = { job: j.live.job, started_at: j.live.started_at, run_id: j.live.run_id, execution_id: j.live.execution_id };
    } else {
      window.__activeRun = null;
      if (prevActive && prevActive.job && prevActive.started_at) {
        if (!prevActive.run_id && j.live?.run_id) prevActive.run_id = j.live.run_id;
        notifyRunFinished(prevActive);
      }
    }
    const currentRunning = Array.isArray(j.running) ? j.running : [];
    window.__activeExecMap = window.__activeExecMap || new Map();
    for (const [execId, prev] of window.__activeExecMap.entries()) {
      if (!currentRunning.some(r => r.execution_id === execId)) {
        window.__activeExecMap.delete(execId);
        notifyRunFinished(prev);
      }
    }
    for (const r of currentRunning) {
      if (r.execution_id) {
        window.__activeExecMap.set(r.execution_id, {
          execution_id: r.execution_id,
          run_id: r.run_id,
          job: r.job,
          started_at: r.started_at,
          target: r.target
        });
      }
    }
    const anyActive = running || currentRunning.length > 0;
    if (window.__pollingIsFast !== anyActive) {
      window.__pollingIsFast = anyActive;
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(pollNav, anyActive ? 3000 : 10000);
    }
    setBadge('#navWorkers', running ? `${(j.running || []).length || 1} running` : '', running ? 'ok' : '');
    patchLiveRuns(j.live && j.live.account_runs);
    const chip = $('#liveChip');
    chip.innerHTML = running
      ? `<span class="dot dot-ok pulse"></span><span>Running: ${esc(JOB_LABELS[j.live.job] || j.live.job || '')}</span>`
      : `<span class="dot ${nav.scheduler_healthy ? 'dot-ok' : 'dot-warn'}"></span><span>${nav.scheduler_healthy ? 'Scheduler live' : 'Scheduler off'}</span>`;
    const stopBtn = $('#topbarStopBtn');
    if (stopBtn) {
      stopBtn.style.display = running ? 'inline-flex' : 'none';
      stopBtn.onclick = () => (j.running || []).length > 1 ? openFloatingConsole() : requestStopJob(j.live.run_id, j.live.execution_id);
      if (j.live?.status === 'stopping') {
        stopBtn.disabled = true;
        stopBtn.innerHTML = '<span class="msym">hourglass_top</span><span>Stopping…</span>';
      } else {
        stopBtn.disabled = false;
        stopBtn.innerHTML = (j.running || []).length > 1 ? '<span class="msym">terminal</span><span>View running jobs</span>' : '<span class="msym">stop</span><span>Stop Job</span>';
      }
    }
    const dot = $('#notifDot');
    dot.hidden = !(nav.unread_replies > 0 || running || !nav.scheduler_healthy);
    window.__navInfo = { nav, live: j.live };
    if (currentRoute === 'accounts') await refreshVisibleAccountHealth();
    if (currentRoute === 'workers' && !$('#modalHost .modal') && window.__workersSignature !== workerStateSignature(j)) await viewWorkers();
  } catch { /* logged out */ }
}
function setBadge(sel, text, cls) {
  const el = $(sel);
  if (!el) return;
  el.textContent = text || '';
  el.className = 'nav-badge' + (cls ? ` ${cls}` : '');
  el.style.display = text ? '' : 'none';
}
function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollNav();
  pollTimer = setInterval(pollNav, 10000);
}

/* Notifications popover */
$('#notifBtn').addEventListener('click', () => {
  const pop = $('#notifPop');
  if (!pop.hidden) { pop.hidden = true; return; }
  const info = window.__navInfo || { nav: {} };
  const items = [];
  if ((info.nav.unread_replies || 0) > 0) items.push(['mark_email_unread', `${info.nav.unread_replies} new replies (7d)`, '#/threads', 'text-ok-dot']);
  if (info.live && info.live.status === 'running') items.push(['play_circle', `Job running: ${JOB_LABELS[info.live.job] || info.live.job}`, '#/workers', '']);
  if (info.nav.scheduler_healthy === false) items.push(['warning', 'Scheduler is off', '#/jobs', '']);
  pop.innerHTML = `<div class="notif-head">Notifications</div>` + (items.length
    ? items.map(([icon, text, to]) => `<button class="notif-item" data-to="${to}"><span class="msym">${icon}</span><span>${esc(text)}</span></button>`).join('')
    : `<div class="notif-item" style="cursor:default">All quiet — no alerts.</div>`);
  pop.hidden = false;
  $$('.notif-item[data-to]', pop).forEach(b => b.onclick = () => { pop.hidden = true; location.hash = b.dataset.to; });
});

/* Global search */
const searchInput = $('#globalSearch');
const searchPop = $('#searchPop');
let searchTimer = null;
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (q.length < 2) { searchPop.hidden = true; return; }
  searchTimer = setTimeout(async () => {
    try {
      const r = await apiGet(`/api/search?q=${encodeURIComponent(q)}`);
      const groups = [
        ['Leads', 'person', r.leads.map(l => ({ to: `#/leads?q=${encodeURIComponent(l.full_name)}`, title: l.full_name, sub: l.company }))],
        ['Campaigns', 'rocket_launch', r.campaigns.map(c => ({ to: `#/campaign/${c.id}`, title: c.name, sub: c.campaign_key }))],
        ['Accounts', 'manage_accounts', r.accounts.map(a => ({ to: '#/accounts', title: a.name, sub: a.status }))],
      ].filter(([, , items]) => items.length);
      searchPop.innerHTML = groups.length
        ? groups.map(([label, icon, items]) => `<div class="search-group">${label}</div>` + items.map(it => `<button class="search-item" data-to="${it.to}"><span class="msym">${icon}</span><span>${esc(it.title)}</span><span class="muted small">${esc(it.sub || '')}</span></button>`).join('')).join('')
        : `<div class="search-item" style="cursor:default">No matches for “${esc(q)}”</div>`;
      searchPop.hidden = false;
      $$('.search-item[data-to]', searchPop).forEach(b => b.onclick = () => { searchPop.hidden = true; searchInput.value = ''; location.hash = b.dataset.to; });
    } catch { /* ignore */ }
  }, 250);
});
document.addEventListener('click', (e) => {
  if (!$('#globalSearchWrap').contains(e.target)) searchPop.hidden = true;
  if (!$('#notifBtn').contains(e.target) && !$('#notifPop').contains(e.target)) $('#notifPop').hidden = true;
});

/* Global live polling belongs to workspace.js. */

function activityFeedHTML(events) {
  if (!events.length) return '<div class="feed-empty"><span class="msym">forum</span><h3>No outreach activity yet</h3><p>Invites, InMails, follow-ups and replies will appear here as workers process leads.</p><a href="#/workers">Open workers</a></div>';
  return events.map(e => {
    const reply = e.kind === 'reply', error = e.kind === 'error';
    const icon = reply ? 'forum' : error ? 'warning' : e.job === 'send_followups' ? 'cached' : 'send';
    return `<article class="activity-item ${reply ? 'activity-reply' : error ? 'activity-error' : ''}">
      <span class="activity-icon"><span class="msym">${icon}</span></span>
      <div class="activity-content">
        <div class="activity-title">
          <div class="activity-name-wrap">
            <strong>${reply ? 'Reply from ' : ''}${esc(e.lead_name || 'Lead')}</strong>
            ${e.company ? `<span class="activity-company">· ${esc(e.company)}</span>` : ''}
          </div>
          <time title="${fmtDT(e.created_at)}">${ago(e.created_at)}</time>
        </div>
        <div class="activity-sub-line">
          <p class="activity-detail">${esc(e.detail)}</p>
          <div class="activity-meta">
            ${e.account ? `<span class="tag">via ${esc(e.account)}</span>` : ''}
            ${e.campaign_id ? `<a href="#/campaign/${e.campaign_id}">${esc(e.campaign)}</a>` : '<span>Unassigned lead</span>'}
            ${reply ? '<a class="activity-inbox" href="#/threads">Open inbox <span class="msym">arrow_forward</span></a>' : ''}
          </div>
        </div>
      </div>
    </article>`;
  }).join('');
}
function workerFeedHTML(runs) {
  return runs.length ? runs.map(r => `<button class="worker-feed-row" data-log="${r.id}"><span class="worker-feed-icon"><span class="msym">${r.status === 'running' ? 'play_arrow' : 'receipt_long'}</span></span><span class="worker-feed-main"><strong>${esc(JOB_LABELS[r.job] || r.job)}</strong><span>Run #${r.id} · ${ago(r.started_at)}${r.duration_s != null ? ' · ' + fmtDur(r.duration_s) : ''}</span></span>${runStatus(r.status, r.dry_run)}<span class="msym">chevron_right</span></button>`).join('') : '<p class="feed-empty">No worker runs recorded yet.</p>';
}
async function refreshDashboardFeed() {
  const feed = $('#activityFeed'), runs = $('#workerFeed');
  if (!feed || APP.hidden) return;
  try {
    const range = dashRange;
    const [events, recent, report] = await Promise.all([apiGet('/api/dashboard/activity'), apiGet('/api/runs?limit=10'), apiGet(`/api/dashboard/campaign-stats?days=${range}&active_only=true`)]);
    if (range !== dashRange) return;
    if (!feed.isConnected) return;
    feed.innerHTML = activityFeedHTML(events); runs.innerHTML = workerFeedHTML(recent);
    const stats = $('#campaignStats');
    if (stats) { stats.innerHTML = campaignStatsHTML(report); bindCampaignStats(); }
    if ($('#dashboardTotals')) $('#dashboardTotals').innerHTML = dashboardTotalsHTML(report);
    $('#activityCount').textContent = `Latest ${events.length} outreach events`;
    $$('[data-log]', runs).forEach(b => b.onclick = () => openRunLog(Number(b.dataset.log)));
  } catch { /* The console connection indicator handles connectivity errors. */ }
}

/* ------------------------------------------------------------------ *
 *  VIEW: Dashboard (with Today / 7 days / 30 days range filter)
 * ------------------------------------------------------------------ */
let dashRange = 1; // Calendar-day filters use UTC.

async function viewDashboard() {
  const [report, accounts, activity, jobsData, campaigns, runs] = await Promise.all([
    apiGet(`/api/dashboard/campaign-stats?days=${dashRange}&active_only=true`),
    apiGet('/api/accounts'), apiGet('/api/dashboard/activity'),
    apiGet('/api/jobs'), apiGet('/api/campaigns'), apiGet('/api/runs?limit=10'),
  ]);
  if (APP.hidden || currentRoute !== 'dashboard') return;
  const label = dashRange === 0 ? 'All time' : dashRange === 1 ? 'Today' : `Last ${dashRange} days`;
  const dashJobs = jobsData.jobs.filter(x => WORKERS.includes(x.key));
  const accountsForScope = accounts;

  MAIN.innerHTML = `<div class="page dashboard-page">
    <div class="page-head">
      <div>
        <h1>Command Dashboard</h1>
        <p class="page-sub">A clear view of your active campaigns and outreach</p>
      </div>
      <div class="page-actions">
        <div class="seg" role="group" aria-label="Date range">
          ${[1, 7, 30].map(d => `<button class="${dashRange === d ? 'on' : ''}" data-range="${d}">${d === 0 ? 'All time' : d === 1 ? 'Today' : `${d} days`}</button>`).join('')}
        </div>
        <button class="btn btn-secondary" id="dashRefresh"><span class="msym">refresh</span>Refresh</button>
      </div>
    </div>

    <section class="dashboard-workers" aria-label="Workers">
      <div class="section-title" style="margin-bottom:6px"><h2 style="margin:0">Workers</h2><a href="#/workers">Open full view <span class="msym">arrow_forward</span></a></div>
      <div class="grid grid-3" style="margin-bottom:16px">
        ${dashJobs.map(job => {
          const last = job.last_run;
          const jobRunning = jobsData.live && jobsData.live.status === 'running';
          const isRun = job.running_now || (jobRunning && jobsData.live.job === job.key);
          return `<div class="card card-pad worker-card dash-worker-card">
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
              <h2 style="margin:0;font-size:15px">${esc(JOB_LABELS[job.key])}</h2>
              ${isRun ? pill('primary', 'running', false) : last && last.status === 'error' ? pill('crit', 'error', false) : pill('idle', 'worker', false)}
            </div>
            <p class="desc">${esc(job.description)}</p>
            <div class="worker-meta" style="margin:4px 0 8px">
              <span style="display:flex;gap:6px;align-items:center">Last run: ${last ? `${runStatus(last.status, last.dry_run)} ${fmtDT(last.started_at)}` : 'never run'}</span>
              ${job.schedule && job.schedule.length ? `<span>Schedule: ${esc(job.schedule.join(' · '))}</span>` : '<span>Schedule: manual</span>'}
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button class="btn btn-primary btn-sm" data-run="${job.key}" ${jobRunning ? 'disabled' : ''}><span class="msym">play_arrow</span>Run now</button>
              ${last ? `<button class="btn btn-secondary btn-sm" data-log="${last.id}"><span class="msym">receipt_long</span>Last log</button>` : ''}
            </div>
          </div>`;
        }).join('')}
      </div>
    </section>

    <div id="dashboardTotals">${dashboardTotalsHTML(report)}</div>
    <section class="campaign-performance" aria-label="Campaign and account performance">
      <div class="section-title">
        <div>
          <div style="display:flex;align-items:center;gap:8px">
            <h2 style="margin:0">Active campaigns</h2>
            <span class="active-badge-pill"><span class="dot-pulse"></span>Live</span>
          </div>
          <p class="card-sub" style="margin-top:2px">Select a campaign to see each account’s performance · ${label.toLowerCase()} (UTC)</p>
        </div>
        <button class="btn btn-secondary btn-sm run-history-btn" onclick="openDashboardHistory()"><span class="msym">history</span>Run history</button>
      </div>
      <div id="campaignStats" tabindex="0" role="region" aria-label="Scrollable active campaigns">${campaignStatsHTML(report)}</div>
      <p class="muted small">Confirmed app sends only. Messages include follow-ups and after-acceptance messages.</p>
    </section>

    <div class="dashboard-work" id="dashboardWork">
      <section class="card activity-card"><div class="feed-heading"><span class="activity-icon"><span class="msym">cached</span></span><div><h2>Recent activity</h2><p class="card-sub">Outreach events across your accounts</p></div><span class="pill pill-ok"><span class="dot"></span>Live feed</span></div><div id="activityFeed">${activityFeedHTML(activity)}</div><div class="feed-footer"><span id="activityCount">Latest ${activity.length} outreach events</span><a href="#/leads">View pipeline<span class="msym">arrow_forward</span></a></div></section>
      <div class="dashboard-console-col"><section class="card worker-feed"><div class="feed-heading"><div><h2>Worker runs</h2><p class="card-sub">Latest execution results</p></div><button class="btn btn-ghost btn-sm" onclick="openDashboardHistory()">View history</button></div><div id="workerFeed">${workerFeedHTML(runs)}</div></section></div>
    </div>
  </div>`;

  $$('[data-range]', MAIN).forEach(b => b.onclick = () => { dashRange = Number(b.dataset.range); viewDashboard().catch(e => toast(errText(e), 'crit')); });
  bindCampaignStats();
  $('#dashRefresh').onclick = () => viewDashboard().catch(e => toast(errText(e), 'crit'));
  $$('[data-run]', MAIN).forEach(b => b.onclick = () => runWorkerDialog(b.dataset.run, campaigns, accountsForScope));
  $$('[data-account-details]', MAIN).forEach(b => b.onclick = () => accountDetails(accounts.find(a => a.id === Number(b.dataset.accountDetails))));
  $$('[data-log]', MAIN).forEach(b => b.onclick = () => openRunLog(Number(b.dataset.log)));
  if (location.hash.includes('history=1')) {
    history.replaceState(null, '', '#/dashboard'); openDashboardHistory();
  }
  // The global console owns live polling.
}

function statCard(label, icon, value, limit, extra = {}) {
  const pct = limit ? Math.min(100, Math.round((value / limit) * 100)) : 0;
  const tone = pct >= 100 ? 'crit' : pct >= 80 ? 'warn' : 'primary';
  return `<div class="stat-card stat-card-v2 ${extra.cls || ''}">
    <div class="stat-top">
      <span class="stat-label">${esc(label)}</span>
      <span class="stat-ic stat-ic-${tone}"><span class="msym">${icon}</span></span>
    </div>
    <div class="stat-value">${Number(value).toLocaleString()}${limit !== undefined ? ` <span class="of">/ ${Number(limit).toLocaleString()}</span>` : ''}</div>
    ${limit !== undefined ? `<div class="quota-track" style="margin-top:8px"><div class="quota-fill ${tone === 'crit' ? 'crit' : tone === 'warn' ? 'warn' : ''}" style="width:${pct}%"></div></div>` : ''}
    ${extra.foot ? `<div class="stat-foot">${extra.foot}</div>` : ''}
  </div>`;
}

function runTable(runs, compact = false) {
  return `<table class="data"><thead><tr>
    <th>Run</th><th>Worker</th><th>Target</th><th>Started</th><th style="text-align:right">Duration</th><th style="text-align:right">Status</th>${compact ? '' : '<th style="text-align:right">Log</th>'}
  </tr></thead><tbody>
    ${runs.map(r => `<tr>
      <td class="mono">#${r.id}</td>
      <td><span class="cell-main">${esc(JOB_LABELS[r.job] || r.job)}</span>${r.schedule_id ? '<div class="cell-sub">scheduled</div>' : ''}</td>
      <td class="small">${esc(r.target || '—')}</td>
      <td class="date-cell">${fmtDT(r.started_at)}</td>
      <td class="cell-num">${r.duration_s != null ? fmtDur(r.duration_s) : '—'}</td>
      <td style="text-align:right">${runStatus(r.status, r.dry_run)}</td>
      ${compact ? '' : `<td style="text-align:right"><button class="btn btn-secondary btn-sm" data-log="${r.id}"><span class="msym">receipt_long</span>Log</button></td>`}
    </tr>`).join('')}
  </tbody></table>`;
}
function fmtDur(s) { return s >= 90 ? `${Math.round(s / 60)}m ${Math.round(s % 60)}s` : `${(s ?? 0).toFixed(0)}s`; }

function runResultText(value) {
  if (value == null) return '—';
  if (Array.isArray(value)) return value.map(runResultText).join(' · ');
  if (typeof value === 'object') return Object.entries(value).map(([key, count]) => `${key.replaceAll('_', ' ')}: ${runResultText(count)}`).join(' · ');
  return typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value);
}

async function openRunLog(runId) {
  if (typeof minimizeFloatingConsole === 'function') minimizeFloatingConsole();
  openModal(`Run #${runId} — details`, `<div class="log-detail-meta" id="runMeta">Loading run…</div><p class="form-error" id="runLoadError" role="status" hidden></p><div id="runErrors"></div><div id="runStats" class="run-stats"></div><h3>Console output</h3><pre id="runOutput" class="runlog" tabindex="0"></pre>`, `<button class="btn btn-danger" id="runStopModalBtn" style="display:none"><span class="msym">stop</span>Stop Run</button><button class="btn btn-secondary" id="runRefresh">Refresh</button><button class="btn btn-primary" id="runClose">Close</button>`);
  const dialog = $('#modalHost .modal'); dialog.classList.remove('modal-compact'); dialog.classList.add('log-dialog');
  let timer, full = null, busy = false;
  const cleanup = modalCleanup;
  modalCleanup = () => { clearTimeout(timer); cleanup?.(); };
  async function refresh() {
    if (busy || !dialog.isConnected) return;
    clearTimeout(timer); busy = true;
    let retry = false;
    try {
      full = await apiGet(`/api/runs/${runId}/log`);
      if (!dialog.isConnected) return;
      $('#runLoadError').hidden = true;
      $('#runMeta').innerHTML = `${runStatus(full.status, full.dry_run)}<strong>${esc(JOB_LABELS[full.job] || full.job || '')}</strong><span>${esc(full.target || '')}</span>${full.duration_s != null ? `<span>${fmtDur(full.duration_s)}</span>` : ''}`;
      const stopModalBtn = $('#runStopModalBtn');
      if (stopModalBtn) stopModalBtn.style.display = full.status === 'running' ? '' : 'none';
      $('#runOutput').textContent = full.log_text || 'No console output recorded.';
      $('#runErrors').innerHTML = (full.errors || []).length ? `<h3>Errors</h3><pre class="runlog run-errors">${esc(full.errors.join('\n'))}</pre>` : '';
      $('#runStats').innerHTML = Object.entries(full.stats || {}).map(([k,v]) => `<div><span>${esc(k.replaceAll('_', ' '))}</span><strong>${esc(runResultText(v))}</strong></div>`).join('');
    } catch(e) {
      retry = true;
      if (dialog.isConnected) { $('#runLoadError').textContent = `Could not refresh log: ${errText(e)}. Retrying…`; $('#runLoadError').hidden = false; }
    } finally {
      busy = false;
      if (dialog.isConnected && !APP.hidden && (retry || ['running','stopping'].includes(full?.status))) timer = setTimeout(refresh, 2000);
    }
  }
  const stopModalBtn = $('#runStopModalBtn');
  if (stopModalBtn) {
    stopModalBtn.onclick = async () => {
      await requestStopJob(runId);
      refresh();
    };
  }
  $('#runRefresh').onclick = refresh;
  $('#runClose').onclick = closeModal;
  refresh();
}
