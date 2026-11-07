import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../static/portadas.js', import.meta.url), 'utf8');
const NOW = Date.parse('2026-11-07T10:00:00Z');
const PAPERS = { elpais: 'https://elpais.com/', abc: 'https://www.abc.es/' };
const ok = (id, title = 'Titular de ' + id, url = PAPERS[id] + 'noticia') =>
  ({ ok: true, json: async () => ({ id, title, url, updated_at: new Date(NOW).toISOString() }) });
const idOf = (url) => decodeURIComponent(url.split('/').pop());
const flush = () => new Promise((resolve) => setImmediate(resolve));

function row(id) {
  const classes = new Set();
  const headline = { children: [], replaceChildren(...nodes) { this.children = nodes; } };
  return {
    dataset: { source: id, home: PAPERS[id] }, headline,
    querySelector: () => headline,
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), has: (c) => classes.has(c) },
  };
}

function setup({ fetcher = async (url) => ok(idOf(url)), storage = new Map(), now = NOW } = {}) {
  const handlers = {}, docHandlers = {}, calls = [], timers = new Map();
  let fetch = fetcher, timerId = 0, clock = now;
  const rows = Object.keys(PAPERS).map(row);
  const button = { disabled: false, textContent: 'Actualizar', addEventListener(e, h) { handlers[e] = h; } };
  const list = { attributes: {}, setAttribute(k, v) { this.attributes[k] = v; }, querySelectorAll: () => rows };
  const status = { textContent: '' }, time = { textContent: '' };
  const ids = { refreshPortadas: button, portadasList: list, portadasStatus: status, portadasTime: time };
  const document = {
    visibilityState: 'visible',
    getElementById: (id) => ids[id],
    addEventListener(e, h) { docHandlers[e] = h; },
    createElement: () => ({ set innerHTML(_) { throw new Error('Do not interpret headlines as HTML'); } }),
  };
  class FakeDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock])); }
    static now() { return clock; }
  }
  vm.runInNewContext(source, {
    document, URL, AbortController, Date: FakeDate, encodeURIComponent,
    localStorage: { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v) },
    fetch: async (...args) => { calls.push(args); return fetch(...args); },
    setTimeout(fn, ms) { timers.set(++timerId, { fn, ms }); return timerId; },
    clearTimeout(id) { timers.delete(id); },
  });
  return {
    rows, button, status, time, list, calls, storage,
    titles: () => rows.map((r) => r.headline.children[0] && r.headline.children[0].textContent),
    click: () => handlers.click(),
    resume() { document.visibilityState = 'visible'; docHandlers.visibilitychange(); },
    setFetch(fn) { fetch = fn; },
    advance(ms) { clock += ms; },
    timeoutAll() { [...timers.values()].forEach((t) => t.fn()); },
  };
}

test('opening with nothing saved fetches every newspaper once and shows literal titles', async () => {
  const text = '<img src=x onerror=bad()> — un titular';
  const page = setup({ fetcher: async (url) => ok(idOf(url), idOf(url) === 'abc' ? text : 'País') });
  await flush(); await flush();
  assert.deepEqual(page.calls.map(([url]) => url).sort(), ['/api/portadas/abc', '/api/portadas/elpais']);
  assert.equal(page.calls[0][1].cache, 'no-store');
  assert.deepEqual(page.titles(), ['País', text]);
  assert.equal(page.rows[1].headline.children[0].href, 'https://www.abc.es/noticia');
  assert.equal(page.time.dateTime, '2026-11-07T10:00:00.000Z');
  assert.equal(page.button.disabled, false);
});

test('each row updates on its own: a fast paper does not wait for a slow one', async () => {
  let releaseSlow;
  const page = setup({ fetcher: (url) => idOf(url) === 'abc'
    ? new Promise((resolve) => { releaseSlow = () => resolve(ok('abc')); })
    : Promise.resolve(ok('elpais')) });
  await flush(); await flush();
  assert.deepEqual(page.titles(), ['Titular de elpais', undefined]);
  assert.equal(page.rows[0].classList.has('is-updating'), false);
  assert.equal(page.rows[1].classList.has('is-updating'), true);
  assert.equal(page.button.disabled, true);
  releaseSlow(); await flush(); await flush();
  assert.deepEqual(page.titles(), ['Titular de elpais', 'Titular de abc']);
  assert.equal(page.button.disabled, false);
});

test('a paper the server could not read links to its home page; a failed request keeps the old title', async () => {
  const page = setup(); await flush(); await flush();
  page.advance(5 * 60 * 1000);
  page.setFetch(async (url) => idOf(url) === 'elpais'
    ? { ok: true, json: async () => ({ id: 'elpais', title: null, url: null }) }
    : Promise.reject(new Error('offline')));
  await page.click();
  assert.equal(page.rows[0].headline.children[0].textContent, 'No disponible · abrir portada');
  assert.equal(page.rows[0].headline.children[0].href, 'https://elpais.com/');
  assert.equal(page.rows[1].headline.children[0].textContent, 'Titular de abc');
});

test('unsafe links never become a headline link', async () => {
  const page = setup({ fetcher: async (url) => ok(idOf(url), 'Título', 'javascript:alert(1)') });
  await flush(); await flush();
  assert.equal(page.rows[0].headline.children[0].href, 'https://elpais.com/');
});

test('recent saved headlines are shown without asking again; old ones refresh by themselves', async () => {
  const first = setup(); await flush(); await flush();
  const reopened = setup({ fetcher: async () => { throw new Error('must not fetch'); },
    storage: first.storage, now: NOW + 60 * 1000 });
  await flush();
  assert.equal(reopened.calls.length, 0);
  assert.deepEqual(reopened.titles(), ['Titular de elpais', 'Titular de abc']);
  assert.equal(reopened.time.dateTime, first.time.dateTime);

  const later = setup({ fetcher: async (url) => ok(idOf(url), 'Nuevo ' + idOf(url)),
    storage: first.storage, now: NOW + 10 * 60 * 1000 });
  assert.deepEqual(later.titles(), ['Titular de elpais', 'Titular de abc']);
  await flush(); await flush();
  assert.equal(later.calls.length, 2);
  assert.deepEqual(later.titles(), ['Nuevo elpais', 'Nuevo abc']);
});

test('coming back to the app refreshes only when the headlines are stale', async () => {
  const page = setup(); await flush(); await flush();
  page.resume(); await flush();
  assert.equal(page.calls.length, 2);
  page.advance(4 * 60 * 1000);
  page.resume(); await flush(); await flush();
  assert.equal(page.calls.length, 4);
});

test('if every paper fails the previous time stays and the button allows a retry', async () => {
  const page = setup(); await flush(); await flush();
  const previous = page.time.dateTime;
  page.advance(5 * 60 * 1000);
  for (const fail of [async () => { throw new Error('offline'); }, async () => ({ ok: false, status: 503 }),
    async () => ({ ok: true, json: async () => { throw new Error('bad JSON'); } })]) {
    page.setFetch(fail);
    await page.click();
    assert.equal(page.time.dateTime, previous);
    assert.match(page.status.textContent, /No se pudo actualizar/);
    assert.equal(page.button.disabled, false);
    assert.equal(page.list.attributes['aria-busy'], 'false');
  }
});

test('repeated clicks do not start overlapping requests', async () => {
  const page = setup(); await flush(); await flush();
  const pending = [];
  page.setFetch((url) => new Promise((resolve) => pending.push(() => resolve(ok(idOf(url))))));
  const first = page.click(); page.click();
  assert.equal(page.calls.length, 4);
  assert.equal(page.button.disabled, true);
  pending.forEach((release) => release()); await first;
  assert.equal(page.button.disabled, false);
});

test('a hung request times out and gives the button back', async () => {
  const page = setup({ fetcher: (_, { signal }) => new Promise((_, reject) =>
    signal.addEventListener('abort', () => reject(new Error('timeout')))) });
  page.timeoutAll(); await flush(); await flush();
  assert.equal(page.button.disabled, false);
  assert.match(page.status.textContent, /No se pudo actualizar/);
});

test('broken or blocked browser storage does not stop the page', async () => {
  for (const value of ['{', 'null', '{"headlines":{},"updated_at":"bad"}']) {
    const page = setup({ storage: new Map([['readerme:portadas:v2', value]]) });
    await flush(); await flush();
    assert.deepEqual(page.titles(), ['Titular de elpais', 'Titular de abc']);
  }
  const page = setup({ storage: { get() { throw new Error('blocked'); }, set() { throw new Error('full'); } } });
  await flush(); await flush();
  assert.equal(page.status.textContent, '');
  assert.deepEqual(page.titles(), ['Titular de elpais', 'Titular de abc']);
});
