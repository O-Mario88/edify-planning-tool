"""Full-document style recalc cost, per stylesheet, plus universal-bucket selector counts."""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "out"
role, url = sys.argv[1], sys.argv[2]
keys = json.loads((OUT / "sessions.json").read_text())
PROBE = r"""
(() => {
  const deep = document.querySelector('main td') || document.body;
  let flip = 0;
  const recalc = () => { document.documentElement.style.setProperty('--edify-probe', String(++flip)); const t = performance.now(); getComputedStyle(deep).display; return performance.now() - t; };
  const best = () => { let m = 1e9; for (let i = 0; i < 5; i++) m = Math.min(m, recalc()); return Math.round(m * 10) / 10; };
  const base = best();
  const rows = [];
  const rightmost = (sel) => { const parts = sel.trim().split(/\s*[>+~]\s*|\s+/); return parts[parts.length - 1]; };
  for (const s of Array.from(document.styleSheets)) {
    let rules = []; try { rules = Array.from(s.cssRules) } catch (e) {}
    const walk = (list, acc) => { for (const r of list) { if (r.selectorText) acc.push(r.selectorText); else if (r.cssRules) walk(Array.from(r.cssRules), acc); } return acc; };
    const sels = walk(rules, []);
    let universal = 0, total = 0;
    for (const st of sels) for (const sel of st.split(',')) { total++; const rm = rightmost(sel); if (/^[\[:*]/.test(rm) && !/^::/.test(rm)) universal++; }
    s.disabled = true; best(); const without = best(); s.disabled = false; best();
    rows.push({ sheet: (s.href || 'inline').split('/').slice(-1)[0].split('?')[0], rules: total, universal, saved: Math.round((base - without) * 10) / 10 });
  }
  rows.sort((a, b) => b.saved - a.saved);
  return { base, rows: rows.slice(0, 16), elements: document.querySelectorAll('*').length };
})()
"""
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies(
        [{"name": "sessionid", "value": keys[role], "domain": "localhost", "path": "/"}]
    )
    page = ctx.new_page()
    page.goto("http://localhost:8000" + url, wait_until="load")
    page.wait_for_timeout(2500)
    r = page.evaluate(PROBE)
    b.close()
print(f"full-document recalc: {r['base']}ms over {r['elements']} elements")
print("  saved(ms) selectors universal-rightmost sheet")
for row in r["rows"]:
    print(
        f"  {row['saved']:7.1f} {row['rules']:6d} {row['universal']:6d}   {row['sheet']}"
    )
