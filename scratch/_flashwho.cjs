/* Which script lines write classes / insert nodes after a page's first paint.
 * Wraps the DOM write methods to keep a short stack. Audit tooling (timings
 * are inflated by the wrapping; counts and order are what matter). */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
const INIT = `(() => { const w = window; w.__w = [];
  const where = () => { const st = (new Error().stack || '').split('\\n').slice(2).map((l) => l.trim()).filter((l) => !/__w|<anonymous>:|addInitScript/.test(l)); const own = st.find((l) => /static\\/js\\/(?!vendor)/.test(l)) || st[0] || '?'; const m = own.match(/at (\\S+)? ?\\(?.*\\/([^/?]+)(?:\\?[^:]*)?:(\\d+):\\d+\\)?$/); return m ? (m[2].replace(/\\.[0-9a-f]{12}\\./, '.') + ':' + m[3] + ' ' + (m[1] || '')) : own.slice(0, 90); };
  const note = (kind, n) => { w.__w.push([performance.now(), kind, where(), n || 1]); };
  const tl = DOMTokenList.prototype; for (const name of ['add', 'remove', 'toggle', 'replace']) { const orig = tl[name]; tl[name] = function () { note('class'); return orig.apply(this, arguments); }; }
  const sa = Element.prototype.setAttribute; Element.prototype.setAttribute = function (n) { note(n === 'class' ? 'class' : 'attr'); return sa.apply(this, arguments); };
  const ra = Element.prototype.removeAttribute; Element.prototype.removeAttribute = function (n) { note(n === 'class' ? 'class' : 'attr'); return ra.apply(this, arguments); };
  const cn = Object.getOwnPropertyDescriptor(Element.prototype, 'className'); Object.defineProperty(Element.prototype, 'className', { get: cn.get, set(v) { note('class'); return cn.set.call(this, v); }, configurable: true });
  for (const [proto, names] of [[Node.prototype, ['appendChild', 'insertBefore', 'removeChild', 'replaceChild']], [Element.prototype, ['append', 'prepend', 'after', 'before', 'remove', 'replaceWith', 'replaceChildren', 'insertAdjacentElement', 'insertAdjacentHTML']]]) for (const name of names) { const orig = proto[name]; if (!orig) continue; proto[name] = function () { note('node'); return orig.apply(this, arguments); }; }
  const ih = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML'); Object.defineProperty(Element.prototype, 'innerHTML', { get: ih.get, set(v) { note('node'); return ih.set.call(this, v); }, configurable: true });
  const tc = Object.getOwnPropertyDescriptor(Node.prototype, 'textContent'); Object.defineProperty(Node.prototype, 'textContent', { get: tc.get, set(v) { note('text'); return tc.set.call(this, v); }, configurable: true });
  const st = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'hidden'); Object.defineProperty(HTMLElement.prototype, 'hidden', { get: st.get, set(v) { note('attr'); return st.set.call(this, v); }, configurable: true });
  document.addEventListener('DOMContentLoaded', () => { w.__dcl = performance.now(); }); })();`;
(async () => { const browser = await chromium.launch(); const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' }); await context.addInitScript(INIT);
  const page = await context.newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  for (const pathname of process.env.PATHS.split(',')) {
    await page.goto(B + '/notifications', { waitUntil: 'load' }); await page.waitForTimeout(500);
    await page.goto(B + pathname, { waitUntil: 'load', timeout: 240000 }); await page.waitForTimeout(3500);
    const r = await page.evaluate(() => { const paints = Object.fromEntries(performance.getEntriesByType('paint').map((e) => [e.name, e.startTime])); return { fp: paints['first-paint'] || 0, dcl: window.__dcl, writes: window.__w }; });
    const phase = (t) => (t <= r.dcl - 0.01 ? '1 before DCL' : t <= r.fp ? '2 DCL→first paint' : '3 after first paint');
    const agg = {}; for (const [t, kind, at] of r.writes) { const k = `${phase(t)} | ${kind.padEnd(5)} | ${at}`; agg[k] = (agg[k] || 0) + 1; }
    const totals = {}; for (const [t, kind] of r.writes) { const k = `${phase(t)} ${kind}`; totals[k] = (totals[k] || 0) + 1; }
    console.log(`${process.env.EMAIL.split('@')[0]} ${pathname}: DCL ${Math.round(r.dcl)} ms, first paint ${Math.round(r.fp)} ms (wrapped); writes by phase: ${JSON.stringify(totals)}`);
    for (const [k, n] of Object.entries(agg).filter(([k]) => k.startsWith(process.env.PHASE || '3')).sort((a, b) => b[1] - a[1]).slice(0, Number(process.env.TOP || 22))) console.log(`   ${String(n).padStart(5)}  ${k}`);
  }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
