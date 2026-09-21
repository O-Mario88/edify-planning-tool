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
 * My Plan's tables became record tables on 2026-09-19 and a record table
 * scrolls instead of taking a plan (micro-ux.js, 2026-09-20), so the journey
 * reads the Country Director's operations dashboard, whose Who's Online and
 * Programme Lead tables still take a plan at 1440px with a control per row.
 *
 * Asserted on the rendered geometry, not the plan: a heading that fits its
 * own box, and a control the reader can actually get to.
 */
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

test('planned columns show their headings and keep their controls reachable', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, 'cd@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.setViewportSize({ width: 1440, height: 950 });
  await page.goto('/dashboard?view=operations');
  await expect(page.locator('main table').first()).toBeVisible();
  await page.waitForTimeout(600);

  const planned = page.locator('main table.edify-table--truncate');
  expect(await planned.count(), 'the operations tables take a column plan at 1440px').toBeGreaterThan(0);

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
});
