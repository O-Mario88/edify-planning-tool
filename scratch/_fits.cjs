const { chromium } = require('@playwright/test'); const fs = require('node:fs');
const B = 'http://127.0.0.1:8376';
(async () => { const browser = await chromium.launch();
  for (const spec of JSON.parse(process.env.SPECS)) { const [vw, vh, mobile, account, path] = spec;
    const context = await browser.newContext({ viewport: { width: vw, height: vh }, isMobile: mobile, hasTouch: mobile, serviceWorkers: 'block' });
    await context.route((u) => u.pathname.includes('/static/js/') && u.pathname.includes('micro-ux'), (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: fs.readFileSync(process.env.FILE) }));
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    await page.goto(B + path, { waitUntil: 'load' }); await page.waitForTimeout(4000);
    const r = await page.evaluate(() => ({ fits: window.__fits, fp: Math.round((performance.getEntriesByType('paint')[0] || {}).startTime || 0) }));
    console.log(`${vw}x${vh}${mobile ? ' phone' : ''} ${account.split('@')[0]} ${path}: first paint ${r.fp}`); for (const f of r.fits || []) console.log(`     @${String(f[0]).padStart(5)} ${String(f[1]).padEnd(34)} ${String(f[2] || "").slice(0, 150)}`); await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
