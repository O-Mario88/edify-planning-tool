/* Breadth of one insertion with the four first-cell rules rewritten in place
 * (candidates), counted from the trace. Audit tooling. */
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
  const hosts = { cell: () => Array.from(document.querySelectorAll('main table tbody td')).pop(), firstcell: () => document.querySelector('main table tbody td'), incell: () => document.querySelector('main table tbody td > *') || document.querySelector('main table tbody td'), card: () => { const t = document.querySelector('main table'); return t && t.closest('section, article, .edify-card, [class*=card]'); }, main: () => document.querySelector('main') };
  const probe = (label, host) => { flush(); performance.mark(label + ':start'); const d = document.createElement('span'); d.className = 'audit-probe-node'; host.appendChild(d); flush(); performance.mark(label + ':end'); d.remove(); flush(); };
  const X = ':is(input[type="checkbox"], input[type="radio"], .edify-table-choice)';
  const find = () => { const out = []; const walk = (rules, parent) => { Array.from(rules).forEach((r, index) => { if (r.selectorText === undefined) { if (r.cssRules) walk(r.cssRules, r); } else if (/:first-child:has\(>/.test(r.selectorText)) out.push({ parent, rule: r }); }); };
    for (const sheet of document.styleSheets) { try { walk(sheet.cssRules, sheet); } catch (e) { /* other origin */ } } return out; };
  const originals = find().map((f) => ({ parent: f.parent, index: Array.from(f.parent.cssRules).indexOf(f.rule), text: f.rule.cssText, selector: f.rule.selectorText, body: f.rule.cssText.slice(f.rule.cssText.indexOf('{')) }));
  const apply = (rewrite) => { const state = [];
    // work from the last rule back so indexes stay valid
    for (const o of [...originals].sort((a, b) => b.index - a.index)) { o.parent.deleteRule(o.index); const sel = rewrite(o.selector); if (sel) { o.parent.insertRule(sel + ' ' + o.body, o.index); state.push({ o, kept: true }); } else state.push({ o, kept: false }); }
    return () => { for (const s of [...state].reverse()) { if (s.kept) s.o.parent.deleteRule(s.o.index); s.o.parent.insertRule(s.o.text, s.o.index); } flush(); }; };
  const isFourth = (sel) => /\) > :first-child:not\(/.test(sel);
  const candidates = {
    original: (s) => s,
    removed: () => null,
    'no-rule-4': (s) => (isFourth(s) ? null : s),
    'only-rule-4': (s) => (isFourth(s) ? s : null),
    'plus-td-th': (s) => s.replace(`:first-child:has(> ${X}) + *`, `:first-child:has(> ${X}) + :is(td, th)`),
    'alt1-only': (s) => s.replace(`, :first-child:has(> ${X}) + *`, ''),
    'alt2-only': (s) => s.replace(`:first-child:not(:has(> ${X})), `, ''),
    'rule4-subject-has': (s) => { if (!isFourth(s)) return s; const prefix = s.slice(0, s.indexOf(':is(:first-child:not(:has(')); const E = ':first-child:not(input, button, .edify-table-choice)';
      return `${prefix}:first-child > ${E}:not(:has(~ ${X})), ${prefix}:first-child:has(> ${X}) + * > ${E}`; },
    'alt2-only-td-th': (s) => s.replace(`:first-child:not(:has(> ${X})), `, '').replace(`:first-child:has(> ${X}) + *`, `:first-child:has(> ${X}) + :is(td, th)`),
  };
  const out = { selectors: originals.map((o) => o.selector), applied: {} };
  for (const [name, rewrite] of Object.entries(candidates)) { let restore; try { restore = apply(rewrite); } catch (e) { out.applied[name] = String(e).slice(0, 200); continue; }
    out.applied[name] = originals.map((o) => rewrite(o.selector)).filter(Boolean).length;
    for (const h of spec.hosts) { const host = hosts[h](); if (host) probe(`${name}|${h}`, host); }
    restore(); }
  return out;
}
(async () => { const browser = await chromium.launch(); const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  for (const pathname of process.env.PATHS.split(',')) {
    await page.goto(B + pathname, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(5000);
    const hosts = ['cell', 'firstcell', 'incell', 'card', 'main'];
    const r = await traced(browser, page, trials, { hosts });
    if (process.env.SHOW) console.log(r.ret.selectors.join('\n'));
    console.log(`${process.env.EMAIL.split('@')[0]} ${pathname}`);
    console.log('  ' + 'candidate'.padEnd(22) + hosts.map((h) => ('span→' + h).padStart(15)).join(''));
    for (const name of Object.keys(r.ret.applied)) console.log('  ' + `${name} (${r.ret.applied[name]})`.padEnd(22) + hosts.map((h) => String(r.counts[`${name}|${h}`] ?? '-').padStart(15)).join(''));
  }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
