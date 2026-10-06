/* Write a copy of one built stylesheet with every long :is() list split into one selector
 * per alternative (rough, in-page splitter). For an end-to-end estimate only — not shipped. */
const fs = require('node:fs'); const { chromium } = require('@playwright/test');
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


  const link = Array.from(document.querySelectorAll('link[rel=stylesheet]')).find((l) => l.href.includes(sheetNeedle));
  const rewrite = (rules) => Array.from(rules).map((r) => { if (r.selectorText && !(r.cssRules && r.cssRules.length)) { const body = r.cssText.slice(r.cssText.indexOf('{')); let sel = r.selectorText; try { sel = splitRule(r.selectorText); } catch (e) {} return sel + ' ' + body; } return r.cssText; }).join('\n');
  return { text: rewrite(link.sheet.cssRules), original: Array.from(link.sheet.cssRules).map((r) => r.cssText).join('\n') };
}
(async () => { const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await p.goto(B + '/login'); await p.fill('input[name=email]', 'cceo1@edify.org'); await p.fill('input[name=password]', 'edify'); await Promise.all([p.waitForNavigation(), p.press('input[name=password]', 'Enter')]);
  await p.goto(B + '/dashboard', { waitUntil: 'load', timeout: 180000 });
  const out = await p.evaluate(pageFn, { indexes: [], sheetNeedle: process.env.SHEET || 'consistency', minAlts: Number(process.env.MIN || '6') });
  fs.writeFileSync(process.env.OUT, out.text); fs.writeFileSync(process.env.OUT.replace('.css', '.orig.css'), out.original);
  const zlib = require('node:zlib'); console.log('original', out.original.length, 'gz', zlib.gzipSync(out.original).length, 'br', zlib.brotliCompressSync(out.original).length, '| split', out.text.length, 'gz', zlib.gzipSync(out.text).length, 'br', zlib.brotliCompressSync(out.text).length);
  await b.close(); })().catch((e) => { console.error(e); process.exit(1); });
