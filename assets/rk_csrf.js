/* RK KANCELARIA 0.4.0-dev2: CSRF header for authenticated same-origin fetch POST. */
(() => {
  'use strict';
  const realFetch = window.fetch.bind(window);
  window.fetch = function(input, init) {
    const token = document.querySelector('meta[name="rk-csrf-token"]')?.content;
    if (!token) return realFetch(input, init);
    try {
      const request = new Request(input, init);
      const url = new URL(request.url, location.href);
      if (request.method.toUpperCase() !== 'POST' || url.origin !== location.origin) {
        return realFetch(input, init);
      }
      const headers = new Headers(request.headers);
      headers.set('X-RK-CSRF', token);
      return realFetch(new Request(request, { headers }));
    } catch (_) {
      return realFetch(input, init);
    }
  };
})();
