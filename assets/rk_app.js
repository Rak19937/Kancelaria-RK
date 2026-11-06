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
    if (key === 'j') {
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

// DEV9 PWA. Service Worker nie cache'uje danych spraw ani dokumentów.
if('serviceWorker' in navigator && (location.protocol==='https:' || location.hostname==='localhost' || location.hostname==='127.0.0.1')){
  window.addEventListener('load',()=>navigator.serviceWorker.register('/service-worker.js',{scope:'/'}).catch(()=>{}));
}

// =========================================================
// DEV9 — prostsza obsługa, progressive disclosure i zegar.
// =========================================================
(() => {
  'use strict';

  // Aktywny zegar na ekranie głównym — czas lokalny komputera użytkownika.
  const clock = document.querySelector('[data-live-clock]');
  const clockDate = document.getElementById('liveClockDate');
  if (clock) {
    const tick = () => {
      const now = new Date();
      clock.textContent = new Intl.DateTimeFormat('pl-PL', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
      }).format(now);
      if (clockDate) {
        clockDate.textContent = new Intl.DateTimeFormat('pl-PL', {
          weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
        }).format(now);
      }
    };
    tick();
    setInterval(tick, 1000);
  }

  // Jeden przycisk „Dodaj” może otworzyć schowany formularz bez przewijania chaosu.
  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-open-details]');
    if (!btn) return;
    const id = btn.dataset.openDetails;
    const panel = id ? document.getElementById(id) : null;
    if (!panel || panel.tagName !== 'DETAILS') return;
    e.preventDefault();
    panel.open = true;
    panel.scrollIntoView({behavior: 'smooth', block: 'start'});
    setTimeout(() => {
      const target = panel.querySelector('input:not([type="hidden"]),select,textarea');
      target?.focus({preventScroll: true});
    }, 250);
  });

  // Jeśli użytkownik wszedł linkiem do sekcji schowanej w <details>, pokaż ją.
  const openHashTarget = () => {
    if (!location.hash) return;
    const el = document.getElementById(location.hash.slice(1));
    if (!el) return;
    if (el.tagName === 'DETAILS') el.open = true;
    let parent = el.closest('details');
    while (parent) {
      parent.open = true;
      parent = parent.parentElement?.closest('details');
    }
  };
  openHashTarget();
  window.addEventListener('hashchange', openHashTarget);

  // Tryb kompaktowy jest preferencją interfejsu i nie zmienia danych spraw.
  const compactBtn = document.querySelector('[data-compact-toggle]');
  const compactKey = 'rk_ui_compact';
  const applyCompact = () => {
    const on = localStorage.getItem(compactKey) === '1';
    document.body.classList.toggle('rk-compact', on);
    if (compactBtn) compactBtn.textContent = on ? '↔ Widok wygodny' : '↔ Tryb kompaktowy';
  };
  applyCompact();
  compactBtn?.addEventListener('click', () => {
    localStorage.setItem(compactKey, document.body.classList.contains('rk-compact') ? '0' : '1');
    applyCompact();
  });

  // Po otwarciu modułu zamień etykietę „Otwórz” na czytelne „Zwiń”.
  document.querySelectorAll('.module-card').forEach(module => {
    const label = module.querySelector('.module-open-label');
    const update = () => { if (label) label.textContent = module.open ? 'Zwiń' : 'Otwórz'; };
    update();
    module.addEventListener('toggle', update);
  });
})();

// RK-INBOX-FEEDBACK-0310 — informacja zwrotna w czasie dłuższej lokalnej analizy OCR.
// Nie przechwytujemy formularza przez fetch: zwykły POST + przekierowanie nadal działa.
(() => {
  'use strict';
  const form = document.querySelector('form[data-rk-inbox-upload="1"]');
  if (!form) return;
  const fileInput = form.querySelector('input[type="file"][name="file"]');
  const submit = form.querySelector('button[type="submit"]');
  const info = document.getElementById('rk-inbox-upload-feedback');
  if (!fileInput || !submit || !info) return;
  const originalLabel = submit.textContent;
  let sending = false;
  let extendedNotice = null;
  function show(message, error = false) {
    info.hidden = false;
    info.textContent = message;
    info.setAttribute('role', error ? 'alert' : 'status');
  }
  function reset() {
    sending = false;
    submit.disabled = false;
    submit.textContent = originalLabel;
    if (extendedNotice !== null) { clearTimeout(extendedNotice); extendedNotice = null; }
    info.hidden = true;
    info.textContent = '';
    info.setAttribute('role', 'status');
  }
  form.addEventListener('submit', e => {
    if (sending) { e.preventDefault(); return; }
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      e.preventDefault();
      show('Najpierw wybierz plik do odczytania.', true);
      return;
    }
    if (!file.size || file.size > 20 * 1024 * 1024) {
      e.preventDefault();
      show('Plik musi mieć od 1 bajta do 20 MB. Wybierz odpowiedni plik.', true);
      return;
    }
    sending = true;
    submit.disabled = true;
    submit.textContent = 'Trwa odczytywanie…';
    show('Przesyłanie pliku i lokalny odczyt. Skany PDF mogą wymagać więcej czasu. Po zakończeniu otworzy się ekran weryfikacji.');
    extendedNotice = setTimeout(() => {
      if (sending) show('Odczyt nadal trwa. OCR większych skanów jest czasochłonny; pozostaw okno otwarte. Jeśli program nie odpowiada, sprawdź lokalny dziennik błędów.');
    }, 25000);
    // Pozostaw domyślne działanie formularza; nie blokuj i nie duplikuj POST.
  });
  fileInput.addEventListener('invalid', () => show('Najpierw wybierz plik do odczytania.', true));
  fileInput.addEventListener('change', reset);
  window.addEventListener('pageshow', e => { if (e.persisted) reset(); });
})();
