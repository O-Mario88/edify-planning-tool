/* Does a changed script leave the page's final DOM as it was? Loads each page
 * with the served scripts twice (the second is the control: what differs
 * between two loads anyway), then with files overridden from disk, and
 * compares every element's tag, classes, inline style and state attributes
 * in document order. Audit tooling.
 *   OVERRIDES='{"micro-ux":"static/js/micro-ux.js"}' PAGES='[["cceo1@edify.org","/my-plan"]]' VIEWPORT=390x844 MOBILE=1 */
const fs = require('node:fs'); const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
const OV = JSON.parse(process.env.OVERRIDES || '{}'); const PAGES = JSON.parse(process.env.PAGES);
const MOBILE = process.env.MOBILE === '1'; const VP = (process.env.VIEWPORT || (MOBILE ? '390x844' : '1440x900')).split('x').map(Number);
function snapshot() {
  const skip = new Set(['data-edify-select-column', 'data-edify-head-run', 'data-edify-beside-link', 'hx-headers', 'value', 'nonce', 'href', 'src', 'action', 'hx-get', 'hx-post', 'hx-vals', 'data-edify-outbox-owner', 'id', 'for', 'aria-controls', 'aria-labelledby', 'aria-describedby', 'name', 'x-data', 'x-init', 'd', 'points', 'transform']);
  const out = [];
  for (const el of document.body.querySelectorAll('*')) { if (el.closest('script, style, template, .apexcharts-canvas, .leaflet-container')) continue;
    const attrs = []; for (const a of el.attributes) { if (skip.has(a.name) || a.name.startsWith('@') || a.name.startsWith(':') || a.name.startsWith('x-on')) continue; attrs.push(a.name + '=' + (a.name === 'class' ? a.value.trim().split(/\s+/).sort().join(' ') : a.value.trim())); }
    // A box only for what is drawn and still: not inside a closed <details> or a hidden subtree, not a spinner.
    const drawn = el.checkVisibility ? el.checkVisibility({ contentVisibilityAuto: true }) : true; const box = drawn && !el.closest('.animate-spin') ? el.getBoundingClientRect() : null;
    const text = el.children.length ? '' : ' \u0000"' + (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40) + '"';
    out.push(el.tagName.toLowerCase() + ' ' + attrs.sort().join(' | ') + (box ? ' @' + Math.round(box.width) + 'x' + Math.round(box.height) : ' @-') + text); }
  return out;
}
const RESIZE = process.env.RESIZE ? process.env.RESIZE.split('x').map(Number) : null;
async function settle(page) { await page.waitForLoadState('load'); await page.evaluate(() => new Promise((resolve) => { let timer; const started = Date.now(); const done = () => { observer.disconnect(); resolve(); }; const quiet = () => { clearTimeout(timer); timer = setTimeout(done, 1800); }; const observer = new MutationObserver(() => { if (Date.now() - started > 12000) done(); else quiet(); }); observer.observe(document.body, { subtree: true, childList: true, attributes: true }); quiet(); })); await page.waitForTimeout(400); }
(async () => { const browser = await chromium.launch(); let bad = 0;
  const open = async (account, overrides) => { const context = await browser.newContext({ viewport: { width: VP[0], height: VP[1] }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' });
    for (const [needle, file] of Object.entries(overrides)) await context.route((u) => u.pathname.includes('/static/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: file.endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(file) }));
    if (overrides === OV && process.env.CSS_OLD) await context.route((u) => /\/static\/build\/css\/.+\.css$/.test(u.pathname), (route) => { const p = new URL(route.request().url()).pathname; const m = p.match(/\/static\/build\/css\/(.+?)\.[0-9a-f]{12}\.css$/) || p.match(/\/static\/build\/css\/(.+?)\.css$/); route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(require('node:path').join(process.env.CSS_OLD, m[1] + '.css')) }); });
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    // HTML_STRIP=1: the changed side also gets the page without the first-frame hold (no blocking script, no rel=expect).
    if (process.env.HTML_STRIP === '1' && overrides === OV) await page.route((u) => u.origin === B && !u.pathname.startsWith('/static/'), async (route) => { if (route.request().resourceType() !== 'document') return route.continue(); const response = await route.fetch(); const body = (await response.text()).replace(/(<script\b[^>]*?) blocking="render"/g, '$1').replace(/<link rel="expect"[^>]*>/, ''); await route.fulfill({ response, body }); });
    return { context, page }; };
  const byAccount = {}; for (const [account, p] of PAGES) (byAccount[account] = byAccount[account] || []).push(p);
  for (const [account, paths] of Object.entries(byAccount)) {
    const served = await open(account, {}); const snaps = {};
    for (const p of paths) { await served.page.goto(B + p, { waitUntil: 'load', timeout: 240000 }); await settle(served.page); if (RESIZE) { await served.page.setViewportSize({ width: RESIZE[0], height: RESIZE[1] }); await served.page.waitForTimeout(900); await settle(served.page); } const a = await served.page.evaluate(snapshot); if (RESIZE) await served.page.setViewportSize({ width: VP[0], height: VP[1] }); await served.page.goto(B + p, { waitUntil: 'load', timeout: 240000 }); await settle(served.page); if (RESIZE) { await served.page.setViewportSize({ width: RESIZE[0], height: RESIZE[1] }); await served.page.waitForTimeout(900); await settle(served.page); } const control = await served.page.evaluate(snapshot); if (RESIZE) await served.page.setViewportSize({ width: VP[0], height: VP[1] }); snaps[p] = { a, control }; }
    await served.context.close();
    const changed = await open(account, OV);
    for (const p of paths) { await changed.page.goto(B + p, { waitUntil: 'load', timeout: 240000 }); await settle(changed.page); if (RESIZE) { await changed.page.setViewportSize({ width: RESIZE[0], height: RESIZE[1] }); await changed.page.waitForTimeout(900); await settle(changed.page); } const b = await changed.page.evaluate(snapshot); if (RESIZE) await changed.page.setViewportSize({ width: VP[0], height: VP[1] }); const { a, control } = snaps[p];
      const diff = (x, y) => { if (x.length !== y.length) return [`element count ${x.length} -> ${y.length}`]; const d = []; for (let i = 0; i < x.length; i++) if (x[i].split('\u0000')[0] !== y[i].split('\u0000')[0]) d.push(`#${i}\n        was ${x[i].slice(0, 260)}\n        now ${y[i].slice(0, 260)}`); return d; };
      const noise = diff(a, control); const real = diff(a, b); const noisy = new Set(noise.map((n) => n.split('\n')[0])); const beyond = real.filter((r) => !noisy.has(r.split('\n')[0]));
      if (beyond.length) bad++;
      console.log(`${beyond.length ? 'DIFF' : 'same'} ${account.split('@')[0].padEnd(8)} ${p.padEnd(26)} ${VP.join('x')}${MOBILE ? ' phone' : ''}${RESIZE ? ' then ' + RESIZE.join('x') : ''}: ${a.length} elements; between two loads of the same scripts ${noise.length} differ; with the change ${real.length} differ (${beyond.length} beyond that)`);
      for (const d of beyond.slice(0, Number(process.env.SHOW || 4))) console.log('     ' + d); }
    await changed.context.close(); }
  await browser.close(); process.exit(bad ? 1 : 0); })().catch((e) => { console.error(e); process.exit(2); });
