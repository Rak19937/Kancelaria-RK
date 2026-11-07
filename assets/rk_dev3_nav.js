/* RK KANCELARIA dev3 R2: predictable sidebar with explicit pin/unpin and keyboard control. */
(() => {
  'use strict';
  const sidebar = document.querySelector('.sidebar');
  const trigger = document.querySelector('[data-dev3-nav-toggle]');
  const pin = document.querySelector('[data-dev3-nav-pin]');
  const finder = document.querySelector('[data-dev3-nav-filter]');
  if (!sidebar || !trigger) return;
  const storageKey = 'rk.dev3.menu.pinned';
  let pinned = false;
  try { pinned = localStorage.getItem(storageKey) === '1'; } catch (_) { /* unavailable storage */ }
  let expanded = pinned;
  let mouseInside = false;
  let preventHoverUntilLeave = false;
  let openTimer = null;
  let closeTimer = null;
  let originalDetails = null;
  const cancelTimers = () => {
    clearTimeout(openTimer); clearTimeout(closeTimer);
    openTimer = null; closeTimer = null;
  };
  function rememberPin() {
    try { localStorage.setItem(storageKey, pinned ? '1' : '0'); } catch (_) { /* private mode */ }
  }
  function paint() {
    sidebar.classList.toggle('dev3-open', expanded);
    sidebar.classList.toggle('dev3-pinned', pinned);
    trigger.setAttribute('aria-expanded', String(expanded));
    trigger.setAttribute('aria-label', expanded ? 'Schowaj menu boczne' : 'Rozwiń menu boczne');
    trigger.title = expanded ? 'Schowaj menu (Alt+M)' : 'Rozwiń menu (Alt+M)';
    if (pin) {
      pin.setAttribute('aria-pressed', String(pinned));
      pin.setAttribute('aria-label', pinned ? 'Odepnij i schowaj menu' : 'Przypnij otwarte menu');
      pin.title = pinned ? 'Odepnij i schowaj menu' : 'Przypnij menu na stałe';
      pin.textContent = pinned ? '📌' : '📍';
    }
  }
  function show() {
    cancelTimers();
    expanded = true;
    paint();
  }
  function hide(explicit = false) {
    cancelTimers();
    pinned = false;
    expanded = false;
    if (explicit) preventHoverUntilLeave = true;
    rememberPin();
    // Focus in a hidden search field keeps keyboard navigation trapped.
    if ((finder && finder.contains && finder.contains(document.activeElement)) ||
        document.activeElement === pin) trigger.focus();
    paint();
  }
  function toggleOpen() {
    if (expanded) hide(true);
    else { preventHoverUntilLeave = false; show(); }
  }
  trigger.addEventListener('click', toggleOpen);
  if (pin) pin.addEventListener('click', () => {
    if (pinned) hide(true);
    else { pinned = true; preventHoverUntilLeave = false; rememberPin(); show(); }
  });
  sidebar.addEventListener('mouseenter', () => {
    mouseInside = true;
    clearTimeout(closeTimer);
    if (!pinned && !preventHoverUntilLeave && !expanded) {
      clearTimeout(openTimer);
      openTimer = setTimeout(() => { if (mouseInside && !preventHoverUntilLeave) show(); }, 170);
    }
  });
  sidebar.addEventListener('mouseleave', () => {
    mouseInside = false;
    preventHoverUntilLeave = false;
    clearTimeout(openTimer);
    if (!pinned) closeTimer = setTimeout(() => { if (!mouseInside && !pinned) { expanded = false; paint(); } }, 240);
  });
  sidebar.addEventListener('focusin', () => {
    if (!preventHoverUntilLeave) show();
  });
  sidebar.addEventListener('focusout', () => {
    if (!pinned && !mouseInside) closeTimer = setTimeout(() => {
      if (!sidebar.contains(document.activeElement)) { expanded = false; paint(); }
    }, 200);
  });
  if (finder) finder.addEventListener('input', () => {
    const query = finder.value.trim().toLocaleLowerCase('pl');
    const groups = sidebar.querySelectorAll('.nav-system');
    if (query && !originalDetails) originalDetails = Array.from(groups, node => [node, node.open]);
    sidebar.querySelectorAll('.nav-link').forEach(link => {
      const words = String(link.textContent || '').toLocaleLowerCase('pl');
      link.hidden = Boolean(query && !words.includes(query));
    });
    if (query) {
      groups.forEach(group => {
        const found = Array.from(group.querySelectorAll('.nav-link')).some(link => !link.hidden);
        group.hidden = !found;
        if (found) group.open = true;
      });
    } else {
      groups.forEach(group => { group.hidden = false; });
      if (originalDetails) {
        originalDetails.forEach(([group, wasOpen]) => { group.open = wasOpen; });
        originalDetails = null;
      }
    }
  });
  document.addEventListener('keydown', event => {
    if (event.altKey && !event.ctrlKey && !event.shiftKey && String(event.key).toLowerCase() === 'm') {
      event.preventDefault(); toggleOpen();
      return;
    }
    if (event.key === 'Escape' && expanded && (sidebar.contains(document.activeElement) || document.activeElement === document.body)) {
      event.preventDefault(); hide(true); trigger.focus();
    }
  });
  // Optional live timer is local display only. Server remains the source of truth.
  const elapsed = document.querySelector('[data-rk-dev3-timer-start]');
  if (elapsed) {
    const base = Date.parse(elapsed.getAttribute('data-rk-dev3-timer-start'));
    if (Number.isFinite(base)) {
      const tick = () => {
        const seconds = Math.max(0, Math.floor((Date.now() - base) / 1000));
        const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
        elapsed.textContent = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
      };
      tick(); setInterval(tick, 1000);
    }
  }
  paint();
})();
