/* UX6: disclosure + custom choices. No external services, no auto-approval of deadlines. */
(() => {
 'use strict';
 function ready(fn){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fn,{once:true});else fn()}
 const kinds={doc_type:'doc_type',task_type:'task_type',alert_type:'alert_type',event_type:'event_type'};
 ready(()=>{
  // Transform each individual OCR proposal into a disclosure with readable copy.
  const form=document.querySelector('form[action^="/inbox/"][action$="/approve"]');
  if(form){
   const checks=[...form.querySelectorAll('input[type="checkbox"][name^="act_"][name$="_selected"]')];
   checks.forEach((cb,n)=>{
    const card=cb.closest('.card');if(!card||card.matches('details')||card.classList.contains('ux6-suggestion-card'))return;
    const current=card.querySelector('[name^="act_"][name$="_title"]');
    const name=current?.value?.trim()||(cb.checked?'Proponowana czynność':'Nowa czynność do wpisania');
    const details=document.createElement('details');details.className='card ux6-suggestion-card';
    if(n===0)details.open=true;
    const summary=document.createElement('summary');summary.textContent=`${cb.checked?'Propozycja':'Własna czynność'} ${n+1}: ${name}`;
    const body=document.createElement('div');body.className='ux6-suggestion-body';
    while(card.firstChild)body.appendChild(card.firstChild);
    details.append(summary,body);card.replaceWith(details);
    current?.addEventListener('input',()=>{summary.textContent=`${cb.checked?'Propozycja':'Własna czynność'} ${n+1}: ${current.value.trim()||'Bez nazwy'}`;});
   });
  }
  // Only open-ended textual taxonomies may grow. IDs, permissions and
  // fixed workflow states are intentionally excluded.
  for(const sel of document.querySelectorAll('select[name]')){
   const kind=kinds[sel.name];if(!kind)continue;
   if(sel.querySelector('option[value="__ux6_add__"]'))continue;
   const option=document.createElement('option');option.value='__ux6_add__';option.textContent='＋ DODAJ WŁASNE…';
   sel.append(option);
   // Populate persistent additions after every reload, including forms
   // generated from older fixed dropdown lists.
   fetch('/ux6/choices?kind='+encodeURIComponent(kind),{credentials:'same-origin'})
    .then(resp=>resp.ok?resp.json():Promise.reject(Error('HTTP '+resp.status)))
    .then(data=>{for(const label of (data.choices||[])){
      if(![...sel.options].some(o=>o.value===label)){
       const o=document.createElement('option');o.value=label;o.textContent=label;sel.insertBefore(o,option);
      }
    }}).catch(()=>{/* old installations remain usable */});
   let previous=sel.value;
   sel.addEventListener('focus',()=>{if(sel.value!=='__ux6_add__')previous=sel.value;});
   sel.addEventListener('change',async()=>{
    if(sel.value!=='__ux6_add__'){previous=sel.value;return;}
    const val=window.prompt('Nowa pozycja dla tej listy (będzie dostępna także później):','');
    if(!val||!val.trim()){sel.value=previous;return;}
    const clean=val.trim().replace(/\s+/g,' ');
    if(clean.length>100){window.alert('Maksymalnie 100 znaków.');sel.value=previous;return;}
    const token=document.querySelector('meta[name="rk-csrf-token"]')?.getAttribute('content');
    if(!token){window.alert('Brak tokenu sesji. Odśwież stronę.');sel.value=previous;return;}
    const formData=new URLSearchParams({kind,value:clean,_rk_csrf:token});
    try{
     const resp=await fetch('/ux6/choice',{method:'POST',body:formData,credentials:'same-origin',
      headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','X-RK-CSRF':token}});
     if(!resp.ok)throw Error('HTTP '+resp.status);
     const data=await resp.json();if(!data.ok)throw Error('Brak potwierdzenia');
     let added=[...sel.options].find(o=>o.value===data.value);
     if(!added){added=document.createElement('option');added.value=data.value;added.textContent=data.value;
      sel.insertBefore(added,option)}
     sel.value=data.value;previous=data.value;
    }catch(e){window.alert('Nie udało się zapisać nowej pozycji. Wymagane jest konto administratora. '+e.message);
      sel.value=previous;}
   });
  }
 });
})();
