/* Shared read ledger for Main, Papers, Thinktanks and the reset in España. */
(function () {
  'use strict';

  const READ_KEY = 'readerme_read';
  const PENDING_KEY = 'readerme_read_pending';
  const TTL = 60 * 86400000;
  const memory = Object.create(null);
  let storageAvailable = true;
  let active = null;
  let clearing = false;
  let retry = null;

  function normUrl(raw) {
    if (typeof raw !== 'string') return '';
    try {
      const u = new URL(raw.trim());
      const tracking = /^(utm_|fbclid|gclid|mc_cid|mc_eid|ref_|ref$|_hsenc|_hsmi)/i;
      const pairs = [...u.searchParams].filter(([k]) => !tracking.test(k));
      pairs.sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0);
      // Match urllib.parse.urlencode, including repeated keys and literal &/+/=.
      const encode = (s) => encodeURIComponent(s).replace(/[!'()*]/g, (c) => '%' + c.charCodeAt(0).toString(16).toUpperCase()).replace(/%20/g, '+');
      const query = pairs.map(([k, v]) => encode(k) + '=' + encode(v)).join('&');
      return u.protocol + '//' + u.host.toLowerCase() + (u.pathname.replace(/\/+$/, '') || '/') + (query ? '?' + query : '');
    } catch { return raw.trim().toLowerCase(); }
  }

  function load(key) {
    let raw = memory[key] || {};
    if (storageAvailable) {
      let stored = null;
      try { stored = window.localStorage.getItem(key); }
      catch { storageAvailable = false; }
      if (storageAvailable) {
        try { raw = JSON.parse(stored || '{}'); }
        catch { raw = {}; }
      }
    }
    const result = Object.create(null);
    const entries = Array.isArray(raw) ? raw.map((url) => [url, Date.now()]) : Object.entries(raw || {});
    for (const [url, ts] of entries) {
      const normalized = normUrl(url);
      if (normalized && typeof ts === 'number' && Number.isFinite(ts) &&
          (key === PENDING_KEY || ts >= Date.now() - TTL)) result[normalized] = ts;
    }
    memory[key] = result;
    return result;
  }

  function save(key, value) {
    memory[key] = value;
    if (storageAvailable) {
      try { window.localStorage.setItem(key, JSON.stringify(value)); }
      catch { storageAvailable = false; }
    }
    return storageAvailable;
  }

  function status(message) {
    const el = document.getElementById('readStatus');
    if (el) { el.textContent = message; el.hidden = !message; }
  }

  function paint() {
    const read = load(READ_KEY), pending = load(PENDING_KEY);
    let visible = 0;
    const cards = document.querySelectorAll('.card[data-url]');
    cards.forEach((card) => {
      const url = normUrl(card.dataset.url);
      // Without local persistence, keep the card until the server confirms it.
      const hidden = !!read[url] && (storageAvailable || !pending[url]);
      card.style.display = hidden ? 'none' : '';
      if (!hidden) visible++;
    });
    const count = document.getElementById('unreadCount');
    if (count) count.textContent = String(visible);
    document.querySelectorAll('.bubble-section, .tt-subsection').forEach((section) => {
      section.hidden = ![...section.querySelectorAll('.card[data-url]')].some((c) => c.style.display !== 'none');
    });
    const empty = document.getElementById('readEmpty');
    if (empty) empty.hidden = cards.length === 0 || visible !== 0;
  }

  async function post(url, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const res = await fetch(url, {
        method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      });
      if (!res.ok || (await res.json()).ok !== true) throw new Error('read ledger unavailable');
    } finally { clearTimeout(timeout); }
  }

  function scheduleRetry() {
    clearTimeout(retry);
    retry = setTimeout(() => { retry = null; flush(); }, 30000);
  }

  function flush() {
    if (active) return active;
    if (clearing) return Promise.resolve();
    clearTimeout(retry);
    active = (async () => {
      while (!clearing) {
        const entry = Object.entries(load(PENDING_KEY))[0];
        if (!entry) { status(''); return; }
        const [url, ts] = entry;
        try { await post('/api/read', { url }); }
        catch {
          status(storageAvailable
            ? 'Lecturas guardadas aquí; pendientes de sincronizar.'
            : 'No se pudo guardar la lectura. Se reintentará mientras esta pestaña siga abierta.');
          scheduleRetry(); return;
        }
        // A previous quota failure may have saved the queue but not the read
        // cache. Retain the confirmed mark before removing its retry entry.
        const read = load(READ_KEY);
        read[url] = Math.max(read[url] || 0, ts);
        save(READ_KEY, read);
        const pending = load(PENDING_KEY);
        if (pending[url] === ts) delete pending[url];
        save(PENDING_KEY, pending);
        paint();
      }
    })().finally(() => { active = null; });
    return active;
  }

  window.markRead = function (btn) {
    if (clearing) return Promise.resolve();
    const card = btn.closest('.card');
    const url = normUrl(card && card.dataset.url);
    if (!url) return Promise.resolve();
    const read = load(READ_KEY), pending = load(PENDING_KEY);
    const ts = Date.now();
    read[url] = ts; pending[url] = ts;
    save(PENDING_KEY, pending); save(READ_KEY, read);
    paint();
    return flush();
  };

  window.resetRead = async function () {
    if (clearing || !window.confirm('¿Borrar el registro de artículos leídos? Volverán a aparecer todos.')) return;
    clearing = true;
    clearTimeout(retry);
    status('Borrando el registro…');
    try {
      // Finish the in-flight mark before clearing; otherwise it could reappear.
      if (active) await active;
      clearTimeout(retry);
      await post('/api/read/clear');
    } catch {
      clearing = false;
      status('No se pudo borrar el registro. Tus lecturas se conservan; puedes volver a intentarlo.');
      if (Object.keys(load(PENDING_KEY)).length) scheduleRetry();
      return;
    }
    for (const key of [PENDING_KEY, READ_KEY]) {
      memory[key] = {};
      try { window.localStorage.removeItem(key); } catch {}
    }
    window.location.reload();
  };

  window.addEventListener('online', flush);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') { paint(); flush(); }
  });
  window.addEventListener('storage', (event) => {
    if (event.key === READ_KEY || event.key === PENDING_KEY) { paint(); flush(); }
  });
  // Migrate the old array format and normalize keys once for all tabs.
  save(READ_KEY, load(READ_KEY));
  paint();
  flush();
})();
