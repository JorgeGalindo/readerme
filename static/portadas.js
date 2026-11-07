(function () {
  'use strict';
  // Portadas refreshes by itself when the page opens or the app comes back
  // and the saved headlines are older than STALE_MS. Each newspaper is its own
  // request, so a fast paper never waits for a slow one.
  const STALE_MS = 3 * 60 * 1000;
  const REQUEST_TIMEOUT_MS = 15000;
  const savedKey = 'readerme:portadas:v2';
  const button = document.getElementById('refreshPortadas');
  const status = document.getElementById('portadasStatus');
  const time = document.getElementById('portadasTime');
  const list = document.getElementById('portadasList');
  const rows = Array.from(list.querySelectorAll('[data-source]'));
  let saved = { updated_at: null, headlines: {} };
  let running = null;

  function safeUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' || url.protocol === 'http:' ? url : null;
    } catch { return null; }
  }

  function renderRow(row, headline) {
    const url = headline && safeUrl(headline.url);
    const available = url && typeof headline.title === 'string' && headline.title.trim();
    const link = document.createElement('a');
    link.textContent = available ? headline.title : 'No disponible · abrir portada';
    link.href = available ? url.href : row.dataset.home;
    link.className = available ? '' : 'portada-unavailable';
    row.querySelector('.portada-headline').replaceChildren(link);
  }

  function renderTime(iso) {
    const date = new Date(iso);
    if (!iso || !Number.isFinite(date.getTime())) return false;
    time.dateTime = date.toISOString();
    time.textContent = 'Consultado: ' + date.toLocaleString('es-ES', {
      day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    });
    return true;
  }

  function persist() {
    try { localStorage.setItem(savedKey, JSON.stringify(saved)); } catch {}
  }

  function restore() {
    try {
      const data = JSON.parse(localStorage.getItem(savedKey));
      if (!data || typeof data.headlines !== 'object' || data.headlines === null) return;
      if (!renderTime(data.updated_at)) return;
      saved = { updated_at: data.updated_at, headlines: data.headlines };
      rows.forEach((row) => {
        const headline = saved.headlines[row.dataset.source];
        if (headline) renderRow(row, headline);
      });
      status.textContent = '';
    } catch {}
  }

  function isStale() {
    const at = new Date(saved.updated_at).getTime();
    return !Number.isFinite(at) || Date.now() - at > STALE_MS;
  }

  async function fetchRow(row) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch('/api/portadas/' + encodeURIComponent(row.dataset.source), {
        cache: 'no-store', signal: controller.signal,
      });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (!data || data.id !== row.dataset.source) throw new Error('Respuesta incompleta');
      const headline = { title: data.title, url: data.url };
      saved.headlines[row.dataset.source] = headline;
      renderRow(row, headline);
      return true;
    } catch {
      return false;
    } finally {
      clearTimeout(timer);
      row.classList.remove('is-updating');
    }
  }

  function refresh() {
    if (running) return running;
    button.disabled = true;
    button.textContent = 'Actualizando…';
    list.setAttribute('aria-busy', 'true');
    status.textContent = '';
    rows.forEach((row) => row.classList.add('is-updating'));
    running = Promise.all(rows.map(fetchRow)).then((results) => {
      if (results.some(Boolean)) {
        saved.updated_at = new Date().toISOString();
        renderTime(saved.updated_at);
        persist();
      } else {
        status.textContent = 'No se pudo actualizar. Vuelve a intentarlo.';
      }
    }).finally(() => {
      running = null;
      button.disabled = false;
      button.textContent = 'Actualizar';
      list.setAttribute('aria-busy', 'false');
    });
    return running;
  }

  restore();
  button.addEventListener('click', refresh);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && isStale()) refresh();
  });
  if (isStale()) refresh();
})();
