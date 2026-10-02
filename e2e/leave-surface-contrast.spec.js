const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

test('leave cards and budget bands retain readable surface pairs in every theme', async ({ page }) => {
  await signIn(page, 'pl1@edify.org', 'edify', { acceptRequiredAgreements: false });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/leave/approvals');
    const queue = page.getByRole('region', { name: 'Leave approval queue' });
    await expect(queue).toBeVisible();
    // The recent-activity table used to misidentify the entire preceding
    // approval card as its heading and turn all card text white.
    await expect(queue).not.toHaveClass(/edify-table-titlebar/);
    for (const theme of ['light', 'dark', 'blue']) {
      await page.evaluate(theme => {
        const html = document.documentElement;
        html.classList.remove('light', 'dark', 'theme-dark', 'theme-blue');
        html.classList.add(...(theme === 'light' ? ['light'] : ['dark', 'theme-' + theme]));
        html.dataset.theme = theme;
      }, theme);
      await expect.poll(() => queue.locator('h3').first().evaluate(el => {
        const foreground = getComputedStyle(el).color;
        const expected = getComputedStyle(document.body).color;
        return foreground === expected;
      })).toBe(true);
      if (theme === 'light') {
        await expect.poll(() => page.locator('.edify-shell').evaluate(el => getComputedStyle(el).backgroundColor))
          .toBe('rgb(219, 228, 235)');
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    }
    await page.goto('/budget');
    const band = page.locator('.budget-ledger-band > th, .budget-ledger-band > td').first();
    await expect(band).toBeVisible();
    // The ledger's group band is the table-header tone with ink text since 2026-10-02.
    await expect(band).toHaveCSS('background-color', 'rgb(220, 230, 236)');
    await expect(band).toHaveCSS('color', 'rgb(23, 35, 43)');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  }
});
