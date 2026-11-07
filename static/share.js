// «Compartir» opens the system share sheet (LinkedIn, X, Mensajes…) with the
// article's title and link. Where the browser has no share sheet it copies
// both to the clipboard. No model writes the post any more.
async function shareArticle(btn) {
  const title = btn.dataset.title || '';
  const url = btn.dataset.url || '';
  if (!url) return;
  if (typeof navigator.share === 'function') {
    try {
      await navigator.share({ title, url });
      return;
    } catch (error) {
      // Closing the sheet is not an error worth reporting.
      if (error && error.name === 'AbortError') return;
    }
  }
  const label = btn.textContent;
  try {
    await navigator.clipboard.writeText(title ? title + '\n' + url : url);
    btn.textContent = 'Enlace copiado';
  } catch {
    btn.textContent = 'No se pudo copiar';
  }
  setTimeout(() => { btn.textContent = label; }, 2000);
}
