/* Breadth of one insertion with named groups of :has() rules removed,
 * cumulatively. Counts from the trace. Audit tooling. */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
function trials(groups) {
  const flush = () => { getComputedStyle(document.body).color; void document.body.offsetWidth; };
  const host = Array.from(document.querySelectorAll('main table tbody td')).pop() || document.querySelector('main [class*=card] *') || document.querySelector('main');
  const probe = (label) => { flush(); performance.mark(label + ':start'); const d = document.createElement('span'); d.className = 'audit-probe-node'; host.appendChild(d); flush(); performance.mark(label + ':end'); d.remove(); flush(); };
  const collect = () => { const found = []; const walk = (rules, parent) => { Array.from(rules).forEach((r) => { if (r.selectorText === undefined) { if (r.cssRules) walk(r.cssRules, r); return; } if (/:has\(/.test(r.selectorText)) found.push({ parent, rule: r }); if (r.cssRules && r.cssRules.length) walk(r.cssRules, r); }); };
    for (const sheet of document.styleSheets) { try { walk(sheet.cssRules, sheet); } catch (e) { /* other origin */ } } return found; };
  probe('0 all rules'); const removed = {};
  groups.forEach(([name, pattern], n) => { const re = new RegExp(pattern); let count = 0; for (const f of collect().reverse()) { if (!re.test(f.rule.selectorText)) continue; const i = Array.from(f.parent.cssRules).indexOf(f.rule); if (i >= 0) { f.parent.deleteRule(i); count++; } } removed[name] = count; probe(`${n + 1} -${name}`); });
  return { removed, left: collect().length, total: document.getElementsByTagName('*').length };
}
(async () => { const browser = await chromium.launch(); const MOBILE = !!process.env.MOBILE; const VP = process.env.VIEWPORT ? process.env.VIEWPORT.split('x').map(Number) : null;
  const page = await (await browser.newContext({ viewport: VP ? { width: VP[0], height: VP[1] } : MOBILE ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' })).newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  const groups = JSON.parse(process.env.GROUPS);
  for (const pathname of process.env.PATHS.split(',')) {
    await page.goto(B + pathname, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(5000);
    await browser.startTracing(page, { categories: ['devtools.timeline', 'blink.user_timing'] });
    const ret = await page.evaluate(trials, groups);
    const events = JSON.parse((await browser.stopTracing()).toString()).traceEvents;
    const marks = events.filter((e) => e.cat && e.cat.includes('blink.user_timing') && /:(start|end)$/.test(e.name)).sort((a, b) => a.ts - b.ts);
    const styles = events.filter((e) => e.name === 'UpdateLayoutTree' && e.ph === 'X');
    console.log(`${process.env.EMAIL.split('@')[0]} ${pathname} ${VP ? VP.join('x') : MOBILE ? 'phone' : '1440'}: ${ret.total} elements; :has() rules left at the end ${ret.left}`);
    for (let i = 0; i < marks.length - 1; i++) { const m = marks[i]; if (!m.name.endsWith(':start')) continue; const label = m.name.slice(0, -6); const end = marks.slice(i + 1).find((x) => x.name === label + ':end'); if (!end) continue;
      const n = styles.filter((s) => s.ts >= m.ts && s.ts <= end.ts).reduce((s, e) => s + ((e.args && e.args.elementCount) || 0), 0); const g = label.replace(/^\d+ -/, ''); console.log(`   ${String(n).padStart(6)}  ${label}${ret.removed[g] !== undefined ? ` (${ret.removed[g]} rules)` : ''}`); }
  }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
