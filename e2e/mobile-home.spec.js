/*
 * Home on a phone (owner, 2026-10-21): the first tab and the native app's
 * start page. Asserted in the phone projects — WebKit as an iPhone, Chromium
 * as an Android phone — on a seeded local database:
 *
 *   npx playwright test e2e/mobile-home.spec.js --project iphone-390 --project android-360
 *
 * The figures, the queue and the bars are the page's promise: real numbers,
 * the priority actions arriving after the page is drawn, nothing wider than
 * the phone, and the bottom and top bars where the owner put them.
 */
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');
const { isDisposableTarget } = require('./helpers/accounts');
const { watchPageErrors } = require('./helpers/page-errors');

const password = process.env.EDIFY_E2E_PASSWORD || 'edify';

test.skip(({ baseURL }) => !isDisposableTarget(baseURL), 'Signs in to seeded local accounts.');

async function openHome(page, email) {
  await signIn(page, email, password, { acceptRequiredAgreements: false });
  await page.goto('/home');
  // The To-Do queue arrives after the page is drawn (/home/queue).
  await expect(page.locator('[data-home-priority-loading]')).toHaveCount(0, { timeout: 30_000 });
}

test('a field officer starts the day on Home', async ({ page }) => {
  const errors = watchPageErrors(page);
  await openHome(page, 'cceo@edify.org');

  await expect(page.locator('.edify-home__greeting')).toContainText(/Good (morning|afternoon|evening)/);
  await expect(page.locator('[data-home-figure]')).toHaveCount(4);
  for (const key of ['upcoming', 'under_way', 'overdue', 'waiting_me']) {
    await expect(page.locator(`[data-home-figure="${key}"] .edify-home__figure-value`)).toHaveText(/^\d+$/);
  }
  await expect(page.locator('[data-home-priority], [data-home-empty="priority"]').first()).toBeVisible();

  const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(sideways, 'Home scrolls sideways').toBeLessThanOrEqual(1);

  // Bottom bar: Home, the role's two pages, Messages, More (owner, 2026-10-21).
  await expect(page.locator('.edify-bottom-nav__label')).toHaveText(['Home', 'My Plan', 'Schools', 'Messages', 'More']);
  await expect(page.locator('.edify-bottom-nav__item--active')).toContainText('Home');

  // Top bar: Messages and the bell both stay, and the week chip names the week
  // wherever the bar has room for it (it gives way at 384px and below).
  await expect(page.locator('.edify-topbar__utility--messages')).toBeVisible();
  await expect(page.locator('.edify-topbar__utility--notifications')).toBeVisible();
  if (page.viewportSize().width > 384) {
    await expect(page.locator('.edify-topbar__when-week')).toHaveText(/^Wk \d+$/, { useInnerText: true });
  }

  expect(errors, 'page errors on Home').toEqual([]);
});

test('a plan figure opens the list of exactly what it counts', async ({ page }) => {
  await openHome(page, 'cceo@edify.org');
  await page.locator('[data-home-figure="upcoming"]').click();
  await expect(page).toHaveURL(/\/my-plan\?status=upcoming$/);
  await expect(page.locator('select[name="status"]')).toHaveValue('upcoming');
});

test('a partner sees its own Home and never the school directory', async ({ page }) => {
  await openHome(page, 'partner@edify.org');
  await expect(page.locator('.edify-home__role')).toHaveText('Partner');
  await expect(page.locator('[data-home-figure]')).toHaveCount(4);
  await expect(page.locator('.edify-home a[href="/schools"]')).toHaveCount(0);
  await expect(page.locator('.edify-bottom-nav a[href="/schools"]')).toHaveCount(0);
});

test('a role with no plan gets its queue, not plan zeros', async ({ page }) => {
  await openHome(page, 'hr@edify.org');
  await expect(page.locator('[data-home-figure]')).toHaveCount(3);
  await expect(page.locator('#home-summary-title')).toBeVisible();
  await expect(page.getByText('Upcoming activities')).toHaveCount(0);
});
