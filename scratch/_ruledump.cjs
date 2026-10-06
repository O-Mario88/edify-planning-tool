const fs = require('node:fs'); const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
(async () => { const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await p.goto(B + '/login'); await p.fill('input[name=email]', 'cceo1@edify.org'); await p.fill('input[name=password]', 'edify'); await Promise.all([p.waitForNavigation(), p.press('input[name=password]', 'Enter')]);
  await p.goto(B + '/dashboard', { waitUntil: 'load', timeout: 180000 });
  const out = await p.evaluate((idx) => { const link = Array.from(document.querySelectorAll('link[rel=stylesheet]')).find((l) => l.href.includes('consistency')); const rules = link.sheet.cssRules;
    const split = (s) => { const parts = []; let depth = 0, cur = ''; for (const ch of s) { if (ch === '(' || ch === '[') depth++; if (ch === ')' || ch === ']') depth--; if (ch === ',' && depth === 0) { parts.push(cur.trim()); cur = ''; } else cur += ch; } if (cur.trim()) parts.push(cur.trim()); return parts; };
    return idx.map((i) => { const r = rules[i]; const sel = r.selectorText || ''; const tops = split(sel); return { i, type: r.constructor.name, selLen: sel.length, topLevel: tops.length, tops: tops.map((t) => t.length > 300 ? t.slice(0, 150) + ' …[' + t.length + ' chars]… ' + t.slice(-110) : t).slice(0, 6), style: r.style ? r.style.cssText.slice(0, 300) : '' }; }); }, JSON.parse(process.env.IDX));
  for (const r of out) { console.log(`#${r.i} ${r.type} selector ${r.selLen} chars, ${r.topLevel} top-level selector(s)`); for (const t of r.tops) console.log('    ' + t); console.log('    { ' + r.style + ' }'); }
  await b.close(); })().catch((e) => { console.error(e); process.exit(1); });
