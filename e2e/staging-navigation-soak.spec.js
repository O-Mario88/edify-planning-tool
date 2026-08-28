const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

const enabled = process.env.EDIFY_STAGING_SOAK === '1';
const password = process.env.EDIFY_E2E_PASSWORD || 'edify';
const routes = ['/schools', '/analytics', '/system-health', '/dashboard', '/todos'];

async function counters(page, cdp) {
  await cdp.send('HeapProfiler.collectGarbage');
  const dom = await cdp.send('Memory.getDOMCounters');
  const performance = await cdp.send('Performance.getMetrics');
  const metrics = Object.fromEntries(
    performance.metrics.map(metric => [metric.name, metric.value]),
  );
  return {
    url: page.url(),
    documents: dom.documents,
    nodes: dom.nodes,
    listeners: dom.jsEventListeners,
    jsHeapBytes: metrics.JSHeapUsedSize,
  };
}

test('50-navigation staging soak stabilizes DOM, listeners and heap', async ({
  page,
  browserName,
}, testInfo) => {
  test.skip(!enabled, 'Run only against an isolated seeded staging deployment.');
  test.skip(browserName !== 'chromium', 'Chromium CDP exposes the required DOM counters.');
  test.setTimeout(12 * 60_000);

  await signIn(page, 'admin@edify.org', password);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Performance.enable');
  await cdp.send('HeapProfiler.enable');

  // Warm the caches and Alpine/HTMX initializers before taking the baseline.
  for (const route of routes) {
    await page.goto(route, { waitUntil: 'domcontentloaded' });
  }
  await page.goto('/schools', { waitUntil: 'domcontentloaded' });
  const baseline = await counters(page, cdp);

  const checkpoints = [];
  for (let cycle = 1; cycle <= 10; cycle += 1) {
    for (const route of routes) {
      const response = await page.goto(route, { waitUntil: 'domcontentloaded' });
      expect(response?.status(), `${route} must stay successful`).toBe(200);
    }
    await page.goto('/schools', { waitUntil: 'domcontentloaded' });
    checkpoints.push({ cycle, ...(await counters(page, cdp)) });
  }

  const final = checkpoints.at(-1);
  const evidence = { baseline, checkpoints, final };
  await testInfo.attach('staging-navigation-soak.json', {
    body: Buffer.from(JSON.stringify(evidence, null, 2)),
    contentType: 'application/json',
  });

  expect(final.documents, 'old documents must be collected').toBeLessThanOrEqual(
    baseline.documents + 1,
  );
  expect(final.nodes, 'DOM nodes must plateau').toBeLessThanOrEqual(
    baseline.nodes + 750,
  );
  expect(final.listeners, 'event listeners must plateau').toBeLessThanOrEqual(
    baseline.listeners + 40,
  );
  expect(final.jsHeapBytes, 'JS heap must remain bounded after GC').toBeLessThanOrEqual(
    baseline.jsHeapBytes * 1.5 + 5 * 1024 * 1024,
  );
});

