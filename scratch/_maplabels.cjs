/* When do the country map's district names get their places and appear, in
 * the final build and in the original? Samples the label layer for ten
 * seconds after the page loads. Audit tooling.
 *   PAGES='[["rvp@edify.org","/country-map/"]]' VIEWPORT=1100x800 */
const fs = require('node:fs'); const path = require('node:path'); const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8379'; const ORIGINAL = JSON.parse(process.env.ORIGINAL || '{}'); const PAGES = JSON.parse(process.env.PAGES);
const VP = (process.env.VIEWPORT || '1100x800').split('x').map(Number); const WORLDS = (process.env.WORLDS || 'final,original').split(',');
const SAMPLE = `(() => { const log = (window.__labels = []); const started = performance.now();
  const read = () => { const layer = document.querySelector('g.sr-labels'); if (!layer) return 'no label layer'; const texts = layer.querySelectorAll('text.sr-dl'); let placed = 0; let hidden = 0; for (const t of texts) { if (t.hasAttribute('data-label-placement')) placed += 1; if (t.getAttribute('data-label-placement') === 'hidden') hidden += 1; }
    return 'layer opacity ' + (layer.style.opacity === '' ? 'shown' : layer.style.opacity) + ', ' + placed + ' of ' + texts.length + ' placed (' + hidden + ' not drawn)'; };
  let last = ''; const tick = () => { const now = read(); if (now !== last) { log.push(Math.round(performance.now() - started) + 'ms ' + now); last = now; } if (performance.now() - started < 10000) setTimeout(tick, 50); };
  document.addEventListener('DOMContentLoaded', tick); })();`;
(async () => { const browser = await chromium.launch();
  for (const [account, p] of PAGES) for (const world of WORLDS) {
    const context = await browser.newContext({ viewport: { width: VP[0], height: VP[1] }, serviceWorkers: 'block' });
    if (world === 'original') { for (const [needle, file] of Object.entries(ORIGINAL)) await context.route((u) => u.pathname.includes('/static/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: file.endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(file) }));
      await context.route((u) => /\/static\/build\/css\/.+\.css$/.test(u.pathname), (route) => { const q = new URL(route.request().url()).pathname; const m = q.match(/\/static\/build\/css\/(.+?)\.[0-9a-f]{12}\.css$/) || q.match(/\/static\/build\/css\/(.+?)\.css$/); route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(path.join(process.env.CSS_OLD, m[1] + '.css')) }); }); }
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    if (world !== 'final') await page.route((u) => u.origin === B && !u.pathname.startsWith('/static/'), async (route) => { if (route.request().resourceType() !== 'document') return route.continue(); const response = await route.fetch(); const body = (await response.text()).replace(/(<script\b[^>]*?) blocking="render"/g, '$1').replace(/<link rel="expect"[^>]*>/, ''); await route.fulfill({ response, body }); });
    await page.addInitScript(SAMPLE);
    for (let run = 1; run <= Number(process.env.RUNS || 2); run++) { await page.goto(B + p, { waitUntil: 'load', timeout: 240000 }); await page.waitForTimeout(10500); const log = await page.evaluate(() => window.__labels);
      console.log(`${world.padEnd(8)} ${account.split('@')[0]} ${p} ${VP.join('x')} load ${run}:`); for (const line of log) console.log('    ' + line); }
    await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(2); });
