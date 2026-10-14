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

// Stamps compare as strings, as the server's ISO times do.
const stamp = (t) => String(t).padStart(12, '0');

function page({ readMs = 300, stamped = false, regions = true } = {}) {
  let now = 0;
  let seq = 0;
  const timers = new Map();
  const reads = [];
  // `after`: the costs a read's answer says the page is now after.
  const state = { ticked: false, source: null, swaps: 0, opened: 0, drawerOpen: false, reloads: 0, after: null };
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
  function EventSource() { state.source = this; state.opened += 1; this.close = () => {}; }
  const sandbox = {
    document,
    window: { EventSource, addEventListener() {} },
    location: { href: 'http://edify.test/work-plan', reload() { state.reloads += 1; } },
    Date: { now: () => now },
    setTimeout: (fn, ms) => schedule(fn, ms, 0),
    clearTimeout: (id) => timers.delete(id),
    setInterval: (fn, ms) => schedule(fn, ms, ms),
    CustomEvent: function CustomEvent() {},
    DOMParser: function DOMParser() { this.parseFromString = () => ({ getElementById: () => fresh }); },
    fetch: () => {
      reads.push(now);
      const began = now;
      // The server stamps a live read with its clock as the read began.
      const named = state.after;
      const headers = { get: (name) => (stamped && name === 'X-Edify-Live-At' ? stamp(began) : name === 'X-Edify-Live-After' ? named : null) };
      return new Promise((resolve) => schedule(() => resolve({ ok: true, redirected: false, headers, text: () => '<html></html>' }), readMs, 0));
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
  // `after`: the costs the notice says it follows, where it follows any.
  const changed = (at = now, after) => state.source.onmessage({ data: JSON.stringify({ type: 'plan.changed', at: stamp(at), ...(after ? { after } : {}) }) });
  // What the page hears from the document: a section settling, say.
  const hear = (type) => (heard[type] || []).forEach((fn) => fn({}));
  return { reads, state, wait, changed, hear, now: () => now, live: sandbox.window.EdifyLive };
}

test('a page passed through opens no stream, however soon a section of it settles', async () => {
  const p = page();
  await p.wait(500);
  p.hear('htmx:afterSettle'); // a section loaded in the page's first second
  await p.wait(500);
  p.hear('htmx:afterSettle');
  assert.equal(p.state.opened, 0, 'the stream was opened on a page a second old');
  await p.wait(1000); // the page has stayed
  assert.equal(p.state.opened, 1);
  p.hear('htmx:afterSettle'); // and one stream is enough
  assert.equal(p.state.opened, 1);
});

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

// A save made from the page (apps.core.htmx_saved, 2026-10-12: "saving takes
// too long"): the regions are read once, and the stream's echo of that save
// is not read again. The page used to reload whole and then read itself a
// second time.
test('a save reads the page once, as soon as its drawer has closed', async () => {
  const p = page({ stamped: true });
  await p.wait(2000);
  p.state.drawerOpen = true;
  p.live.saved();
  await p.wait(200);
  assert.equal(p.reads.length, 0, 'read under the closing drawer');
  p.state.drawerOpen = false;
  await p.wait(200);
  assert.equal(p.reads.length, 1);
  assert.equal(p.state.reloads, 0);
});

test('the stream\'s echo of the page\'s own save is not read again; a later change is', async () => {
  const p = page({ stamped: true });
  await p.wait(2000);
  const committed = p.now();
  p.live.saved();
  await p.wait(100);
  assert.equal(p.reads.length, 1);
  await p.wait(400);
  p.changed(committed); // the save, published before the read began
  await p.wait(3000);
  assert.equal(p.reads.length, 1, 'the echo was read again');
  p.changed(); // somebody else's change, after the read
  await p.wait(1000);
  assert.equal(p.reads.length, 2);
});

test('the echo that arrives while the save is still being read is not read again either', async () => {
  const p = page({ stamped: true, readMs: 600 });
  await p.wait(2000);
  const committed = p.now();
  p.live.saved();
  await p.wait(100);
  assert.equal(p.reads.length, 1);
  p.changed(committed); // the stream's notice lands while the read is in flight
  await p.wait(4000);
  assert.equal(p.reads.length, 1, 'read again for a change the first read already showed');
  p.changed(); // and a change after the read is still read
  await p.wait(1500);
  assert.equal(p.reads.length, 2);
});

test('the echo that arrives while the drawer is still closing is not read again', async () => {
  const p = page({ stamped: true });
  await p.wait(2000);
  const committed = p.now();
  p.state.drawerOpen = true;
  p.live.saved();
  p.changed(committed); // the stream's notice lands before the save's read begins
  await p.wait(200);
  p.state.drawerOpen = false;
  await p.wait(6000);
  assert.equal(p.reads.length, 1, 'read again for the change the save\'s own read showed');
  p.changed();
  await p.wait(1500);
  assert.equal(p.reads.length, 2);
});

test('a save on a page with no live region reloads it, as before', async () => {
  const p = page({ regions: false });
  p.live.saved();
  assert.equal(p.state.reloads, 1);
  assert.equal(p.reads.length, 0);
});

test('a slow page rests three times as long as its read took', async () => {
  const p = page({ readMs: 3000 });
  await p.wait(2000);
  p.changed();
  await p.wait(3600); // the read of three seconds has just ended
  p.changed();
  await p.wait(12000);
  assert.equal(p.reads.length, 2);
  assert.ok(p.reads[1] - p.reads[0] >= 3000 + 9000, `gap ${p.reads[1] - p.reads[0]} ms`);
});

// A save answers before its day is priced, and its notice goes out once the
// pricing has committed. The page that saved reads itself once the costs are
// in, and by the clock that notice is newer than the read that already shows
// it: with the save on one server process and the read on another, the page
// read itself twice after every save (2026-10-14). The notice names the costs
// it follows, and the read's answer names the costs it waited for.
test('the notice of costs the page has already read past is not read again, though its time is later', async () => {
  const p = page({ stamped: true, readMs: 600 });
  await p.wait(2000);
  p.state.after = '12';
  p.live.saved();
  await p.wait(100);
  assert.equal(p.reads.length, 1);
  p.changed(p.now() + 50, '12'); // stamped after the read began, heard while it is in flight
  await p.wait(6000);
  assert.equal(p.reads.length, 1, 'read again for costs the first read waited for');
  p.changed(p.now(), '12'); // and heard again once the read is back
  await p.wait(3000);
  assert.equal(p.reads.length, 1);
  p.state.after = null;
  p.changed(); // somebody else's change is still read
  await p.wait(1500);
  assert.equal(p.reads.length, 2);
});

test('a page that did not wait for those costs reads itself when told of them', async () => {
  const p = page({ stamped: true });
  await p.wait(2000);
  p.changed(p.now(), '12'); // another person's page: its reads name no costs
  await p.wait(1500);
  assert.equal(p.reads.length, 1);
  p.changed(p.now(), '12');
  await p.wait(3000);
  assert.equal(p.reads.length, 2);
});

test('a notice of other costs, or of anything else beside it, is read', async () => {
  const p = page({ stamped: true, readMs: 600 });
  await p.wait(2000);
  p.state.after = '12';
  p.live.saved();
  await p.wait(100);
  p.changed(p.now() + 50, '12');
  p.changed(p.now() + 60, '13'); // a second save's costs, which this read did not wait for
  await p.wait(6000);
  assert.equal(p.reads.length, 2, 'the costs it had not read past were not read');

  const q = page({ stamped: true, readMs: 600 });
  await q.wait(2000);
  q.state.after = '12';
  q.live.saved();
  await q.wait(100);
  q.changed(q.now() + 50, '12');
  q.changed(q.now() + 60); // and a plain change beside the page's own
  await q.wait(6000);
  assert.equal(q.reads.length, 2, 'a change beside the page\'s own costs was not read');
});

test('a save of several records names them all, and all must have been read past', async () => {
  const p = page({ stamped: true, readMs: 600 });
  await p.wait(2000);
  p.state.after = '12.13';
  p.live.saved();
  await p.wait(100);
  p.changed(p.now() + 50, '12.13');
  await p.wait(6000);
  assert.equal(p.reads.length, 1);
  p.changed(p.now(), '13.14');
  await p.wait(3000);
  assert.equal(p.reads.length, 2);
});
