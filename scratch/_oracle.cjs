/* Computed-style oracle: does a rebuilt set of stylesheets change anything the
 * browser computes? For each page state it records every computed property of
 * every element (and its ::before / ::after / ::selection) with the stylesheets
 * the server sends, swaps each built stylesheet in place for the candidate on
 * disk, records again on the SAME DOM, and reports every difference. The
 * comparison happens inside the page; only differences come back. A state
 * whose DOM changed between the two recordings is retried. Audit tooling only.
 *
 *   PAGES_FILE=pages.json CANDIDATE=static/build/css node scratch/_oracle.cjs
 */
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require('@playwright/test');

const B = process.env.BASE || 'http://127.0.0.1:8376';
const CANDIDATE = path.resolve(process.env.CANDIDATE || 'static/build/css');
const ENGINE = process.env.ENGINE === 'webkit' ? webkit : chromium;
const THEMES = (process.env.THEMES || 'light,blue,dark').split(',');
const VIEWPORTS = (process.env.VIEWPORTS || '1440x900,820x1180,390x844').split(',').map((v) => v.split('x').map(Number));
const PAGES = JSON.parse(fs.readFileSync(process.env.PAGES_FILE, 'utf8'));
const OUT = process.env.OUT;
// Stylesheets served as written (not built) that are compared too: {"css/components/mobile-shell": "/path/to/the/other.css"}.
const ALSO = JSON.parse(process.env.ALSO || '{}');
const SETTLE = Number(process.env.SETTLE || 9000);

/* Runs in the page. mode 'record' keeps the first reading on window; mode
 * 'compare' reads again and returns the differences. */
function readFn(mode) {
  const norm = (v) => String(v).replace(/\s+/g, ' ').replace(/(^|[\s,(\/*:])([-+]?)\.(\d)/g, '$1$20.$3').trim();
  if (!window.__oracleNames) {
    const root = getComputedStyle(document.documentElement); const standard = []; for (let i = 0; i < root.length; i++) if (!root[i].startsWith('--')) standard.push(root[i]);
    const scoped = new Set();
    // One optional tail, not a repeated one: the tail's own characters already
    // include `.`, `:` and `[`, so repeating it matched nothing more and only
    // multiplied the ways a long non-match could be tried.
    const rootish = /^(:root|html)(?:[.:\[][^\s,>+~]*)?$/;
    const walk = (rules) => { for (const r of rules) { if (r.style && r.selectorText !== undefined) { if (!r.selectorText.split(',').every((part) => rootish.test(part.trim()))) for (let i = 0; i < r.style.length; i++) if (r.style[i].startsWith('--')) scoped.add(r.style[i]); }
        if (r.cssRules && r.cssRules.length) walk(r.cssRules); } };
    for (const sheet of document.styleSheets) { try { walk(sheet.cssRules); } catch (e) { /* another origin */ } }
    window.__oracleNames = { standard, scoped: Array.from(scoped) };
  }
  const { standard, scoped } = window.__oracleNames;
  const read = (el, pseudo) => { const cs = getComputedStyle(el, pseudo); const out = [];
    for (const p of standard) out.push(p + '\u0001' + cs.getPropertyValue(p));
    if (!pseudo && (el === document.documentElement || el === document.body)) { for (let i = 0; i < cs.length; i++) { const p = cs[i]; if (p.startsWith('--')) out.push(p + '\u0001' + norm(cs.getPropertyValue(p))); } }
    else for (const p of scoped) out.push(p + '\u0001' + norm(cs.getPropertyValue(p)));
    return out.join('\u0002'); };
  const els = [document.documentElement, document.body].concat(Array.from(document.body.querySelectorAll('*')));
  const now = els.map((el) => { const before = getComputedStyle(el, '::before').content; const after = getComputedStyle(el, '::after').content; const sel = getComputedStyle(el, '::selection');
    return [read(el, null), before !== 'none' && before !== 'normal' ? read(el, '::before') : '', after !== 'none' && after !== 'normal' ? read(el, '::after') : '', sel.backgroundColor + '|' + sel.color]; });
  if (mode === 'record') { window.__oracleEls = els; window.__oracleA = now; window.__oracleMutated = 0;
    window.__oracleObserver = new MutationObserver((records) => { window.__oracleMutated += records.length; });
    window.__oracleObserver.observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
    return { elements: els.length, values: now.reduce((s, e) => s + e[0].split('\u0002').length, 0) }; }
  const was = window.__oracleA; const same = els.length === was.length && els.every((el, i) => el === window.__oracleEls[i]);
  window.__oracleObserver.disconnect();
  if (!same || window.__oracleMutated) return { unstable: true, mutated: window.__oracleMutated, count: [was.length, els.length] };
  const name = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + '.' + String(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className).trim().split(/\s+/).slice(0, 4).join('.');
  const parts = ['element', '::before', '::after', '::selection']; const diffs = []; let count = 0;
  for (let i = 0; i < els.length; i++) for (let k = 0; k < 4; k++) { if (was[i][k] === now[i][k]) continue; count++;
    if (diffs.length >= 12) continue;
    if (k === 3) { diffs.push({ el: name(els[i]), part: parts[k], was: was[i][k], now: now[i][k] }); continue; }
    if (!was[i][k] || !now[i][k]) { diffs.push({ el: name(els[i]), part: parts[k], what: 'pseudo-element appeared or disappeared' }); continue; }
    const a = new Map(was[i][k].split('\u0002').map((x) => x.split('\u0001'))); const b = new Map(now[i][k].split('\u0002').map((x) => x.split('\u0001')));
    for (const [p, v] of a) if (b.get(p) !== v && diffs.length < 12) diffs.push({ el: name(els[i]), part: parts[k], prop: p, was: String(v).slice(0, 80), now: String(b.get(p)).slice(0, 80) }); }
  return { differences: count, sample: diffs };
}

/* param 'oraclesame' asks the server for the same file again (the control);
 * 'oraclesplit' is answered from the candidate directory. */
async function swapFn(arg) {
  const param = typeof arg === 'string' ? arg : arg.param; const also = (arg && arg.also) || [];
  const links = Array.from(document.querySelectorAll('link[rel=stylesheet]')).filter((l) => /\/static\/build\/css\//.test(l.href) || also.some((needle) => l.href.includes(needle)));
  await Promise.all(links.map((old) => new Promise((resolve, reject) => {
    const fresh = document.createElement('link'); fresh.rel = 'stylesheet'; const u = new URL(old.href); u.searchParams.delete('oraclesame'); u.searchParams.set(param, '1'); fresh.href = u.href;
    fresh.onload = () => { old.remove(); resolve(); }; fresh.onerror = () => reject(new Error('failed ' + fresh.href));
    old.insertAdjacentElement('afterend', fresh);
  })));
  getComputedStyle(document.body).color; void document.body.offsetWidth;
  return links.length;
}

async function state(page, pagePath, settle, extra) {
  await page.goto(B + pagePath, { waitUntil: 'load', timeout: 240000 });
  if (extra) await page.waitForTimeout(extra);
  await page.evaluate((cap) => new Promise((resolve) => { let timer = null; const started = Date.now();
    const quiet = () => { clearTimeout(timer); timer = setTimeout(done, 1500); }; const done = () => { observer.disconnect(); resolve(); };
    const observer = new MutationObserver(() => { if (Date.now() - started > cap) done(); else quiet(); });
    observer.observe(document.body, { subtree: true, childList: true, attributes: true }); quiet(); setTimeout(done, cap + 2000); }), settle);
  await page.addStyleTag({ content: '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}' });
  await page.waitForTimeout(250);
  // Control first: the same stylesheets swapped in once, so both readings
  // follow a stylesheet swap. (Without it a `content-visibility: auto` grid
  // below the fold reads its tracks from the layout a page script forced
  // during load, then `none` after any swap -- with identical CSS too.)
  await page.evaluate(swapFn, { param: 'oraclesame', also: Object.keys(ALSO) });
  await page.waitForTimeout(200);
  const first = await page.evaluate(readFn, 'record');
  const sheets = await page.evaluate(swapFn, { param: 'oraclesplit', also: Object.keys(ALSO) });
  await page.waitForTimeout(200);
  const result = await page.evaluate(readFn, 'compare');
  return { ...first, sheets, ...result, landed: new URL(page.url()).pathname };
}

(async () => {
  const browser = await ENGINE.launch();
  const report = []; let states = 0, elements = 0, values = 0, bad = 0, errors = 0, unstable = 0;
  for (const [width, height] of VIEWPORTS) for (const theme of THEMES) for (const [account, paths] of Object.entries(PAGES)) {
    const context = await browser.newContext({ viewport: { width, height }, colorScheme: 'light', hasTouch: width < 500 });
    await context.route((u) => u.searchParams.get('oraclesplit') === '1', (route) => {
      const p = new URL(route.request().url()).pathname; const other = Object.keys(ALSO).find((needle) => p.includes(needle));
      if (other) return route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(ALSO[other]) });
      const m = p.match(/\/static\/build\/css\/(.+?)\.[0-9a-f]{12}\.css$/) || p.match(/\/static\/build\/css\/(.+?)\.css$/);
      route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(path.join(CANDIDATE, m[1] + '.css')) });
    });
    const page = await context.newPage();
    try {
      await page.goto(B + '/login'); await page.evaluate((t) => localStorage.setItem('edify_theme', t), theme);
      await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify');
      await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    } catch (e) { errors++; console.log(`ERROR signing in ${account}: ${String(e).slice(0, 120)}`); await context.close(); continue; }
    for (const p of paths) {
      states++; let r = null;
      for (let attempt = 0; attempt < 3; attempt++) {
        try { r = await state(page, p, SETTLE, attempt * 5000); } catch (e) { r = { error: String(e).slice(0, 160) }; }
        if (!r.unstable) break;
      }
      const tag = `${account.split('@')[0].padEnd(24)} ${p.padEnd(30)} ${theme.padEnd(5)} ${[width, height].join('x').padEnd(9)}`;
      if (r.error) { errors++; console.log(`ERROR ${tag} ${r.error}`); continue; }
      if (r.unstable) { unstable++; console.log(`MOVED ${tag} the page kept changing (mutations ${r.mutated}, elements ${r.count})`); continue; }
      if (/\/login/.test(r.landed)) { errors++; console.log(`ERROR ${tag} landed on the sign-in page`); continue; }
      elements += r.elements; values += r.values;
      if (r.differences) bad++;
      console.log(`${r.differences ? 'DIFF ' : 'same '} ${tag} elements ${String(r.elements).padStart(5)} sheets ${r.sheets} differences ${r.differences}`);
      for (const d of r.sample) console.log('        ' + JSON.stringify(d).slice(0, 260));
      report.push({ account, page: p, theme, viewport: `${width}x${height}`, elements: r.elements, values: r.values, differences: r.differences, sample: r.sample });
    }
    await context.close();
  }
  console.log(`\n${states} page states; ${report.length} compared: ${elements} elements, ${values} computed values; ${bad} with differences; ${unstable} kept changing; ${errors} errors`);
  if (OUT) fs.writeFileSync(OUT, JSON.stringify(report, null, 1));
  await browser.close();
  process.exit(bad || errors || unstable ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
