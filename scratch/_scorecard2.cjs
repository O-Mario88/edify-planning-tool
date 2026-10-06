/* Before / after for one page load, same session, same server: the page as
 * served ("after") against the same page with the changes taken back out on
 * the way in ("before": no rel=expect, no blocking script, the pre-change
 * stylesheets and date-picker), plus "noblock" (everything new except the
 * first-frame hold). Audit tooling.
 *   EMAIL=.. PATHS=/a,/b CPU=4 VARIANTS=before,noblock,after CSS_BEFORE=dir JS_BEFORE='{"date-picker":"/abs/file.js"}'
 *   EXTRA_BEFORE='{"css/components/mobile-shell":"/abs/orig.css"}' swaps any other static file for the "before" variant. */
const fs = require('node:fs'); const path = require('node:path');
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
const CPU = Number(process.env.CPU || 1); const RUNS = Number(process.env.RUNS || 5);
const VARIANTS = (process.env.VARIANTS || 'before,after').split(',');
const CSS_BEFORE = process.env.CSS_BEFORE; const JS_BEFORE = JSON.parse(process.env.JS_BEFORE || '{}');
const MOBILE = process.env.MOBILE === '1';
const strip = (h, expect) => { let out = h.replace(/(<script\b[^>]*?) blocking="render"/g, '$1'); if (expect) out = out.replace(/<link rel="expect"[^>]*>/, ''); return out; };
const VARIANT = { after: { html: (h) => h }, noblock: { html: (h) => strip(h, false) }, before: { html: (h) => strip(h, true), css: CSS_BEFORE, js: JS_BEFORE, extra: JSON.parse(process.env.EXTRA_BEFORE || '{}') }, alt: { html: (h) => h, css: process.env.CSS_ALT } };
const VP = process.env.VIEWPORT ? process.env.VIEWPORT.split('x').map(Number) : null;
const INIT = `(() => { const w = window; w.__f = { muts: [], shifts: [], long: [] };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) w.__f.shifts.push([e.startTime, e.value]); }).observe({ type: 'layout-shift', buffered: true });
        new PerformanceObserver((l) => { for (const e of l.getEntries()) w.__f.long.push([e.startTime, e.duration]); }).observe({ type: 'longtask', buffered: true });
        new PerformanceObserver((l) => { for (const e of l.getEntries()) w.__f.lcp = e.startTime; }).observe({ type: 'largest-contentful-paint', buffered: true }); } catch (e) {}
  new MutationObserver((records) => { const t = performance.now(); let cls = 0, nodes = 0; for (const r of records) { if (r.type === 'attributes') { if (r.attributeName === 'class') cls++; } else nodes += r.addedNodes.length + r.removedNodes.length; } w.__f.muts.push([t, cls, nodes]); }).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] });
  document.addEventListener('DOMContentLoaded', () => { w.__f.dcl = performance.now(); }); })();`;
(async () => { const browser = await chromium.launch(); const out = [];
  for (const variant of VARIANTS) { const v = VARIANT[variant];
    const context = await browser.newContext({ viewport: VP ? { width: VP[0], height: VP[1] } : MOBILE ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' }); await context.addInitScript(INIT);
    if (v.css) await context.route((u) => /\/static\/build\/css\/.+\.css$/.test(u.pathname), (route) => { const p = new URL(route.request().url()).pathname; const m = p.match(/\/static\/build\/css\/(.+?)\.[0-9a-f]{12}\.css$/) || p.match(/\/static\/build\/css\/(.+?)\.css$/); route.fulfill({ status: 200, contentType: 'text/css', body: fs.readFileSync(path.join(v.css, m[1] + '.css')) }); });
    for (const [needle, file] of Object.entries(v.js || {})) await context.route((u) => u.pathname.includes('/static/js/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: fs.readFileSync(file) }));
    for (const [needle, file] of Object.entries(v.extra || {})) await context.route((u) => u.pathname.includes('/static/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: file.endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(file) }));
    const page = await context.newPage();
    await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    await page.route((u) => u.origin === B && !u.pathname.startsWith('/static/'), async (route) => { if (route.request().resourceType() !== 'document') return route.continue(); const response = await route.fetch(); await route.fulfill({ response, body: v.html(await response.text()) }); });
    const cdp = await context.newCDPSession(page); await cdp.send('Performance.enable'); if (CPU > 1) await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU });
    for (const pathname of process.env.PATHS.split(',')) { const rows = [];
      for (let i = 0; i <= RUNS; i++) { await page.goto('about:blank'); await page.goto(B + pathname, { waitUntil: 'load', timeout: 240000 }); await page.waitForTimeout(Number(process.env.WAIT || 2500 * Math.max(1, CPU / 2)));
        const r = await page.evaluate(() => { const paints = Object.fromEntries(performance.getEntriesByType('paint').map((e) => [e.name, e.startTime])); const fp = paints['first-paint'] || 0; const f = window.__f; const nav = performance.getEntriesByType('navigation')[0];
          const after = f.muts.filter((m) => m[0] > fp); const lastWrite = f.muts.length ? f.muts[f.muts.length - 1][0] : fp; const lastLong = f.long.length ? Math.max(...f.long.map((l) => l[0] + l[1])) : 0;
          return { ttfb: Math.round(nav.responseStart), fp: Math.round(fp), fcp: Math.round(paints['first-contentful-paint'] || 0), lcp: Math.round(f.lcp || 0), dcl: Math.round(f.dcl || 0), load: Math.round(nav.loadEventEnd), classAfter: after.reduce((s, m) => s + m[1], 0), nodesAfter: after.reduce((s, m) => s + m[2], 0), cls: +f.shifts.reduce((s, x) => s + x[1], 0).toFixed(3), shiftAfter: +f.shifts.filter((s) => s[0] > fp).reduce((s, x) => s + x[1], 0).toFixed(3), settled: Math.round(Math.max(lastWrite, lastLong)), longMs: Math.round(f.long.reduce((s, l) => s + l[1], 0)), longMax: Math.round(Math.max(0, ...f.long.map((l) => l[1]))), blocking: document.querySelectorAll('script[blocking]').length, expect: document.querySelectorAll('link[rel=expect]').length, elements: document.getElementsByTagName('*').length }; });
        const m0 = Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((x) => [x.name, x.value]));
        Object.assign(r, { task: Math.round(m0.TaskDuration * 1000), style: Math.round(m0.RecalcStyleDuration * 1000), layout: Math.round(m0.LayoutDuration * 1000), script: Math.round(m0.ScriptDuration * 1000), recalcs: m0.RecalcStyleCount, layouts: m0.LayoutCount, heapMB: +(m0.JSHeapUsedSize / 1048576).toFixed(1) });
        if (i) rows.push(r); }
      const med = (k) => { const a = rows.map((r) => r[k]).sort((x, y) => x - y); return a[Math.floor(a.length / 2)]; };
      const m = Object.fromEntries(Object.keys(rows[0]).map((k) => [k, med(k)]));
      out.push({ variant, cpu: CPU, mobile: MOBILE, viewport: process.env.VIEWPORT || (MOBILE ? '390x844' : '1440x900'), account: process.env.EMAIL, path: pathname, ...m });
      console.log(`${variant.padEnd(8)} ×${CPU}${MOBILE ? ' phone' : ''}${VP ? ' ' + VP.join('x') : ''} ${pathname.padEnd(26)} ttfb ${String(m.ttfb).padStart(5)} fp ${String(m.fp).padStart(5)} lcp ${String(m.lcp).padStart(5)} dcl ${String(m.dcl).padStart(5)} settled ${String(m.settled).padStart(5)} | main ${String(m.task).padStart(5)} style ${String(m.style).padStart(5)} layout ${String(m.layout).padStart(4)} script ${String(m.script).padStart(4)} recalcs ${String(m.recalcs).padStart(3)} | long ${String(m.longMs).padStart(5)} (max ${String(m.longMax).padStart(4)}) | after 1st frame: classes ${String(m.classAfter).padStart(5)} shift ${m.shiftAfter.toFixed(3)} cls ${m.cls.toFixed(3)} [blk ${m.blocking} exp ${m.expect}]`); }
    await context.close(); }
  if (process.env.OUT) { const prev = fs.existsSync(process.env.OUT) ? JSON.parse(fs.readFileSync(process.env.OUT, 'utf8')) : []; fs.writeFileSync(process.env.OUT, JSON.stringify(prev.concat(out), null, 1)); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
