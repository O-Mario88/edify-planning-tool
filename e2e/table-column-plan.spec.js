/*
 * A re-planned table shows its headings and reaches its controls.
 *
 * micro-ux.js plans the columns of any table wider than its region, writes
 * them to a <colgroup> and switches the table to a fixed layout so nothing
 * scrolls and nothing wraps (consistency.css). Two things were wrong with the
 * plan, and My Plan's School Visits table showed both at 1440px:
 *
 *  - A strip of status pills reads as a rigid column — one that keeps its
 *    width while text columns give theirs up. Six stages asked for 617px of a
 *    1108px region, so every other column went to its last floor and rendered
 *    as an ellipsis, headings included: "Distr…", "Plan…", "Purp…", "Assig…".
 *
 *  - Every width in the plan comes from a body row, so a column could finish
 *    narrower than its own heading, and a cell holding one control could
 *    finish narrower than the control. The actions column was planned to the
 *    width of the word "Actions" and its 90px button painted 36px past the
 *    table, with no scroll to reach it.
 *
 * The journey used to read a live table that took a plan: My Plan's until it
 * became a record table (2026-09-19; record tables scroll), then the Who's
 * Online table on the Country Director's operations dashboard. Who's Online
 * moved under Country Oversight's planning tab (owner, 2026-09-28), where it
 * has the page's width and fits or scrolls depending on who was online, so no
 * live table is a stable subject any more. The plan is exercised here on a
 * table of the shape that showed both defects — text columns, a strip of six
 * status pills and an actions column — served with the platform's own
 * stylesheets and script, in a region narrower than the table.
 *
 * Asserted on the rendered geometry, not the plan: a heading that fits its
 * own box, and a control the reader can actually get to.
 */
const path = require('path');
const { test, expect } = require('@playwright/test');
const { snapshotServer } = require('./helpers/snapshot-server');

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

const STAGES = ['Planned', 'Scheduled', 'Started', 'Evidence', 'Reviewed', 'Verified'];

function fixture() {
  const pills = STAGES.map(
    (stage) => `<span class="rounded-pill bg-emerald-50 text-emerald-700 px-2 py-0.5">${stage}</span>`
  ).join('');
  const rows = Array.from({ length: 8 }, (_, n) => `
    <tr>
      <td>Kampala Hill Primary School ${n + 1}</td>
      <td>Mukono</td>
      <td>12 Oct 2026</td>
      <td>Follow Up Visit</td>
      <td>Officer One Namukasa</td>
      <td>${pills}</td>
      <td><button type="button" class="btn">Open record</button></td>
    </tr>`).join('');
  return `<!doctype html><html class="theme-light"><head>
<link rel="stylesheet" href="/static/css/design-system.css">
<link rel="stylesheet" href="/static/css/components.css">
<link rel="stylesheet" href="/static/css/consistency.css">
<script defer src="/static/js/micro-ux.js"></script>
</head><body><main id="main-content"><section style="inline-size: 1100px; padding: 16px">
<table><thead><tr>
  <th>School</th><th>District</th><th>Planned date</th><th>Purpose</th><th>Assigned to</th><th>Stages</th><th>Actions</th>
</tr></thead><tbody>${rows}</tbody></table>
</section></main></body></html>`;
}

test('planned columns show their headings and keep their controls reachable', async ({ page }) => {
  const server = await snapshotServer(path.resolve(__dirname, '..'));
  try {
    server.setHtml(fixture());
    await page.setViewportSize({ width: 1440, height: 950 });
    await page.goto(server.origin + '/page');
    await expect(page.locator('main table')).toBeVisible();
    await page.waitForTimeout(600);

    const planned = page.locator('main table.edify-table--truncate');
    expect(await planned.count(), 'a table wider than its region takes a column plan').toBeGreaterThan(0);

    const report = await planned.evaluateAll((tables) =>
      tables.map((table) => {
        const wrap = table.parentElement;
        const room = wrap.getBoundingClientRect().right + (wrap.scrollWidth - wrap.clientWidth);
        return {
          clipped: [...table.querySelectorAll('thead th')]
            .filter((th) => th.scrollWidth > th.clientWidth + 1)
            .map((th) => th.textContent.trim()),
          unreachable: [...table.querySelectorAll('tbody tr')]
            .slice(0, 8)
            .map((row) => row.querySelector('.row-menu__trigger') || row.querySelector('td:last-child :is(a, button)'))
            .filter((control) => control && control.getBoundingClientRect().right > room + 1).length,
        };
      })
    );

    for (const table of report) {
      expect(table.clipped).toEqual([]);
      expect(table.unreachable).toBe(0);
    }
  } finally {
    await server.close();
  }
});
