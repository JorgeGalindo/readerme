(function () {
  'use strict';
  const button = document.getElementById('refreshPortadas');
  const status = document.getElementById('portadasStatus');
  const time = document.getElementById('portadasTime');
  const list = document.getElementById('portadasList');
  const savedKey = 'readerme:portadas:v1';

  function render(data) {
    const date = new Date(data && data.updated_at);
    if (!data || !Array.isArray(data.headlines) || !Number.isFinite(date.getTime())) throw new Error('Respuesta incompleta');
    const headlines = new Map(data.headlines.filter((h) => h && typeof h.id === 'string').map((h) => [h.id, h]));
    list.querySelectorAll('[data-source]').forEach((row) => {
      const headline = headlines.get(row.dataset.source);
      let url;
      try { url = new URL(headline && headline.url); } catch {}
      const available = headline && typeof headline.title === 'string' && headline.title.trim() &&
        url && (url.protocol === 'https:' || url.protocol === 'http:');
      const link = document.createElement('a');
      link.textContent = available ? headline.title : 'No disponible · abrir portada';
      link.href = available ? url.href : row.dataset.home;
      link.className = available ? '' : 'portada-unavailable';
      row.querySelector('.portada-headline').replaceChildren(link);
    });
    time.dateTime = date.toISOString();
    time.textContent = 'Consultado: ' + date.toLocaleString('es-ES', {
      day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    });
    status.textContent = '';
  }

  try {
    const saved = localStorage.getItem(savedKey);
    if (saved) render(JSON.parse(saved));
  } catch {}

  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = 'Actualizando…';
    list.setAttribute('aria-busy', 'true');
    status.textContent = '';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch('/api/portadas', {
        method: 'POST', cache: 'no-store', signal: controller.signal,
      });
      if (!response.ok) throw new Error('No disponible');
      const data = await response.json();
      render(data);
      try { localStorage.setItem(savedKey, JSON.stringify(data)); } catch {}
    } catch {
      status.textContent = 'No se pudo actualizar. Vuelve a intentarlo.';
    } finally {
      clearTimeout(timeout);
      button.disabled = false;
      button.textContent = 'Actualizar';
      list.setAttribute('aria-busy', 'false');
    }
  });
})();
