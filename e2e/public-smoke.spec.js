const { test, expect } = require('@playwright/test');

test.describe('public release smoke', () => {
  test('login is interactive, accessible, and free of runtime failures', async ({ page }, testInfo) => {
    const consoleErrors = [];
    const failedRequests = [];
    page.on('console', message => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('pageerror', error => consoleErrors.push(error.message));
    page.on('requestfailed', request => {
      failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`);
    });

    const response = await page.goto('/login', { waitUntil: 'networkidle' });
    expect(response?.status()).toBeLessThan(500);
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
    await expect(page.getByLabel('Email address')).toBeEditable();
    const password = page.locator('#current-password');
    await expect(password).toHaveAttribute('type', 'password');

    await page.getByRole('button', { name: 'Show password' }).click();
    await expect(password).toHaveAttribute('type', 'text');
    await page.getByRole('button', { name: 'Hide password' }).click();
    await expect(password).toHaveAttribute('type', 'password');

    const forgotPassword = page.getByRole('button', { name: 'Forgot password?' });
    await expect(forgotPassword).toBeEnabled();
    // One request is sufficient to validate the backend chain. Repeating the
    // reset request in every browser correctly trips the IP throttle and
    // creates a console 429, obscuring the browser-compatibility signal.
    if (testInfo.project.name === 'chromium-desktop') {
      await page.getByLabel('Email address').fill('release-test-nonexistent@edify.test');
      await forgotPassword.click();
      await expect(page.getByRole('alert')).toContainText(
        'If that account exists, a password reset link has been sent.'
      );
      await expect(forgotPassword).toBeEnabled();
    }

    const metrics = await page.evaluate(() => ({
      domNodes: document.querySelectorAll('*').length,
      interactiveElements: document.querySelectorAll(
        'a[href],button,input,select,textarea,[role="button"],[role="tab"],[hx-get],[hx-post]'
      ).length,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    }));
    await testInfo.attach('public-page-metrics.json', {
      body: Buffer.from(JSON.stringify(metrics, null, 2)),
      contentType: 'application/json',
    });

    expect(metrics.domNodes).toBeLessThan(2_000);
    expect(metrics.horizontalOverflow).toBe(false);
    expect(failedRequests).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });

  test('health endpoints distinguish process and dependency state', async ({ request }) => {
    const live = await request.get('/api/health/live');
    expect(live.status()).toBe(200);
    expect(await live.json()).toMatchObject({ status: 'ok' });

    const ready = await request.get('/api/health/ready');
    expect([200, 503]).toContain(ready.status());
    const state = await ready.json();
    expect(state).toHaveProperty('db');
    expect(state).toHaveProperty('cache');
  });
});
