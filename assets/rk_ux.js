/* RK KANCELARIA 0.3.9 — interakcje lokalne i preferencje widoku. */
(() => {
  'use strict';
  const root = document.body;
  if (!root) return;
  const prefix = 'rk_ux_039_';
  const get = k => {try{return localStorage.getItem(prefix+k)}catch(_){return null}};
  const set = (k,v) => {try{localStorage.setItem(prefix+k,v)}catch(_){}};
  const isEditable = node => node && (node.closest('input,textarea,select,[contenteditable="true"]') !== null);
  // Jeden punkt uruchamiania poleceń, bez kopiowania danych do pamięci przeglądarki.
  const modal = document.createElement('div');
  modal.className='rk-ux-command'; modal.hidden=true;
  modal.innerHTML=`<div class="rk-ux-command-dialog" role="dialog" aria-modal="true" aria-label="Szybkie wyszukiwanie i polecenia">
    <form action="/search" method="get"><label for="rk-ux-command-q">Szukaj w kancelarii</label><input id="rk-ux-command-q" name="q" autocomplete="off" placeholder="Sygnatura, klient, dokument, zadanie…" required></form>
    <div class="rk-ux-command-links"><a href="/cases">Sprawy</a><a href="/documents">Dokumenty</a><a href="/inbox">Skrzynka wpływu</a><a href="/today">Dzisiaj</a><a href="/quick-add">+ Dodaj</a></div>
    <small>Enter — szukaj · Esc — zamknij · Ctrl+F — otwórz</small></div>`;
  document.body.append(modal);
  let prevFocus;
  function close(){ modal.hidden=true; if(prevFocus && prevFocus.isConnected)prevFocus.focus(); }
  function open(){ prevFocus=document.activeElement; modal.hidden=false; modal.querySelector('input').focus(); }
  modal.addEventListener('click',e=>{if(e.target===modal)close()});
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape' && !modal.hidden){e.preventDefault();close();return;}
    if((e.ctrlKey||e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase()==='f'){
      e.preventDefault();e.stopImmediatePropagation();if(!e.repeat){modal.hidden?open():close();}return;
    }
    if(!e.ctrlKey&&!e.altKey&&!e.metaKey&&!isEditable(e.target) && e.key==='/'){
      e.preventDefault();open();
    }
  },true);
  // Wybranie sprawy przy przejściu z jej karty / z podglądu dokumentu.
  const params=new URLSearchParams(location.search);const cid=params.get('case_id');
  if(location.pathname==='/quick-add' && /^\d+$/.test(cid||'')){
    document.querySelectorAll('select[name="case_id"]').forEach(select=>{
      if([...select.options].some(opt=>opt.value===cid)){select.value=cid;select.dispatchEvent(new Event('change',{bubbles:true}));}
    });
  }
  // Zachowujemy kontekst sprawy dla dodawania kolejnych pozycji i powrotu.
  if(location.pathname==='/quick-add' && /^\d+$/.test(cid||'')){
    document.querySelectorAll('input[name="return_to"]').forEach(x=>{
      if(x.value.startsWith('/quick-add?done='))x.value += '&case_id='+encodeURIComponent(cid);
    });
  }
  // Pulpit skupiony na najczęstszej pracy; reszta wciąż dostępna.
  const dash=document.querySelector('.dashboard-hero');
  if(dash){
    const bar=document.createElement('div');bar.className='rk-ux-toolbar';
    bar.innerHTML='<b>Moja praca</b><button type="button" class="btn small" data-ux-focus>Widok</button>';
    dash.before(bar);
    const apply=()=>{const on=get('focus')==='1';root.classList.toggle('rk-ux-focus',on);bar.querySelector('button').textContent=on?'Pokaż cały pulpit':'Pokaż tylko najważniejsze';};
    bar.querySelector('button').addEventListener('click',()=>{set('focus',get('focus')==='1'?'0':'1');apply()});apply();
  }
  const sidebar=document.querySelector('.sidebar-tools');
  if(sidebar){const b=document.createElement('button');b.type='button';b.className='sidebar-mini-btn';b.textContent='☷ Uproszczone menu';
    sidebar.append(b);const apply=()=>{const on=get('compactnav')==='1';root.classList.toggle('rk-ux-compact-nav',on);b.textContent=on?'☷ Pełne menu':'☷ Uproszczone menu';};
    b.addEventListener('click',()=>{set('compactnav',get('compactnav')==='1'?'0':'1');apply()});apply();}
  // Filtrowanie chronologii tylko widokowe — nigdy nie zmienia dat lub danych.
  document.querySelectorAll('[data-ux-timeline]').forEach(view=>{
    view.querySelectorAll('[data-ux-category]').forEach(btn=>btn.addEventListener('click',()=>{
      const value=btn.dataset.uxCategory;
      view.querySelectorAll('[data-ux-category]').forEach(x=>x.setAttribute('aria-pressed',String(x===btn)));
      view.querySelectorAll('.rk-ux-timeline-item').forEach(x=>x.hidden=value!=='all' && x.dataset.uxSource!==value);
    }));
  });
  // Nie wyświetlamy fałszywych komunikatów „zapisano”; standardowe formularze nadal przeładowują stronę.
})();
