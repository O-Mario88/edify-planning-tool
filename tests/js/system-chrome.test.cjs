// The phone's own bars take the page canvas, --edify-bg (2026-10-24): the
// browser's address bar through <meta name="theme-color"> (the approved light
// workspace's colour, templates/base.html), and in the iOS and Android app the
// status bar itself, its icons dark on a light canvas and light on a dark one
// (static/js/system-chrome.js). The meta was left empty and the app's bar was
// the old brand blue.
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { hexOf, isLight, apply } = require('../../static/js/system-chrome.js');

test('icons are dark on a light bar and light on a dark one', () => {
  assert.equal(isLight('#ffffff'), true);
  assert.equal(isLight('#fdfefe'), true);
  assert.equal(isLight('#0b1219'), false);
  assert.equal(isLight('#062847'), false);
});

test('the canvas token is read as a colour whichever way it is written', () => {
  assert.equal(hexOf(' #dbe4eb'), '#dbe4eb');
  assert.equal(hexOf('#ABC'), '#aabbcc');
  assert.equal(hexOf('rgb(0, 29, 57)'), null);
  assert.equal(hexOf(''), null);
});

function fakeWindow({ native = false, platform = 'android', canvas = ' #dbe4eb' } = {}) {
  const calls = [];
  const meta = { content: '' };
  const document = {
    documentElement: 'html',
    querySelector: sel => (sel === 'meta[name="theme-color"]' ? meta : null),
  };
  const win = {
    document,
    getComputedStyle: () => ({ getPropertyValue: name => (name === '--edify-bg' ? canvas : '') }),
    Capacitor: native
      ? {
          isNativePlatform: () => true,
          getPlatform: () => platform,
          Plugins: {
            StatusBar: {
              setStyle: o => calls.push(['style', o.style]),
              setBackgroundColor: o => calls.push(['background', o.color]),
            },
          },
        }
      : undefined,
  };
  return { win, meta, calls };
}

test('in a browser only the address bar colour is set', () => {
  const { win, meta, calls } = fakeWindow();
  assert.equal(apply(win), '#dbe4eb');
  assert.equal(meta.content, '#dbe4eb');
  assert.deepEqual(calls, []);
});

test('on Android the status bar takes the canvas and dark icons', () => {
  const { win, calls } = fakeWindow({ native: true, platform: 'android' });
  apply(win);
  assert.deepEqual(calls, [['style', 'LIGHT'], ['background', '#dbe4eb']]);
});

test('on iOS the page shows through, so only the icons are set', () => {
  const { win, calls } = fakeWindow({ native: true, platform: 'ios', canvas: '#001d39' });
  apply(win);
  assert.deepEqual(calls, [['style', 'DARK']]);
});
