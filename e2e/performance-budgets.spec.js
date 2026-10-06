// Performance gates that count rather than time, so they read the same on a
// laptop and on a loaded runner. Each one holds a cause the 2026-10-05 audit
// found and fixed (docs/performance-forensic-audit-2026-10-05.md):
//
//   - the page was drawn in the server's plain markup and redrawn a moment
//     later ("old UI, then new UI"): 1,200-4,500 class changes and a layout
//     shift of up to 0.40 after the first frame;
//   - one element added to a table cell restyled 52-136 % of the page —
//     all of it on a phone, where rules asked a table, a heading row, a tab
//     rail, a page header or the search box a question with `:has()` and
//     styled any element beneath;
//   - a script that measures after every write resolved style once per
//     field (98 date fields: 11 s on Strategic Priorities);
//   - a phone reports the viewport it settled on as a resize event with its
//     first frame, and every rail and table was fitted a second time;
//   - between 1024 and 1279px the sidebar is served open and shut by a script
//     as the page starts: drawn before its scripts had run, the page was
//     fitted while the sidebar slid shut, for a column narrower than its own.
//
// Chromium only: the counts come from its protocol and its trace.
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

const password = process.env.EDIFY_E2E_PASSWORD || 'edify';

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });
test.beforeEach(({}, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Counted once, in Chromium.');
  test.setTimeout(240_000);
});

// Records every DOM write with the time it was delivered, from before the
// page's own scripts run.
const RECORD_WRITES = `(() => {
  const record = { writes: [], shifts: [] };
  window.__edifyPerf = record;
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) if (!entry.hadRecentInput) record.shifts.push([entry.startTime, entry.value]);
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (error) { /* not supported */ }
  // What the server sent: the elements in the document when it had been parsed.
  // Sections a page fetches afterwards, and the charts and maps that draw
  // themselves, arrive later by design and are not the page being redrawn.
  let sent = null;
  document.addEventListener('DOMContentLoaded', () => { sent = new WeakSet(document.querySelectorAll('*')); }, true);
  // htmx names the element that is fetching: \`htmx-request\` while it waits,
  // \`htmx-swapping\` and \`htmx-settling\` as the section goes in, and takes
  // each name off again. That is a fetch announced on the element making it,
  // seven writes a dashboard with two such sections cannot do without, and
  // not the page's markup being stamped a second time. Only a write that
  // changes nothing else is set aside.
  const FETCHING = /^htmx-(?:request|swapping|settling|added)$/;
  const names = (value) => new Set((value || '').split(/\\s+/).filter(Boolean));
  const onlyAnnouncesAFetch = (before, after) => {
    const was = names(before);
    const now = names(after);
    const changed = [...was].filter((name) => !now.has(name)).concat([...now].filter((name) => !was.has(name)));
    return changed.length > 0 && changed.every((name) => FETCHING.test(name));
  };
  new MutationObserver((records) => {
    const at = performance.now();
    let classes = 0;
    // A record carries the value it replaced. What it wrote is what the next
    // record for the same element replaced, or what the element holds now.
    const wrote = new Map();
    for (let index = records.length - 1; index >= 0; index -= 1) {
      const item = records[index];
      const after = wrote.has(item.target) ? wrote.get(item.target) : item.target.getAttribute('class');
      wrote.set(item.target, item.oldValue);
      if (sent && !sent.has(item.target)) continue;
      if (item.target.closest && item.target.closest('.apexcharts-canvas, .leaflet-container, svg')) continue;
      if (onlyAnnouncesAFetch(item.oldValue, after)) continue;
      classes += 1;
    }
    if (classes) record.writes.push([at, classes]);
  }).observe(document, { subtree: true, attributes: true, attributeFilter: ['class'], attributeOldValue: true });
})();`;

async function settle(page) {
  await page.waitForLoadState('load');
  await page.waitForTimeout(2500);
}

// [account, page, whether the page fetches sections after it is shown]
const FIRST_FRAME_PAGES = [
  ['cceo1@edify.org', '/planning', false],
  ['cceo1@edify.org', '/my-plan', false],
  ['cceo1@edify.org', '/dashboard', false],
  ['pl1@edify.org', '/work-plan', false],
  ['pl1@edify.org', '/dashboard', true],
];

test('the first frame is the finished page', async ({ browser }) => {
  for (const [account, path, fetchesSections] of FIRST_FRAME_PAGES) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
    await context.addInitScript(RECORD_WRITES);
    const page = await context.newPage();
    await signIn(page, account, password);
    await page.goto(path);
    await settle(page);
    const result = await page.evaluate(() => {
      const paints = Object.fromEntries(performance.getEntriesByType('paint').map((entry) => [entry.name, entry.startTime]));
      const navigation = performance.getEntriesByType('navigation')[0];
      const firstPaint = paints['first-paint'] || 0;
      const record = window.__edifyPerf;
      const deferred = Array.from(document.querySelectorAll('script[defer][src], script[type="module"]'));
      const last = deferred[deferred.length - 1];
      return {
        firstPaint,
        startedUp: navigation.domContentLoadedEventEnd,
        classesAfter: record.writes.filter(([at]) => at > firstPaint).reduce((sum, [, count]) => sum + count, 0),
        classesBefore: record.writes.filter(([at]) => at <= firstPaint).reduce((sum, [, count]) => sum + count, 0),
        shiftAfter: record.shifts.filter(([at]) => at > firstPaint).reduce((sum, [, value]) => sum + value, 0),
        deferredInBody: deferred.filter((script) => !script.closest('head')).map((script) => script.getAttribute('src')),
        lastDeferredHolds: Boolean(last && last.closest('head') && last.hasAttribute('blocking')),
      };
    });
    const where = `${account} ${path}`;
    // The markup: nothing deferred in the body, and the last deferred script holds the frame.
    expect(result.deferredInBody, where).toEqual([]);
    expect(result.lastDeferredHolds, where).toBe(true);
    // The effect: the page's startup scripts ran, and wrote their classes, before the first frame.
    expect(result.firstPaint, `${where}: a first frame was recorded`).toBeGreaterThan(0);
    expect(result.firstPaint, `${where}: first frame before the page had started up`).toBeGreaterThanOrEqual(result.startedUp);
    // However many rows the page has: it stamps its markup, and (all but a sliver of) that is before the first frame.
    const stamped = result.classesBefore + result.classesAfter;
    expect(stamped, `${where}: the page still stamps its markup`).toBeGreaterThan(0);
    expect(result.classesAfter, `${where}: ${result.classesAfter} of ${stamped} class changes drawn after the first frame`).toBeLessThanOrEqual(Math.max(5, stamped * 0.1));
    // A section that arrives later moves what is below it; that is not this gate's subject.
    if (!fetchesSections) expect(result.shiftAfter, `${where}: layout shift after the first frame`).toBeLessThanOrEqual(0.05);
    await context.close();
  }
});

// The control for the count above: a recorder that set aside too much would
// pass a page that is stamped late, so each kind of write is made here and
// counted on its own.
test('the recorder sets aside a fetch being announced, and nothing else', async ({ browser }) => {
  const context = await browser.newContext({ serviceWorkers: 'block' });
  await context.addInitScript(RECORD_WRITES);
  const page = await context.newPage();
  const address = 'http://recorder-control.test/';
  await page.route(address, (route) => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><div id="fetching" class="card"></div><div id="stamped" class="card"></div><div id="both" class="card"></div><div id="same" class="card"></div>',
  }));
  await page.goto(address);
  const counted = await page.evaluate(async () => {
    const total = () => window.__edifyPerf.writes.reduce((sum, [, count]) => sum + count, 0);
    const counts = {};
    const write = async (name, change) => {
      const before = total();
      change();
      await new Promise((resolve) => setTimeout(resolve, 0));
      counts[name] = total() - before;
    };
    const classes = (id) => document.getElementById(id).classList;
    // What htmx does to an element that fetches a section as the page loads.
    await write('a fetch announced', () => {
      const list = classes('fetching');
      list.add('htmx-request'); list.remove('htmx-request');
      list.add('htmx-swapping'); list.remove('htmx-swapping');
      list.add('htmx-settling'); list.remove('htmx-settling');
    });
    await write('a class stamped', () => { classes('stamped').add('is-ready'); });
    await write('a class stamped in the same write as an announcement', () => { document.getElementById('both').className = 'card htmx-request is-ready'; });
    await write('the same classes written again', () => { document.getElementById('same').className = 'card'; });
    await write('a class stamped between two announcements', () => {
      const list = classes('fetching');
      list.add('htmx-request'); list.add('is-ready'); list.remove('htmx-request');
    });
    return counts;
  });
  expect(counted).toEqual({
    'a fetch announced': 0,
    'a class stamped': 1,
    'a class stamped in the same write as an announcement': 1,
    'the same classes written again': 1,
    'a class stamped between two announcements': 1,
  });
  await context.close();
});

// Sum of the elements each style recalculation between two marks worked on.
async function restyled(browser, page, action) {
  await browser.startTracing(page, { categories: ['devtools.timeline', 'blink.user_timing'] });
  await page.evaluate(action);
  const events = JSON.parse((await browser.stopTracing()).toString()).traceEvents;
  const mark = (name) => events.find((event) => event.name === name && event.cat && event.cat.includes('blink.user_timing'));
  const [from, to] = [mark('edify-probe:start'), mark('edify-probe:end')];
  if (!from || !to) throw new Error('probe marks missing from the trace');
  return events
    .filter((event) => event.name === 'UpdateLayoutTree' && event.ph === 'X' && event.ts >= from.ts && event.ts <= to.ts)
    .reduce((sum, event) => sum + ((event.args && event.args.elementCount) || 0), 0);
}

// [what, viewport, share of the page's elements one inserted <span> may restyle]
const BREADTH = [
  // 2-4 % at every width (3-7 % on the 700-school seed, whose pages are half
  // the size) since the rules that asked an ancestor with `:has()` ask the
  // element they style, count its siblings, or read a fact the shell script
  // keeps as an attribute (e2e/has-rewrites.spec.js,
  // e2e/maintained-facts.spec.js). It was 110-136 % on a desktop and
  // 106-137 % below 1280px; the last to go was the pinned table column, which
  // held a desktop at 9-19 % until it read the row's box cell from the cell.
  ['a desktop', { viewport: { width: 1440, height: 900 } }, 0.15],
  ['a small laptop', { viewport: { width: 1100, height: 800 } }, 0.15],
  ['a phone', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }, 0.15],
];

test('one element added to a table cell does not restyle the page', async ({ browser }) => {
  for (const [device, options, ceiling] of BREADTH) {
    const context = await browser.newContext({ ...options, serviceWorkers: 'block' });
    const page = await context.newPage();
    await signIn(page, 'cceo1@edify.org', password);
    let measured = 0;
    for (const path of ['/my-plan', '/dashboard', '/planning', '/schools']) {
      await page.goto(path);
      await settle(page);
      // A page with no table rows in this dataset has nothing to measure.
      if (!(await page.locator('main table tbody td').count())) continue;
      measured += 1;
      const total = await page.evaluate(() => document.getElementsByTagName('*').length);
      const count = await restyled(browser, page, () => {
        const resolve = () => { getComputedStyle(document.body).color; void document.body.offsetWidth; };
        const cell = Array.from(document.querySelectorAll('main table tbody td')).pop();
        resolve();
        performance.mark('edify-probe:start');
        const probe = document.createElement('span');
        cell.appendChild(probe);
        resolve();
        performance.mark('edify-probe:end');
        probe.remove();
      });
      expect(count, `${path} on ${device}: something was measured`).toBeGreaterThan(0);
      expect(count / total, `${path} on ${device}: ${count} of ${total} elements restyled by one <span>`).toBeLessThan(ceiling);
    }
    expect(measured, `pages with a table to measure on ${device}`).toBeGreaterThan(0);
    await context.close();
  }
});

const RECALCULATION_CEILINGS = [
  // [account, page, ceiling]: measured 28-41 (field officer) and 104
  // (programme lead dashboard) on a 16,700-school dataset; the count follows
  // the number of scripts that measure, not the number of rows.
  ['cceo1@edify.org', '/my-plan', 80],
  ['cceo1@edify.org', '/planning', 80],
  ['cceo1@edify.org', '/dashboard', 80],
  ['pl1@edify.org', '/dashboard', 200],
  // 98 date fields: 242, where one resolution per field was 1,269.
  ['cd@edify.org', '/strategic-priorities', 480],
];

test('a page load resolves style a bounded number of times', async ({ browser }) => {
  const measured = [];
  for (const [account, path, ceiling] of RECALCULATION_CEILINGS) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
    const page = await context.newPage();
    await signIn(page, account, password);
    const session = await context.newCDPSession(page);
    await session.send('Performance.enable');
    const count = async () => (await session.send('Performance.getMetrics')).metrics.find((metric) => metric.name === 'RecalcStyleCount').value;
    await page.goto('about:blank');
    const before = await count();
    await page.goto(path);
    await settle(page);
    const recalculations = (await count()) - before;
    measured.push({ account, path, recalculations, ceiling });
    expect(recalculations, `${account} ${path}: something was measured`).toBeGreaterThan(0);
    expect(recalculations, `${account} ${path}: style recalculations in one load`).toBeLessThanOrEqual(ceiling);
    await context.close();
  }
  await test.info().attach('style-recalculations.json', { body: Buffer.from(JSON.stringify(measured, null, 2)), contentType: 'application/json' });
});

// Every time a tab rail is fitted its More menu is put away and brought back,
// so the number of times that menu's `hidden` changes is the number of fits.
const COUNT_RAIL_FITS = `(() => {
  const fits = new Map();
  window.__edifyRailFits = fits;
  new MutationObserver((records) => {
    for (const item of records) {
      if (!item.target.classList || !item.target.classList.contains('edify-rail-more')) continue;
      fits.set(item.target, (fits.get(item.target) || 0) + 1);
    }
  }).observe(document, { subtree: true, attributes: true, attributeFilter: ['hidden'] });
})();`;

test('a phone fits a page once, and fits it again when it is turned', async ({ browser }) => {
  // A phone lays the page out 980px wide until it has read the viewport line,
  // and reports the width it settled on as a resize event with its first frame.
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
  await context.addInitScript(COUNT_RAIL_FITS);
  const page = await context.newPage();
  await signIn(page, 'hr@edify.org', password);
  await page.goto('/leave/approvals');
  await settle(page);

  const rails = () => page.evaluate(() => {
    const shown = Array.from(window.__edifyRailFits.keys()).filter((more) => more.isConnected && !more.hidden);
    return {
      // `hidden` comes off once when the menu is first shown, and goes on and off again for each later fit.
      changes: shown.map((more) => window.__edifyRailFits.get(more)),
      overflowing: shown.filter((more) => more.parentElement.scrollWidth > more.parentElement.clientWidth + 1).length,
    };
  });
  const loaded = await rails();
  expect(loaded.changes.length, 'the page has a tab rail with a More menu at this width').toBeGreaterThan(0);
  expect(Math.max(...loaded.changes), 'times a rail was fitted while the page opened').toBe(1);
  expect(loaded.overflowing).toBe(0);

  // Turned on its side: the viewport has changed, so everything is fitted for it.
  const before = await page.evaluate(() => Array.from(window.__edifyRailFits.values()).reduce((sum, count) => sum + count, 0));
  await page.setViewportSize({ width: 844, height: 390 });
  await page.waitForTimeout(1200);
  const after = await page.evaluate(() => Array.from(window.__edifyRailFits.values()).reduce((sum, count) => sum + count, 0));
  expect(after, 'the rails were fitted again for the new width').toBeGreaterThan(before);
  expect((await rails()).overflowing, 'tab rails that overflow after the turn').toBe(0);
  await context.close();
});

// What a page was fitted to: the fields each filter row shows before its More,
// the tabs each rail has put in its menu, the width each table was fitted for.
const FITTED = `(() => ({
  sidebar: Math.round(document.querySelector('aside.app-sidebar').getBoundingClientRect().width),
  shut: document.querySelector('aside.app-sidebar').classList.contains('app-sidebar--collapsed'),
  rows: Array.from(document.querySelectorAll('[data-edify-filter-slots]')).map((row) => [row.dataset.edifyFilterSlots, row.style.getPropertyValue('--edify-filter-cols').trim(), row.querySelectorAll('[data-edify-filter-moved]').length].join('/')),
  rails: Array.from(document.querySelectorAll('.edify-rail-more')).map((more) => (more.hidden ? 0 : more.querySelectorAll('.edify-rail-more__item').length)),
  tables: Array.from(document.querySelectorAll('table[data-edify-wrap-at]')).map((table) => table.getAttribute('data-edify-wrap-at')),
}))()`;

test('beside a sidebar that shuts itself, a page opens fitted for the width it has', async ({ browser }) => {
  // At this width the sidebar arrives open (260px) and the shell's script
  // shuts it to its icon rail as the page starts, over 200ms. A page drawn
  // before its scripts had run was fitted during that: its filter rows for
  // the column it had with the sidebar open, its rails and tables for
  // wherever the slide had got to — one field or tab fewer than there was
  // room for, until the window was next resized. Held until the scripts have
  // run, the page is never drawn with the sidebar open, nothing slides, and
  // what it opens with is what fitting it again gives.
  const context = await browser.newContext({ viewport: { width: 1100, height: 800 }, serviceWorkers: 'block' });
  const page = await context.newPage();
  await signIn(page, 'cceo1@edify.org', password);
  let fitted = 0;
  for (const path of ['/my-plan', '/core-schools']) {
    await page.goto(path);
    await settle(page);
    const opened = await page.evaluate(FITTED);
    expect(opened.shut, `${path}: the sidebar is shut at this width`).toBe(true);
    expect(opened.sidebar, `${path}: the sidebar has finished shutting`).toBeLessThan(100);
    fitted += opened.rows.length + opened.rails.length + opened.tables.length;

    // A resize event is what makes the page fit itself again (micro-ux.js).
    await page.evaluate(() => window.dispatchEvent(new Event('resize')));
    await page.waitForTimeout(900);
    const again = await page.evaluate(FITTED);
    expect({ rows: again.rows, rails: again.rails, tables: again.tables }, `${path}: fitted again for the same window`).toEqual({ rows: opened.rows, rails: opened.rails, tables: opened.tables });
  }
  expect(fitted, 'these pages have filter rows, rails or tables to fit').toBeGreaterThan(0);
  await context.close();
});
