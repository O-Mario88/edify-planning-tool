#!/usr/bin/env node
/* Main-thread attribution per page: where the client time goes after the HTML
 * arrives (script by file, style recalculation, layout), plus CSS/JS coverage.
 * Audit tooling only. */
'use strict';
const fs = require('node:fs');
const { chromium } = require('@playwright/test');

const BASE = process.env.BASE || 'http://127.0.0.1:8376';
const OUT = process.env.OUT;
const CPU = Number(process.env.CPU || '4');
const PAGES = JSON.parse(process.env.PAGES);
const MOBILE = process.env.MOBILE === '1';

async function login(context, email) {
  const page = await context.newPage();
  await page.goto(BASE + '/login');
  await page.fill('input[name=email]', email);
  await page.fill('input[name=password]', 'edify');
  await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  await page.waitForLoadState('load');
  return page;
}

(async () => {
  const browser = await chromium.launch();
  const results = [];
  const byEmail = {};
  for (const p of PAGES) (byEmail[p.email] = byEmail[p.email] || []).push(p.path);
  for (const email of Object.keys(byEmail)) {
    const context = await browser.newContext({ viewport: MOBILE ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: MOBILE, hasTouch: MOBILE });
    await context.addInitScript("window.__a={long:[],shifts:[]};try{new PerformanceObserver(l=>{for(const e of l.getEntries())window.__a.long.push({d:Math.round(e.duration)})}).observe({type:'longtask',buffered:true});new PerformanceObserver(l=>{for(const e of l.getEntries())if(!e.hadRecentInput)window.__a.shifts.push({v:e.value})}).observe({type:'layout-shift',buffered:true})}catch(e){}");
    const page = await login(context, email);
    const cdp = await context.newCDPSession(page);
    await cdp.send('Performance.enable');
    await cdp.send('Profiler.enable');
    await cdp.send('DOM.enable');
    await cdp.send('CSS.enable');
    for (const path of byEmail[email]) {
      // warm the HTTP cache for this page's assets, then measure a warm visit
      await page.goto(BASE + path, { waitUntil: 'load', timeout: 180000 });
      await page.waitForTimeout(800);
      await page.goto('about:blank');
      if (CPU > 1) await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU });
      const PROFILE = process.env.PROFILE === '1';
      if (PROFILE) { await cdp.send('Profiler.setSamplingInterval', { interval: 1000 }); await cdp.send('Profiler.start'); }
      const t0 = Date.now();
      await page.goto(BASE + path, { waitUntil: 'load', timeout: 180000 });
      await page.waitForTimeout(3000);
      const { profile } = PROFILE ? await cdp.send('Profiler.stop') : { profile: { timeDeltas: [], samples: [], nodes: [] } };
      const usage = { ruleUsage: [] };
      const long = await page.evaluate(() => (window.__a ? { n: window.__a.long.length, ms: window.__a.long.reduce((s, e) => s + e.d, 0), max: Math.max(0, ...window.__a.long.map((e) => e.d)), cls: +window.__a.shifts.reduce((s, e) => s + e.v, 0).toFixed(3) } : {}));
      const metrics = Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((m) => [m.name, m.value]));
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });

      // self time by script file and by function
      const dt = profile.timeDeltas; const ids = profile.samples; const self = {};
      for (let i = 0; i < ids.length; i++) self[ids[i]] = (self[ids[i]] || 0) + dt[i];
      const byFile = {}; const byFn = {};
      for (const node of profile.nodes) {
        const us = self[node.id] || 0; if (!us) continue;
        const cf = node.callFrame; let file = cf.url ? cf.url.split('/').pop().split('?')[0].replace(/\.[0-9a-f]{12}\./, '.') : `(${cf.functionName || 'native'})`;
        if (cf.url && cf.url.indexOf('/static/') === -1 && cf.url.indexOf('http') === 0) file = '(inline script in page)';
        byFile[file] = (byFile[file] || 0) + us;
        const fn = `${file}:${cf.functionName || '(anon)'}`;
        byFn[fn] = (byFn[fn] || 0) + us;
      }
      const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n).map(([k, v]) => [k, Math.round(v / 1000)]);

      // css coverage
      const sheets = {};
      for (const r of usage.ruleUsage) { const s = (sheets[r.styleSheetId] = sheets[r.styleSheetId] || { used: 0 }); if (r.used) s.used += r.endOffset - r.startOffset; }
      let cssTotal = 0; let cssUsed = 0;
      for (const id of Object.keys(sheets)) {
        try { const { text } = await cdp.send('CSS.getStyleSheetText', { styleSheetId: id }); cssTotal += text.length; cssUsed += sheets[id].used; } catch (e) {}
      }
      const page_ = await page.evaluate(() => {
        const n = performance.getEntriesByType('navigation')[0];
        return { ttfb: Math.round(n.responseStart), dcl: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd),
          fcp: Math.round((performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0),
          nodes: document.getElementsByTagName('*').length, tables: document.querySelectorAll('table').length, rows: document.querySelectorAll('tr').length,
          xhr: performance.getEntriesByType('resource').filter((r) => r.initiatorType === 'xmlhttprequest' || r.initiatorType === 'fetch').map((r) => new URL(r.name).pathname + ' ' + Math.round(r.duration) + 'ms') };
      });
      const row = { email, path, cpu: CPU, ...page_, long, taskMs: Math.round(metrics.TaskDuration * 1000), scriptMs: Math.round(metrics.ScriptDuration * 1000), styleMs: Math.round(metrics.RecalcStyleDuration * 1000), layoutMs: Math.round(metrics.LayoutDuration * 1000),
        heapMB: +(metrics.JSHeapUsedSize / 1048576).toFixed(1), listeners: metrics.JSEventListeners, layoutCount: metrics.LayoutCount, styleCount: metrics.RecalcStyleCount,
        cssTotalKB: Math.round(cssTotal / 1024), cssUsedKB: Math.round(cssUsed / 1024), byFile: top(byFile, 10), byFn: top(byFn, 14) };
      results.push(row);
      console.log(JSON.stringify({ path, long, recalcs: row.styleCount, email: email.split('@')[0], ttfb: row.ttfb, fcp: row.fcp, load: row.load, task: row.taskMs, script: row.scriptMs, style: row.styleMs, layout: row.layoutMs, nodes: row.nodes, cssUsed: `${row.cssUsedKB}/${row.cssTotalKB}KB`, xhr: row.xhr.length, top: row.byFile.slice(0, 5) }));
    }
    await context.close();
  }
  fs.writeFileSync(OUT, JSON.stringify(results, null, 1));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
