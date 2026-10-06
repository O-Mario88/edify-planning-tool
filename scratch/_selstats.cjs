'use strict';
const fs = require('node:fs');
const { chromium } = require('@playwright/test');
const BASE = process.env.BASE || 'http://127.0.0.1:8376';
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto(BASE + '/login');
  await page.fill('input[name=email]', process.env.EMAIL);
  await page.fill('input[name=password]', 'edify');
  await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  await page.waitForLoadState('load');
  await page.goto('about:blank');
  await browser.startTracing(page, { categories: ['blink', 'devtools.timeline', 'disabled-by-default-devtools.timeline', 'disabled-by-default-blink.debug'] });
  await page.goto(BASE + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 });
  await page.waitForTimeout(2500);
  const buf = await browser.stopTracing();
  const dom = await page.evaluate(() => {
    const c = {}; for (const e of document.getElementsByTagName('*')) c[e.tagName] = (c[e.tagName] || 0) + 1;
    const selects = Array.from(document.querySelectorAll('select')).map((s) => [s.name || s.id, s.options.length]).sort((a, b) => b[1] - a[1]).slice(0, 6);
    let maxKids = [0, '']; for (const e of document.getElementsByTagName('*')) if (e.children.length > maxKids[0]) maxKids = [e.children.length, e.tagName + '.' + String(e.className).slice(0, 60)];
    let depth = 0; (function walk(n, d) { if (d > depth) depth = d; for (const k of n.children) walk(k, d + 1); })(document.documentElement, 0);
    return { tags: Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 12), selects, maxKids, depth, templates: document.querySelectorAll('template').length };
  });
  const trace = JSON.parse(buf.toString());
  const events = trace.traceEvents || trace;
  const sel = {}; let recalcs = [];
  for (const e of events) {
    if (e.name === 'SelectorStats' && e.args && e.args.selector_stats) {
      for (const t of e.args.selector_stats.selector_timings) {
        const s = (sel[t.selector] = sel[t.selector] || { us: 0, attempts: 0, matches: 0, fast: 0 });
        s.us += t['elapsed (us)']; s.attempts += t.match_attempts; s.matches += t.match_count; s.fast += t.fast_reject_count;
      }
    }
    if ((e.name === 'UpdateLayoutTree' || e.name === 'RecalculateStyles') && e.ph === 'X') recalcs.push({ ms: Math.round(e.dur / 1000), elements: e.args && e.args.elementCount, t: e.ts });
  }
  recalcs.sort((a, b) => b.ms - a.ms);
  const rows = Object.entries(sel).map(([k, v]) => ({ selector: k, ms: +(v.us / 1000).toFixed(1), attempts: v.attempts, matches: v.matches })).sort((a, b) => b.ms - a.ms);
  const total = rows.reduce((s, r) => s + r.ms, 0);
  fs.writeFileSync(process.env.OUT, JSON.stringify({ dom, recalcs: recalcs.slice(0, 40), totalSelectorMs: total, selectors: rows.slice(0, 400) }, null, 1));
  console.log(JSON.stringify(dom));
  console.log('recalcs', recalcs.length, 'sum ms', recalcs.reduce((s, r) => s + r.ms, 0), 'top', JSON.stringify(recalcs.slice(0, 8)));
  console.log('selector matching total ms', Math.round(total), 'distinct selectors', rows.length);
  for (const r of rows.slice(0, 30)) console.log(String(r.ms).padStart(8), String(r.attempts).padStart(9), String(r.matches).padStart(7), r.selector.slice(0, 200));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
