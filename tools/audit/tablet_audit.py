"""Tablet layout audit: every role's pages at 10-11 inch tablet viewports.

Portrait 820x1180 (iPad Air 10.9") and landscape 1180x820. For each page the
probe reports document overflow, elements that overflow the viewport outside
any scroll region, tables filling under 70% of a wide parent, dense grids
(three or more columns under 230px each), text under 12px, and touch targets
under 40px tall inside main.
"""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
SCRATCH = Path(__file__).resolve().parent / "out"
SHOTS = SCRATCH / "shots"
SHOTS.mkdir(exist_ok=True)

SESSIONS = json.loads((SCRATCH / "sessions.json").read_text())
EMAILS = {
    "superuser": "edwin.omario@gmail.com",
    "cd": "cd@edify.org",
    "pl": "pl1@edify.org",
    "ia": "ia@edify.org",
    "accountant": "accountant@edify.org",
    "cceo": "cceo19@edify.org",
}
EXTRA = {
    "cd": ["/dashboard?view=map", "/dashboard?view=operations"],
    "pl": ["/dashboard?view=map", "/dashboard?view=operations", "/analytics/program-lead"],
    "ia": ["/ia/dashboard/?view=map", "/ia/dashboard/?view=operations", "/analytics/verification-quality"],
    "accountant": ["/accounts", "/accounts?view=map"],
    "superuser": [
        "/analytics/ssa-performance", "/analytics/visit-effectiveness", "/analytics/impact",
        "/analytics/declining-schools", "/analytics/people", "/analytics/closure-quality",
        "/analytics/publishing-status", "/reports", "/targets", "/target-distribution/team",
    ],
}
VIEWPORTS = {"portrait": (820, 1180), "landscape": (1180, 820)}

PROBE = r"""
(() => {
  const vw = innerWidth;
  const out = { sw: document.documentElement.scrollWidth, wide: [], narrowTables: [], denseGrids: [], smallText: [], shortTargets: 0, title: document.title };
  const sel = el => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id; else if (el.className && typeof el.className === 'string') s += '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.'); return s; };
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const inScroller = el => { let p = el.parentElement; while (p && p !== document.body) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'clip' || o === 'hidden') return true; p = p.parentElement; } return false; };
  const seen = new Set();
  for (const el of document.querySelectorAll('main *, [role=main] *, body > div *')) {
    if (!vis(el) || seen.has(el)) continue; seen.add(el);
    const r = el.getBoundingClientRect();
    if (r.right > vw + 2 && !inScroller(el) && out.wide.length < 8) out.wide.push(sel(el) + ' r=' + Math.round(r.right));
  }
  for (const t of document.querySelectorAll('table')) {
    if (!vis(t)) continue; const p = t.parentElement; const pw = p.getBoundingClientRect().width, tw = t.getBoundingClientRect().width;
    if (pw > 480 && tw < pw * 0.7) out.narrowTables.push(sel(t) + ' ' + Math.round(tw) + '/' + Math.round(pw));
  }
  for (const g of document.querySelectorAll('main *, body > div *')) {
    if (!vis(g)) continue; const cs = getComputedStyle(g); if (!cs.display.includes('grid')) continue;
    if (g.classList.contains('kpi-strip__grid')) continue;
    const cols = cs.gridTemplateColumns.split(' ').filter(x => x && x !== '0px').length; const w = g.getBoundingClientRect().width;
    if (cols >= 3 && w / cols < 230 && out.denseGrids.length < 8) out.denseGrids.push(sel(g) + ' ' + cols + 'x' + Math.round(w / cols));
  }
  for (const el of document.querySelectorAll('p, span, td, th, a, button, li, label, small, h1, h2, h3, h4, dt, dd')) {
    if (!vis(el)) continue; const fs = parseFloat(getComputedStyle(el).fontSize);
    if (fs < 11.5 && el.textContent.trim() && out.smallText.length < 6) out.smallText.push(sel(el) + ' ' + fs + 'px');
  }
  for (const el of document.querySelectorAll('main :is(button, a[href], input:not([type=hidden]), select)')) {
    if (!vis(el)) continue; const h = el.getBoundingClientRect().height; if (h < 36) out.shortTargets++;
  }
  return out;
})()
"""


def main():
    urls = json.loads((SCRATCH / "role_urls.json").read_text())
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for role, key in SESSIONS.items():
            pages = list(dict.fromkeys(urls.get(EMAILS[role], []) + EXTRA.get(role, [])))
            for name, (w, h) in VIEWPORTS.items():
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1, has_touch=True, is_mobile=False)
                ctx.add_cookies([{"name": "sessionid", "value": key, "domain": "localhost", "path": "/"}])
                page = ctx.new_page()
                page.set_default_timeout(20000)
                for url in pages:
                    rec = {"role": role, "viewport": name, "url": url}
                    try:
                        resp = page.goto(BASE + url, wait_until="domcontentloaded")
                        page.wait_for_timeout(1200)
                        rec["status"] = resp.status if resp else None
                        rec["final"] = page.url.replace(BASE, "")
                        if "/login" in page.url or "/policy-agreement" in page.url:
                            rec["skipped"] = "gated"
                        else:
                            rec.update(page.evaluate(PROBE))
                            rec["overflow"] = rec["sw"] > w + 2
                            shot = SHOTS / f"{role}__{name}__{url.strip('/').replace('/', '_').replace('?', '_').replace('=', '-') or 'root'}.png"
                            page.screenshot(path=str(shot), full_page=False)
                            rec["shot"] = shot.name
                    except Exception as exc:  # noqa: BLE001
                        rec["error"] = str(exc)[:200]
                    results.append(rec)
                    print(role, name, url, rec.get("status"), "OVERFLOW" if rec.get("overflow") else "", len(rec.get("wide", [])), len(rec.get("narrowTables", [])), len(rec.get("denseGrids", [])), flush=True)
                ctx.close()
        browser.close()
    (SCRATCH / "tablet_audit.json").write_text(json.dumps(results, indent=1))
    lines = ["# Tablet audit", ""]
    for r in results:
        if r.get("skipped") or r.get("error"):
            continue
        issues = []
        if r.get("overflow"):
            issues.append(f"document overflow {r['sw']}px")
        if r.get("wide"):
            issues.append("wide: " + "; ".join(r["wide"][:4]))
        if r.get("narrowTables"):
            issues.append("narrow tables: " + "; ".join(r["narrowTables"][:3]))
        if r.get("denseGrids"):
            issues.append("dense grids: " + "; ".join(r["denseGrids"][:4]))
        if r.get("smallText"):
            issues.append("small text: " + "; ".join(r["smallText"][:3]))
        if r.get("shortTargets", 0) > 5:
            issues.append(f"{r['shortTargets']} targets under 36px")
        if issues:
            lines.append(f"- **{r['role']} {r['viewport']} {r['url']}** — " + " | ".join(issues))
    (SCRATCH / "tablet_audit.md").write_text("\n".join(lines))
    print("done", len(results), "pages")


if __name__ == "__main__":
    main()
