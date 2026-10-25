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

test('on iOS the page runs under the status bar, and only the icons are set', () => {
  // The bar's strip was the config's fixed slate, so white icons on a dark
  // page were unreadable on it (2026-10-25): the page draws there itself.
  const { win, calls } = fakeWindow({ native: true, platform: 'ios', canvas: '#001d39' });
  win.Capacitor.Plugins.StatusBar.setOverlaysWebView = o => calls.push(['overlay', o.overlay]);
  apply(win);
  apply(win);
  assert.deepEqual(calls, [['overlay', true], ['style', 'DARK'], ['style', 'DARK']]);
});

// In the app the bars sit beside the page's own top and bottom, not its canvas
// (2026-10-25): on an iPhone the page runs under both, so Android's bars take
// the colours actually there, the white top bar above and the bottom
// navigation below, and an iPhone's icons follow the top of the page.
const { rgbHex, surfaceAt } = require('../../static/js/system-chrome.js');

test('a computed background is read as a colour only when it is opaque', () => {
  assert.equal(rgbHex('rgb(255, 255, 255)'), '#ffffff');
  assert.equal(rgbHex('rgba(10, 77, 134, 1)'), '#0a4d86');
  assert.equal(rgbHex('rgb(231 244 252)'), '#e7f4fc');
  assert.equal(rgbHex('rgba(0, 0, 0, 0)'), null);
  assert.equal(rgbHex('rgba(255, 255, 255, 0.5)'), null);
  assert.equal(rgbHex('transparent'), null);
});

// A page whose top is a white bar on a slate canvas, with a navy footer.
function pageWindow({ platform = 'android', withChrome = true } = {}) {
  const calls = [];
  const canvas = { backgroundColor: 'rgb(219, 228, 235)', parentElement: null, nodeType: 1 };
  const topbar = { backgroundColor: 'rgb(255, 255, 255)', parentElement: canvas, nodeType: 1 };
  const label = { backgroundColor: 'rgba(0, 0, 0, 0)', parentElement: topbar, nodeType: 1 };
  const footer = { backgroundColor: 'rgb(0, 29, 57)', parentElement: canvas, nodeType: 1 };
  const meta = { content: '' };
  const plugins = {
    StatusBar: {
      setStyle: o => calls.push(['style', o.style]),
      setBackgroundColor: o => calls.push(['background', o.color]),
    },
  };
  if (withChrome) plugins.EdifyChrome = { setBars: o => { calls.push(['bars', o.top, o.bottom]); return Promise.resolve(); } };
  const win = {
    innerWidth: 400,
    innerHeight: 800,
    document: {
      documentElement: 'html',
      querySelector: sel => (sel === 'meta[name="theme-color"]' ? meta : null),
      elementFromPoint: (x, y) => (y < 50 ? label : y > 750 ? footer : canvas),
    },
    getComputedStyle: el =>
      el === 'html'
        ? { getPropertyValue: name => (name === '--edify-bg' ? '#dbe4eb' : '') }
        : { backgroundColor: el.backgroundColor },
    Capacitor: { isNativePlatform: () => true, getPlatform: () => platform, Plugins: plugins },
  };
  return { win, calls, label, footer };
}

test('the colour at a point is the nearest opaque background there', () => {
  const { win } = pageWindow();
  assert.equal(surfaceAt(win, 200, 1), '#ffffff');
  assert.equal(surfaceAt(win, 200, 799), '#001d39');
});

test("Android's bars take the page's top and bottom, through the app's plugin", () => {
  const { win, calls } = pageWindow();
  assert.equal(apply(win), '#dbe4eb');
  assert.deepEqual(calls, [['bars', '#ffffff', '#001d39']]);
});

test('an Android build from before the plugin still colours its status bar', () => {
  const { win, calls } = pageWindow({ withChrome: false });
  apply(win);
  assert.deepEqual(calls, [['style', 'LIGHT'], ['background', '#dbe4eb']]);
});

test("an iPhone's status bar icons follow the top of the page", () => {
  const { win, calls, label } = pageWindow({ platform: 'ios' });
  label.parentElement = { backgroundColor: 'rgb(0, 29, 57)', parentElement: null, nodeType: 1 };
  apply(win);
  assert.deepEqual(calls, [['style', 'DARK']]);
});

test('a see-through bar is read as it looks: blended onto what is under it', () => {
  // Home's top bar is white at 90% over the slate canvas.
  const { win, label } = pageWindow();
  label.parentElement = {
    backgroundColor: 'rgba(255, 255, 255, 0.9)',
    nodeType: 1,
    parentElement: { backgroundColor: 'rgb(219, 228, 235)', parentElement: null, nodeType: 1 },
  };
  assert.equal(surfaceAt(win, 200, 1), '#fbfcfd');
});

test('what is painted there decides, and an invisible overlay counts for nothing', () => {
  // The bell drawer's backdrop covers the page at opacity 0 (it only catches
  // taps); the white top bar under it is what shows.
  const { win } = pageWindow();
  const layer = (backgroundColor, opacity = '1') => ({ backgroundColor, opacity, nodeType: 1, parentElement: null });
  win.document.elementsFromPoint = () => [
    layer('rgba(6, 27, 45, 0.58)', '0'),
    layer('rgba(255, 255, 255, 0.9)'),
    layer('rgba(0, 0, 0, 0)'),
    layer('rgb(219, 228, 235)'),
  ];
  win.getComputedStyle = el => (el === 'html' ? { getPropertyValue: () => '#dbe4eb' } : el);
  assert.equal(surfaceAt(win, 200, 1), '#fbfcfd');
});

test('Android is told again only when the colours change', () => {
  const { win, calls } = pageWindow();
  apply(win);
  apply(win);
  assert.deepEqual(calls, [['bars', '#ffffff', '#001d39']]);
});

test("a gradient is read at the bar's own end: the More menu's navy, top and bottom", () => {
  const { win } = pageWindow();
  const sidebar = {
    backgroundColor: 'rgba(0, 0, 0, 0)',
    backgroundImage:
      'radial-gradient(circle at 10% 5%, rgba(123, 189, 232, 0.12), rgba(0, 0, 0, 0) 22rem), ' +
      'linear-gradient(rgb(0, 29, 57) 0%, rgb(6, 40, 71) 56%, rgb(10, 77, 134) 100%)',
    opacity: '1',
  };
  win.document.elementsFromPoint = () => [sidebar, { backgroundColor: 'rgb(219, 228, 235)', opacity: '1' }];
  win.getComputedStyle = el => (el === 'html' ? { getPropertyValue: () => '#dbe4eb' } : el);
  assert.equal(surfaceAt(win, 200, 1), '#001d39');
  assert.equal(surfaceAt(win, 200, 799), '#0a4d86');
});
