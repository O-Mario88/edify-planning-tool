/* Which :has() rules, each on its own, make one insertion restyle the page:
 * every :has() rule is taken out, then put back one at a time. Counts from
 * the trace. Audit tooling. */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
function trials() {
  const flush = () => { getComputedStyle(document.body).color; void document.body.offsetWidth; };
  const host = Array.from(document.querySelectorAll('main table tbody td')).pop() || document.querySelector('main [class*=card] *') || document.querySelector('main');
  const probe = (label) => { flush(); performance.mark(label + ':start'); const d = document.createElement('span'); d.className = 'audit-probe-node'; host.appendChild(d); flush(); performance.mark(label + ':end'); d.remove(); flush(); };
  const found = []; const walk = (rules, parent, sheet) => { Array.from(rules).forEach((r) => { if (r.selectorText === undefined) { if (r.cssRules) walk(r.cssRules, r, sheet); return; } if (/:has\(/.test(r.selectorText)) found.push({ parent, rule: r, sheet }); if (r.cssRules && r.cssRules.length) walk(r.cssRules, r, sheet); }); };
  for (const sheet of document.styleSheets) { try { walk(sheet.cssRules, sheet, (sheet.href || 'inline').split('/static/').pop().split('?')[0].replace(/\.[0-9a-f]{12}\./, '.')); } catch (e) { /* other origin */ } }
  probe('all');
  const items = found.map((f) => ({ parent: f.parent, text: f.rule.cssText, selector: f.rule.selectorText, sheet: f.sheet, rule: f.rule }));
  for (const it of [...items].reverse()) { const list = Array.from(it.parent.cssRules); const i = list.indexOf(it.rule); if (i >= 0) it.parent.deleteRule(i); else it.lost = true; }
  probe('none');
  items.forEach((it, n) => { if (it.lost) return; let i; try { i = it.parent.insertRule(it.text, it.parent.cssRules.length); } catch (e) { it.lost = true; return; } probe('only|' + n); it.parent.deleteRule(i); });
  return { host: host.tagName + '.' + host.className, total: document.getElementsByTagName('*').length, rules: items.map((it) => { let chain = []; for (let q = it.parent; q && q.conditionText !== undefined || (q && q.type === 12); q = q.parentRule) { if (!q) break; chain.push((q.constructor.name.replace('CSS', '').replace('Rule', '')) + ' ' + (q.conditionText || '')); } let matches = -1; try { matches = document.querySelectorAll(it.selector).length; } catch (e) { /* not a selector querySelector takes */ } return { sheet: it.sheet, selector: it.selector.replace(/\s+/g, ' ').slice(0, 300), full: it.text.replace(/\s+/g, ' '), chain: chain.join(' < '), matches, lost: !!it.lost }; }) };
}
(async () => { const browser = await chromium.launch(); const MOBILE = !!process.env.MOBILE;
  const page = await (await browser.newContext({ viewport: process.env.VIEWPORT ? { width: Number(process.env.VIEWPORT.split('x')[0]), height: Number(process.env.VIEWPORT.split('x')[1]) } : MOBILE ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' })).newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  await page.goto(B + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(5000);
  await browser.startTracing(page, { categories: ['devtools.timeline', 'blink.user_timing'] });
  const ret = await page.evaluate(trials);
  const events = JSON.parse((await browser.stopTracing()).toString()).traceEvents;
  const marks = events.filter((e) => e.cat && e.cat.includes('blink.user_timing') && /:(start|end)$/.test(e.name)).sort((a, b) => a.ts - b.ts);
  const styles = events.filter((e) => e.name === 'UpdateLayoutTree' && e.ph === 'X'); const counts = {};
  for (let i = 0; i < marks.length - 1; i++) { const m = marks[i]; if (!m.name.endsWith(':start')) continue; const label = m.name.slice(0, -6); const end = marks.slice(i + 1).find((x) => x.name === label + ':end'); if (!end) continue; counts[label] = styles.filter((s) => s.ts >= m.ts && s.ts <= end.ts).reduce((s, e) => s + ((e.args && e.args.elementCount) || 0), 0); }
  console.log(`${process.env.EMAIL.split('@')[0]} ${process.env.PATHNAME}${MOBILE ? ' (phone)' : ''}: ${ret.total} elements, host ${ret.host.slice(0, 50)}; all :has() rules ${counts.all}, none ${counts.none}; ${ret.rules.length} rules (${ret.rules.filter((r) => r.lost).length} could not be isolated)`);
  const rows = ret.rules.map((r, n) => ({ ...r, n: counts['only|' + n] })).filter((r) => r.n !== undefined).sort((a, b) => b.n - a.n);
  for (const r of rows.filter((r) => r.n > counts.none * 1.08).slice(0, Number(process.env.TOP || 14))) console.log(process.env.FULL ? `   ${String(r.n).padStart(6)}  [${r.sheet.split('/').pop()}] matches ${r.matches}${r.chain ? ' {' + r.chain + '}' : ''}\n           ${r.full.slice(0, Number(process.env.FULL))}` : `   ${String(r.n).padStart(6)}  [${r.sheet.split('/').pop()}] ${r.selector.slice(0, 250)}`);
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
