// What an open page reads again by itself (static/js/live-regions.js).
//
// Owner, 2026-10-14: "behave like salesforce where a user has to refresh for
// the data to be updated", and of one's own saves: "everything is updated
// upon refresh icon clicked. so that the save, reschedule, schedule,
// complete, cancel... functionalities can be fast". So the page follows
// nothing: no stream, and a save reads nothing. What remains is a page
// finishing itself (EdifyLive.refresh). The real script runs here against a
// clock the test moves.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

const SCRIPT = fs.readFileSync('static/js/live-regions.js', 'utf8');

function page({ readMs = 300, regions = true } = {}) {
  let now = 0;
  let seq = 0;
  const timers = new Map();
  const reads = [];
  const state = { ticked: false, swaps: 0, opened: 0, drawerOpen: false, reloads: 0 };
  const heard = {};

  const schedule = (fn, ms, every) => {
    seq += 1;
    timers.set(seq, { fn, at: now + ms, every });
    return seq;
  };
  const region = { id: 'plan', replaceWith() { state.swaps += 1; } };
  const fresh = { querySelectorAll: () => [] };
  const document = {
    hidden: false,
    activeElement: null,
    addEventListener(type, fn) { (heard[type] = heard[type] || []).push(fn); },
    dispatchEvent() {},
    getElementById: (id) => (id === 'drawer-container' ? { childElementCount: state.drawerOpen ? 1 : 0 } : null),
    importNode: () => fresh,
    querySelectorAll: () => (regions ? [region] : []),
    // busy(): the one question it asks the page besides the drawer.
    querySelector: (selector) => (state.ticked && selector.includes('td input[type="checkbox"]:checked') ? {} : null),
  };
  function EventSource() { state.opened += 1; this.close = () => {}; }
  const sandbox = {
    document,
    window: { EventSource, addEventListener() {} },
    EventSource,
    location: { href: 'http://edify.test/work-plan', reload() { state.reloads += 1; } },
    Date: { now: () => now },
    setTimeout: (fn, ms) => schedule(fn, ms, 0),
    clearTimeout: (id) => timers.delete(id),
    setInterval: (fn, ms) => schedule(fn, ms, ms),
    CustomEvent: function CustomEvent() {},
    DOMParser: function DOMParser() { this.parseFromString = () => ({ getElementById: () => fresh }); },
    fetch: () => {
      reads.push(now);
      return new Promise((resolve) => schedule(() => resolve({ ok: true, redirected: false, text: () => '<html></html>' }), readMs, 0));
    },
  };
  vm.runInNewContext(SCRIPT, sandbox);

  const settle = () => new Promise((resolve) => setImmediate(resolve));
  // The clock, moved a tenth of a second at a time; whatever came due runs.
  async function wait(ms) {
    const end = now + ms;
    while (now < end) {
      now += 100;
      for (const [id, timer] of [...timers]) {
        if (timer.at > now) continue;
        if (timer.every) timer.at += timer.every; else timers.delete(id);
        timer.fn();
      }
      await settle();
    }
  }
  const hear = (type) => (heard[type] || []).forEach((fn) => fn({}));
  return { reads, state, wait, hear, live: sandbox.window.EdifyLive };
}

test('no stream is opened, however long the page stays and whatever settles', async () => {
  const p = page();
  await p.wait(2000);
  p.hear('htmx:afterSettle');
  p.hear('visibilitychange');
  await p.wait(60000);
  assert.equal(p.state.opened, 0);
  assert.equal(p.reads.length, 0, 'the page read itself with nobody asking');
});

test('a save reads nothing and reloads nothing: Refresh brings the page up to date', async () => {
  const p = page();
  await p.wait(2000);
  p.state.drawerOpen = true;
  p.live.saved();
  p.state.drawerOpen = false;
  await p.wait(10000);
  assert.equal(p.reads.length, 0);
  assert.equal(p.state.reloads, 0);
});

test('a page finishing itself reads its region once and swaps it in', async () => {
  const p = page();
  p.live.refresh();
  await p.wait(500);
  assert.equal(p.reads.length, 1);
  assert.equal(p.state.swaps, 1);
  await p.wait(10000);
  assert.equal(p.reads.length, 1, 'one ask, one read');
});

test('nothing is read under a ticked row or an open drawer, and the ask is not lost', async () => {
  const p = page();
  p.state.ticked = true;
  p.live.refresh();
  await p.wait(5000);
  assert.equal(p.reads.length, 0);
  p.state.ticked = false;
  p.state.drawerOpen = true;
  await p.wait(5000);
  assert.equal(p.reads.length, 0);
  p.state.drawerOpen = false;
  await p.wait(1500);
  assert.equal(p.reads.length, 1);
});

test('a page with no live region reads nothing', async () => {
  const p = page({ regions: false });
  p.live.refresh();
  p.live.saved();
  await p.wait(5000);
  assert.equal(p.reads.length, 0);
  assert.equal(p.state.reloads, 0);
});
