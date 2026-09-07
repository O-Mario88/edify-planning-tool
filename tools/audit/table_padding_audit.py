"""Measure every visible table's cell padding, row height and type size."""

import json
from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
SCRATCH = Path(__file__).resolve().parent / "out"
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
    "pl": ["/dashboard?view=operations", "/analytics/program-lead"],
    "ia": ["/ia/dashboard/?view=map", "/ia/dashboard/?view=operations"],
    "accountant": ["/accounts"],
    "superuser": [
        "/analytics/ssa-performance",
        "/analytics/people",
        "/reports",
        "/targets",
        "/target-distribution/team",
    ],
}

PROBE = r"""
(() => {
  const out = [];
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const sel = el => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id; else if (el.className && typeof el.className === 'string') s += '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.'); return s; };
  for (const t of document.querySelectorAll('table')) {
    if (!vis(t)) continue;
    const th = t.querySelector('thead th') || t.querySelector('th');
    const rows = [...t.querySelectorAll('tbody tr')].filter(vis);
    const td = rows[0] && rows[0].querySelector('td');
    if (!td) continue;
    const cs = getComputedStyle(td), hs = th ? getComputedStyle(th) : null;
    const rowH = rows.slice(0, 5).map(r => Math.round(r.getBoundingClientRect().height));
    out.push({
      table: sel(t), rows: rows.length,
      tdPad: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].map(v => Math.round(parseFloat(v))).join('/'),
      thPad: hs ? [hs.paddingTop, hs.paddingRight, hs.paddingBottom, hs.paddingLeft].map(v => Math.round(parseFloat(v))).join('/') : null,
      rowH: rowH, font: Math.round(parseFloat(cs.fontSize) * 10) / 10, thFont: hs ? Math.round(parseFloat(hs.fontSize) * 10) / 10 : null,
      thUpper: hs ? hs.textTransform : null, borders: getComputedStyle(rows[0]).borderTopWidth,
      width: Math.round(t.getBoundingClientRect().width), parent: Math.round(t.parentElement.getBoundingClientRect().width),
      scroller: (() => { let p = t.parentElement; while (p && p !== document.body) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll') return true; p = p.parentElement; } return false; })(),
    });
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
            pages = list(
                dict.fromkeys(urls.get(EMAILS[role], []) + EXTRA.get(role, []))
            )
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_cookies(
                [
                    {
                        "name": "sessionid",
                        "value": key,
                        "domain": "localhost",
                        "path": "/",
                    }
                ]
            )
            page = ctx.new_page()
            page.set_default_timeout(20000)
            for url in pages:
                try:
                    page.goto(BASE + url, wait_until="domcontentloaded")
                    page.wait_for_timeout(900)
                    if "/login" in page.url or "/policy-agreement" in page.url:
                        continue
                    for t in page.evaluate(PROBE):
                        results.append({"role": role, "url": url, **t})
                except Exception as exc:  # noqa: BLE001
                    results.append({"role": role, "url": url, "error": str(exc)[:120]})
            ctx.close()
        browser.close()
    (SCRATCH / "table_padding.json").write_text(json.dumps(results, indent=1))
    ok = [r for r in results if "table" in r]
    print("tables measured", len(ok), "on", len({r["url"] for r in ok}), "pages")
    print("td padding schemes:", Counter(r["tdPad"] for r in ok).most_common(12))
    print("th padding schemes:", Counter(r["thPad"] for r in ok).most_common(8))
    print(
        "row heights:",
        Counter(min(r["rowH"]) if r["rowH"] else None for r in ok).most_common(12),
    )
    print("body font:", Counter(r["font"] for r in ok).most_common(6))
    print(
        "head font/transform:",
        Counter((r["thFont"], r["thUpper"]) for r in ok).most_common(6),
    )
    narrow = [r for r in ok if r["parent"] > 480 and r["width"] < r["parent"] * 0.7]
    print(
        "tables under 70% of parent:",
        len(narrow),
        [(r["url"], r["table"], r["width"], r["parent"]) for r in narrow[:8]],
    )
    wide = [r for r in ok if r["width"] > r["parent"] + 2 and not r["scroller"]]
    print(
        "tables overflowing without a scroll region:",
        len(wide),
        [(r["url"], r["table"]) for r in wide[:8]],
    )


if __name__ == "__main__":
    main()
