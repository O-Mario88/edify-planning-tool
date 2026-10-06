const { chromium } = require('@playwright/test'); const fs = require('node:fs');
const B = 'http://127.0.0.1:8376';
(async () => { const browser = await chromium.launch();
  for (const variant of ['served', 'changed']) { const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    if (variant === 'changed') await context.route((u) => u.pathname.includes('/static/js/') && u.pathname.includes('micro-ux'), (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: fs.readFileSync('static/js/micro-ux.js') }));
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', 'pl1@edify.org'); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    await page.goto(B + '/dashboard', { waitUntil: 'load' }); await page.waitForTimeout(4000);
    const r = await page.evaluate(() => { const span = document.querySelector('.dashboard-view-nav__updating'); const rail = span.parentElement; const cs = getComputedStyle(span);
      return { order: Array.from(rail.children).map((c) => c.tagName.toLowerCase() + (c.classList.contains('edify-rail-more') ? '.more' : c === span ? '.updating' : '')).join(' '), spanOpacity: cs.opacity, spanVisibility: cs.visibility, spanDisplay: cs.display, spanZ: cs.zIndex,
        links: Array.from(rail.querySelectorAll(':scope > a, :scope > button')).map((a) => getComputedStyle(a).position + '/' + getComputedStyle(a).zIndex).join(' '), more: (() => { const m = rail.querySelector(':scope > .edify-rail-more'); return m ? getComputedStyle(m).position + '/' + getComputedStyle(m).zIndex + (m.hidden ? ' hidden' : ' shown') : 'none'; })(),
        spanBox: JSON.stringify(span.getBoundingClientRect()), a11y: span.getAttribute('aria-hidden') }; });
    console.log(variant, JSON.stringify(r)); await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
