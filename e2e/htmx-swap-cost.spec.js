const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

/* An HTMX swap must not redraw the charts that are already on the page.
 *
 * Every swap used to dispatch `edify-theme-change`, which every live chart
 * listens for, so opening a drawer, turning a table page or typing in the
 * top-bar search redrew each chart: 280-350 ms of blocked main thread per
 * chart per swap on the SSA workspace (performance rescue, 2026-09-23). The
 * swap below lands in an off-screen element, so any chart render it causes
 * is pure waste.
 */
test('an unrelated HTMX swap redraws no existing chart', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Main-thread cost is measured once.');
  await signIn(page, 'pl1@edify.org', 'edify');
  // Tall enough that the trend chart is on screen and renders at once rather
  // than waiting for the lazy observer.
  await page.setViewportSize({ width: 1440, height: 2400 });
  await page.goto('/ssa', { waitUntil: 'networkidle' });
  await expect.poll(() => page.evaluate(() => document.querySelectorAll('.apexcharts-canvas').length)).toBeGreaterThan(0);

  const renders = await page.evaluate(() => new Promise(done => {
    let count = 0;
    const render = ApexCharts.prototype.render;
    ApexCharts.prototype.render = function () { count += 1; return render.apply(this, arguments); };
    const host = document.createElement('div');
    host.id = 'swap-cost-probe';
    host.style.cssText = 'position:absolute;left:-9999px;top:0;width:10px';
    document.body.appendChild(host);
    htmx.ajax('GET', '/api/health/build', { target: '#swap-cost-probe', swap: 'innerHTML' })
      .then(() => setTimeout(() => { ApexCharts.prototype.render = render; done(count); }, 800));
  }));
  expect(renders).toBe(0);
});

/* A real theme switch still redraws them: that is what the event is for. */
test('a theme switch still redraws the charts', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium-desktop', 'Measured once.');
  await signIn(page, 'pl1@edify.org', 'edify');
  // Tall enough that the trend chart is on screen and renders at once rather
  // than waiting for the lazy observer.
  await page.setViewportSize({ width: 1440, height: 2400 });
  await page.goto('/ssa', { waitUntil: 'networkidle' });
  await expect.poll(() => page.evaluate(() => document.querySelectorAll('.apexcharts-canvas').length)).toBeGreaterThan(0);
  const renders = await page.evaluate(() => new Promise(done => {
    let count = 0;
    const render = ApexCharts.prototype.render;
    ApexCharts.prototype.render = function () { count += 1; return render.apply(this, arguments); };
    window.dispatchEvent(new CustomEvent('edify-theme-change', { detail: { theme: 'dark', preference: 'dark' } }));
    setTimeout(() => { ApexCharts.prototype.render = render; done(count); }, 800);
  }));
  expect(renders).toBeGreaterThan(0);
});
