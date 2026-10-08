// A chart that is asked for before the chart library has run.
//
// The library (527 KB) is a deferred script that comes after Alpine, so on a
// slow first visit Alpine starts, and a chart an Alpine component draws as it
// starts asks to be drawn, before the library has arrived. The chart system
// used to give such a chart up without a word and its card stayed empty: My
// Targets' trend, found in Safari on 2026-10-08, where the timing falls that
// way more often. It is drawn once the library has run (base.html,
// EdifyChartSystem.whenLibraryRuns).
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

// The service worker would answer for the page and the library from its own
// store, and the request held below would never be made.
test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

test('a chart asked for before the chart library has run is drawn once it has', async ({ page }) => {
  // Held back the way a slow connection holds it: the page is given the
  // library under an address no cache has, and that request waits.
  await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  await page.route(/\/my-targets\?fy=2026$/, async (route) => {
    const response = await route.fetch();
    const html = (await response.text()).replace(/(<script defer src="[^"]*apexcharts-[^"]*\.js)([^"]*")/, (tag, address, rest) =>
      address + (rest.startsWith('?') ? rest.replace('?', '?held=1&') : '?held=1' + rest));
    expect(html).toContain('held=1');
    await route.fulfill({ response, body: html });
  });
  await page.route(/apexcharts-[^/]*\.js\?held=1/, async (route) => { await held; await route.continue(); });
  await page.goto('/my-targets?fy=2026', { waitUntil: 'commit' });
  const trend = page.locator('#myTargetTrend');
  // Alpine has started the card and the library has not run: nothing is drawn
  // yet. (Polled on a timer: the first frame is held until the scripts have run.)
  await page.waitForFunction(() => {
    const card = document.querySelector('#myTargetTrend')?.closest('[x-data]');
    return Boolean(window.Alpine && card && card._x_dataStack);
  }, null, { polling: 100 });
  expect(await page.evaluate(() => typeof window.ApexCharts)).toBe('undefined');
  await expect(trend.locator('.apexcharts-svg')).toHaveCount(0);

  release();
  await page.waitForLoadState('load');
  await trend.scrollIntoViewIfNeeded();
  await expect(trend.locator('.apexcharts-svg')).toBeVisible();
});
