/* Why does a filter row or a tab rail settle differently between the original
 * build and the final one at 1100px? Logs, in each world, the width of the
 * sidebar and the page column at the moments the scripts measure them.
 * Audit tooling.
 *   BASE=http://127.0.0.1:8379 PAGES='[["cceo1@edify.org","/notifications"]]' VIEWPORT=1100x800
 *   OVERRIDES / CSS_OLD / HTML_STRIP as in _domdiff.cjs describe the original world. */
const fs = require('node:fs'); const path = require('node:path'); const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8379';
const OV = JSON.parse(process.env.OVERRIDES || '{}'); const PAGES = JSON.parse(process.env.PAGES);
const VP = (process.env.VIEWPORT || '1100x800').split('x').map(Number);
const PROBE = `(() => {
  const log = (window.__log = []);
  const widths = () => {
    const aside = document.querySelector('aside.app-sidebar'); const main = document.querySelector('main');
    const row = document.querySelector('[data-edify-filter-row], .edify-filter-row'); const rail = document.querySelector('[role="tablist"], [data-edify-tablist]');
    const w = (el) => (el ? Math.round(el.getBoundingClientRect().width) : null);
    return 'aside ' + w(aside) + (aside && aside.classList.contains('app-sidebar--collapsed') ? ' (collapsed)' : '') + ' main ' + w(main) + ' row ' + w(row) + ' rail ' + w(rail) + ' inner ' + window.innerWidth;
  };
  const note = (what, measure) => log.push(Math.round(performance.now()) + 'ms ' + what + (measure === false ? '' : ' | ' + widths()));
  window.__note = note;
  document.addEventListener('DOMContentLoaded', () => note('DOMContentLoaded (before the page scripts hear it)'), true);
  window.addEventListener('load', () => note('load'));
  window.addEventListener('resize', () => note('resize event'));
  document.addEventListener('alpine:init', () => note('alpine:init'));
  document.addEventListener('alpine:initialized', () => note('alpine:initialized'));
  let frames = 0; const frame = () => { frames += 1; if (frames <= 3) note('frame ' + frames); if (frames < 3) requestAnimationFrame(frame); }; requestAnimationFrame(frame);
  new MutationObserver((records) => { for (const r of records) {
    if (r.type === 'attributes' && r.attributeName === 'data-edify-filter-slots') note('slots = ' + r.target.getAttribute('data-edify-filter-slots') + ' (was ' + r.oldValue + ')', false);
    if (r.type === 'attributes' && r.attributeName === 'class' && r.target.matches && r.target.matches('aside.app-sidebar')) note('sidebar class -> ' + (r.target.classList.contains('app-sidebar--collapsed') ? 'collapsed' : 'open'), false);
    if (r.type === 'attributes' && r.attributeName === 'hidden' && r.target.matches && r.target.matches('.edify-rail-more')) note('rail More hidden = ' + r.target.hidden, false);
    if (r.type === 'childList') for (const n of r.addedNodes) if (n.nodeType === 1 && n.matches('.edify-rail-more')) note('rail More added', false);
  } }).observe(document, { subtree: true, childList: true, attributes: true, attributeOldValue: true, attributeFilter: ['data-edify-filter-slots', 'class', 'hidden'] });
})();`;
(async () => { const browser = await chromium.launch();
  const open = async (account, original) => { const context = await browser.newContext({ viewport: { width: VP[0], height: VP[1] }, serviceWorkers: 'block' });
    if (original) { for (const [needle, file] of Object.entries(OV)) await context.route((u) => u.pathname.includes('/static/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: file.endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(file) }));
      if (process.env.CSS_OLD) await context.route((u) => /\/static\/build\/css\/.+\.css$/.test(u.pathname), (route) => { const p = new URL(route.request().url()).pathname; const m = p.match(/\/static\/build\/css\/(.+?)\.[0-9a-f]{12}\.css$/) || p.match(/\/static\/build\/css\/(.+?)\.css$/); route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(path.join(process.env.CSS_OLD, m[1] + '.css')) }); }); }
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    if (original && process.env.HTML_STRIP === '1') await page.route((u) => u.origin === B && !u.pathname.startsWith('/static/'), async (route) => { if (route.request().resourceType() !== 'document') return route.continue(); const response = await route.fetch(); const body = (await response.text()).replace(/(<script\b[^>]*?) blocking="render"/g, '$1').replace(/<link rel="expect"[^>]*>/, ''); await route.fulfill({ response, body }); });
    await page.addInitScript(PROBE); return { context, page }; };
  for (const [account, p] of PAGES) for (const original of [false, true]) {
    if (original && process.env.ONLY === 'final') continue; if (!original && process.env.ONLY === 'original') continue;
    const { context, page } = await open(account, original);
    await page.goto(B + p, { waitUntil: 'load', timeout: 240000 }); await page.waitForTimeout(Number(process.env.WAIT || 2500));
    const end = await page.evaluate(() => { window.__note('settled'); return { log: window.__log, slots: [...document.querySelectorAll('[data-edify-filter-slots]')].map((r) => r.getAttribute('data-edify-filter-slots')), more: [...document.querySelectorAll('.edify-rail-more')].map((m) => (m.hidden ? 'hidden' : 'shown')) }; });
    console.log(`\n== ${original ? 'ORIGINAL' : 'FINAL'} ${account.split('@')[0]} ${p} ${VP.join('x')}: slots ${JSON.stringify(end.slots)} rail More ${JSON.stringify(end.more)}`); for (const line of end.log) console.log('   ' + line);
    await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(2); });
