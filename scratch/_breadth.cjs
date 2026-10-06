/* How many elements one DOM insertion restyles, and which CSS rules widen it.
 * Counts come from the trace's UpdateLayoutTree.elementCount, so they are exact
 * and repeatable (no timing noise). Audit tooling only. */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';

async function traced(browser, page, fn, arg) {
  await browser.startTracing(page, { categories: ['devtools.timeline', 'blink.user_timing'] });
  const ret = await page.evaluate(fn, arg);
  const events = JSON.parse((await browser.stopTracing()).toString()).traceEvents;
  const marks = events.filter((e) => e.cat && e.cat.includes('blink.user_timing') && /:(start|end)$/.test(e.name)).sort((a, b) => a.ts - b.ts);
  const styles = events.filter((e) => e.name === 'UpdateLayoutTree' && e.ph === 'X');
  const out = {};
  for (let i = 0; i < marks.length - 1; i++) { const m = marks[i]; if (!m.name.endsWith(':start')) continue; const label = m.name.slice(0, -6); const end = marks.slice(i + 1).find((x) => x.name === label + ':end'); if (!end) continue;
    const inside = styles.filter((s) => s.ts >= m.ts && s.ts <= end.ts); out[label] = { elements: inside.reduce((s, e) => s + ((e.args && e.args.elementCount) || 0), 0), ms: +(inside.reduce((s, e) => s + e.dur, 0) / 1000).toFixed(1) }; }
  return { counts: out, ret };
}

function pageTrials(spec) {
  const flush = () => { getComputedStyle(document.body).color; void document.body.offsetWidth; };
  if (spec.fix4 && !window.__fixed4) { window.__fixed4 = true; const X = ':is(input[type="checkbox"], input[type="radio"], .edify-table-choice)'; const E = ':first-child:not(input, button, .edify-table-choice)';
    const visit = (rules, parent) => { for (let i = rules.length - 1; i >= 0; i--) { const r = rules[i]; if (r.selectorText === undefined) { if (r.cssRules) visit(r.cssRules, r); continue; }
      if (!/:first-child:has\(>/.test(r.selectorText) || !/\) > :first-child:not\(/.test(r.selectorText)) continue; const sel = r.selectorText; const prefix = sel.slice(0, sel.indexOf(':is(:first-child:not(:has(')); const body = r.cssText.slice(r.cssText.indexOf('{'));
      parent.deleteRule(i); parent.insertRule(`${prefix}:first-child > ${E}:not(:has(~ ${X})), ${prefix}:first-child:has(> ${X}) + * > ${E} ${body}`, i); window.__fixed4 = 'applied'; } };
    for (const sheet of document.styleSheets) { try { visit(sheet.cssRules, sheet); } catch (e) { /* other origin */ } } flush(); }
  const host = (() => { if (spec.host === 'cell') return Array.from(document.querySelectorAll('main table tbody td')).pop(); if (spec.host === 'wrapper') return Array.from(document.querySelectorAll('main table')).pop().parentElement; return document.querySelector(spec.host); })();
  const probe = (label) => { flush(); performance.mark(label + ':start'); const d = document.createElement('span'); d.className = 'audit-probe-node'; host.appendChild(d); flush(); performance.mark(label + ':end'); d.remove(); flush(); };
  const sheets = Array.from(document.querySelectorAll('link[rel=stylesheet]')).map((l) => ({ l, name: l.href.split('/static/')[1].split('?')[0].replace(/\.[0-9a-f]{12}\./, '.') }));
  const walk = (rules, pathPrefix, out) => { Array.from(rules).forEach((r, i) => { const path = pathPrefix.concat(i); if (r.cssRules && r.cssRules.length && !(r.selectorText) && typeof r.insertRule === 'function') walk(r.cssRules, path, out); else out.push({ path, text: r.cssText }); }); return out; };
  const getRule = (sheet, path) => { let parent = sheet; for (let k = 0; k < path.length - 1; k++) parent = parent.cssRules[path[k]]; return { parent, index: path[path.length - 1] }; };
  const labels = [];
  if (spec.mode === 'baseline') { probe('baseline'); labels.push('baseline'); for (const s of sheets) { s.l.disabled = true; probe('sheet|' + s.name); s.l.disabled = false; flush(); labels.push('sheet|' + s.name); } }
  if (spec.mode === 'chunks') { // remove [from,to) of the flattened leaf rules of one sheet
    const s = sheets.find((x) => x.name.includes(spec.sheet)); const leaves = walk(s.l.sheet.cssRules, [], []);
    for (const [from, to] of spec.ranges) { const removed = []; for (let k = Math.min(to, leaves.length) - 1; k >= from; k--) { const { parent, index } = getRule(s.l.sheet, leaves[k].path); removed.push({ parent, index, text: leaves[k].text }); parent.deleteRule(index); }
      probe(`chunk|${from}|${to}`); for (const r of removed.reverse()) r.parent.insertRule(r.text, r.index); flush(); }
    return { leaves: leaves.length, texts: spec.wantText ? spec.ranges.map(([from]) => leaves[from] && leaves[from].text.slice(0, 420)) : undefined }; }
  return { sheets: sheets.map((s) => s.name) };
}

(async () => { const browser = await chromium.launch(); const MOBILE = !!process.env.MOBILE; const page = await (await browser.newContext({ viewport: MOBILE ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' })).newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  await page.goto(B + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(5000);
  const host = process.env.HOST || 'cell';
  const total = await page.evaluate(() => document.getElementsByTagName('*').length);
  const base = await traced(browser, page, pageTrials, { mode: 'baseline', host, fix4: !!process.env.FIX4 });
  console.log(`${process.env.EMAIL.split('@')[0]} ${process.env.PATHNAME}: ${total} elements. One <span> appended to a ${host}: ${base.counts.baseline.elements} elements restyled (${base.counts.baseline.ms} ms traced)`);
  const bySheet = Object.entries(base.counts).filter(([k]) => k.startsWith('sheet|')).map(([k, v]) => [k.slice(6), v.elements]).sort((a, b) => a[1] - b[1]);
  console.log('  elements restyled with one stylesheet disabled:'); for (const [s, n] of bySheet.slice(0, 7)) console.log(`     ${String(n).padStart(6)}  without ${s}`);
  const baseline = base.counts.baseline.elements; const culprits = [];
  for (const [sheet, n] of bySheet.filter(([, n]) => n < baseline * 0.9).slice(0, 4)) {
    // bisect this sheet by leaf rule
    const size = (await traced(browser, page, pageTrials, { mode: 'chunks', host, sheet, ranges: [], fix4: !!process.env.FIX4 })).ret.leaves; let ranges = []; const CH = Math.ceil(size / 24); for (let i = 0; i < size; i += CH) ranges.push([i, Math.min(size, i + CH)]);
    let found = [];
    for (let depth = 0; depth < 6 && ranges.length; depth++) { const r = await traced(browser, page, pageTrials, { mode: 'chunks', host, sheet, ranges, fix4: !!process.env.FIX4 }); const good = ranges.map((rg) => ({ rg, n: (r.counts[`chunk|${rg[0]}|${rg[1]}`] || {}).elements })).filter((x) => x.n !== undefined && x.n < baseline * 0.97);
      const singles = good.filter((x) => x.rg[1] - x.rg[0] === 1); found = found.concat(singles); const wide = good.filter((x) => x.rg[1] - x.rg[0] > 1).sort((a, b) => a.n - b.n).slice(0, 6);
      ranges = []; for (const w of wide) { const [a, z] = w.rg; const step = Math.max(1, Math.ceil((z - a) / 8)); for (let i = a; i < z; i += step) ranges.push([i, Math.min(z, i + step)]); } }
    if (found.length) { const texts = (await traced(browser, page, pageTrials, { mode: 'chunks', host, sheet, ranges: found.map((f) => f.rg), wantText: true, fix4: !!process.env.FIX4 })).ret.texts; found.forEach((f, i) => culprits.push({ sheet, leaf: f.rg[0], restyledWithout: f.n, text: texts[i] })); }
  }
  console.log('  single rules whose removal narrows the restyle:');
  for (const c of culprits.sort((a, b) => a.restyledWithout - b.restyledWithout).slice(0, 16)) console.log(`     ${String(c.restyledWithout).padStart(6)} restyled without [${c.sheet.split('/').pop()} leaf ${c.leaf}] ${String(c.text).replace(/\s+/g, ' ').slice(0, 300)}`);
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
