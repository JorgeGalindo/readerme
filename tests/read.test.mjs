import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../static/read.js', import.meta.url), 'utf8');
const urlCases = JSON.parse(readFileSync(new URL('./read-url-cases.json', import.meta.url), 'utf8'));
const READ = 'readerme_read', PENDING = 'readerme_read_pending';
const ok = () => ({ ok: true, json: async () => ({ ok: true }) });
const tick = () => new Promise((resolve) => setImmediate(resolve));
function deferred() { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; }

async function reader({ urls = ['https://example.com/a', 'https://example.com/b'], saved = {}, blocked = false, denyWrite = () => false, fetch = async () => ok() } = {}) {
  const listeners = {}, timers = new Map(), calls = [];
  let nextTimer = 0, reloads = 0, request = fetch;
  const cards = urls.map((url) => ({ dataset: { url }, style: {} }));
  const section = { hidden: false, querySelectorAll: () => cards };
  const ids = { readStatus: { hidden: true, textContent: '' }, readEmpty: { hidden: true }, unreadCount: { textContent: '' } };
  const listen = (event, fn) => { (listeners[event] ||= []).push(fn); };
  const document = {
    visibilityState: 'visible', addEventListener: listen,
    getElementById: (id) => ids[id],
    querySelectorAll: (selector) => selector.startsWith('.card') ? cards : [section],
  };
  const window = {
    addEventListener: listen, confirm: () => true,
    location: { reload() { reloads++; } },
    localStorage: {
      getItem(k) { if (blocked) throw new Error('denied'); return saved[k] ?? null; },
      setItem(k, v) { if (blocked || denyWrite(k, v)) throw new Error('denied'); saved[k] = v; },
      removeItem(k) { if (blocked) throw new Error('denied'); delete saved[k]; },
    },
  };
  vm.runInNewContext(source, {
    window, document, URL, AbortController,
    fetch: async (url, opts) => { calls.push({ url, body: JSON.parse(opts.body) }); return request(url, opts); },
    setTimeout(fn, ms) { const id = ++nextTimer; timers.set(id, { fn, ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  await tick();
  return {
    cards, ids, saved, calls, section,
    mark(i = 0) { return window.markRead({ closest: () => cards[i] }); },
    reset: () => window.resetRead(),
    setFetch(fn) { request = fn; },
    reloads: () => reloads,
    async emit(event, value = {}) { for (const fn of listeners[event] || []) fn(value); await tick(); },
    async timeout(ms) { const t = [...timers].find(([, v]) => v.ms === ms); assert.ok(t, `temporizador de ${ms} ms`); timers.delete(t[0]); t[1].fn(); await tick(); },
    pending: () => JSON.parse(saved[PENDING] || '{}'),
  };
}

test('las claves URL coinciden con las del servidor sin perder parámetros repetidos ni caracteres', async () => {
  const r = await reader({ urls: urlCases.map((c) => c.raw) });
  for (let i = 0; i < urlCases.length; i++) await r.mark(i);
  assert.deepEqual(r.calls.map((c) => c.body.url), urlCases.map((c) => c.normalized));
});

test('las lecturas se guardan en orden y se vacía la cola solo tras confirmarlas', async () => {
  const first = deferred();
  const r = await reader({ fetch: () => first.promise });
  const a = r.mark(0), b = r.mark(1);
  assert.equal(r.calls.length, 1);
  assert.equal(Object.keys(r.pending()).length, 2);
  r.setFetch(async () => ok()); first.resolve(ok());
  await Promise.all([a, b]);
  assert.deepEqual(r.calls.map((c) => c.body.url), ['https://example.com/a', 'https://example.com/b']);
  assert.deepEqual(r.pending(), {});
});

test('una lectura sin conexión sobrevive a la recarga y se reenvía al abrir otra página', async () => {
  const saved = {};
  const offline = await reader({ saved, fetch: async () => { throw new Error('offline'); } });
  await offline.mark();
  assert.equal(offline.cards[0].style.display, 'none');
  assert.equal(Object.keys(offline.pending()).length, 1);
  assert.match(offline.ids.readStatus.textContent, /pendientes de sincronizar/);
  const online = await reader({ saved });
  assert.equal(online.calls.length, 1);
  assert.deepEqual(online.pending(), {});
  assert.equal(online.cards[0].style.display, 'none');
});

test('HTTP fallido, JSON inválido y respuestas negativas conservan el reintento', async () => {
  for (const response of [
    { ok: false },
    { ok: true, json: async () => ({ ok: false }) },
    { ok: true, json: async () => ({}) },
    { ok: true, json: async () => { throw new Error('not JSON'); } },
  ]) {
    const r = await reader({ fetch: async () => response });
    await r.mark();
    assert.equal(Object.keys(r.pending()).length, 1);
    r.setFetch(async () => ok()); await r.emit('online');
    assert.deepEqual(r.pending(), {});
    assert.equal(r.ids.readStatus.hidden, true);
  }
});

test('un fallo temporal se reintenta sin exigir que cambie el estado de conexión', async () => {
  const r = await reader({ fetch: async () => ({ ok: false }) });
  await r.mark(); r.setFetch(async () => ok());
  await r.timeout(30000);
  assert.deepEqual(r.pending(), {});
});

test('una petición colgada se cancela y conserva la lectura pendiente', async () => {
  const r = await reader({ fetch: (_, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('timeout')))) });
  const marking = r.mark();
  await r.timeout(12000); await marking;
  assert.equal(Object.keys(r.pending()).length, 1);
});

test('borrar leídos espera al guardado en curso para que no reaparezca después del borrado', async () => {
  const first = deferred();
  const r = await reader({ fetch: () => first.promise });
  const marking = r.mark();
  const clearing = r.reset();
  assert.equal(r.calls.length, 1);
  r.setFetch(async () => ok()); first.resolve(ok());
  await marking; await clearing;
  assert.deepEqual(r.calls.map((c) => c.url), ['/api/read', '/api/read/clear']);
  assert.equal(r.saved[READ], undefined);
  assert.equal(r.saved[PENDING], undefined);
  assert.equal(r.reloads(), 1);
});

test('borrar leídos conserva los datos y permite reintentar si falla el servidor', async () => {
  const r = await reader(); await r.mark();
  const before = r.saved[READ];
  r.setFetch(async () => ({ ok: false })); await r.reset();
  assert.equal(r.saved[READ], before);
  assert.equal(r.reloads(), 0);
  assert.match(r.ids.readStatus.textContent, /No se pudo borrar/);
  r.setFetch(async () => ok()); await r.reset();
  assert.equal(r.reloads(), 1);
});

test('con almacenamiento bloqueado la tarjeta espera a que confirme el servidor', async () => {
  const response = deferred();
  const r = await reader({ blocked: true, fetch: () => response.promise });
  const marking = r.mark();
  assert.equal(r.cards[0].style.display, '');
  response.resolve(ok()); await marking;
  assert.equal(r.cards[0].style.display, 'none');
});

test('si fallan navegador y servidor la tarjeta sigue visible y puede reintentarse', async () => {
  const r = await reader({ blocked: true, fetch: async () => { throw new Error('offline'); } });
  await r.mark();
  assert.equal(r.cards[0].style.display, '');
  assert.match(r.ids.readStatus.textContent, /No se pudo guardar/);
  r.setFetch(async () => ok()); await r.emit('online');
  assert.equal(r.cards[0].style.display, 'none');
});

test('marcar el último artículo actualiza contador, secciones y estado vacío', async () => {
  const r = await reader(); await r.mark(0);
  assert.equal(r.ids.unreadCount.textContent, '1');
  assert.equal(r.section.hidden, false);
  await r.mark(1);
  assert.equal(r.ids.unreadCount.textContent, '0');
  assert.equal(r.section.hidden, true);
  assert.equal(r.ids.readEmpty.hidden, false);
});

test('todas las tarjetas de una URL se ocultan juntas', async () => {
  const r = await reader({ urls: ['https://example.com/a', 'https://example.com/a/?utm_source=x'] });
  await r.mark();
  assert.ok(r.cards.every((c) => c.style.display === 'none'));
});

test('migra el formato antiguo y tolera valores inválidos en localStorage', async () => {
  const legacy = await reader({ saved: { [READ]: '["https://example.com/a/?utm_source=x"]' } });
  assert.equal(legacy.cards[0].style.display, 'none');
  assert.ok(JSON.parse(legacy.saved[READ])['https://example.com/a']);
  for (const raw of ['null', '42', '"texto"', '{mal json']) {
    const r = await reader({ saved: { [READ]: raw } });
    await r.mark();
    assert.equal(r.cards[0].style.display, 'none');
  }
});

test('los cambios en otra pestaña se reflejan en la lista actual', async () => {
  const r = await reader();
  r.saved[READ] = JSON.stringify({ 'https://example.com/a': Date.now() });
  await r.emit('storage', { key: READ });
  assert.equal(r.cards[0].style.display, 'none');
});

test('un JSON antiguo ilegible no impide guardar nuevos reintentos sin conexión', async () => {
  const r = await reader({ saved: { [READ]: '{mal json' }, fetch: async () => { throw new Error('offline'); } });
  await r.mark();
  assert.equal(Object.keys(r.pending()).length, 1);
  assert.equal(r.cards[0].style.display, 'none');
});

test('si solo cabe la cola pendiente, la siguiente página recupera la lectura confirmada', async () => {
  const saved = {};
  const first = await reader({
    saved,
    denyWrite: (key, value) => key === READ && value !== '{}',
    fetch: async () => { throw new Error('offline'); },
  });
  await first.mark();
  assert.equal(Object.keys(first.pending()).length, 1);
  const retry = await reader({ saved });
  assert.equal(retry.calls.length, 1);
  assert.deepEqual(retry.pending(), {});
  const restored = await reader({ saved });
  assert.equal(restored.cards[0].style.display, 'none');
  assert.equal(restored.calls.length, 0);
});
