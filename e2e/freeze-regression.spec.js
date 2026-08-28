const { test, expect } = require('@playwright/test');

const adminEmail = process.env.EDIFY_E2E_ADMIN_EMAIL || 'admin@edify.org';
const password = process.env.EDIFY_E2E_PASSWORD || 'edify';

const formerlyHeavyRoutes = [
  '/core-schools/champion-candidates',
  '/activities/closure/blocked',
  '/core-school-health',
  '/planning/schedule',
  '/ssa/manual/',
  '/strategic-priorities',
];

test('formerly freezing pages remain bounded and responsive', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'The full freeze trace runs once.');
  test.setTimeout(180_000);

  await page.goto('/login');
  await page.getByLabel('Email address').fill(adminEmail);
  await page.locator('#current-password').fill(password);
  await Promise.all([
    page.waitForURL(url => !url.pathname.endsWith('/login') && url.pathname !== '/'),
    page.getByRole('button', { name: 'Access workspace' }).click(),
  ]);

  const measurements = [];
  const consoleErrors = [];
  let currentRoute = '';
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(`${currentRoute}: ${message.text()}`);
  });
  page.on('pageerror', error => consoleErrors.push(`${currentRoute}: ${error.message}`));

  for (const route of formerlyHeavyRoutes) {
    currentRoute = route;
    const started = Date.now();
    const response = await page.goto(route, { waitUntil: 'domcontentloaded' });
    const durationMs = Date.now() - started;
    const state = await page.evaluate(() => ({
      domNodes: document.querySelectorAll('*').length,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    }));
    measurements.push({ route, status: response?.status(), durationMs, ...state });
  }

  await testInfo.attach('freeze-regression-measurements.json', {
    body: Buffer.from(JSON.stringify(measurements, null, 2)),
    contentType: 'application/json',
  });

  for (const result of measurements) {
    expect(result.status, result.route).toBeLessThan(500);
    expect(result.domNodes, result.route).toBeLessThan(5_000);
    expect(result.durationMs, result.route).toBeLessThan(8_000);
    expect(result.horizontalOverflow, result.route).toBe(false);
  }
  expect(consoleErrors).toEqual([]);
});
