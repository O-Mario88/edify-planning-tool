/* Every style recalculation and layout of one page load: how long, how many
 * elements, and which script line forced it. Light tracing only (timeline +
 * stacks), so durations are close to real. Audit tooling. */
const fs = require('node:fs');
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: process.env.MOBILE ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: !!process.env.MOBILE, hasTouch: !!process.env.MOBILE, serviceWorkers: 'block' });
  const page = await context.newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify');
  await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]); await page.waitForLoadState('load');
  await page.goto(B + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(1500); // warm cache
  await page.goto('about:blank');
  await browser.startTracing(page, { categories: ['devtools.timeline', 'disabled-by-default-devtools.timeline', 'disabled-by-default-devtools.timeline.stack'] });
  await page.goto(B + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(3500);
  const trace = JSON.parse((await browser.stopTracing()).toString()); const events = trace.traceEvents || trace;
  const nav = events.filter((e) => e.name === 'navigationStart' || (e.name === 'ResourceSendRequest' && e.args && e.args.data && /\/static\//.test(e.args.data.url || '') === false)).sort((a, b) => a.ts - b.ts);
  const t0 = (events.find((e) => e.name === 'ResourceSendRequest' && e.args && e.args.data && (e.args.data.url || '').endsWith(process.env.PATHNAME)) || nav[0] || events[0]).ts;
  const short = (u) => (u || '').split('/').pop().split('?')[0].replace(/\.[0-9a-f]{12}\./, '.');
  const frameOf = (st) => { if (!st || !st.length) return '(browser: no script on the stack)'; const f = st.find((x) => x.url && /static\/js\/(?!vendor)/.test(x.url)) || st[0]; return `${short(f.url) || '(inline)'}:${f.lineNumber} ${f.functionName || '(anonymous)'}`; };
  const rows = [];
  for (const e of events) {
    if (e.ph !== 'X' || !e.dur) continue;
    if (e.name === 'UpdateLayoutTree' || e.name === 'RecalculateStyles') rows.push({ kind: 'style', ms: e.dur / 1000, t: (e.ts - t0) / 1000, elements: e.args && e.args.elementCount, by: frameOf(e.args && e.args.beginData && e.args.beginData.stackTrace) });
    if (e.name === 'Layout') rows.push({ kind: 'layout', ms: e.dur / 1000, t: (e.ts - t0) / 1000, elements: e.args && e.args.beginData && e.args.beginData.dirtyObjects, by: frameOf(e.args && e.args.beginData && e.args.beginData.stackTrace) });
  }
  const style = rows.filter((r) => r.kind === 'style'); const layout = rows.filter((r) => r.kind === 'layout');
  { const spans = events.filter((e) => e.ph === 'X' && e.dur && (e.name === 'Layout' || e.name === 'UpdateLayoutTree')); const lay = spans.filter((e) => e.name === 'Layout'); const nested = spans.filter((e) => e.name === 'UpdateLayoutTree' && lay.some((l) => l.tid === e.tid && e.ts >= l.ts && e.ts + e.dur <= l.ts + l.dur));
    console.log(`  style recalculation inside layout (container queries): ${nested.length} = ${(nested.reduce((s, e) => s + e.dur, 0) / 1000).toFixed(0)} ms, ${nested.reduce((s, e) => s + ((e.args && e.args.elementCount) || 0), 0)} elements`);
    const byLayout = {}; for (const r of layout) { (byLayout[r.by] = byLayout[r.by] || { n: 0, ms: 0 }); byLayout[r.by].n++; byLayout[r.by].ms += r.ms; }
    console.log('  layout by the script line that forced it:'); for (const [k, v] of Object.entries(byLayout).sort((a, b) => b[1].ms - a[1].ms).slice(0, 8)) console.log(`   ${v.ms.toFixed(0).padStart(6)} ms  ${String(v.n).padStart(4)}x  ${k}`); }
  const sum = (a) => a.reduce((s, r) => s + r.ms, 0);
  console.log(`${process.env.EMAIL.split('@')[0]} ${process.env.PATHNAME}: ${style.length} style recalculations = ${sum(style).toFixed(0)} ms; ${layout.length} layouts = ${sum(layout).toFixed(0)} ms`);
  const by = {}; for (const r of style) { const k = r.by; (by[k] = by[k] || { n: 0, ms: 0, el: 0, max: 0 }); by[k].n++; by[k].ms += r.ms; by[k].el += r.elements || 0; by[k].max = Math.max(by[k].max, r.ms); }
  console.log('  style recalculation by the script line that forced it:');
  for (const [k, v] of Object.entries(by).sort((a, b) => b[1].ms - a[1].ms).slice(0, Number(process.env.TOP || 16))) console.log(`   ${v.ms.toFixed(0).padStart(6)} ms  ${String(v.n).padStart(4)}x  max ${v.max.toFixed(0).padStart(4)} ms  elements ${String(v.el).padStart(6)}  ${k}`);
  console.log('  largest single recalculations:');
  for (const r of [...style].sort((a, b) => b.ms - a.ms).slice(0, 10)) console.log(`   ${r.ms.toFixed(0).padStart(6)} ms at +${r.t.toFixed(0).padStart(5)} ms  elements ${String(r.elements).padStart(5)}  ${r.by}`);
  if (process.env.OUT) fs.writeFileSync(process.env.OUT, JSON.stringify(rows));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
