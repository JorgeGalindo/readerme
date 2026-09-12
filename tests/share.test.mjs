import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../static/share.js', import.meta.url), 'utf8');

function element(tagName) {
  return {
    tagName, children: [], textContent: '', disabled: false,
    setAttribute() {}, addEventListener() {},
    set innerHTML(_) { throw new Error('Generated text must never be parsed as HTML'); },
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
  };
}

function setup(fetch) {
  const result = element('div');
  const btn = element('button');
  btn.dataset = { title: 'Article', url: 'https://example.com' };
  btn.closest = () => ({ querySelector: () => result });
  const context = vm.createContext({ fetch, document: { createElement: element }, navigator: {}, setTimeout: () => {} });
  vm.runInContext(source, context);
  return { context, result, btn };
}

test('el texto generado se muestra literalmente, incluso si contiene HTML', async () => {
  const text = '<img src=x onerror="alert(1)"><script>bad()</script>';
  const { context, result, btn } = setup(async () => ({ ok: true, json: async () => ({ ok: true, text }) }));
  await context.getShareText(btn);
  const [wrapper] = result.children;
  assert.equal(wrapper.children[0].tagName, 'pre');
  assert.equal(wrapper.children[0].textContent, text);
  assert.equal(wrapper.children[1].textContent, 'Copiar');
  assert.equal(btn.disabled, false);
});

for (const [name, fetch] of [
  ['red desconectada', async () => { throw new TypeError('offline'); }],
  ['error HTTP', async () => ({ ok: false, status: 503 })],
  ['respuesta no JSON', async () => ({ ok: true, json: async () => { throw new SyntaxError('not json'); } })],
  ['respuesta incompleta', async () => ({ ok: true, json: async () => ({ ok: true }) })],
]) {
  test(`permite reintentar tras ${name}`, async () => {
    const { context, result, btn } = setup(fetch);
    await context.getShareText(btn);
    assert.equal(btn.disabled, false);
    assert.equal(btn.textContent, 'Compartir');
    assert.equal(result.children[0].className, 'share-error');
  });
}

test('no anuncia que copió si el portapapeles deniega el acceso', async () => {
  const { context, btn } = setup();
  btn.previousElementSibling = { textContent: 'Text' };
  await context.copyShare(btn);
  assert.equal(btn.textContent, 'No se pudo copiar');
});
