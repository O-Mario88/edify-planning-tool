/* How many elements one DOM insertion restyles with named groups of rules
 * removed, alone and together. Exact counts from the trace. Audit tooling. */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
async function traced(browser, page, fn, arg) {
  await browser.startTracing(page, { categories: ['devtools.timeline', 'blink.user_timing'] });
  const ret = await page.evaluate(fn, arg);
  const events = JSON.parse((await browser.stopTracing()).toString()).traceEvents;
  const marks = events.filter((e) => e.cat && e.cat.includes('blink.user_timing') && /:(start|end)$/.test(e.name)).sort((a, b) => a.ts - b.ts);
  const styles = events.filter((e) => e.name === 'UpdateLayoutTree' && e.ph === 'X'); const out = {};
  for (let i = 0; i < marks.length - 1; i++) { const m = marks[i]; if (!m.name.endsWith(':start')) continue; const label = m.name.slice(0, -6); const end = marks.slice(i + 1).find((x) => x.name === label + ':end'); if (!end) continue;
    const inside = styles.filter((s) => s.ts >= m.ts && s.ts <= end.ts); out[label] = inside.reduce((s, e) => s + ((e.args && e.args.elementCount) || 0), 0); }
  return { counts: out, ret };
}
function trials(spec) {
  const flush = () => { getComputedStyle(document.body).color; void document.body.offsetWidth; };
  const hosts = { cell: () => Array.from(document.querySelectorAll('main table tbody td')).pop(), firstcell: () => document.querySelector('main table tbody td'), main: () => document.querySelector('main'), body: () => document.body, kpi: () => document.querySelector('main [class*=kpi]') || document.querySelector('main') };
  const probe = (label, host) => { flush(); performance.mark(label + ':start'); const d = document.createElement('span'); d.className = 'audit-probe-node'; host.appendChild(d); flush(); performance.mark(label + ':end'); d.remove(); flush(); };
  const classProbe = (label, host) => { flush(); performance.mark(label + ':start'); host.classList.add('edify-numeric-cell'); flush(); performance.mark(label + ':end'); host.classList.remove('edify-numeric-cell'); flush(); };
  const groups = { selection: (r) => /^::selection$|^\*::selection$/.test(r.selectorText || ''), pin: (r) => /table:(not\(:)?has\(/.test(r.selectorText || ''), firsthas: (r) => /:first-child:(not\(:)?has\(/.test(r.selectorText || ''), tabhas: (r) => /:has\(> :is\(\[role="?tablist/.test(r.selectorText || ''), anyhas: (r) => /:has\(/.test(r.selectorText || '') };
  const collect = () => { const leaves = []; const walk = (rules, parent) => { Array.from(rules).forEach((r) => { if (r.cssRules && r.cssRules.length && r.selectorText === undefined) walk(r.cssRules, r); else if (r.selectorText !== undefined) { leaves.push({ parent, rule: r }); if (r.cssRules && r.cssRules.length) walk(r.cssRules, r); } }); };
    for (const sheet of document.styleSheets) { try { walk(sheet.cssRules, sheet); } catch (e) { /* other origin */ } } return leaves; };
  const counts = {}; { const leaves = collect(); for (const g of Object.keys(groups)) counts[g] = leaves.filter((l) => groups[g](l.rule)).length; }
  const without = (names, label) => { const removed = []; const leaves = collect();
    for (const l of leaves) { if (!names.some((n) => groups[n](l.rule))) continue; const list = Array.from(l.parent.cssRules); const index = list.indexOf(l.rule); if (index < 0) continue; removed.push({ parent: l.parent, index, text: l.rule.cssText }); }
    // delete from the end of each parent so earlier indexes stay valid
    removed.sort((a, b) => (a.parent === b.parent ? b.index - a.index : 0)); for (const r of removed) r.parent.deleteRule(r.index);
    for (const h of spec.hosts) { const host = hosts[h](); if (host) { probe(`${label}|span|${h}`, host); if (h !== 'body' && h !== 'main') classProbe(`${label}|class|${h}`, host); } }
    for (const r of removed.reverse()) { try { r.parent.insertRule(r.text, r.index); } catch (e) { /* nested */ } } flush(); return removed.length; };
  const done = {}; for (const [label, names] of spec.sets) done[label] = without(names, label);
  return { counts, done, total: document.getElementsByTagName('*').length };
}
(async () => { const browser = await chromium.launch(); const MOBILE = !!process.env.MOBILE; const page = await (await browser.newContext({ viewport: MOBILE ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' })).newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  for (const pathname of process.env.PATHS.split(',')) {
    await page.goto(B + pathname, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(5000);
    const hosts = ['cell', 'firstcell', 'main', 'body'];
    const sets = [['baseline', []], ['-selection', ['selection']], ['-pin', ['pin']], ['-firsthas', ['firsthas']], ['-tabhas', ['tabhas']], ['-pin-firsthas', ['pin', 'firsthas']], ['-firsthas-selection', ['firsthas', 'selection']], ['-pin-firsthas-selection', ['pin', 'firsthas', 'selection']], ['-anyhas', ['anyhas']], ['-anyhas-selection', ['anyhas', 'selection']]];
    const r = await traced(browser, page, trials, { hosts, sets });
    console.log(`${process.env.EMAIL.split('@')[0]} ${pathname}${MOBILE ? ' (phone)' : ''}: ${r.ret.total} elements; rules: ${JSON.stringify(r.ret.counts)}`);
    console.log('  ' + JSON.stringify(await page.evaluate(() => { const all = Array.from(document.querySelectorAll('*')); const containers = all.filter((e) => getComputedStyle(e).containerType !== 'normal'); const byTag = {}; for (const c of containers) { const k = c.tagName.toLowerCase() + (c.classList.length ? '.' + c.classList[0] : ''); byTag[k] = (byTag[k] || 0) + 1; }
      let containerRules = 0; const walk = (rules) => { for (const r of rules) { if (r.constructor.name === 'CSSContainerRule') containerRules++; if (r.cssRules) walk(r.cssRules); } }; for (const sh of document.styleSheets) { try { walk(sh.cssRules); } catch (e) {} }
      const inside = all.filter((e) => { for (let p = e.parentElement; p; p = p.parentElement) if (getComputedStyle(p).containerType !== 'normal') return true; return false; }).length;
      return { containers: containers.length, elementsInsideAContainer: inside, containerRules, top: Object.entries(byTag).sort((a, b) => b[1] - a[1]).slice(0, 8) }; })));
    console.log('  ' + 'removed'.padEnd(26) + hosts.map((h) => ('span→' + h).padStart(15)).join('') + ['cell', 'firstcell'].map((h) => ('class→' + h).padStart(17)).join(''));
    for (const [label] of sets) console.log('  ' + `${label} (${r.ret.done[label]})`.padEnd(26) + hosts.map((h) => String(r.counts[`${label}|span|${h}`] ?? '-').padStart(15)).join('') + ['cell', 'firstcell'].map((h) => String(r.counts[`${label}|class|${h}`] ?? '-').padStart(17)).join(''));
  }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
