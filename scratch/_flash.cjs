/* What changes on screen after a page's first paint: class writes, nodes
 * added/removed, layout shift -- for the server's HTML as sent and for
 * variants rewritten on the way in. Audit tooling.
 *   VARIANTS=asis,noexpect,block  CPU=4  EMAIL=.. PATHS=/a,/b */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
const CPU = Number(process.env.CPU || 1); const RUNS = Number(process.env.RUNS || 3);
const VARIANTS = (process.env.VARIANTS || 'asis,block').split(',');
const BLOCK = (process.env.BLOCK || 'alpine-3').split(',');   // which deferred scripts get blocking="render"
const rewrite = { asis: (h) => h, noexpect: (h) => h.replace(/<link rel="expect"[^>]*>/, ''),
  // What the template change will send: every deferred script that sat in the
  // body moved, in order, to the end of the head's deferred list; the last one holds the first frame.
  planned: (h) => { const cut = h.indexOf('<body'); let head = h.slice(0, cut), body = h.slice(cut); const moved = [];
    // Until a pass moves nothing: text either side of a cut can close up into
    // another deferred script, and that one belongs in the head as well.
    let before;
    do { before = body; body = body.replace(/<script\b[^>]*\bdefer\b[^>]*><\/script>\n?/g, (tag) => { if (!/\bsrc=/.test(tag)) return tag; moved.push(tag.trim()); return ''; }); } while (body !== before);
    if (!moved.length) return h; moved[moved.length - 1] = moved[moved.length - 1].replace('<script', '<script blocking="render"');
    const anchor = head.lastIndexOf('<script>', head.indexOf('App-wide ordered palette')); if (anchor < 0) throw new Error('palette script not found');
    return head.slice(0, anchor) + moved.join('\n') + '\n' + head.slice(anchor) + body; },
  nobody: (h) => rewrite.block(h.replace(/<script src="[^"]*analytics-workspace[^"]*"[^>]*><\/script>/, '')),
  movebody: (h) => { const m = h.match(/<script src="[^"]*analytics-workspace[^"]*"[^>]*><\/script>/); if (!m) return rewrite.block(h); return h.replace(m[0], '').replace(/<script\b[^>]*\bdefer\b[^>]*>/g, (tag) => tag).replace('</head>', m[0].replace('<script', '<script blocking="render"') + '</head>'); },
  block: (h) => h.replace(/<script\b[^>]*\bdefer\b[^>]*>/g, (tag) => (BLOCK.some((n) => tag.includes(n)) || BLOCK[0] === 'all' ? tag.replace('<script', '<script blocking="render"') : tag)) };
const INIT = `(() => { const w = window; w.__f = { muts: [], shifts: [], t0: performance.now() };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) w.__f.shifts.push([e.startTime, e.value]); }).observe({ type: 'layout-shift', buffered: true }); } catch (e) {}
  const mo = new MutationObserver((records) => { const t = performance.now(); let cls = 0, added = 0, removed = 0, attrs = 0; for (const r of records) { if (r.type === 'attributes') { if (r.attributeName === 'class') cls++; else attrs++; } else { added += r.addedNodes.length; removed += r.removedNodes.length; } } w.__f.muts.push([t, cls, attrs, added, removed]); });
  mo.observe(document, { subtree: true, childList: true, attributes: true });
  document.addEventListener('DOMContentLoaded', () => { w.__f.dcl = performance.now(); }); })();`;
(async () => { const browser = await chromium.launch();
  for (const variant of VARIANTS) { const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' }); await context.addInitScript(INIT);
    const page = await context.newPage();
    await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    await page.route((u) => u.origin === B && !u.pathname.startsWith('/static/'), async (route) => { if (route.request().resourceType() !== 'document') return route.continue(); const response = await route.fetch(); const body = await response.text(); await route.fulfill({ response, body: rewrite[variant](body) }); });
    const cdp = await context.newCDPSession(page); await cdp.send('Performance.enable'); if (CPU > 1) await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU });
    for (const pathname of process.env.PATHS.split(',')) { const rows = [];
      for (let i = 0; i <= RUNS; i++) { await page.goto(B + '/notifications', { waitUntil: 'load' }); await page.waitForTimeout(600);
        await page.goto(B + pathname, { waitUntil: 'load', timeout: 240000 }); await page.waitForTimeout(3000 * Math.max(1, CPU / 2));
        const r = await page.evaluate(() => { const paints = Object.fromEntries(performance.getEntriesByType('paint').map((e) => [e.name, e.startTime])); const fp = paints['first-paint'] || 0; const f = window.__f;
          const after = f.muts.filter((m) => m[0] > fp); const sum = (k) => after.reduce((s, m) => s + m[k], 0); const last = after.length ? after[after.length - 1][0] : fp;
          const lateShift = f.shifts.filter((s) => s[0] > fp).reduce((s, x) => s + x[1], 0);
          return { fp: Math.round(fp), fcp: Math.round(paints['first-contentful-paint'] || 0), dcl: Math.round(f.dcl || 0), cls: +f.shifts.reduce((s, x) => s + x[1], 0).toFixed(3), lateShift: +lateShift.toFixed(3), classAfter: sum(1), attrAfter: sum(2), addedAfter: sum(3), removedAfter: sum(4), settled: Math.round(last), blocking: document.querySelectorAll('script[blocking]').length, expect: document.querySelectorAll('link[rel=expect]').length }; });
        const m0 = Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((x) => [x.name, x.value]));
        r.task = Math.round(m0.TaskDuration * 1000); r.style = Math.round(m0.RecalcStyleDuration * 1000); r.layout = Math.round(m0.LayoutDuration * 1000); r.recalcs = m0.RecalcStyleCount; r.layouts = m0.LayoutCount;
        if (i) rows.push(r); }
      rows.sort((a, b) => a.fp - b.fp); const m = rows[Math.floor(rows.length / 2)];
      console.log(`${variant.padEnd(9)} cpu×${CPU} ${pathname.padEnd(18)} first paint ${String(m.fp).padStart(5)} ms  DCL ${String(m.dcl).padStart(5)}  after first paint: classes ${String(m.classAfter).padStart(5)} attrs ${String(m.attrAfter).padStart(5)} nodes +${String(m.addedAfter).padStart(4)}/-${String(m.removedAfter).padStart(4)}  shift ${m.lateShift.toFixed(3)} (total ${m.cls.toFixed(3)})  last write ${String(m.settled).padStart(5)} ms | main ${String(m.task).padStart(5)} style ${String(m.style).padStart(5)} layout ${String(m.layout).padStart(4)} recalcs ${String(m.recalcs).padStart(3)} layouts ${String(m.layouts).padStart(3)} [blk ${m.blocking}]`); }
    await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
