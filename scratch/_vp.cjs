const { chromium } = require('@playwright/test');
const B = 'http://127.0.0.1:8376';
(async () => { const browser = await chromium.launch(); const MOBILE = process.env.MOBILE === '1'; const VP = (process.env.VIEWPORT || (MOBILE ? '390x844' : '1440x900')).split('x').map(Number);
  const context = await browser.newContext({ viewport: { width: VP[0], height: VP[1] }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' });
  await context.addInitScript(`(() => { const sig = () => [innerWidth, innerHeight, document.documentElement ? document.documentElement.clientWidth : '-', document.documentElement ? document.documentElement.clientHeight : '-', window.visualViewport ? Math.round(visualViewport.width) + '/' + Math.round(visualViewport.height) + '@' + visualViewport.scale.toFixed(2) : ''].join('x');
    window.__ev = [['start', 0, [innerWidth, innerHeight].join('x')]]; const note = (n) => window.__ev.push([n, Math.round(performance.now()), sig()]);
    window.addEventListener('resize', () => note('resize')); if (window.visualViewport) visualViewport.addEventListener('resize', () => note('vv-resize'));
    document.addEventListener('DOMContentLoaded', () => note('dcl')); window.addEventListener('load', () => note('load'));
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__ev.push(['paint ' + e.name, Math.round(e.startTime), '']); }).observe({ type: 'paint', buffered: true });
    requestAnimationFrame(function tick() { note('raf'); if (performance.now() < 2500 && window.__ev.filter((e) => e[0] === 'raf').length < 4) requestAnimationFrame(tick); }); })();`);
  const page = await context.newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]); await page.waitForLoadState('load');
  for (const p of process.env.PATHS.split(',')) { await page.goto(B + p, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(2500);
    const ev = await page.evaluate(() => window.__ev); console.log(p + ': ' + ev.sort((a, b) => a[1] - b[1]).map((e) => `${e[0]}@${e[1]}${e[2] ? ' ' + e[2] : ''}`).join('  |  ')); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
