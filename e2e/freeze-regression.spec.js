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

async function signIn(page) {
  await page.goto('/login');
  await page.getByLabel('Email address').fill(adminEmail);
  await page.locator('#current-password').fill(password);
  await Promise.all([
    page.waitForURL(url => !url.pathname.endsWith('/login') && url.pathname !== '/'),
    page.getByRole('button', { name: 'Access workspace' }).click(),
  ]);
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

test('critical workspace style recalculation stays within one frame', async ({ page, context }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'CDP performance metrics are Chromium-only.');
  await signIn(page);
  const session = await context.newCDPSession(page);
  await session.send('Performance.enable');
  const results = [];

  for (const route of ['/analytics', '/schools', '/system-health']) {
    await page.goto(route, { waitUntil: 'networkidle' });
    await page.evaluate(() => {
      const target = document.querySelector('main > *');
      target.classList.toggle('edify-recalc-warmup');
      void getComputedStyle(target).color;
    });
    const samples = [];
    for (let iteration = 0; iteration < 7; iteration += 1) {
      const before = await session.send('Performance.getMetrics');
      await page.evaluate((sample) => {
        const target = document.querySelector('main > *');
        target.classList.toggle(`edify-recalc-probe-${sample}`);
        void getComputedStyle(target).color;
      }, iteration);
      const after = await session.send('Performance.getMetrics');
      const value = (metrics, name) => metrics.metrics.find(item => item.name === name).value;
      samples.push((value(after, 'RecalcStyleDuration') - value(before, 'RecalcStyleDuration')) * 1000);
    }
    results.push({ route, medianMs: Number(median(samples).toFixed(2)), samples });
  }

  await testInfo.attach('style-recalculation.json', {
    body: Buffer.from(JSON.stringify(results, null, 2)),
    contentType: 'application/json',
  });
  for (const result of results) expect(result.medianMs, result.route).toBeLessThan(16);
});

test('school tab churn reaches a stable DOM and listener plateau', async ({ page, context }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'CDP memory counters are Chromium-only.');
  test.setTimeout(180_000);
  await signIn(page);
  await page.goto('/schools', { waitUntil: 'networkidle' });
  const session = await context.newCDPSession(page);

  async function sample(cycle) {
    await session.send('HeapProfiler.collectGarbage');
    const counters = await session.send('Memory.getDOMCounters');
    return {
      cycle,
      ...counters,
      connectedNodes: await page.locator('*').count(),
    };
  }

  const samples = [await sample(0)];
  const tabs = [
    '#schools-tab-unclustered', '#schools-tab-clustered',
    '#schools-tab-not-assigned', '#schools-tab-assigned', '#schools-tab-all',
  ];
  for (let cycle = 1; cycle <= 50; cycle += 1) {
    const tab = page.locator(tabs[(cycle - 1) % tabs.length]);
    await Promise.all([
      page.waitForResponse(response => new URL(response.url()).pathname === '/schools'),
      tab.click(),
    ]);
    await expect(tab).toHaveAttribute('aria-selected', 'true');
    if (cycle % 10 === 0) samples.push(await sample(cycle));
  }

  await testInfo.attach('schools-dom-stability.json', {
    body: Buffer.from(JSON.stringify(samples, null, 2)),
    contentType: 'application/json',
  });
  const warm = samples[1];
  const final = samples.at(-1);
  expect(final.connectedNodes - warm.connectedNodes).toBeLessThanOrEqual(2);
  expect(final.jsEventListeners - warm.jsEventListeners).toBeLessThanOrEqual(2);
  const previous = samples.at(-2);
  /* Memory.getDOMCounters includes Chromium's bounded parser/document pool.
   * A leak keeps growing; that internal counter and the connected DOM must
   * both plateau in the final ten cycles after a long warm-up sequence. */
  expect(final.nodes - previous.nodes).toBeLessThanOrEqual(100);
});
