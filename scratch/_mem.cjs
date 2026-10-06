const { chromium } = require('@playwright/test');
const B = 'http://127.0.0.1:8376';
(async () => { const b = await chromium.launch({ args: ['--js-flags=--expose-gc'] }); const ctx = await b.newContext({viewport:{width:1440,height:900}}); const p = await ctx.newPage();
await p.goto(B + '/login'); await p.fill('input[name=email]','cceo1@edify.org'); await p.fill('input[name=password]','edify'); await Promise.all([p.waitForNavigation(), p.press('input[name=password]','Enter')]);
const cdp = await ctx.newCDPSession(p); await cdp.send('Performance.enable');
const snap = async () => { await cdp.send('HeapProfiler.collectGarbage'); const m = Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(x => [x.name, x.value])); return { heapMB: +(m.JSHeapUsedSize/1048576).toFixed(1), nodes: m.Nodes, listeners: m.JSEventListeners, docs: m.Documents, frames: m.Frames }; };
const route = ['/dashboard','/planning','/my-plan','/schools','/clusters','/calendar','/core-schools','/todos','/partner-oversight/','/projects'];
const series = [];
for (let i = 0; i < 60; i++) { await p.goto(B + route[i % route.length], { waitUntil: 'load', timeout: 120000 }); await p.waitForTimeout(700); if (i % 10 === 9 || i < 10) series.push({ nav: i + 1, page: route[i % route.length], ...(await snap()) }); }
console.log('60 full navigations:'); for (const s of series) console.log(' ', JSON.stringify(s));
// in-page HTMX swaps: the same search fired 60 times on the School Directory
await p.goto(B + '/schools', { waitUntil: 'load' }); await p.waitForTimeout(1500);
const target = await p.evaluate(() => { const i = document.querySelector('input[type=search][hx-get], input[name=q]'); return i ? { name: i.name, hx: i.getAttribute('hx-get'), tgt: i.getAttribute('hx-target') } : null; });
console.log('search input', JSON.stringify(target));
const swaps = [];
swaps.push({ swap: 0, ...(await snap()) });
for (let i = 1; i <= 60; i++) {
  await p.evaluate((i) => new Promise((res) => { const el = document.querySelector('input[type=search][hx-get], input[name=q]'); el.value = i % 2 ? 'pri' : 'hill'; document.body.addEventListener('htmx:afterSettle', () => setTimeout(res, 150), { once: true }); htmx.trigger(el, 'search'); htmx.trigger(el, 'keyup'); htmx.trigger(el, 'input'); setTimeout(res, 6000); }), i);
  if (i % 10 === 0) swaps.push({ swap: i, ...(await snap()) });
}
console.log('60 HTMX search swaps on /schools:'); for (const s of swaps) console.log(' ', JSON.stringify(s));
await b.close(); })().catch(e => { console.error(e); process.exit(1); });
