/* The laptop-width gate of e2e/performance-budgets.spec.js, run against the
 * original build and against the final one, to see it fail on the first.
 * Audit tooling. */
const fs = require('node:fs'); const path = require('node:path'); const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8379'; const ORIGINAL = JSON.parse(process.env.ORIGINAL || '{}');
const FITTED = `(() => ({
  sidebar: Math.round(document.querySelector('aside.app-sidebar').getBoundingClientRect().width),
  shut: document.querySelector('aside.app-sidebar').classList.contains('app-sidebar--collapsed'),
  rows: Array.from(document.querySelectorAll('[data-edify-filter-slots]')).map((row) => [row.dataset.edifyFilterSlots, row.style.getPropertyValue('--edify-filter-cols').trim(), row.querySelectorAll('[data-edify-filter-moved]').length].join('/')),
  rails: Array.from(document.querySelectorAll('.edify-rail-more')).map((more) => (more.hidden ? 0 : more.querySelectorAll('.edify-rail-more__item').length)),
  tables: Array.from(document.querySelectorAll('table[data-edify-wrap-at]')).map((table) => table.getAttribute('data-edify-wrap-at')),
}))()`;
(async () => { const browser = await chromium.launch();
  for (const world of ['original', 'unheld', 'final']) {
    const context = await browser.newContext({ viewport: { width: 1100, height: 800 }, serviceWorkers: 'block' });
    if (world === 'original') { for (const [needle, file] of Object.entries(ORIGINAL)) await context.route((u) => u.pathname.includes('/static/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: file.endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(file) }));
      await context.route((u) => /\/static\/build\/css\/.+\.css$/.test(u.pathname), (route) => { const q = new URL(route.request().url()).pathname; const m = q.match(/\/static\/build\/css\/(.+?)\.[0-9a-f]{12}\.css$/) || q.match(/\/static\/build\/css\/(.+?)\.css$/); route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(path.join(process.env.CSS_OLD, m[1] + '.css')) }); }); }
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', 'cceo1@edify.org'); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    if (world !== 'final') await page.route((u) => u.origin === B && !u.pathname.startsWith('/static/'), async (route) => { if (route.request().resourceType() !== 'document') return route.continue(); const response = await route.fetch(); const body = (await response.text()).replace(/(<script\b[^>]*?) blocking="render"/g, '$1').replace(/<link rel="expect"[^>]*>/, ''); await route.fulfill({ response, body }); });
    for (const p of ['/my-plan', '/core-schools']) { await page.goto(B + p, { waitUntil: 'load' }); await page.waitForTimeout(2500); const opened = await page.evaluate(FITTED);
      await page.evaluate(() => window.dispatchEvent(new Event('resize'))); await page.waitForTimeout(900); const again = await page.evaluate(FITTED);
      const same = JSON.stringify([opened.rows, opened.rails, opened.tables]) === JSON.stringify([again.rows, again.rails, again.tables]);
      console.log(`${same ? 'PASS' : 'FAIL'} ${world.padEnd(8)} ${p.padEnd(14)} opened rows ${JSON.stringify(opened.rows)} rails ${JSON.stringify(opened.rails)} tables ${JSON.stringify(opened.tables)}${same ? '' : '\n' + ' '.repeat(29) + 're-fit rows ' + JSON.stringify(again.rows) + ' rails ' + JSON.stringify(again.rails) + ' tables ' + JSON.stringify(again.tables)}`); }
    await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(2); });
