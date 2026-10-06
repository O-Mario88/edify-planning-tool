/* Is the embedded Staff Activity "Period" rail on the PL dashboard fitted the same way on every load? */
const { chromium } = require('@playwright/test'); const fs = require('node:fs');
const B = 'http://127.0.0.1:8376';
(async () => { const browser = await chromium.launch();
  for (const variant of ['served', 'old', 'served', 'old']) { const context = await browser.newContext({ viewport: { width: 820, height: 1180 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    if (variant === 'old') await context.route((u) => u.pathname.includes('/static/js/') && u.pathname.includes('micro-ux'), (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: fs.readFileSync(process.env.OLD) }));
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    const out = [];
    for (let i = 0; i < 5; i++) { await page.goto(B + '/dashboard', { waitUntil: 'load' }); await page.waitForTimeout(6000);
      out.push(await page.evaluate(() => { const nav = document.querySelector('nav[aria-label="Period"]'); if (!nav) return 'no rail'; const more = nav.querySelector(':scope > .edify-rail-more'); return Math.round(nav.getBoundingClientRect().width) + 'px/' + nav.querySelectorAll(':scope > a').length + ' tabs' + (more ? (more.hidden ? '/more hidden' : '/More') : ''); })); }
    console.log(variant.padEnd(7), out.join('  |  ')); await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
