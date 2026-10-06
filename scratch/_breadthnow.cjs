/* Share of a page's elements one <span> added to a table cell restyles, as
 * e2e/performance-budgets.spec.js measures it. Audit tooling.
 *   VIEWPORT=1440x900 EMAIL=cceo1@edify.org PATHS=/my-plan,/dashboard */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376'; const VP = (process.env.VIEWPORT || (process.env.MOBILE === '1' ? '390x844' : '1440x900')).split('x').map(Number);
(async () => { const browser = await chromium.launch(); const context = await browser.newContext({ viewport: { width: VP[0], height: VP[1] }, isMobile: process.env.MOBILE === '1', hasTouch: process.env.MOBILE === '1', serviceWorkers: 'block' }); const page = await context.newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  for (const p of process.env.PATHS.split(',')) { await page.goto(B + p, { waitUntil: 'load' }); await page.waitForTimeout(2500);
    if (!(await page.locator('main table tbody td').count())) { console.log(p + ': no table'); continue; }
    const total = await page.evaluate(() => document.getElementsByTagName('*').length);
    await browser.startTracing(page, { categories: ['devtools.timeline', 'blink.user_timing'] });
    await page.evaluate(() => { const resolve = () => { getComputedStyle(document.body).color; void document.body.offsetWidth; }; const cell = Array.from(document.querySelectorAll('main table tbody td')).pop(); resolve(); performance.mark('edify-probe:start'); const probe = document.createElement('span'); cell.appendChild(probe); resolve(); performance.mark('edify-probe:end'); probe.remove(); });
    const events = JSON.parse((await browser.stopTracing()).toString()).traceEvents; const mark = (name) => events.find((e) => e.name === name && e.cat && e.cat.includes('blink.user_timing')); const from = mark('edify-probe:start'); const to = mark('edify-probe:end');
    const count = events.filter((e) => e.name === 'UpdateLayoutTree' && e.ph === 'X' && e.ts >= from.ts && e.ts <= to.ts).reduce((sum, e) => sum + ((e.args && e.args.elementCount) || 0), 0);
    console.log(`${VP.join('x')} ${p.padEnd(12)} ${count} of ${total} elements restyled by one <span>: ${(100 * count / total).toFixed(0)} %`); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(2); });
