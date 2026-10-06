/* What one small DOM insertion deep in the page costs in style recalculation, and which
 * stylesheet / :has() rule makes it expensive. Audit tooling. */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
(async () => { const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await p.goto(B + '/login'); await p.fill('input[name=email]', process.env.EMAIL); await p.fill('input[name=password]', 'edify'); await Promise.all([p.waitForNavigation(), p.press('input[name=password]', 'Enter')]);
  await p.goto(B + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 }); await p.waitForTimeout(5000);
  const out = await p.evaluate(async () => {
    const flush = () => { getComputedStyle(document.body).color; void document.body.offsetWidth; };
    const targets = { 'cell in the last table': () => { const t = Array.from(document.querySelectorAll('main table tbody td')).pop(); return t; }, 'table wrapper': () => { const t = Array.from(document.querySelectorAll('main table')).pop(); return t && t.parentElement; }, 'first child of main': () => document.querySelector('main').firstElementChild };
    const cost = (host, kind) => { const a = []; for (let i = 0; i < 5; i++) { flush(); let undo; const t = performance.now();
        if (kind === 'insert') { const d = document.createElement('span'); d.className = 'audit-probe-node'; host.appendChild(d); flush(); const ms = performance.now() - t; d.remove(); a.push(ms); }
        else if (kind === 'class') { host.classList.add('edify-cell'); flush(); const ms = performance.now() - t; host.classList.remove('edify-cell'); a.push(ms); }
        else { host.setAttribute('data-audit-x', '1'); flush(); const ms = performance.now() - t; host.removeAttribute('data-audit-x'); a.push(ms); } }
      a.sort((x, y) => x - y); return +a[2].toFixed(1); };
    const res = { elements: document.getElementsByTagName('*').length, base: {}, sheets: [], hasRules: [] };
    for (const [name, get] of Object.entries(targets)) { const h = get(); if (!h) continue; res.base[name] = { insert: cost(h, 'insert'), classAdd: cost(h, 'class') }; }
    const host = targets['cell in the last table'](); const baseInsert = res.base['cell in the last table'].insert;
    const links = Array.from(document.querySelectorAll('link[rel=stylesheet]'));
    for (const l of links) { l.disabled = true; await new Promise((r) => setTimeout(r, 30)); const v = cost(host, 'insert'); l.disabled = false; await new Promise((r) => setTimeout(r, 30)); flush(); res.sheets.push([l.href.split('/static/')[1].split('?')[0].replace(/\.[0-9a-f]{12}\./, '.'), v]); }
    // rule-level: remove each top-level rule containing :has( in every sheet, one at a time
    for (const l of links) { let sheet; try { sheet = l.sheet; void sheet.cssRules; } catch (e) { continue; }
      const idx = []; Array.from(sheet.cssRules).forEach((r, i) => { if (r.cssText.includes(':has(')) idx.push(i); });
      for (const i of idx) { const text = sheet.cssRules[i].cssText; sheet.deleteRule(i); const v = cost(host, 'insert'); sheet.insertRule(text, i); if (baseInsert - v > Math.max(1.5, baseInsert * 0.04)) res.hasRules.push({ sheet: l.href.split('/').pop().split('?')[0].replace(/\.[0-9a-f]{12}\./, '.'), i, saved: +(baseInsert - v).toFixed(1), text: text.slice(0, 330) }); } }
    res.hasRules.sort((x, y) => y.saved - x.saved);
    return res; });
  console.log(`${process.env.EMAIL.split('@')[0]} ${process.env.PATHNAME}: ${out.elements} elements`);
  for (const [k, v] of Object.entries(out.base)) console.log(`  one <span> appended to ${k}: ${v.insert} ms of style+layout; one class added there: ${v.classAdd} ms`);
  console.log('  cost of the insertion with one stylesheet disabled:'); for (const [s, v] of out.sheets.sort((a, c) => a[1] - c[1]).slice(0, 8)) console.log(`     ${String(v).padStart(7)} ms  without ${s}`);
  console.log('  single :has() rules whose removal makes the insertion cheaper:'); for (const r of out.hasRules.slice(0, 14)) console.log(`     saves ${String(r.saved).padStart(6)} ms  [${r.sheet} #${r.i}] ${r.text.replace(/\s+/g, ' ').slice(0, 250)}`);
  await b.close(); })().catch((e) => { console.error(e); process.exit(1); });
