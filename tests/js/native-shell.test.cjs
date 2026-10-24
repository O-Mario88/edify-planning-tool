// The iOS and Android app's bridge (static/js/native-shell.js): a link that
// opens the app reaches a page of this site and nowhere else, the back button
// closes a drawer before it leaves a page, and a browser is left alone.
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { internalPath, start } = require('../../static/js/native-shell.js');

const ORIGIN = 'https://edifyplanning.app';

test('a link into this site opens that page with its query and anchor', () => {
  assert.equal(internalPath(`${ORIGIN}/my-plan/abc?tab=x#row`, ORIGIN), '/my-plan/abc?tab=x#row');
  assert.equal(internalPath('edify://open/notifications', ORIGIN), '/notifications');
  assert.equal(internalPath('edify://open', ORIGIN), '/');
});

test('a link anywhere else is refused', () => {
  for (const raw of [
    'https://evil.example/home',
    'http://edifyplanning.app/home',
    'https://edifyplanning.app.evil.example/home',
    'edify://elsewhere/home',
    'edify://open//evil.example/x',
    'javascript:alert(1)',
    'not a url',
    '',
    null,
  ]) {
    assert.equal(internalPath(raw, ORIGIN), null, String(raw));
  }
});

function fakeWindow({ native = true, platform = 'android', path = '/schools', drawer = false } = {}) {
  const listeners = {};
  const calls = [];
  const attrs = {};
  const viewport = { content: 'width=device-width, initial-scale=1.0, viewport-fit=cover' };
  const document = {
    viewport,
    querySelector: sel => (sel === 'meta[name="viewport"]'
      ? { getAttribute: () => viewport.content, setAttribute: (k, v) => { viewport.content = v; } }
      : null),
    documentElement: { setAttribute: (k, v) => { attrs[k] = v; } },
    getElementById: id => (id === 'drawer-container' ? { children: drawer ? [{}] : [] } : null),
    querySelectorAll: () => [],
    dispatchEvent: event => calls.push(['key', event.key]),
  };
  const win = {
    document,
    KeyboardEvent: function (type, init) { this.type = type; this.key = init.key; },
    location: { origin: ORIGIN, pathname: path, assign: to => calls.push(['assign', to]) },
    history: { back: () => calls.push(['back']) },
    Capacitor: {
      isNativePlatform: () => native,
      getPlatform: () => platform,
      Plugins: {
        App: {
          addListener: (name, fn) => { listeners[name] = fn; },
          minimizeApp: () => calls.push(['minimize']),
        },
      },
    },
  };
  return { win, listeners, calls, attrs };
}

test('in a browser nothing is wired', () => {
  const { win, listeners, attrs } = fakeWindow({ native: false });
  assert.equal(start(win), false);
  assert.deepEqual(listeners, {});
  assert.deepEqual(attrs, {});
});

test('the app marks its platform and follows only links into this site', () => {
  const { win, listeners, calls, attrs } = fakeWindow({ platform: 'ios' });
  assert.equal(start(win), true);
  assert.equal(attrs['data-native-app'], 'ios');
  listeners.appUrlOpen({ url: `${ORIGIN}/activities/a1/complete` });
  listeners.appUrlOpen({ url: 'https://evil.example/login' });
  assert.deepEqual(calls, [['assign', '/activities/a1/complete']]);
});

test('on iOS a tapped field no longer zooms the page; Android is left alone', () => {
  const ios = fakeWindow({ platform: 'ios' });
  start(ios.win);
  assert.match(ios.win.document.viewport.content, /maximum-scale=1$/);
  start(ios.win);
  assert.equal((ios.win.document.viewport.content.match(/maximum-scale/g) || []).length, 1);

  const android = fakeWindow({ platform: 'android' });
  start(android.win);
  assert.doesNotMatch(android.win.document.viewport.content, /maximum-scale/);
});

test('back closes an open drawer before it leaves the page', () => {
  const { win, listeners, calls } = fakeWindow({ drawer: true });
  start(win);
  listeners.backButton({ canGoBack: true });
  assert.deepEqual(calls, [['key', 'Escape']]);
});

test('back goes back a page, and on Home leaves the app in the background', () => {
  const page = fakeWindow({ path: '/schools' });
  start(page.win);
  page.listeners.backButton({ canGoBack: true });
  assert.deepEqual(page.calls, [['back']]);

  const home = fakeWindow({ path: '/home' });
  start(home.win);
  home.listeners.backButton({ canGoBack: true });
  assert.deepEqual(home.calls, [['minimize']]);
});
