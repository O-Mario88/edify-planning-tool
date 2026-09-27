/*
 * The owner's 2026-09-27 rules, held on the pages the platform sweep changed:
 * page-header actions take the phone action height, filters are fields of
 * the row (no hand-rolled "More filters" panels or "Apply advanced filters"),
 * pills are the platform tab rail, exports are one Excel button, and a
 * table's title band carries no shortcut buttons.
 *
 * Run: npx playwright test e2e/platform-sweep.spec.js --project chromium-desktop --no-deps
 */
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

test.use({ video: 'off', trace: 'off' });

test('phone page-header actions take the 32px action height', async ({ browser }) => {
  test.setTimeout(120_000);
  const context = await browser.newContext({ isMobile: true, hasTouch: true, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await signIn(page, 'cd@edify.org', 'edify', { acceptRequiredAgreements: false });
  for (const route of ['/analytics', '/my-plan', '/my-performance']) {
    await page.goto(route);
    const heights = await page.locator('main .edify-page-header :is(a.btn, button.btn, a.edify-action-button, button.edify-action-button):visible')
      .evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().height)));
    for (const height of heights) expect(height, route).toBeLessThanOrEqual(33);
  }
  await context.close();
});

test('filters are fields of the row, not hand-rolled panels', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
  for (const route of ['/core-schools', '/work-plan', '/analytics', '/projects']) {
    await page.goto(route);
    await expect(page.locator('main').getByText(/Apply Advanced Filters/i), route).toHaveCount(0);
    await expect(page.locator('main details.analytics-more-filters, main .work-plan-filter-popover, main button[hx-get*="/projects/filters-drawer"]'), route).toHaveCount(0);
  }
  await page.goto('/core-schools?ssa_status=done');
  await expect(page.locator('main [data-edify-filter-clear]')).toHaveCount(1);
});

test('pill groups are the platform tab rail', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto('/decision-log');
  const rail = page.locator('main nav[data-edify-tablist][aria-label="Decision group"]');
  await expect(rail).toBeVisible();
  await expect(rail.locator('[data-edify-tab][aria-current="page"]')).toHaveText('All');
});

test('exports are one Excel button', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, 'cd@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto('/analytics');
  await expect(page.locator('main .edify-page-header').getByText(/CSV/)).toHaveCount(0);
  await expect(page.locator('main .edify-page-header a[aria-label="Export to Excel"]')).toHaveCount(1);
  await page.goto('/analytics/country-director');
  await expect(page.locator('main [data-component="cd-export-set"]')).toHaveCount(0);
  await expect(page.locator('main a[data-component="cd-export"]')).toHaveCount(1);
});

test("a table's title band carries no shortcut buttons", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, 'pl1@edify.org', 'edify', { acceptRequiredAgreements: false });
  for (const route of ['/dashboard?view=coaching', '/dashboard?view=priorities', '/partners']) {
    await page.goto(route);
    const offenders = await page.locator('main .edify-table-titlebar').evaluateAll((bands) => bands.flatMap((band) =>
      [...band.querySelectorAll('a[href], button')]
        .filter((c) => c.getBoundingClientRect().width > 0 && !c.matches('.edify-band-glyph, [aria-sort], th *'))
        .map((c) => (c.textContent || '').trim())));
    expect(offenders, route).toEqual([]);
  }
});

test('special projects filters are fields of the row', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, 'admin@edify.org', 'edify', { acceptRequiredAgreements: false });
  for (const route of ['/projects/planning', '/projects/my-plan']) {
    await page.goto(route);
    await expect(page.locator('main :is(.spp-more-filters, .sp-more-filters)'), route).toHaveCount(0);
    await expect(page.locator('main').getByText(/· active/), route).toHaveCount(0);
  }
  await page.goto('/projects/planning');
  await expect(page.locator('main .edify-page-header').getByRole('link', { name: /Open My Plan/ })).toHaveCount(0);
});

test("a header's actions never sit over its title, and share its line when they fit", async ({ browser }) => {
  test.setTimeout(120_000);
  const context = await browser.newContext({ isMobile: true, hasTouch: true, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await signIn(page, 'pl1@edify.org', 'edify', { acceptRequiredAgreements: false });
  for (const route of ['/team/coaching', '/my-performance', '/recovery-plans', '/my-plan', '/calendar']) {
    await page.goto(route);
    const result = await page.locator('main .edify-page-header').first().evaluate((header) => {
      const title = header.querySelector('h1, .edify-page-title');
      const range = document.createRange(); range.selectNodeContents(title);
      const text = range.getBoundingClientRect();
      const actions = [...header.querySelectorAll('.edify-page-header__controls > :is(a, button)')].filter((a) => a.getBoundingClientRect().width > 0);
      return actions.map((a) => { const b = a.getBoundingClientRect(); return b.left < text.right - 1 && b.top < text.bottom && b.bottom > text.top; });
    });
    expect(result.filter(Boolean), route).toEqual([]);
  }
  await context.close();
});

test('a pinned name leaves room for the columns after it on a phone', async ({ browser }) => {
  test.setTimeout(120_000);
  const context = await browser.newContext({ isMobile: true, hasTouch: true, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await signIn(page, 'cd@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto('/cost-settings');
  await page.locator('main [hx-get^="/cost-settings/row/"]').first().click();
  await expect(page.locator('.drawer-surface.active')).toBeVisible();
  await context.close();
});

test('core school rows take Planning’s type', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto('/core-schools');
  const title = page.locator('main .core-school-row .school-record-row__title').first();
  test.skip(!(await title.count()), 'no core schools in this seed');
  const size = await title.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(size).toBeLessThanOrEqual(14.5);
});
