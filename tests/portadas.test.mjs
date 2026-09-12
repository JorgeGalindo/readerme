import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../static/portadas.js', import.meta.url), 'utf8');
const payload = (title = 'Titular principal') => ({
  updated_at: '2026-09-12T10:00:00Z',
  headlines: [{ id: 'elpais', title, url: 'https://elpais.com/noticia' }],
});
const response = (data = payload()) => ({ ok: true, json: async () => data });

function setup(fetcher = async () => response()) {
  const handlers = {}, calls = [], timers = new Map();
  let fetch = fetcher, timerId = 0;
  const button = { disabled: false, textContent: 'Actualizar', addEventListener(event, handler) { handlers[event] = handler; } };
  const headline = { children: [], replaceChildren(...nodes) { this.children = nodes; } };
  const row = { dataset: { source: 'elpais', home: 'https://elpais.com/' }, querySelector: () => headline };
  const list = { attributes: {}, setAttribute(key, value) { this.attributes[key] = value; }, querySelectorAll: () => [row] };
  const status = { textContent: '' }, time = { textContent: '' };
  const ids = { refreshPortadas: button, portadasList: list, portadasStatus: status, portadasTime: time };
  const document = {
    getElementById: (id) => ids[id],
    createElement: () => ({ set innerHTML(_) { throw new Error('Do not interpret headlines as HTML'); } }),
  };
  vm.runInNewContext(source, {
    document, URL, AbortController,
    fetch: async (...args) => { calls.push(args); return fetch(...args); },
    setTimeout(fn, ms) { timers.set(++timerId, { fn, ms }); return timerId; },
    clearTimeout(id) { timers.delete(id); },
  });
  return { button, headline, status, time, list, calls,
    click: () => handlers.click(),
    setFetch(fn) { fetch = fn; },
    timeout() { [...timers.values()][0].fn(); },
  };
}

test('only refresh requests headlines, and displays a literal linked title', async () => {
  const text = '<img src=x onerror=bad()> — un titular';
  const page = setup(async () => response(payload(text)));
  assert.equal(page.calls.length, 0);
  await page.click();
  assert.equal(page.calls[0][0], '/api/portadas');
  assert.equal(page.calls[0][1].cache, 'no-store');
  assert.equal(page.headline.children[0].textContent, text);
  assert.equal(page.headline.children[0].href, 'https://elpais.com/noticia');
  assert.equal(page.time.dateTime, '2026-09-12T10:00:00.000Z');
  await page.click();
  assert.equal(page.calls.length, 2);
});

test('a failed newspaper replaces its old headline with a link to the home page', async () => {
  const page = setup(); await page.click();
  page.setFetch(async () => response({ ...payload(), headlines: [{ id: 'elpais', title: null, url: null }] }));
  await page.click();
  assert.equal(page.headline.children[0].textContent, 'No disponible · abrir portada');
  assert.equal(page.headline.children[0].href, 'https://elpais.com/');
});

test('unsafe links and omitted newspapers do not retain an apparently fresh headline', async () => {
  for (const headlines of [[], [{ id: 'elpais', title: 'Título', url: 'javascript:alert(1)' }]]) {
    const page = setup(async () => response({ ...payload(), headlines }));
    await page.click();
    assert.equal(page.headline.children[0].href, 'https://elpais.com/');
  }
});

test('a failed refresh preserves the previous consultation time and allows retry', async () => {
  for (const fetch of [
    async () => { throw new Error('offline'); },
    async () => ({ ok: false }),
    async () => ({ ok: true, json: async () => { throw new Error('bad JSON'); } }),
    async () => response({ headlines: [], updated_at: 'invalid' }),
  ]) {
    const page = setup(); await page.click();
    const previous = page.time.dateTime;
    page.setFetch(fetch); await page.click();
    assert.equal(page.time.dateTime, previous);
    assert.match(page.status.textContent, /No se pudo actualizar/);
    assert.equal(page.button.disabled, false);
    assert.equal(page.list.attributes['aria-busy'], 'false');
    page.setFetch(async () => response(payload('Nuevo titular'))); await page.click();
    assert.equal(page.headline.children[0].textContent, 'Nuevo titular');
  }
});

test('repeated clicks do not start overlapping requests', async () => {
  let resolve;
  const page = setup(() => new Promise((r) => { resolve = r; }));
  const first = page.click(); await page.click();
  assert.equal(page.calls.length, 1);
  assert.equal(page.button.disabled, true);
  resolve(response()); await first;
  assert.equal(page.button.disabled, false);
});

test('a hung request times out and restores the button', async () => {
  const page = setup((_, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('timeout')))));
  const pending = page.click(); page.timeout(); await pending;
  assert.equal(page.button.disabled, false);
  assert.match(page.status.textContent, /No se pudo actualizar/);
});
