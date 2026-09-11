/* RK KANCELARIA DEV8 PWA — cache wyłącznie statycznego interfejsu.
   Dane spraw, HTML, API i dokumenty zawsze idą przez sieć i nie są zapisywane offline. */
const CACHE='rk-kancelaria-static-dev8';
const STATIC=[
  '/assets/rk_app.css',
  '/assets/rk_app.js',
  '/assets/rk_kancelaria_logo.png',
  '/assets/rk_kancelaria.ico',
  '/manifest.webmanifest'
];
self.addEventListener('install',event=>{
  event.waitUntil(caches.open(CACHE).then(c=>c.addAll(STATIC)).catch(()=>null));
  self.skipWaiting();
});
self.addEventListener('activate',event=>{
  event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch',event=>{
  const req=event.request;
  if(req.method!=='GET') return;
  const url=new URL(req.url);
  if(url.origin!==self.location.origin) return;
  if(url.pathname.startsWith('/assets/') || url.pathname==='/manifest.webmanifest'){
    event.respondWith(caches.match(req).then(hit=>hit || fetch(req).then(resp=>{
      const copy=resp.clone(); caches.open(CACHE).then(c=>c.put(req,copy)); return resp;
    })));
  }
});
