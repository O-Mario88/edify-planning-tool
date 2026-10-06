/* Full script stacks of the large forced style/layout passes in one load. Audit tooling. */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
(async () => { const browser = await chromium.launch(); const MOBILE = !!process.env.MOBILE; const VP = process.env.VIEWPORT ? process.env.VIEWPORT.split('x').map(Number) : null;
  const context = await browser.newContext({ viewport: VP ? { width: VP[0], height: VP[1] } : MOBILE ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' });
  await context.addInitScript(`window.__ev = []; window.addEventListener('resize', () => window.__ev.push(['resize', Math.round(performance.now()), innerWidth + 'x' + innerHeight])); document.addEventListener('DOMContentLoaded', () => { window.__ev.push(['dcl', Math.round(performance.now())]); if (document.fonts) { window.__ev.push(['fonts.status at dcl', document.fonts.status]); document.fonts.ready.then(() => window.__ev.push(['fonts.ready', Math.round(performance.now())])); document.fonts.addEventListener('loadingdone', (e) => window.__ev.push(['loadingdone', Math.round(performance.now()), e.fontfaces.length])); } });`);
  for (const [needle, file] of Object.entries(JSON.parse(process.env.OVERRIDES || '{}'))) await context.route((u) => u.pathname.includes('/static/js/') && u.pathname.includes(needle), (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: require('node:fs').readFileSync(file) }));
  const page = await context.newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]); await page.waitForLoadState('load');
  await page.goto(B + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(1500); await page.goto('about:blank');
  await browser.startTracing(page, { categories: ['devtools.timeline', 'disabled-by-default-devtools.timeline', 'disabled-by-default-devtools.timeline.stack'] });
  await page.goto(B + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(3500);
  const ev = await page.evaluate(() => ({ ev: window.__ev, fp: Math.round((performance.getEntriesByType('paint')[0] || {}).startTime || 0) }));
  const events = JSON.parse((await browser.stopTracing()).toString()).traceEvents;
  const t0 = (events.find((e) => e.name === 'ResourceSendRequest' && e.args && e.args.data && (e.args.data.url || '').endsWith(process.env.PATHNAME)) || events[0]).ts;
  const short = (u) => (u || '').split('/').pop().split('?')[0].replace(/\.[0-9a-f]{12}\./, '.');
  console.log('page events: first paint ' + ev.fp + ' ms; ' + JSON.stringify(ev.ev));
  const big = events.filter((e) => e.ph === 'X' && e.dur >= Number(process.env.MIN || 40) * 1000 && (e.name === 'UpdateLayoutTree' || e.name === 'Layout')).sort((a, b) => a.ts - b.ts);
  for (const e of big) { const st = (e.args && e.args.beginData && e.args.beginData.stackTrace) || []; console.log(`+${((e.ts - t0) / 1000).toFixed(0).padStart(5)} ms ${e.name === 'Layout' ? 'layout' : 'style '} ${(e.dur / 1000).toFixed(0).padStart(4)} ms  ` + st.filter((f) => f.url).map((f) => `${f.functionName || '(anon)'}@${short(f.url)}:${f.lineNumber}`).slice(0, 9).join(' < ')); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
