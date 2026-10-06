/* Which DOM writes invalidate how much style: invalidation tracking for one page load. Audit tooling. */
const fs = require('node:fs'); const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
(async () => { const browser = await chromium.launch(); const context = await browser.newContext({ viewport: { width: 1440, height: 900 } }); const page = await context.newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]); await page.waitForLoadState('load');
  await page.goto(B + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(1500); await page.goto('about:blank');
  await browser.startTracing(page, { categories: ['devtools.timeline', 'disabled-by-default-devtools.timeline', 'disabled-by-default-devtools.timeline.stack', 'disabled-by-default-devtools.timeline.invalidationTracking'] });
  await page.goto(B + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(3500);
  const trace = JSON.parse((await browser.stopTracing()).toString()); const events = trace.traceEvents || trace;
  const short = (u) => (u || '').split('/').pop().split('?')[0].replace(/\.[0-9a-f]{12}\./, '.');
  const frameOf = (st) => { if (!st || !st.length) return '(no script)'; const f = st.find((x) => x.url && /static\/js\/(?!vendor)/.test(x.url)) || st[0]; return `${short(f.url) || '(inline)'}:${f.lineNumber} ${f.functionName || '(anon)'}`; };
  const names = {}; for (const e of events) if (/Invalidation/.test(e.name)) names[e.name] = (names[e.name] || 0) + 1;
  console.log('invalidation events:', JSON.stringify(names));
  const sched = events.filter((e) => e.name === 'ScheduleStyleInvalidationTracking' && e.args && e.args.data);
  const agg = {}; for (const e of sched) { const d = e.args.data; const what = d.changedClass ? 'class ' + d.changedClass : d.changedAttribute ? 'attr ' + d.changedAttribute : d.changedId ? 'id ' + d.changedId : d.changedPseudo ? 'pseudo ' + d.changedPseudo : (d.invalidatedSelectorId || '?'); const k = `${what} | set: ${(d.invalidationSet || '')} | ${frameOf(d.stackTrace)}`; (agg[k] = agg[k] || { n: 0, node: d.nodeName }); agg[k].n++; }
  console.log('scheduled invalidations by changed class/attribute and writer (top 25 of', Object.keys(agg).length, '):');
  for (const [k, v] of Object.entries(agg).sort((a, b) => b[1].n - a[1].n).slice(0, 25)) console.log(`   ${String(v.n).padStart(5)}x  ${k.slice(0, 190)}`);
  const inv = events.filter((e) => e.name === 'StyleInvalidatorInvalidationTracking' && e.args && e.args.data);
  const agg2 = {}; for (const e of inv) { const d = e.args.data; const k = `${d.reason || ''} | ${(d.invalidationList || []).map((x) => (x.classes || []).concat(x.attributes || [], x.tagNames || [], x.ids || []).slice(0, 4).join(',')).slice(0, 2).join(' / ')} | ${d.invalidatedSelectorId || ''} | subtree:${d.subtree || ''}`; (agg2[k] = agg2[k] || { n: 0, nodes: new Set() }); agg2[k].n++; agg2[k].nodes.add(d.nodeName); }
  console.log('style-invalidator results (top 20 of', Object.keys(agg2).length, '):');
  for (const [k, v] of Object.entries(agg2).sort((a, b) => b[1].n - a[1].n).slice(0, 20)) console.log(`   ${String(v.n).padStart(5)}x  ${k.slice(0, 170)}  e.g. ${[...v.nodes].slice(0, 2).join(' ; ').slice(0, 80)}`);
  const rec = events.filter((e) => e.name === 'StyleRecalcInvalidationTracking' && e.args && e.args.data);
  const agg3 = {}; for (const e of rec) { const d = e.args.data; const k = `${d.reason || ''} ${d.extraData || ''} | subtree:${d.subtree} | ${frameOf(d.stackTrace)}`; (agg3[k] = agg3[k] || { n: 0, nodes: [] }); agg3[k].n++; if (agg3[k].nodes.length < 3) agg3[k].nodes.push(d.nodeName); }
  console.log('recalc invalidations by reason and writer (top 30 of', Object.keys(agg3).length, '):');
  for (const [k, v] of Object.entries(agg3).sort((a, b) => b[1].n - a[1].n).slice(0, 30)) console.log(`   ${String(v.n).padStart(5)}x  ${k.slice(0, 150)}  e.g. ${v.nodes.join(' ; ').slice(0, 110)}`);
  if (process.env.OUT) fs.writeFileSync(process.env.OUT, JSON.stringify(events.filter((e) => /Invalidation|UpdateLayoutTree|^Layout$/.test(e.name))));
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
