const { chromium } = require('@playwright/test');
const B = 'http://127.0.0.1:8376';
(async () => { const browser = await chromium.launch();
  for (const [vw, vh, mobile] of [[390, 844, true], [360, 740, true], [820, 1180, true], [1100, 800, false]]) for (const [account, path] of [['pl1@edify.org', '/dashboard'], ['cd@edify.org', '/dashboard'], ['cceo1@edify.org', '/dashboard'], ['ia@edify.org', '/ia/dashboard/'], ['hr@edify.org', '/dashboard']]) {
    const context = await browser.newContext({ viewport: { width: vw, height: vh }, isMobile: mobile, hasTouch: mobile, serviceWorkers: 'block' });
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    await page.goto(B + path, { waitUntil: 'load' }); await page.waitForTimeout(3500);
    const r = await page.evaluate(() => Array.from(document.querySelectorAll('.dashboard-view-nav__updating')).map((span) => { const rail = span.parentElement; const s = span.getBoundingClientRect(); const hit = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.left < s.right && b.right > s.left && b.top < s.bottom && b.bottom > s.top; };
      const kids = Array.from(rail.children); return { order: kids.map((c) => (c === span ? 'UPDATING' : c.classList.contains('edify-rail-more') ? (c.hidden ? 'more(hidden)' : 'more') : c.tagName.toLowerCase())).join(' '), overlapsPositionedSibling: kids.filter((c) => c !== span && getComputedStyle(c).position !== 'static' && hit(c)).length, overlapsAnySibling: kids.filter((c) => c !== span && hit(c)).length }; }));
    console.log(`${vw}x${vh} ${account.split('@')[0].padEnd(5)} ${path.padEnd(15)} ${JSON.stringify(r)}`); await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
