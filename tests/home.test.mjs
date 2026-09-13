import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../static/home.js', import.meta.url), 'utf8');
function setup({ path = '/main', ios = true, storage = new Map() } = {}) {
  const events = {}, changes = [];
  const document = { visibilityState: 'visible', addEventListener: (name, fn) => { events[name] = fn; } };
  vm.runInNewContext(source, {
    document, URL,
    navigator: { userAgent: ios ? 'iPhone' : 'Linux', platform: '', maxTouchPoints: 0 },
    location: { pathname: path, origin: 'https://readerme.vercel.app', href: 'https://readerme.vercel.app' + path, replace: (url) => changes.push(url) },
    sessionStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    window: { addEventListener: (name, fn) => { events[name] = fn; } },
  });
  return { changes, storage, events,
    visible(state) { document.visibilityState = state; events.visibilitychange(); },
    click(href, extra = {}) { events.click({ button: 0, target: { closest: () => ({ href }) }, ...extra }); },
  };
}

test('normal navigation between Readerme tabs stays on the chosen tab', () => {
  const page = setup();
  page.events.pageshow({ persisted: false });
  page.click('https://readerme.vercel.app/papers');
  page.events.focus();
  assert.deepEqual(page.changes, []);
  assert.equal(page.storage.size, 0);
});

test('reopening the iOS app returns to Portadas', () => {
  const page = setup();
  page.visible('hidden'); page.visible('visible');
  assert.deepEqual(page.changes, ['/']);
});

test('returning from an article survives a full document reload', () => {
  const page = setup();
  page.click('https://elpais.com/noticia');
  const returned = setup({ storage: page.storage });
  returned.events.pageshow({ persisted: false });
  assert.deepEqual(returned.changes, ['/']);
  assert.equal(page.storage.size, 0);
});

test('closing the internal news browser or restoring iOS history returns home', () => {
  const page = setup();
  page.click('https://www.elmundo.es/noticia');
  page.events.focus();
  assert.deepEqual(page.changes, ['/']);
  const restored = setup(); restored.events.pageshow({ persisted: true });
  assert.deepEqual(restored.changes, ['/']);
});

test('returning to Portadas itself keeps the document and saved headlines', () => {
  const page = setup({ path: '/' });
  page.click('https://elpais.com/noticia');
  page.visible('hidden'); page.visible('visible');
  page.events.pageshow({ persisted: true });
  assert.deepEqual(page.changes, []);
});

test('desktop background tabs and modified clicks do not change section', () => {
  const page = setup({ ios: false });
  page.click('https://elpais.com/noticia', { metaKey: true });
  page.visible('hidden'); page.visible('visible');
  page.events.pageshow({ persisted: true });
  assert.deepEqual(page.changes, []);
});
