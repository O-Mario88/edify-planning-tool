/* Heights of the sections a browser may leave undrawn (content-visibility:
 * auto), as loaded and after each has been scrolled to, in the final build
 * and the original. Audit tooling.
 *   SELECTOR='.priority-record-row' PAGES='[["cd@edify.org","/strategic-priorities"]]' VIEWPORT=820x1180 */
const fs = require('node:fs'); const path = require('node:path'); const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8379'; const ORIGINAL = JSON.parse(process.env.ORIGINAL || '{}'); const PAGES = JSON.parse(process.env.PAGES);
const MOBILE = process.env.MOBILE === '1'; const VP = (process.env.VIEWPORT || '820x1180').split('x').map(Number); const SELECTOR = process.env.SELECTOR;
const heights = (selector) => { const tally = {}; let skipped = 0; for (const el of document.querySelectorAll(selector)) { const h = Math.round(el.getBoundingClientRect().height); tally[h] = (tally[h] || 0) + 1; if (el.checkVisibility && el.firstElementChild && !el.firstElementChild.checkVisibility({ contentVisibilityAuto: true })) skipped += 1; } const main = document.querySelector('main'); return { tally, skipped, page: Math.max(document.scrollingElement.scrollHeight, main ? main.scrollHeight : 0) }; };
(async () => { const browser = await chromium.launch();
  for (const [account, p] of PAGES) for (const original of [false, true]) {
    const context = await browser.newContext({ viewport: { width: VP[0], height: VP[1] }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' });
    if (original) { for (const [needle, file] of Object.entries(ORIGINAL)) await context.route((u) => u.pathname.includes('/static/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: file.endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(file) }));
      if (process.env.CSS_OLD) await context.route((u) => /\/static\/build\/css\/.+\.css$/.test(u.pathname), (route) => { const q = new URL(route.request().url()).pathname; const m = q.match(/\/static\/build\/css\/(.+?)\.[0-9a-f]{12}\.css$/) || q.match(/\/static\/build\/css\/(.+?)\.css$/); route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(path.join(process.env.CSS_OLD, m[1] + '.css')) }); }); }
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    if (original) await page.route((u) => u.origin === B && !u.pathname.startsWith('/static/'), async (route) => { if (route.request().resourceType() !== 'document') return route.continue(); const response = await route.fetch(); const body = (await response.text()).replace(/(<script\b[^>]*?) blocking="render"/g, '$1').replace(/<link rel="expect"[^>]*>/, ''); await route.fulfill({ response, body }); });
    await page.goto(B + p, { waitUntil: 'load', timeout: 240000 }); await page.waitForTimeout(Number(process.env.WAIT || 4000));
    const loaded = await page.evaluate(heights, SELECTOR);
    await page.evaluate(async () => { const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))); const scrollers = [document.scrollingElement, ...document.querySelectorAll('main')].filter((el) => el && el.scrollHeight > el.clientHeight + 4); for (const s of scrollers) { for (let pass = 0; pass < 2; pass++) for (let y = 0; y < s.scrollHeight; y += Math.max(200, Math.floor(s.clientHeight * 0.8))) { s.scrollTop = y; await frame(); } s.scrollTop = 0; await frame(); } });
    await page.waitForTimeout(300); const scrolled = await page.evaluate(heights, SELECTOR);
    console.log(`${original ? 'ORIGINAL' : 'FINAL   '} ${account.split('@')[0]} ${p} ${VP.join('x')}${MOBILE ? ' phone' : ''} ${SELECTOR}\n   as loaded:        page ${loaded.page}px, undrawn ${loaded.skipped}, heights ${JSON.stringify(loaded.tally)}\n   scrolled through: page ${scrolled.page}px, undrawn ${scrolled.skipped}, heights ${JSON.stringify(scrolled.tally)}`);
    await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(2); });
