"""UI consistency audit: control heights, type sizes, radii, card padding.

For every role's sidebar pages at 1440x900, collect the computed size of
each visible control (buttons, button-like links, inputs, selects), heading
sizes, card paddings and border radii, then report the distributions and the
pages that carry outliers. Numbers, not impressions.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
SCRATCH = Path(__file__).resolve().parent / "out"
EMAILS = {"superuser": "edwin.omario@gmail.com", "cd": "cd@edify.org", "pl": "pl1@edify.org", "ia": "ia@edify.org", "accountant": "accountant@edify.org"}

PROBE = r"""
(() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.top < 4000; };
  const sel = el => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id; else if (el.className && typeof el.className === 'string') s += '.' + el.className.trim().split(/\s+/).slice(0,2).join('.'); return s; };
  const main = document.querySelector('main') || document.body;
  const controls = [];
  for (const el of main.querySelectorAll('button, a.btn, a[class*="btn"], a[class*="button"], input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, [role=tab]')) {
    if (!vis(el)) continue; if (el.closest('table')) continue; if (el.closest('.apexcharts-canvas')) continue;
    const cs = getComputedStyle(el);
    controls.push({ kind: el.tagName.toLowerCase() + (el.getAttribute('role') ? '[' + el.getAttribute('role') + ']' : ''), h: Math.round(el.getBoundingClientRect().height), fs: Math.round(parseFloat(cs.fontSize) * 10) / 10, radius: cs.borderTopLeftRadius, sel: sel(el).slice(0, 60), text: (el.textContent || el.value || '').trim().slice(0, 24) });
  }
  const headings = [];
  for (const h of main.querySelectorAll('h1, h2, h3')) { if (!vis(h)) continue; const cs = getComputedStyle(h); headings.push({ tag: h.tagName.toLowerCase(), fs: Math.round(parseFloat(cs.fontSize) * 10) / 10, fw: cs.fontWeight, text: h.textContent.trim().slice(0, 30) }); }
  const cards = [];
  for (const c of main.querySelectorAll('.card, .edify-surface, section[class*="card"], article[class*="panel"], .rounded-surface')) { if (!vis(c)) continue; if (c.closest('table')) continue; const cs = getComputedStyle(c); cards.push({ pad: Math.round(parseFloat(cs.paddingLeft)), radius: cs.borderTopLeftRadius, sel: sel(c).slice(0, 50) }); }
  return { controls, headings, cards };
})()
"""


def main():
    wanted = sys.argv[1:] or list(EMAILS)
    keys = json.loads((SCRATCH / "sessions.json").read_text())
    urls = json.loads((SCRATCH / "role_urls.json").read_text())
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for role in wanted:
            pages = list(dict.fromkeys(urls.get(EMAILS[role], [])))
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_cookies([{"name": "sessionid", "value": keys[role], "domain": "localhost", "path": "/"}])
            page = ctx.new_page(); page.set_default_timeout(25000)
            for url in pages:
                try:
                    page.goto(BASE + url, wait_until="domcontentloaded"); page.wait_for_timeout(1200)
                    if "/login" in page.url or "/policy-agreement" in page.url:
                        continue
                    r = page.evaluate(PROBE); r.update({"role": role, "url": url}); results.append(r)
                except Exception as exc:  # noqa: BLE001
                    results.append({"role": role, "url": url, "error": str(exc)[:120]})
            ctx.close()
        browser.close()
    (SCRATCH / ("ui_audit_%s.json" % "_".join(wanted))).write_text(json.dumps(results, indent=1))
    ok = [r for r in results if "controls" in r]
    heights = Counter(); fonts = Counter(); radii = Counter(); hfs = defaultdict(Counter); cpad = Counter(); crad = Counter()
    odd_pages = defaultdict(list)
    for r in ok:
        for c in r["controls"]:
            heights[(c["kind"], c["h"])] += 1; fonts[c["fs"]] += 1; radii[c["radius"]] += 1
            if c["kind"].startswith("button") or c["kind"].startswith("a"):
                if c["h"] not in (28, 30, 32, 36, 40, 44): odd_pages[r["url"]].append(f"{c['sel']} h={c['h']} '{c['text']}'")
        for h in r["headings"]: hfs[h["tag"]][h["fs"]] += 1
        for c in r["cards"]: cpad[c["pad"]] += 1; crad[c["radius"]] += 1
    print("pages", len(ok))
    print("control heights:", sorted(heights.items(), key=lambda kv: -kv[1])[:24])
    print("control font sizes:", fonts.most_common(8))
    print("control radii:", radii.most_common(6))
    for tag in ("h1", "h2", "h3"): print(tag, hfs[tag].most_common(6))
    print("card padding:", cpad.most_common(8)); print("card radii:", crad.most_common(6))
    print("\npages with off-scale button heights:", len(odd_pages))
    for url, items in list(odd_pages.items())[:25]: print(" ", url, "|", " ; ".join(items[:3]))


if __name__ == "__main__":
    main()
