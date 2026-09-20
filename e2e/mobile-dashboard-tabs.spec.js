const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

test('Program Lead dashboard tabs fit the mobile viewport', async ({ page }) => {
  await signIn(page, 'pl1@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto('/dashboard');

  const rail = page.locator('.dashboard-view-nav .edify-section-nav__inner').first();
  await expect(rail).toBeVisible();
  await expect.poll(async () => rail.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
  await expect(rail.locator('[role="tab"][aria-selected="true"]')).toBeVisible();
  const tabs = rail.locator(':scope > [role="tab"]');
  for (const tab of await tabs.all()) {
    await expect.poll(() => tab.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
  }
  await expect(rail.locator('.edify-rail-more:not([hidden])')).toBeVisible();
});
