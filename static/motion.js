/* ============================================================
   Motion & theme utilities for the redesign layer.
   Dependency-free; every helper no-ops gracefully under
   prefers-reduced-motion. Loaded BEFORE app.js.
   Hooks run from a MutationObserver on #main, so existing view
   code needs zero changes.
   ============================================================ */
(() => {
  'use strict';

  const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------------- Theme (dark default, light optional) ----------------
     UI preference only — deliberately localStorage, never app data. */
  const THEME_KEY = 'occ-theme';
  const applyTheme = (t) => {
    if (t === 'light') document.documentElement.dataset.theme = 'light';
    else delete document.documentElement.dataset.theme;   // dark = default
    const btn = document.getElementById('themeToggle');
    if (btn) {
      btn.setAttribute('aria-label', t === 'light' ? 'Switch to dark theme' : 'Switch to light theme');
      const ic = btn.querySelector('.msym');
      if (ic) ic.textContent = t === 'light' ? 'dark_mode' : 'light_mode';
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = t === 'light' ? '#F5F6FB' : '#0B0E15';
  };
  // Restore collapse state as early as possible to avoid a width jump.
  try { if (localStorage.getItem('occ-sb') === '1' && matchMedia('(min-width:1025px)').matches) document.body.classList.add('sb-collapsed'); } catch { /* ignore */ }

  let stored = null;
  try { stored = localStorage.getItem(THEME_KEY); } catch { /* storage unavailable */ }
  applyTheme(stored === 'light' ? 'light' : 'dark');
  window.__toggleTheme = () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem(THEME_KEY, next); } catch { /* ignore */ }
    applyTheme(next);
  };
  document.addEventListener('click', e => {
    if (e.target.closest && e.target.closest('#themeToggle')) window.__toggleTheme();
    const col = e.target.closest && e.target.closest('#sbCollapse');
    if (col) {
      const collapsed = document.body.classList.toggle('sb-collapsed');
      col.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
      col.title = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
      try { localStorage.setItem('occ-sb', collapsed ? '1' : '0'); } catch { /* ignore */ }
    }
  });
  try { if (localStorage.getItem('occ-sb') === '1') document.body.classList.add('sb-collapsed'); } catch { /* ignore */ }

  /* ---------------- Count-up for numeric stat values ----------------
     Animates ONLY the leading number text node of a stat element,
     preserving any nested markup (e.g. the "/ limit" span). */
  const seen = new WeakMap();
  const NUM_RE = /^\s*([\d,]+(?:\.\d+)?)\s*$/;
  function animateCount(el) {
    // First non-empty text node carries the number; the rest of the
    // markup (spans like "/ 500") is left untouched.
    const tn = [...el.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
    if (!tn) return;
    const m = tn.textContent.match(NUM_RE);
    if (!m) return;
    const target = parseFloat(m[1].replace(/,/g, ''));
    if (!isFinite(target)) return;
    const prev = seen.get(el) ?? 0;
    seen.set(el, target);
    const fmt = v => Math.round(v).toLocaleString();
    if (reduceMotion() || target === prev) { tn.textContent = fmt(target); return; }
    const dur = 700, start = performance.now();
    const ease = t => 1 - Math.pow(1 - t, 3);   // easeOutCubic
    (function frame(now) {
      const p = Math.min(1, (now - start) / dur);
      tn.textContent = fmt(prev + (target - prev) * ease(p));
      if (p < 1) requestAnimationFrame(frame);
    })(start);
  }
  function runCountUps(root) {
    if (!root || root.nodeType !== 1) return;
    const nodes = root.matches('.stat-value, .hero-num, [data-count]')
      ? [root, ...root.querySelectorAll('.stat-value, .hero-num, [data-count]')]
      : [...root.querySelectorAll('.stat-value, .hero-num, [data-count]')];
    nodes.forEach(animateCount);
  }
  window.__runCountUps = runCountUps;

  /* ---------------- Staggered row entrance (visual layer only) -------- */
  function staggerRows(root) {
    if (!root || root.nodeType !== 1) return;
    root.querySelectorAll('table.data tbody').forEach(tb => {
      if (tb.dataset.staggered) return;
      tb.dataset.staggered = '1';
      [...tb.rows].slice(0, 12).forEach((tr, i) => {
        if (tr.classList.contains('empty-row')) return;
        tr.style.setProperty('--i', i);
        tr.classList.add('row-in');
      });
    });
  }
  window.__staggerRows = staggerRows;

  /* ---------------- One observer drives every view hook --------------- */
  const main = document.getElementById('main');
  if (main && !reduceMotion()) {
    new MutationObserver(muts => {
      for (const m of muts) for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        if (n.matches && n.matches('.page, .card, .banner')) {
          runCountUps(n);
          staggerRows(n);
        } else if (n.matches && n.matches('table')) {
          staggerRows(n.parentElement || n);
        }
      }
    }).observe(main, { childList: true, subtree: true });
  }

  /* ---------------- Shared modal close animation ----------------
     Wraps the app's closeModal AFTER app.js evaluates, so every
     modal exits with the same scale+fade. openModal's internal
     closeModal() call is routed through the wrapper too — a pending
     animated close is cancelled synchronously there so it can never
     wipe the modal that is about to open. */
  let pendingClose = null;
  let opening = false;   // openModal's internal close-before-build must be instant
  function wireModalClose() {
    if (typeof closeModal !== 'function' || closeModal.__animated) return;
    const orig = closeModal;
    const wrapped = function () {
      const bd = document.querySelector('#modalHost .modal-backdrop');
      if (!bd || bd.classList.contains('closing') || opening || reduceMotion()) return orig.apply(this, arguments);
      bd.classList.add('closing');
      const dlg = bd.querySelector('[role="dialog"]');
      if (dlg) { dlg.removeAttribute('role'); dlg.setAttribute('aria-hidden', 'true'); }
      pendingClose = setTimeout(() => { pendingClose = null; orig(); }, 150);
    };
    wrapped.__animated = true;
    window.closeModal = wrapped;
    const origOpen = openModal;
    window.openModal = function (...args) {
      if (pendingClose) { clearTimeout(pendingClose); pendingClose = null; orig(); } // finish any exit now
      opening = true;
      try {
        const host = origOpen.apply(this, args);  // its internal closeModal() bypasses the animation
        try { runCountUps(host || document.getElementById('modalHost')); } catch { /* decorative */ }
        return host;
      } finally { opening = false; }
    };
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(wireModalClose, 0));
  } else {
    setTimeout(wireModalClose, 0);
  }
})();