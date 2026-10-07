// How often an open page reads itself again (static/js/live-regions.js).
//
// Owner, 2026-10-05: "Every event should update ... in real time and fast";
// 2026-10-06: the app froze when many people were on, and these re-reads were
// the main cause; 2026-10-07: "everything should update live as data change".
// More pages are read again now, so the pace matters: one save is on the page
// at once, and changes that keep coming cost one read per rest, not one per
// change. The real script runs here against a clock the test moves.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

const SCRIPT = fs.readFileSync('static/js/live-regions.js', 'utf8');

function page({ readMs = 300 } = {}) {
  let now = 0;
  let seq = 0;
  const timers = new Map();
  const reads = [];
  const state = { ticked: false, source: null, swaps: 0 };

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
    addEventListener() {},
    dispatchEvent() {},
    getElementById: () => null,
    importNode: () => fresh,
    querySelectorAll: () => [region],
    // busy(): the one question it asks the page besides the drawer.
    querySelector: (selector) => (state.ticked && selector.includes('td input[type="checkbox"]:checked') ? {} : null),
  };
  function EventSource() { state.source = this; this.close = () => {}; }
  const sandbox = {
    document,
    window: { EventSource, addEventListener() {} },
    location: { href: 'http://edify.test/work-plan' },
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
  sandbox.EventSource = EventSource;
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
  const changed = () => state.source.onmessage({ data: JSON.stringify({ type: 'plan.changed', at: String(now) }) });
  return { reads, state, wait, changed, now: () => now };
}

test('one change is read about half a second later', async () => {
  const p = page();
  await p.wait(2000); // the stream opens a moment after the page
  p.changed();
  const at = p.now();
  await p.wait(3000);
  assert.equal(p.reads.length, 1);
  assert.ok(p.reads[0] - at <= 500, `read ${p.reads[0] - at} ms after the change`);
  assert.equal(p.state.swaps, 1);
});

test('a save in several steps is whole on the page within two seconds', async () => {
  const p = page();
  await p.wait(2000);
  p.changed(); // the first record of the save
  await p.wait(500);
  p.changed(); // the last one, while the page is reading the first
  const last = p.now();
  await p.wait(6000);
  assert.equal(p.reads.length, 2);
  assert.ok(p.reads[1] - last <= 2000, `second read ${p.reads[1] - last} ms after the last step`);
});

test('changes that keep coming cost one read per rest, and the rest grows to sixteen seconds', async () => {
  const p = page();
  await p.wait(2000);
  for (let i = 0; i < 240; i += 1) { // two minutes of a change every half second
    p.changed();
    await p.wait(500);
  }
  const gaps = p.reads.slice(1).map((at, i) => at - p.reads[i]);
  // 1 s, 2 s, 4 s, 8 s, then sixteen for as long as it lasts.
  assert.ok(gaps[0] <= 2000, `first gap ${gaps[0]}`);
  assert.ok(gaps.slice(4).every((gap) => gap >= 16000), `gaps ${gaps}`);
  assert.ok(gaps.every((gap, i) => i === 0 || gap >= gaps[i - 1]), `gaps never shrink while it lasts: ${gaps}`);
  // Resting one second, as it did, this is eighty reads.
  assert.ok(p.reads.length <= 12, `${p.reads.length} reads in two minutes`);
});

test('after a quiet spell the next change is read at once again', async () => {
  const p = page();
  await p.wait(2000);
  for (let i = 0; i < 120; i += 1) { p.changed(); await p.wait(500); }
  await p.wait(40000); // the last change is read, and then nothing comes
  const before = p.reads.length;
  p.changed();
  const at = p.now();
  await p.wait(1000);
  assert.equal(p.reads.length, before + 1);
  assert.ok(p.reads[before] - at <= 500);
  // And the rest after it is a second again, not sixteen.
  await p.wait(1500);
  p.changed();
  const again = p.now();
  await p.wait(2000);
  assert.equal(p.reads.length, before + 2);
  assert.ok(p.reads[before + 1] - again <= 1000);
});

test('nothing is read under a ticked row, and the change is not lost', async () => {
  const p = page();
  await p.wait(2000);
  p.state.ticked = true;
  p.changed();
  await p.wait(10000);
  assert.equal(p.reads.length, 0);
  p.state.ticked = false;
  await p.wait(1500);
  assert.equal(p.reads.length, 1);
});
