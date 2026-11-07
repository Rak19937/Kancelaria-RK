/* RK KANCELARIA 0.4.0-dev3: accessible, optional pinned Start-like navigation. */
(() => {
  'use strict';
  const sidebar = document.querySelector('.sidebar');
  const trigger = document.querySelector('[data-dev3-nav-toggle]');
  const pin = document.querySelector('[data-dev3-nav-pin]');
  const finder = document.querySelector('[data-dev3-nav-filter]');
  if (!sidebar || !trigger) return;
  let pinned = false;
  try { pinned = localStorage.getItem('rk.dev3.menu.pinned') === '1'; } catch (_) {}
  function update() {
    sidebar.classList.toggle('dev3-pinned', pinned);
    trigger.setAttribute('aria-expanded', String(pinned));
    if (pin) pin.setAttribute('aria-pressed', String(pinned));
    trigger.title = pinned ? 'Zwiń menu (Alt+M)' : 'Rozwiń menu (Alt+M)';
  }
  function toggle() {
    pinned = !pinned;
    try { localStorage.setItem('rk.dev3.menu.pinned', pinned ? '1' : '0'); } catch (_) {}
    update();
    if (pinned && finder) finder.focus();
  }
  trigger.addEventListener('click', toggle);
  if (pin) pin.addEventListener('click', toggle);
  if (finder) finder.addEventListener('input', () => {
    const q = finder.value.trim().toLocaleLowerCase('pl');
    sidebar.querySelectorAll('.nav-link').forEach(link => {
      const text = String(link.textContent || '').toLocaleLowerCase('pl');
      link.hidden = Boolean(q && !text.includes(q));
    });
  });
  document.addEventListener('keydown', ev => {
    if (ev.altKey && !ev.ctrlKey && !ev.shiftKey && ev.key.toLowerCase() === 'm') {
      ev.preventDefault(); toggle();
    }
    if (ev.key === 'Escape' && sidebar.contains(document.activeElement) && !pinned) {
      document.activeElement.blur();
    }
  });
  update();
})();
