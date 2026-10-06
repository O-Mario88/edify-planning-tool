/* Which element is extra: the same page loaded with the served script and with the changed one, several times each. */
const { chromium } = require('@playwright/test'); const fs = require('node:fs');
const B = 'http://127.0.0.1:8376';
(async () => { const browser = await chromium.launch();
  for (const variant of ['served', 'changed', 'served', 'changed']) { const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    if (variant === 'changed') await context.route((u) => u.pathname.includes('/static/js/') && u.pathname.includes('micro-ux'), (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: fs.readFileSync('static/js/micro-ux.js') }));
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    await page.goto(B + process.env.PATHNAME, { waitUntil: 'load' });
    const out = [];
    for (const wait of [1500, 2500, 3000, 4000]) { await page.waitForTimeout(wait); out.push(await page.evaluate(() => ({ n: document.body.querySelectorAll('*').length, hints: Array.from(document.querySelectorAll('[class*="scroll-hint"], [class*="swipe"], .edify-table-scroll-hint')).map((e) => e.className).join(',') }))); }
    console.log(variant.padEnd(8), JSON.stringify(out)); await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
