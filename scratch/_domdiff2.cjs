/* The final build against the original one, page by page: which side is which
 * is a setting, and so is whether a side is re-fitted (a resize event, which
 * makes micro-ux.js fit the whole page again) before it is read. Two readings
 * of each page: its elements in document order (as _domdiff.cjs), and what is
 * drawn where (tag, classes, box and text of every drawn element, order
 * ignored), the second also after every section has been scrolled through
 * once so that nothing is standing in for itself at a remembered height.
 * Audit tooling.
 *   A=final B=original B_REFIT=1 VIEWPORT=1100x800 PAGES='[["cceo1@edify.org","/my-plan"]]'
 *   ORIGINAL='{"js/micro-ux":"…/micro-ux.orig.js"}' CSS_OLD=dir   (what "original" is served from) */
const fs = require('node:fs'); const path = require('node:path'); const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
const ORIGINAL = JSON.parse(process.env.ORIGINAL || '{}'); const PAGES = JSON.parse(process.env.PAGES);
const MOBILE = process.env.MOBILE === '1'; const VP = (process.env.VIEWPORT || (MOBILE ? '390x844' : '1440x900')).split('x').map(Number);
const SIDE = { a: { world: process.env.A || 'final', refit: process.env.A_REFIT === '1' }, b: { world: process.env.B || 'original', refit: process.env.B_REFIT === '1' } };
const SHOW = Number(process.env.SHOW || 4); const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function structure() {
  const skip = new Set(['data-edify-select-column', 'data-edify-head-run', 'data-edify-beside-link', 'data-edify-has-submit', 'hx-headers', 'value', 'nonce', 'href', 'src', 'action', 'hx-get', 'hx-post', 'hx-vals', 'data-edify-outbox-owner', 'id', 'for', 'aria-controls', 'aria-labelledby', 'aria-describedby', 'name', 'x-data', 'x-init', 'd', 'points', 'transform']);
  const out = [];
  for (const el of document.body.querySelectorAll('*')) { if (el.closest('script, style, template, .apexcharts-canvas, .leaflet-container')) continue;
    const attrs = []; for (const a of el.attributes) { if (skip.has(a.name) || a.name.startsWith('@') || a.name.startsWith(':') || a.name.startsWith('x-on')) continue; attrs.push(a.name + '=' + (a.name === 'class' ? a.value.trim().split(/\s+/).sort().join(' ') : a.value.trim())); }
    const drawn = el.checkVisibility ? el.checkVisibility({ contentVisibilityAuto: true }) : true; const box = drawn && !el.closest('.animate-spin') ? el.getBoundingClientRect() : null;
    const text = el.children.length ? '' : ' \u0000"' + (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40) + '"';
    out.push(el.tagName.toLowerCase() + ' ' + attrs.sort().join(' | ') + (box ? ' @' + Math.round(box.width) + 'x' + Math.round(box.height) : ' @-') + text); }
  return out;
}
/* What is drawn where: one line per drawn element, sorted, so the order of the markup does not matter. */
function drawn() {
  const out = [];
  for (const el of document.body.querySelectorAll('*')) { if (el.closest('script, style, template, .apexcharts-canvas, .leaflet-container, .animate-spin')) continue;
    if (el.checkVisibility && !el.checkVisibility({ contentVisibilityAuto: true, visibilityProperty: true })) continue;
    const box = el.getBoundingClientRect(); if (!box.width || !box.height) continue;
    const scroller = el.closest('main') || document.scrollingElement; const top = box.top + (el.closest('main') ? scroller.scrollTop : window.scrollY);
    const text = el.children.length ? '' : (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    out.push([Math.round(box.left), Math.round(top), Math.round(box.width), Math.round(box.height)].join(',') + ' ' + el.tagName.toLowerCase() + '.' + String(el.getAttribute('class') || '').trim().split(/\s+/).sort().join('.') + ' \u0000"' + text + '"'); }
  return out.sort();
}
async function scrollThrough(page) { await page.evaluate(async () => { const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const scrollers = [document.scrollingElement, ...document.querySelectorAll('main')].filter((el) => el && el.scrollHeight > el.clientHeight + 4);
  for (const scroller of scrollers) { for (let pass = 0; pass < 2; pass++) { for (let y = 0; y < scroller.scrollHeight; y += Math.max(200, Math.floor(scroller.clientHeight * 0.8))) { scroller.scrollTop = y; await frame(); } } scroller.scrollTop = 0; await frame(); } }); await page.waitForTimeout(300); }
async function settle(page) { await page.waitForLoadState('load'); await page.evaluate(() => new Promise((resolve) => { let timer; const started = Date.now(); const done = () => { observer.disconnect(); resolve(); }; const quiet = () => { clearTimeout(timer); timer = setTimeout(done, 1800); }; const observer = new MutationObserver(() => { if (Date.now() - started > 12000) done(); else quiet(); }); observer.observe(document.body, { subtree: true, childList: true, attributes: true }); quiet(); })); await page.waitForTimeout(400); }
(async () => { const browser = await chromium.launch(); let bad = 0; let looks = 0; let worded = 0;
  const open = async (account, side) => { const original = side.world === 'original';
    const context = await browser.newContext({ viewport: { width: VP[0], height: VP[1] }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' });
    if (original) { for (const [needle, file] of Object.entries(ORIGINAL)) await context.route((u) => u.pathname.includes('/static/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: file.endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(file) }));
      if (process.env.CSS_OLD) await context.route((u) => /\/static\/build\/css\/.+\.css$/.test(u.pathname), (route) => { const p = new URL(route.request().url()).pathname; const m = p.match(/\/static\/build\/css\/(.+?)\.[0-9a-f]{12}\.css$/) || p.match(/\/static\/build\/css\/(.+?)\.css$/); route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(path.join(process.env.CSS_OLD, m[1] + '.css')) }); }); }
    // SIDEBAR=collapsed: someone who keeps the sidebar shut (their choice is remembered in the browser).
    if (process.env.SIDEBAR === 'collapsed') await context.addInitScript(() => { try { localStorage.setItem('edify-sidebar-collapsed', '1'); } catch (e) { /* no storage */ } });
    await sleep(Number(process.env.SIGNIN_GAP || 6500)); // ten sign-ins a minute is the limit
    const page = await context.newPage(); await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    if (new URL(page.url()).pathname.startsWith('/login')) throw new Error('sign-in refused for ' + account);
    // 'unheld' is the final build's own files with only the first-frame hold taken out of the page.
    if (original || side.world === 'unheld') await page.route((u) => u.origin === B && !u.pathname.startsWith('/static/'), async (route) => { if (route.request().resourceType() !== 'document') return route.continue(); const response = await route.fetch(); const body = (await response.text()).replace(/(<script\b[^>]*?) blocking="render"/g, '$1').replace(/<link rel="expect"[^>]*>/, ''); await route.fulfill({ response, body }); });
    return { context, page }; };
  const read = async (page, p, side) => { await page.goto(B + p, { waitUntil: 'load', timeout: 240000 }); if (new URL(page.url()).pathname.startsWith('/login')) throw new Error('signed out at ' + p); await settle(page);
    if (side.refit) { await page.evaluate(() => window.dispatchEvent(new Event('resize'))); await page.waitForTimeout(500); await settle(page); }
    const order = await page.evaluate(structure); const seen = await page.evaluate(drawn); await scrollThrough(page); const all = await page.evaluate(drawn); return { order, seen, all }; };
  const byAccount = {}; for (const [account, p] of PAGES) (byAccount[account] = byAccount[account] || []).push(p);
  const inOrder = (x, y) => { if (x.length !== y.length) return [`element count ${x.length} -> ${y.length}`]; const d = []; for (let i = 0; i < x.length; i++) if (x[i].split('\u0000')[0] !== y[i].split('\u0000')[0]) d.push(`#${i}\n        A ${x[i].slice(0, 260)}\n        B ${y[i].slice(0, 260)}`); return d; };
  /* Lines on one side and not the other. Where the box, tag and classes are the same and only the text is not, that is a
     pair of texts (a clock, a count); anything else is a box that is drawn on one side and not the other. What two loads
     of A already disagree about is left out. */
  const key = (line) => line.split('\u0000')[0];
  const apart = (x, y, noisy) => { const count = new Map(); for (const line of x) count.set(line, (count.get(line) || 0) + 1); const onlyB = []; for (const line of y) { const n = count.get(line) || 0; if (n) count.set(line, n - 1); else onlyB.push(line); } const onlyA = []; for (const [line, n] of count) for (let i = 0; i < n; i++) onlyA.push(line);
    const waiting = new Map(); for (const line of onlyA) { const k = key(line); if (!waiting.has(k)) waiting.set(k, []); waiting.get(k).push(line); }
    let texts = []; let boxB = []; for (const line of onlyB) { const list = waiting.get(key(line)); if (list && list.length) texts.push([list.shift(), line]); else boxB.push(line); } let boxA = []; for (const list of waiting.values()) boxA.push(...list);
    const keys = new Set([...onlyA, ...onlyB].map(key)); if (noisy) { boxA = boxA.filter((l) => !noisy.has(key(l))); boxB = boxB.filter((l) => !noisy.has(key(l))); texts = texts.filter((pair) => !noisy.has(key(pair[0]))); }
    return { boxA, boxB, texts, keys }; };
  /* One account at a time; if the machine sleeps under a run (a lid closed), its timeouts fire on waking: the account is done again. */
  const account_ = async (account, paths) => {
    const out = []; const tally = { bad: 0, looks: 0, worded: 0 }; const first = await open(account, SIDE.a); const kept = {};
    for (const p of paths) { const a = await read(first.page, p, SIDE.a); const control = await read(first.page, p, SIDE.a); kept[p] = { a, control }; }
    await first.context.close();
    const second = await open(account, SIDE.b);
    for (const p of paths) { const b = await read(second.page, p, SIDE.b); const { a, control } = kept[p];
      const noise = inOrder(a.order, control.order); const real = inOrder(a.order, b.order); const noisyAt = new Set(noise.map((n) => n.split('\n')[0])); const beyond = real.filter((r) => !noisyAt.has(r.split('\n')[0]));
      const seen = apart(a.seen, b.seen, apart(a.seen, control.seen).keys); const all = apart(a.all, b.all, apart(a.all, control.all).keys);
      const boxes = seen.boxA.length + seen.boxB.length + all.boxA.length + all.boxB.length; const texts = seen.texts.length + all.texts.length;
      if (beyond.length) tally.bad++; if (boxes) tally.looks++; if (!boxes && texts) tally.worded++;
      out.push(`${beyond.length ? 'DIFF' : 'same'} ${boxes ? 'LOOKS-DIFFERENT' : texts ? 'TEXT-DIFFERS' : 'looks-same'} ${account.split('@')[0].padEnd(8)} ${p.padEnd(26)} ${VP.join('x')}${MOBILE ? ' phone' : ''}: ${a.order.length} elements, ${a.all.length} drawn; in order ${real.length} differ (${beyond.length} beyond two loads of A); drawn as loaded: ${seen.boxA.length + seen.boxB.length} boxes, ${seen.texts.length} texts differ; scrolled through: ${all.boxA.length + all.boxB.length} boxes, ${all.texts.length} texts`);
      for (const d of beyond.slice(0, SHOW)) out.push('     ' + d);
      const show = (line) => line.replace('\u0000', '').slice(0, 220);
      for (const [label, set] of [['as loaded', seen], ['scrolled through', all]]) { for (const line of set.boxA.slice(0, SHOW)) out.push(`     ${label} only A: ${show(line)}`); for (const line of set.boxB.slice(0, SHOW)) out.push(`     ${label} only B: ${show(line)}`); for (const pair of set.texts.slice(0, SHOW)) out.push(`     ${label} text: ${show(pair[0])}  ->  ${pair[1].split('\u0000')[1]}`); } }
    await second.context.close(); return { out, tally }; };
  for (const [account, paths] of Object.entries(byAccount)) { for (let attempt = 1; ; attempt++) { try { const done = await account_(account, paths); for (const line of done.out) console.log(line); bad += done.tally.bad; looks += done.tally.looks; worded += done.tally.worded; break; } catch (error) { if (attempt >= 4) throw error; console.log(`     (again: ${account.split('@')[0]} — ${String(error.message).split('\n')[0]})`); for (const context of browser.contexts()) await context.close().catch(() => {}); await sleep(8000); } } }
  console.log(`A = ${SIDE.a.world}${SIDE.a.refit ? ' re-fitted' : ''}, B = ${SIDE.b.world}${SIDE.b.refit ? ' re-fitted' : ''}: ${PAGES.length} pages, ${bad} differ in order, ${looks} have a box drawn differently, ${worded} differ in a text only`);
  await browser.close(); process.exit(bad || looks ? 1 : 0); })().catch((e) => { console.error(e); process.exit(2); });
