/* Two pictures of one page at laptop width as it has just opened: the original
 * build and the final one, one above the other. Audit tooling.
 *   PAGES='[["cceo1@edify.org","/my-plan","my-plan"]]' OUT=dir VIEWPORT=1100x800 CLIP=560 */
const fs = require('node:fs'); const path = require('node:path'); const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8379'; const ORIGINAL = JSON.parse(process.env.ORIGINAL || '{}'); const PAGES = JSON.parse(process.env.PAGES);
const VP = (process.env.VIEWPORT || '1100x800').split('x').map(Number); const CLIP = Number(process.env.CLIP || 560); const OUT = process.env.OUT;
(async () => { const browser = await chromium.launch();
  for (const [account, p, name] of PAGES) { const shots = {};
    for (const original of [true, false]) {
      const context = await browser.newContext({ viewport: { width: VP[0], height: VP[1] }, deviceScaleFactor: 1, serviceWorkers: 'block' });
      if (original) { for (const [needle, file] of Object.entries(ORIGINAL)) await context.route((u) => u.pathname.includes('/static/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: file.endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(file) }));
        if (process.env.CSS_OLD) await context.route((u) => /\/static\/build\/css\/.+\.css$/.test(u.pathname), (route) => { const q = new URL(route.request().url()).pathname; const m = q.match(/\/static\/build\/css\/(.+?)\.[0-9a-f]{12}\.css$/) || q.match(/\/static\/build\/css\/(.+?)\.css$/); route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(path.join(process.env.CSS_OLD, m[1] + '.css')) }); }); }
      const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
      if (original) await page.route((u) => u.origin === B && !u.pathname.startsWith('/static/'), async (route) => { if (route.request().resourceType() !== 'document') return route.continue(); const response = await route.fetch(); const body = (await response.text()).replace(/(<script\b[^>]*?) blocking="render"/g, '$1').replace(/<link rel="expect"[^>]*>/, ''); await route.fulfill({ response, body }); });
      await page.goto(B + p, { waitUntil: 'load', timeout: 240000 }); await page.waitForTimeout(3500);
      if (process.env.SCROLL_TO) await page.evaluate((selector) => { const el = document.querySelector(selector); if (el) el.scrollIntoView({ block: 'start' }); }, process.env.SCROLL_TO).then(() => page.waitForTimeout(400));
      shots[original ? 'original' : 'final'] = (await page.screenshot({ clip: { x: 0, y: Number(process.env.TOP || 0), width: VP[0], height: CLIP } })).toString('base64');
      await context.close(); }
    const sheet = await browser.newPage({ viewport: { width: VP[0] + 48, height: 2 * CLIP + 150 }, deviceScaleFactor: 1 });
    await sheet.setContent(`<body style="margin:0;padding:16px 24px;background:#f3f4f6;font:600 15px/1.4 system-ui,sans-serif;color:#111827">
      <p style="margin:0 0 8px">Before — the build that is live today, ${VP[0]} px wide, page just opened</p><img style="display:block;border:1px solid #9ca3af" src="data:image/png;base64,${shots.original}">
      <p style="margin:18px 0 8px">After — this work, same page, same width, just opened</p><img style="display:block;border:1px solid #9ca3af" src="data:image/png;base64,${shots.final}"></body>`);
    await sheet.waitForTimeout(300); const file = path.join(OUT, `laptop-fit-${name}.png`); await sheet.screenshot({ path: file, fullPage: true }); await sheet.close(); console.log('wrote ' + file); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(2); });
