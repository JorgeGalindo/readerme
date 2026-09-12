async function getShareText(btn) {
  const card = btn.closest('.card');
  const result = card.querySelector('.share-result');
  result.setAttribute('aria-live', 'polite');
  btn.textContent = 'Generando...';
  btn.disabled = true;
  try {
    const response = await fetch('/api/share-text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: btn.dataset.title, url: btn.dataset.url, content: '' })
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    if (!data.ok || typeof data.text !== 'string') throw new Error('Invalid response');

    const wrapper = document.createElement('div');
    wrapper.className = 'share-text';
    const text = document.createElement('pre');
    // El texto del modelo puede contener HTML: se muestra siempre como texto.
    text.textContent = data.text;
    const copy = document.createElement('button');
    copy.type = 'button';
    copy.className = 'btn-copy';
    copy.textContent = 'Copiar';
    copy.addEventListener('click', () => { void copyShare(copy); });
    wrapper.append(text, copy);
    result.replaceChildren(wrapper);
  } catch {
    const error = document.createElement('p');
    error.className = 'share-error';
    error.textContent = 'No se pudo generar el texto. Puedes volver a intentarlo.';
    result.replaceChildren(error);
  } finally {
    btn.textContent = 'Compartir';
    btn.disabled = false;
  }
}

async function copyShare(btn) {
  try {
    await navigator.clipboard.writeText(btn.previousElementSibling.textContent);
    btn.textContent = 'Copiado';
  } catch {
    btn.textContent = 'No se pudo copiar';
  }
  setTimeout(() => { btn.textContent = 'Copiar'; }, 1500);
}
