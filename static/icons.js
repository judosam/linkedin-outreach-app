/* Decorative local Lucide icons for existing static and dynamically rendered views. */
(() => {
  const upgrade = root => {
    const nodes = [];
    if (root.nodeType !== 1) return;
    if (root.matches('.msym')) nodes.push(root);
    nodes.push(...root.querySelectorAll('.msym'));
    for (const el of nodes) {
      if (el.querySelector('svg')) continue;
      const name = el.textContent.trim();
      if (!/^[a-z_]+$/.test(name)) continue;
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
      const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
      use.setAttribute('href', '/static/icons.svg#' + name); svg.append(use);
      const button = el.closest('button');
      if (button && !button.getAttribute('aria-label') && button.textContent.trim() === name) button.setAttribute('aria-label', button.title || name.replaceAll('_', ' '));
      el.setAttribute('aria-hidden', 'true'); el.replaceChildren(svg);
    }
  };
  upgrade(document.body);
  new MutationObserver(changes => {
    for (const change of changes) for (const node of change.addedNodes) upgrade(node);
  }).observe(document.body, { childList: true, subtree: true });
  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('sidebarToggle');
  const mobile = matchMedia('(max-width:1024px)');
  const syncDrawer = () => {
    const open = sidebar.classList.contains('open');
    sidebar.inert = mobile.matches && !open;
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-controls', 'sidebar');
  };
  mobile.addEventListener('change', syncDrawer);
  new MutationObserver(syncDrawer).observe(sidebar,{attributes:true,attributeFilter:['class']});
  syncDrawer();
  const main = document.getElementById('main');
  const footer = () => {
    if (!main.querySelector('.page') || main.querySelector('.workspace-footer')) return;
    const element = document.createElement('footer'); element.className='workspace-footer';
    element.innerHTML='<span>Campaign Manager</span><span>Accounts · Campaigns · Conversations</span>';
    main.append(element);
  };
  new MutationObserver(footer).observe(main,{childList:true}); footer();
  document.addEventListener('keydown', event => {
    if (!mobile.matches || !sidebar.classList.contains('open')) return;
    if (event.key === 'Escape') { toggle.click(); toggle.focus(); }
    if (event.key === 'Tab') {
      const items=[...sidebar.querySelectorAll('a,button')], first=items[0], last=items[items.length-1];
      if (event.shiftKey && (document.activeElement===first || !sidebar.contains(document.activeElement))) { event.preventDefault();last.focus(); }
      else if (!event.shiftKey && (document.activeElement===last || !sidebar.contains(document.activeElement))) { event.preventDefault();first.focus(); }
    }
  });
})();
