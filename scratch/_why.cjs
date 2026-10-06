/* Why one inserted element restyles what it does: invalidation tracking
 * between two marks, grouped by reason. Audit tooling. FIX4=1 applies the
 * rewritten pinned-name rule in the page first. */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
function prepare(fix4) {
  const flush = () => { getComputedStyle(document.body).color; void document.body.offsetWidth; };
  if (fix4) { const X = ':is(input[type="checkbox"], input[type="radio"], .edify-table-choice)'; const E = ':first-child:not(input, button, .edify-table-choice)';
    const visit = (rules, parent) => { for (let i = rules.length - 1; i >= 0; i--) { const r = rules[i]; if (r.selectorText === undefined) { if (r.cssRules) visit(r.cssRules, r); continue; }
      if (!/:first-child:has\(>/.test(r.selectorText) || !/\) > :first-child:not\(/.test(r.selectorText)) continue; const sel = r.selectorText; const prefix = sel.slice(0, sel.indexOf(':is(:first-child:not(:has(')); const body = r.cssText.slice(r.cssText.indexOf('{'));
      parent.deleteRule(i); parent.insertRule(`${prefix}:first-child > ${E}:not(:has(~ ${X})), ${prefix}:first-child:has(> ${X}) + * > ${E} ${body}`, i); } };
    for (const sheet of document.styleSheets) { try { visit(sheet.cssRules, sheet); } catch (e) { /* other origin */ } } }
  flush();
}
function probe(hostName) {
  const flush = () => { getComputedStyle(document.body).color; void document.body.offsetWidth; };
  const host = hostName === 'main' ? document.querySelector('main') : Array.from(document.querySelectorAll('main table tbody td')).pop();
  flush(); performance.mark('probe:start'); const d = document.createElement('span'); d.className = 'audit-probe-node'; host.appendChild(d); flush(); performance.mark('probe:end'); d.remove(); flush();
  const chain = []; for (let el = host; el && el !== document.documentElement; el = el.parentElement) chain.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.classList.length ? '.' + Array.from(el.classList).slice(0, 3).join('.') : ''));
  return chain;
}
(async () => { const browser = await chromium.launch(); const MOBILE = process.env.MOBILE === '1'; const VPT = process.env.VIEWPORT ? process.env.VIEWPORT.split('x').map(Number) : MOBILE ? [390, 844] : [1440, 900]; const page = await (await browser.newContext({ viewport: { width: VPT[0], height: VPT[1] }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' })).newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  await page.goto(B + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(5000);
  await page.evaluate(prepare, !!process.env.FIX4);
  await browser.startTracing(page, { categories: ['devtools.timeline', 'blink.user_timing', 'disabled-by-default-devtools.timeline.invalidationTracking'] });
  const chain = await page.evaluate(probe, process.env.HOST || 'cell');
  const events = JSON.parse((await browser.stopTracing()).toString()).traceEvents;
  const marks = events.filter((e) => e.cat && e.cat.includes('blink.user_timing') && /^probe:/.test(e.name)).sort((a, b) => a.ts - b.ts);
  const [t0, t1] = [marks[0].ts, marks[marks.length - 1].ts]; const within = events.filter((e) => e.ts >= t0 && e.ts <= t1);
  const styles = within.filter((e) => e.name === 'UpdateLayoutTree' && e.ph === 'X');
  console.log(`${process.env.EMAIL.split('@')[0]} ${process.env.PATHNAME} host ${process.env.HOST || 'cell'}${process.env.FIX4 ? ' (rule 4 rewritten)' : ''}: ${styles.reduce((s, e) => s + (e.args.elementCount || 0), 0)} elements in ${styles.length} recalculations [${styles.map((e) => e.args.elementCount).join(', ')}]`);
  console.log('  inserted under: ' + chain.slice(0, 9).join(' < '));
  const names = {}; for (const e of within) if (/Invalidat/.test(e.name)) names[e.name] = (names[e.name] || 0) + 1; console.log('  events: ' + JSON.stringify(names));
  const group = (name, key) => { const agg = {}; for (const e of within) { if (e.name !== name || !e.args || !e.args.data) continue; const k = key(e.args.data); agg[k] = (agg[k] || 0) + 1; } return Object.entries(agg).sort((a, b) => b[1] - a[1]); };
  console.log('  recalc reasons (StyleRecalcInvalidationTracking):'); for (const [k, n] of group('StyleRecalcInvalidationTracking', (d) => `${d.reason}${d.extraData ? ' / ' + d.extraData : ''} on <${(d.nodeName || '').split(' ')[0]}>${d.subtree ? ' +subtree' : ''}`).slice(0, 14)) console.log(`     ${String(n).padStart(5)}  ${k.slice(0, 170)}`);
  console.log('  invalidator (StyleInvalidatorInvalidationTracking):'); for (const [k, n] of group('StyleInvalidatorInvalidationTracking', (d) => `${d.reason} on <${(d.nodeName || '').split(' ')[0]}> ${JSON.stringify(d.invalidationList || d.selectorPart || '').slice(0, 110)}`).slice(0, 14)) console.log(`     ${String(n).padStart(5)}  ${k.slice(0, 220)}`);
  console.log('  scheduled (ScheduleStyleInvalidationTracking):'); for (const [k, n] of group('ScheduleStyleInvalidationTracking', (d) => `${d.invalidatedSelectorId || ''} ${d.changedClass ? 'class ' + d.changedClass : ''}${d.changedPseudo ? 'pseudo ' + d.changedPseudo : ''}${d.changedAttribute ? 'attr ' + d.changedAttribute : ''} on <${(d.nodeName || '').split(' ')[0]}> set ${JSON.stringify(d.invalidationSet || '').slice(0, 80)}`).slice(0, 14)) console.log(`     ${String(n).padStart(5)}  ${k.slice(0, 220)}`);
  if (process.env.SETS) { const sets = {}; for (const e of within) { if (e.name !== 'StyleInvalidatorInvalidationTracking' || !e.args || !e.args.data) continue; for (const st of e.args.data.invalidationList || []) sets[st.id] = st; }
    for (const st of Object.values(sets)) console.log('  SET ' + JSON.stringify(st)); }
  if (process.env.DUMP) { const sample = within.filter((e) => /Invalidat/.test(e.name)).slice(0, Number(process.env.DUMP)); for (const e of sample) console.log(JSON.stringify({ n: e.name, d: e.args.data }).slice(0, 600)); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
