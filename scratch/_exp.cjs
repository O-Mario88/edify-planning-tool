/* A/B a page's main-thread cost with static files overridden from disk
 * (OVERRIDES='{"date-picker":"/abs/path.js"}', value "" = serve empty file). */
const fs = require('node:fs');
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
const OV = JSON.parse(process.env.OVERRIDES || '{}');
const RUNS = Number(process.env.RUNS || '3');
(async () => { const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript("window.__a={long:[]};try{new PerformanceObserver(l=>{for(const e of l.getEntries())window.__a.long.push(Math.round(e.duration))}).observe({type:'longtask',buffered:true})}catch(e){}");
  for (const [needle, file] of Object.entries(OV)) await ctx.route((u) => u.pathname.includes('/static/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: needle.endsWith('.css') || file.endsWith('.css') ? 'text/css' : 'application/javascript', body: file ? fs.readFileSync(file) : '' }));
  const p = await ctx.newPage();
  await p.goto(B + '/login'); await p.fill('input[name=email]', process.env.EMAIL); await p.fill('input[name=password]', 'edify'); await Promise.all([p.waitForNavigation(), p.press('input[name=password]', 'Enter')]);
  const cdp = await ctx.newCDPSession(p); await cdp.send('Performance.enable');
  for (const path of process.env.PATHS.split(',')) { const rows = [];
    for (let i = 0; i <= RUNS; i++) { await p.goto('about:blank'); await p.goto(B + path, { waitUntil: 'load', timeout: 240000 }); await p.waitForTimeout(2500);
      const m = Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((x) => [x.name, x.value]));
      const long = await p.evaluate(() => ({ ms: window.__a.long.reduce((s, v) => s + v, 0), max: Math.max(0, ...window.__a.long) }));
      if (i) rows.push({ task: Math.round(m.TaskDuration * 1000), style: Math.round(m.RecalcStyleDuration * 1000), layout: Math.round(m.LayoutDuration * 1000), script: Math.round(m.ScriptDuration * 1000), recalcs: m.RecalcStyleCount, layouts: m.LayoutCount, longMs: long.ms, maxLong: long.max }); }
    rows.sort((x, y) => x.task - y.task); const r = rows[Math.floor(rows.length / 2)];
    console.log(`${(process.env.LABEL || 'run').padEnd(14)} ${path.padEnd(28)} main ${String(r.task).padStart(6)}  style ${String(r.style).padStart(6)}  layout ${String(r.layout).padStart(5)}  script ${String(r.script).padStart(5)}  recalcs ${String(r.recalcs).padStart(5)}  layouts ${String(r.layouts).padStart(5)}  long ${String(r.longMs).padStart(6)} (max ${r.maxLong})`); }
  await b.close(); })().catch((e) => { console.error(e); process.exit(1); });
