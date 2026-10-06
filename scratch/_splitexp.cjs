/* Experiment: does splitting a rule's big :is() list into one complex selector
 * per alternative make style recalculation cheaper, and by how much?
 * Audit tooling only — nothing here ships. */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';

function pageFn(args) {
  const { indexes, sheetNeedle, minAlts } = args;
  // ── a small selector reader: enough for top-level splitting ──────────────
  const splitTop = (s, sepTest) => { const parts = []; let depth = 0, cur = ''; for (let i = 0; i < s.length; i++) { const ch = s[i]; if (ch === '\\') { cur += ch + (s[i + 1] || ''); i++; continue; } if (ch === '(' || ch === '[') depth++; if (ch === ')' || ch === ']') depth--; if (depth === 0 && sepTest(ch)) { parts.push(cur); cur = ''; } else cur += ch; } parts.push(cur); return parts; };
  const commaSplit = (s) => splitTop(s, (c) => c === ',').map((x) => x.trim()).filter(Boolean);
  // find top-level ":is(" occurrences in a complex selector; return [{start, end, inner}]
  const findIs = (s) => { const out = []; let depth = 0; for (let i = 0; i < s.length; i++) { const ch = s[i]; if (ch === '\\') { i++; continue; } if (depth === 0 && s.startsWith(':is(', i)) { let d = 0, j = i + 3; for (; j < s.length; j++) { if (s[j] === '\\') { j++; continue; } if (s[j] === '(' || s[j] === '[') d++; if (s[j] === ')' || s[j] === ']') { d--; if (d === 0) break; } } out.push({ start: i, end: j + 1, inner: s.slice(i + 4, j) }); i = j; continue; } if (ch === '(' || ch === '[') depth++; if (ch === ')' || ch === ']') depth--; } return out; };
  const flatten = (inner) => commaSplit(inner).flatMap((a) => { const m = a.match(/^:is\((.*)\)$/s); if (m && findIs(a).length === 1 && findIs(a)[0].start === 0 && findIs(a)[0].end === a.length) return flatten(m[1]); return [a]; });
  const spec = (sel) => { // rough specificity of one alternative: [ids, classes, tags]
    let s = sel.replace(/\\./g, 'x'); let a = 0, b = 0, c = 0;
    s = s.replace(/:(is|not|has)\(([^()]*(\([^()]*\)[^()]*)*)\)/g, (m, k, inner) => { const best = commaSplit(inner).map(spec).sort((x, y) => (y[0] - x[0]) || (y[1] - x[1]) || (y[2] - x[2]))[0] || [0, 0, 0]; a += best[0]; b += best[1]; c += best[2]; return ' '; });
    s = s.replace(/:where\([^)]*\)/g, ' ');
    a += (s.match(/#[\w-]+/g) || []).length; b += (s.match(/\.[\w-]+/g) || []).length + (s.match(/\[[^\]]*\]/g) || []).length + (s.match(/:(?!:)[\w-]+/g) || []).length;
    c += (s.replace(/[#.][\w-]+|\[[^\]]*\]|:{1,2}[\w-]+/g, ' ').match(/(^|[\s>+~])[a-zA-Z][\w-]*/g) || []).length; return [a, b, c]; };
  const cmp = (x, y) => (x[0] - y[0]) || (x[1] - y[1]) || (x[2] - y[2]);
  const pad = (from, to) => { let p = ''; for (let i = from[0]; i < to[0]; i++) p += ':not(#\\_e)'; for (let i = from[1]; i < to[1]; i++) p += ':not(.\\_e)'; for (let i = from[2]; i < to[2]; i++) p += ':not(edify-e)'; return p; };
  const splitComplex = (complex) => { const lists = findIs(complex).map((x) => ({ ...x, alts: flatten(x.inner) })).filter((x) => x.alts.length >= minAlts); if (!lists.length) return [complex];
    const big = lists.sort((x, y) => y.alts.length - x.alts.length)[0]; const max = big.alts.map(spec).sort((x, y) => -cmp(x, y))[0];
    return big.alts.map((alt) => { const s = spec(alt); const simple = /^[.\w\\:-]+$/.test(alt) || /^\[[^\]]*\]$/.test(alt); const piece = (cmp(s, max) === 0 && simple) ? alt : `:where(${alt})${pad([0, 0, 0], max)}`; return complex.slice(0, big.start) + piece + complex.slice(big.end); }); };
  const splitRule = (selectorText) => commaSplit(selectorText).flatMap(splitComplex).join(', ');

  const probe = document.createElement('style'); document.head.appendChild(probe);
  const full = (n) => { const a = []; for (let i = 0; i < (n || 5); i++) { probe.textContent = '*{--audit-probe:' + Math.random() + '}'; const t = performance.now(); getComputedStyle(document.body).color; void document.body.offsetWidth; a.push(performance.now() - t); } a.sort((x, y) => x - y); return a[Math.floor(a.length / 2)]; };
  const snapshot = () => { const out = []; const props = ['font-weight', 'font-size', 'line-height', 'font-family', 'color', 'background-color', 'background-image', 'border-top-color', 'border-radius', 'box-shadow', 'padding-top', 'padding-left', 'padding-right', 'padding-bottom', 'backdrop-filter', 'fill', 'white-space', 'text-wrap', 'overflow-wrap', 'word-break']; for (const e of document.querySelectorAll('*')) { const cs = getComputedStyle(e); out.push(props.map((p) => cs.getPropertyValue(p)).join('|')); } return out; };
  const link = Array.from(document.querySelectorAll('link[rel=stylesheet]')).find((l) => l.href.includes(sheetNeedle)); const sheet = link.sheet;
  const res = { elements: document.getElementsByTagName('*').length, base: +full(7).toFixed(1), rules: [] };
  const before = snapshot();
  let allSplitSaved = 0; const replaced = [];
  const todo = indexes === 'all' ? Array.from(sheet.cssRules).map((r, i) => (r.selectorText && commaSplit(r.selectorText).some((c) => findIs(c).some((x) => flatten(x.inner).length >= minAlts))) ? i : -1).filter((i) => i >= 0) : indexes;
  res.candidates = todo.length; res.totalRules = sheet.cssRules.length; let growth = 0;
  for (const i of todo) { const rule = sheet.cssRules[i]; const original = rule.cssText; const body = original.slice(original.indexOf('{'));
    const newSel = splitRule(rule.selectorText); const info = { i, selectorChars: rule.selectorText.length, splitChars: newSel.length, complexBefore: commaSplit(rule.selectorText).length, complexAfter: commaSplit(newSel).length };
    sheet.deleteRule(i); info.withoutRule = indexes === 'all' ? 0 : +full(5).toFixed(1);
    let ok = true; try { sheet.insertRule(newSel + ' ' + body, i); } catch (e) { ok = false; info.error = String(e).slice(0, 160); sheet.insertRule(original, i); }
    info.withSplit = indexes === 'all' ? 0 : +full(5).toFixed(1); growth += newSel.length - info.selectorChars; info.accepted = ok && sheet.cssRules[i].selectorText.length > 0; replaced.push(i); res.rules.push(info); }
  res.afterAllSplits = +full(7).toFixed(1); res.growthKB = Math.round(growth / 1024);
  const after = snapshot(); let diff = 0; const samples = []; for (let k = 0; k < before.length; k++) if (before[k] !== after[k]) { diff++; if (samples.length < 4) { const e = document.querySelectorAll('*')[k]; const b = before[k].split('|'), a = after[k].split('|'); samples.push(e.tagName + '.' + String(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className).slice(0, 60) + ' :: ' + b.map((v, n) => v !== a[n] ? `${n}: ${v} → ${a[n]}` : '').filter(Boolean).join('; ').slice(0, 200)); } }
  res.computedStyleDifferences = diff; res.samples = samples; probe.remove();
  return res;
}

(async () => { const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await p.goto(B + '/login'); await p.fill('input[name=email]', process.env.EMAIL || 'cceo1@edify.org'); await p.fill('input[name=password]', 'edify'); await Promise.all([p.waitForNavigation(), p.press('input[name=password]', 'Enter')]);
  await p.goto(B + (process.env.PATHNAME || '/dashboard'), { waitUntil: 'load', timeout: 180000 }); await p.waitForTimeout(3500);
  const out = await p.evaluate(pageFn, { indexes: process.env.IDX === 'all' ? 'all' : JSON.parse(process.env.IDX || '[243]'), sheetNeedle: process.env.SHEET || 'consistency', minAlts: Number(process.env.MIN || '6') });
  console.log(`elements ${out.elements}; full recalc before ${out.base} ms → after all splits ${out.afterAllSplits} ms; computed-style differences on ${out.computedStyleDifferences} elements`);
  console.log(`  candidates ${out.candidates} of ${out.totalRules} top-level rules; selector text growth ${out.growthKB} KB; rules that failed to insert: ${out.rules.filter((r) => r.error).length}`);
  for (const r of (process.env.IDX === 'all' ? out.rules.filter((r) => r.error).slice(0, 5) : out.rules)) console.log(`  rule #${r.i}: selectors ${r.complexBefore} → ${r.complexAfter}, chars ${r.selectorChars} → ${r.splitChars}; recalc without rule ${r.withoutRule} ms, with split form ${r.withSplit} ms${r.error ? '  ERROR ' + r.error : ''}`);
  for (const s of out.samples) console.log('   diff: ' + s);
  await b.close(); })().catch((e) => { console.error(e); process.exit(1); });
