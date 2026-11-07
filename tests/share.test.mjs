import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../static/share.js', import.meta.url), 'utf8');

function setup(navigator) {
  const timers = [];
  const btn = { textContent: 'Compartir', dataset: { title: 'Artículo', url: 'https://example.com/a' } };
  const context = vm.createContext({ navigator, setTimeout: (fn) => timers.push(fn) });
  vm.runInContext(source, context);
  return { btn, share: () => context.shareArticle(btn), runTimers: () => timers.forEach((fn) => fn()) };
}

test('abre la hoja de compartir del sistema con título y enlace', async () => {
  const shared = [];
  const page = setup({ share: async (data) => shared.push(data), clipboard: { writeText: () => assert.fail() } });
  await page.share();
  assert.equal(JSON.stringify(shared), JSON.stringify([{ title: 'Artículo', url: 'https://example.com/a' }]));
  assert.equal(page.btn.textContent, 'Compartir');
});

test('cerrar la hoja no copia nada ni muestra un error', async () => {
  const page = setup({
    share: async () => { throw Object.assign(new Error('cancel'), { name: 'AbortError' }); },
    clipboard: { writeText: () => assert.fail('should not copy') },
  });
  await page.share();
  assert.equal(page.btn.textContent, 'Compartir');
});

test('sin hoja de compartir copia título y enlace, y vuelve a su texto', async () => {
  let copied;
  const page = setup({ clipboard: { writeText: async (text) => { copied = text; } } });
  await page.share();
  assert.equal(copied, 'Artículo\nhttps://example.com/a');
  assert.equal(page.btn.textContent, 'Enlace copiado');
  page.runTimers();
  assert.equal(page.btn.textContent, 'Compartir');
});

test('no anuncia que copió si el portapapeles deniega el acceso', async () => {
  const page = setup({ clipboard: { writeText: async () => { throw new Error('denied'); } } });
  await page.share();
  assert.equal(page.btn.textContent, 'No se pudo copiar');
});
