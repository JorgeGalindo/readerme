(function () {
  'use strict';
  const key = 'readerme:return-home';
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  let away = false;
  let outbound = false;
  function pending() {
    try { return outbound || sessionStorage.getItem(key) === '1'; } catch { return outbound; }
  }
  function home() {
    away = false;
    outbound = false;
    try { sessionStorage.removeItem(key); } catch {}
    if (location.pathname !== '/') location.replace('/');
  }
  // The marker survives a trip to a news site even if iOS discards this page.
  document.addEventListener('click', (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest && event.target.closest('a[href]');
    if (!link) return;
    let url;
    try { url = new URL(link.href, location.href); } catch { return; }
    if (url.origin === location.origin || !/^https?:$/.test(url.protocol)) return;
    outbound = true;
    try { sessionStorage.setItem(key, '1'); } catch {}
  });
  window.addEventListener('pageshow', (event) => {
    if (pending() || (ios && event.persisted)) home();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') away = true;
    else if (away && (ios || pending())) home();
  });
  window.addEventListener('focus', () => {
    if (pending()) home();
  });
})();
