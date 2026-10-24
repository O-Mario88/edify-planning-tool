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

// The phone layout is asserted in the phone projects; the desktop test below
// sets its own desktop width in any project.
const phoneOnly = ({ isMobile }) => !isMobile;

async function openHome(page, email) {
  await signIn(page, email, password, { acceptRequiredAgreements: false });
  await page.goto('/home');
  // The To-Do queue arrives after the page is drawn (/home/queue).
  await expect(page.locator('[data-home-priority-loading]')).toHaveCount(0, { timeout: 30_000 });
}

test('a field officer starts the day on Home', async ({ page }) => {
  test.skip(phoneOnly({ isMobile: test.info().project.use.isMobile }), 'Phone layout.');
  const errors = watchPageErrors(page);
  await openHome(page, 'cceo@edify.org');

  await expect(page.locator('.edify-home__greeting')).toContainText(/Good (morning|afternoon|evening)/);
  await expect(page.locator('[data-home-figure]')).toHaveCount(4);
  for (const key of ['upcoming', 'under_way', 'overdue', 'waiting_me']) {
    await expect(page.locator(`[data-home-figure="${key}"] .edify-home__figure-value`)).toHaveText(/^\d+$/);
  }
  await expect(page.locator('[data-home-priority], [data-home-empty="priority"]').first()).toBeVisible();

  // A CCEO's Priority actions are their role's own six, each linked to its
  // list (owner, 2026-10-24), and Quick access is the four the owner named.
  await expect(page.locator('[data-home-priority]')).toHaveCount(6);
  await expect(page.locator('[data-home-priority="my_overdue"]')).toHaveAttribute('href', '/dashboard?view=week#what-needs-you-now');
  await expect(page.locator('[data-home-priority="no_ssa"]')).toHaveAttribute('href', '/schools?gap=no_ssa');
  await expect(page.locator('[data-home-priority="my_performance"]')).toHaveAttribute('href', '/team-performance/');
  await expect(page.locator('.edify-home__shortcut-label')).toHaveText(['Dashboard', 'Clusters', 'My Plan', 'Calendar']);
  // The sidebar's lockup heads the band, centred.
  await expect(page.locator('.edify-home__wordmark-product')).toHaveText(/Planning &\s*Monitoring/);
  const band = await page.locator('.edify-home__hero').boundingBox();
  const mark = await page.locator('.edify-home__wordmark').boundingBox();
  const offCentre = Math.abs(mark.x + mark.width / 2 - (band.x + band.width / 2));
  expect(offCentre, 'the lockup sits on the band’s centre line').toBeLessThanOrEqual(2);

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
  test.skip(phoneOnly({ isMobile: test.info().project.use.isMobile }), 'Phone layout.');
  await openHome(page, 'cceo@edify.org');
  await page.locator('[data-home-figure="upcoming"]').click();
  await expect(page).toHaveURL(/\/my-plan\?status=upcoming$/);
  await expect(page.locator('select[name="status"]')).toHaveValue('upcoming');
});

test('a partner sees its own Home and never the school directory', async ({ page }) => {
  test.skip(phoneOnly({ isMobile: test.info().project.use.isMobile }), 'Phone layout.');
  await openHome(page, 'partner@edify.org');
  await expect(page.locator('.edify-home__role')).toHaveText('Partner');
  await expect(page.locator('[data-home-figure]')).toHaveCount(4);
  await expect(page.locator('.edify-home a[href="/schools"]')).toHaveCount(0);
  await expect(page.locator('.edify-bottom-nav a[href="/schools"]')).toHaveCount(0);
});

test('on a desktop Home is a desktop page, not the phone layout made wider', async ({ page }) => {
  // Owner, 2026-10-23: "don't extend the mobile or tablet screen view to desktop".
  test.skip(Boolean(test.info().project.use.isMobile), 'Desktop layout.');
  await page.setViewportSize({ width: 1440, height: 900 });
  await openHome(page, 'cceo@edify.org');
  await expect(page.locator('.edify-home__hero')).toBeHidden();
  await expect(page.locator('.edify-bottom-nav')).toBeHidden();
  await expect(page.locator('.edify-home__desk-head h1')).toContainText(/Good (morning|afternoon|evening)/);
  const queue = await page.locator('.edify-home__card--queue').boundingBox();
  const side = await page.locator('.edify-home__card--side').first().boundingBox();
  expect(side.x, 'Quick access sits beside the queue').toBeGreaterThan(queue.x + queue.width);
  const overview = await page.locator('.edify-home__overview').boundingBox();
  expect(overview.width, 'the overview runs across the page').toBeGreaterThan(900);
});

test('a role with no plan gets its queue, not plan zeros', async ({ page }) => {
  test.skip(phoneOnly({ isMobile: test.info().project.use.isMobile }), 'Phone layout.');
  await openHome(page, 'hr@edify.org');
  await expect(page.locator('[data-home-figure]')).toHaveCount(3);
  await expect(page.locator('#home-summary-title')).toBeVisible();
  await expect(page.getByText('Upcoming activities')).toHaveCount(0);
});

test('signing in opens Home', async ({ page }) => {
  // Owner, 2026-10-24: "on logging in, the new home page is loaded by default".
  await signIn(page, 'pl1@edify.org', password, { acceptRequiredAgreements: false });
  await expect(page).toHaveURL(/\/home$/);
});

async function inView(page, selector) {
  const place = page.locator(selector);
  await expect(place).toBeVisible({ timeout: 30_000 });
  // Brought into view once the dashboard's monitor has loaded above it.
  await expect.poll(async () => {
    const box = await place.boundingBox();
    const height = page.viewportSize().height;
    return Boolean(box) && box.y < height * 0.5 && box.y + box.height > 0;
  }, { timeout: 30_000 }).toBe(true);
}

test('a Lead’s Priority action opens the dashboard table it names', async ({ page }) => {
  // Owner, 2026-10-24: overdue rows open the dashboard's overdue plans, the
  // Lead's own or their CCEOs'; Verify opens the completed activities table.
  await openHome(page, 'pl1@edify.org');

  await page.locator('[data-home-priority="team_overdue"]').click();
  await expect(page).toHaveURL(/\/dashboard\?view=week&plans=team#what-needs-you-now$/);
  await expect(page.locator('details[data-pl-backlog]')).toHaveAttribute('open', '');
  await expect(page.locator('#what-needs-you-now [data-edify-tab][aria-current="true"]')).toHaveText(/^Team Plans/);

  await page.goto('/home');
  await expect(page.locator('[data-home-priority-loading]')).toHaveCount(0, { timeout: 30_000 });
  await page.locator('[data-home-priority="verify"]').click();
  await expect(page).toHaveURL(/#completion-reviews$/);
  await inView(page, '#completion-reviews');

  await page.goto('/home');
  await expect(page.locator('[data-home-priority-loading]')).toHaveCount(0, { timeout: 30_000 });
  await page.locator('[data-home-priority="not_clustered"]').click();
  await expect(page).toHaveURL(/#monitor-list$/);
  await inView(page, '#monitor-list');
  await expect(page.locator('#monitor-list-title')).toHaveText(/Not clustered/);
});
