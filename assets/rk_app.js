(() => {
  'use strict';

  const statusEl = document.getElementById('autosaveStatus');
  let statusTimer = null;
  function status(msg) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.classList.add('show');
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => statusEl.classList.remove('show'), 1800);
  }

  const dirty = new Set();
  const state = new WeakMap();
  function formState(form) {
    let s = state.get(form);
    if (!s) {
      s = {timer: null, saving: false, pending: false};
      state.set(form, s);
    }
    return s;
  }

  function paramsFor(form) {
    const p = new URLSearchParams();
    new FormData(form).forEach((v, k) => {
      if (!(v instanceof File)) p.append(k, String(v));
    });
    p.set('_autosave', '1');
    return p;
  }

  async function saveForm(form) {
    if (!form || !dirty.has(form)) return;
    const s = formState(form);
    if (s.saving) {
      s.pending = true;
      return;
    }
    const required = [...form.querySelectorAll('[required]')];
    if (required.some(x => !String(x.value || '').trim())) return;

    s.saving = true;
    s.pending = false;
    try {
      const r = await fetch(form.action, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
          'X-Sprawnik-Autosave': '1'
        },
        body: paramsFor(form).toString(),
        credentials: 'same-origin',
        cache: 'no-store',
        keepalive: true
      });
      if (r.ok) {
        dirty.delete(form);
        status('Zapisano');
      } else {
        status('Błąd autosave');
      }
    } catch (_) {
      status('Zmiany czekają na zapis');
    } finally {
      s.saving = false;
      if (s.pending && dirty.has(form)) {
        clearTimeout(s.timer);
        s.timer = setTimeout(() => saveForm(form), 350);
      }
    }
  }

  document.querySelectorAll('form[data-autosave="1"]').forEach(form => {
    const s = formState(form);
    const schedule = () => {
      dirty.add(form);
      clearTimeout(s.timer);
      // 1.25 s redukuje lawinę zapisów podczas szybkiego pisania,
      // ale nadal daje odczuwalnie natychmiastowy autosave.
      s.timer = setTimeout(() => saveForm(form), 1250);
    };
    form.addEventListener('input', e => {
      if (e.target && e.target.type !== 'file') schedule();
    }, {passive: true});
    form.addEventListener('change', e => {
      if (e.target && e.target.type !== 'file') schedule();
    }, {passive: true});
    form.addEventListener('submit', () => dirty.delete(form));
  });

  function flushDirtyWithBeacon() {
    dirty.forEach(form => {
      try {
        const p = paramsFor(form);
        navigator.sendBeacon(
          form.action,
          new Blob([p.toString()], {type: 'application/x-www-form-urlencoded;charset=UTF-8'})
        );
      } catch (_) {}
    });
  }
  window.rkFlushAutosave = flushDirtyWithBeacon;

  document.addEventListener('keydown', e => {
    if (!e.ctrlKey || e.altKey || e.metaKey) return;
    const key = String(e.key || '').toLowerCase();
    if (key === 'k') {
      e.preventDefault();
      const inp = document.querySelector('[data-global-search], #globalSearchInput');
      if (inp) { inp.focus(); inp.select(); }
      else location.href = '/search?focus=1';
    } else if (key === 'j') {
      e.preventDefault();
      location.href = '/quick-add';
    } else if (key === 'n') {
      e.preventDefault();
      location.href = '/case/new';
    } else if (key === 'd') {
      const ctx = document.getElementById('rkCaseContext');
      if (ctx) {
        e.preventDefault();
        const det = document.querySelector('#documents details');
        if (det) det.open = true;
        document.getElementById('newDocTitle')?.focus();
        document.getElementById('documents')?.scrollIntoView({block: 'start'});
      }
    }
  });

  window.addEventListener('pagehide', flushDirtyWithBeacon);

  // Obecność kart potrzebna jest wyłącznie w klasycznym lokalnym trybie
  // przeglądarkowym. Desktop 0.15 nie uruchamia tego WebSocketu ani heartbeatów.
  if (document.body?.dataset.autoShutdown === '1') {
    let tabId = sessionStorage.getItem('sprawnik_tab_id');
    if (!tabId) {
      tabId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + '-' + Math.random();
      sessionStorage.setItem('sprawnik_tab_id', tabId);
    }
    let ws = null;
    try {
      const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
      ws = new WebSocket(proto + location.host + '/system/ws?tab=' + encodeURIComponent(tabId));
    } catch (_) {}
    const heartbeat = () => fetch('/system/heartbeat?tab=' + encodeURIComponent(tabId), {
      method: 'GET', cache: 'no-store', credentials: 'same-origin'
    }).catch(() => {});
    heartbeat();
    const hb = setInterval(heartbeat, 2500);
    window.addEventListener('pagehide', () => {
      clearInterval(hb);
      try { navigator.sendBeacon('/system/closing?tab=' + encodeURIComponent(tabId), ''); } catch (_) {}
      try { if (ws && ws.readyState < 2) ws.close(1000, 'karta zamknieta'); } catch (_) {}
    }, {once: true});
  }
})();

// DEV8 — Timeline 2.0: filtruj typy wpisów bez przeładowania strony.
document.addEventListener('click',e=>{
  const btn=e.target.closest('[data-timeline-filter]');
  if(!btn) return;
  e.preventDefault();
  const filter=btn.dataset.timelineFilter||'all';
  const root=btn.closest('.timeline-wrap') || document;
  root.querySelectorAll('[data-timeline-filter]').forEach(x=>x.classList.toggle('active',x===btn));
  root.querySelectorAll('.timeline-item').forEach(item=>{
    item.hidden = filter!=='all' && item.dataset.kind!==filter;
  });
});

// DEV8 PWA. Service Worker nie cache'uje danych spraw ani dokumentów.
if('serviceWorker' in navigator && (location.protocol==='https:' || location.hostname==='localhost' || location.hostname==='127.0.0.1')){
  window.addEventListener('load',()=>navigator.serviceWorker.register('/service-worker.js',{scope:'/'}).catch(()=>{}));
}
