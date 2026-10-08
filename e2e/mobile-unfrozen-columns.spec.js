// No frozen columns in mobile mode (owner, 2026-09-30): "can you look into
// freezing of first column and last columns on mobile mode. can you make sure
// no column is [frozen] so that the users can scroll well without freezing
// half of the mobile screen. Apply throughout the platform."
//
// Below 64rem (the bottom-navigation shell) a wide table scrolls as one
// piece: its identity, its tick box and a pinned Actions column all move with
// the rest. Laptops and desktops keep their pins. The real stylesheets and
// static/js/micro-ux.js on a page of two wide tables, so what is checked is
// the platform rule, not whichever seeded page happens to overflow.
const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

const root = path.resolve(__dirname, '..');
const sheets = [
  'fonts.css', 'main.css', 'design-system.css', 'components.css', 'components/mobile-patterns.css', 'pages.css',
  'drawers.css', 'app.css', 'platform.css', 'consistency.css', 'components/mobile-micro-ux.css', 'form-refinement.css',
  'components/responsive-system.css', 'components/interactions.css',
];
// Long text, not sized spans: from 768px up the platform holds a cell's spans
// inline, where a width is ignored.
const wide = (text) => `${text} with a long enough value to keep its column wide`;
const row = (i) => `<tr><td><label><input type="checkbox" value="${i}"><span class="sr-only">Select</span></label></td>`
  + `<td>${wide(`Kampala Primary School ${i}`)}</td>`
  + Array.from({ length: 6 }, (_, c) => `<td>${wide(`Value ${i}.${c}`)}</td>`).join('') + '</tr>';
const actionsRow = (i) => `<tr><td>${wide(`Activity ${i}`)}</td>`
  + Array.from({ length: 6 }, (_, c) => `<td>${wide(`Field ${i}.${c}`)}</td>`).join('')
  + '<td><button type="button">Actions</button></td></tr>';
const body = `
<main class="edify-workspace"><h1>Tables</h1>
  <section><h2>Schools</h2>
    <table id="identity" data-table-fit="scroll"><thead><tr><th scope="col"><span class="sr-only">Select</span></th><th scope="col">School</th>
      ${Array.from({ length: 6 }, (_, c) => `<th scope="col">Column ${c}</th>`).join('')}</tr></thead>
      <tbody>${[1, 2, 3].map(row).join('')}</tbody></table>
  </section>
  <section><h2>Activities</h2>
    <table id="actions" data-pinned-actions data-table-fit="scroll"><thead><tr><th scope="col">Activity</th>
      ${Array.from({ length: 6 }, (_, c) => `<th scope="col">Field ${c}</th>`).join('')}<th scope="col">Actions</th></tr></thead>
      <tbody>${[1, 2].map(actionsRow).join('')}</tbody></table>
  </section>
</main>`;

async function open(browser, viewport, touch) {
  const context = await browser.newContext({ viewport, hasTouch: touch, isMobile: touch && viewport.width < 768 });
  const page = await context.newPage();
  await page.route('http://tables.test/**', (route) => {
    const file = path.join(root, new URL(route.request().url()).pathname);
    if (fs.existsSync(file) && fs.statSync(file).isFile()) return route.fulfill({ path: file });
    return route.fulfill({
      contentType: 'text/html',
      body: `<html class="light"><head><meta name="viewport" content="width=device-width, initial-scale=1">
        ${sheets.map((s) => `<link rel="stylesheet" href="/static/css/${s}">`).join('')}
        <script defer src="/static/js/micro-ux.js"></script></head><body>${body}</body></html>`,
    });
  });
  await page.goto('http://tables.test/');
  await page.waitForFunction(() => document.querySelectorAll('.edify-table-scroll-region[data-scroll-state]').length === 2);
  return { context, page };
}

// Scrolls a table's region by `by` pixels and returns how far each watched
// cell moved on screen: 0 = frozen, about -by = scrolled with the table.
async function moved(page, tableId, by) {
  return page.evaluate(async ({ tableId, by }) => {
    const table = document.getElementById(tableId);
    const region = table.closest('.edify-table-scroll-region');
    const cells = {
      tick: table.querySelector('tbody tr > :first-child'),
      identity: table.querySelector('tbody tr > :nth-child(2)'),
      first: table.querySelector('tbody tr > :first-child'),
      last: table.querySelector('tbody tr > :last-child'),
      heading: table.querySelector('thead tr > :first-child'),
    };
    const before = Object.fromEntries(Object.entries(cells).map(([k, el]) => [k, el.getBoundingClientRect().left]));
    region.scrollLeft = by;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return {
      state: region.dataset.scrollState,
      scrolled: region.scrollLeft,
      ...Object.fromEntries(Object.entries(cells).map(([k, el]) => [k, Math.round(el.getBoundingClientRect().left - before[k])])),
    };
  }, { tableId, by });
}

for (const [label, viewport] of [['phone', { width: 390, height: 844 }], ['tablet', { width: 820, height: 1180 }]]) {
  test(`${label}: every column scrolls with the table, first and last alike`, async ({ browser }) => {
    const { context, page } = await open(browser, viewport, true);
    try {
      const identity = await moved(page, 'identity', 160);
      expect(identity.state).toMatch(/middle|end/);
      expect(identity.tick).toBe(-identity.scrolled);
      expect(identity.identity).toBe(-identity.scrolled);
      expect(identity.heading).toBe(-identity.scrolled);

      const actions = await moved(page, 'actions', 160);
      expect(actions.first).toBe(-actions.scrolled);
      expect(actions.last).toBe(-actions.scrolled);

      // Nothing left anywhere on the page that sticks sideways.
      const frozen = await page.evaluate(() => [...document.querySelectorAll('th, td')]
        .filter((cell) => { const s = getComputedStyle(cell); return s.position === 'sticky' && (s.left !== 'auto' || s.right !== 'auto'); }).length);
      expect(frozen).toBe(0);

      // Unpinned, a name is not cut to the pinned identity measure: its box is
      // as wide as its words. (Measured as the words against the box. The
      // name is an inline span, where scrollWidth and clientWidth are both 0
      // in Chromium and WebKit, so comparing those passed whatever the name
      // looked like, and failed in Firefox, which gives an inline box its
      // content's width for the first and 0 for the second.)
      const name = page.locator('#identity tbody tr:first-child > :nth-child(2) > :first-child');
      const cutBy = (el) => {
        const words = document.createRange();
        words.selectNodeContents(el);
        return words.getBoundingClientRect().width - el.getBoundingClientRect().width;
      };
      expect(await name.evaluate(cutBy)).toBeLessThanOrEqual(1);
      // The measure does see a name that is cut.
      expect(await name.evaluate((el, cutBy) => {
        // Over the stylesheet's own rules for a cell's text, which are !important.
        const clamp = { display: 'block', 'max-width': '6rem', overflow: 'hidden' };
        Object.entries(clamp).forEach(([name, value]) => el.style.setProperty(name, value, 'important'));
        const by = new Function('el', `return (${cutBy})(el)`)(el);
        Object.keys(clamp).forEach((name) => el.style.removeProperty(name));
        return by;
      }, cutBy.toString())).toBeGreaterThan(50);
    } finally {
      await context.close();
    }
  });
}

test('laptop: the identity, the tick box and Actions stay pinned as before', async ({ browser }) => {
  const { context, page } = await open(browser, { width: 1100, height: 800 }, false);
  try {
    const identity = await moved(page, 'identity', 160);
    expect(identity.scrolled).toBeGreaterThan(0);
    expect(Math.abs(identity.tick)).toBeLessThanOrEqual(1);
    expect(Math.abs(identity.identity)).toBeLessThanOrEqual(1);

    const actions = await moved(page, 'actions', 160);
    expect(actions.scrolled).toBeGreaterThan(0);
    expect(Math.abs(actions.first)).toBeLessThanOrEqual(1);
    expect(Math.abs(actions.last)).toBeLessThanOrEqual(1);
  } finally {
    await context.close();
  }
});
