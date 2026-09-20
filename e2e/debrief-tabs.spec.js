const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

test('debrief tabs retain filters and fit desktop and mobile after HTMX swaps', async ({ page }) => {
  await signIn(page, 'pl1@edify.org', 'edify', { acceptRequiredAgreements: false });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto('/debriefs?range_days=90');
    const rail = page.getByRole('tablist', { name: 'Team and partner debrief views' });
    await expect(rail).toBeVisible();

    for (const key of ['team', 'partner', 'mine']) {
      const tab = page.locator('[data-debrief-tab="' + key + '"]');
      if (!await tab.isVisible()) await rail.locator(':scope > details > summary').click();
      const response = page.waitForResponse(r =>
        r.url().includes('/debriefs?') && r.request().headers()['hx-request'] === 'true');
      await tab.click();
      const result = await response;
      expect(result.status()).toBe(200);
      expect(new URL(result.url()).searchParams.get('range_days')).toBe('90');
      await expect(tab).toHaveAttribute('aria-selected', 'true');
      await expect(tab).toHaveAttribute('role', 'tab'); // active item stays out of More
      await page.mouse.move(0, 0);
      await expect(tab).toHaveCSS('background-color', 'rgb(25, 118, 210)');
      await expect(tab).toHaveCSS('color', 'rgb(255, 255, 255)');
      await expect(page.locator('#debrief-results')).toHaveAttribute('aria-labelledby', 'debrief-tab-' + key);
    }

    const response = page.waitForResponse(r =>
      r.url().includes('/debriefs?') && r.request().headers()['hx-request'] === 'true');
    await page.locator('[name="range_days"]').selectOption('30');
    expect(new URL((await response).url()).searchParams.get('tab')).toBe('mine');
    await expect(page.locator('[data-debrief-tab="mine"]')).toHaveAttribute('aria-selected', 'true');
    expect(await rail.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  }
});
