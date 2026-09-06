import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
OUT = Path(__file__).resolve().parent / "out"; keys = json.loads((OUT / "sessions.json").read_text()); urls = json.loads((OUT / "role_urls.json").read_text())
EMAILS = {"cd": "cd@edify.org", "pl": "pl1@edify.org", "ia": "ia@edify.org", "accountant": "accountant@edify.org"}
S = str(Path(__file__).resolve().parent / "out")
SHOTS = {("cd", "/analytics/country-director"): ".edify-section-nav__inner", ("cd", "/fund-requests/weekly"): "nav[data-edify-tablist]", ("cd", "/staff"): "main table", ("cd", "/cost-settings"): "main table", ("cd", "/dashboard?view=operations"): "table.edify-table--truncate", ("cd", "/work-plan"): "main table", ("pl", "/partners"): "main table", ("ia", "/ia/verification/"): "main table", ("pl", "/leave/team-availability"): "main table", ("cd", "/debriefs"): "main table"}
PROBE = r"""() => {
  const rails = Array.from(document.querySelectorAll('[role=tablist], [data-edify-tablist], .messages-inbox-tabs, .pto-tabs, .sp-period-tabs, .spp-tabs, .tt-segmented, .oversight-entity-tabs, .edify-section-nav__inner, .edify-section-nav__clusters, .fund-requesters__strip')).filter(t => t.getBoundingClientRect().width > 0 && !t.closest('.edify-rail-more')).map(t => { const kids = Array.from(t.children).filter(c => c.getBoundingClientRect().height > 8 && !c.classList.contains('edify-rail-more')); const tops = new Set(kids.map(c => Math.round(c.getBoundingClientRect().top))); const more = t.querySelector(':scope > .edify-rail-more'); return { cls: (t.className || t.tagName).toString().split(' ')[0].slice(0, 26), rows: tops.size, shown: kids.length, more: more && !more.hidden ? more.querySelector('.edify-rail-more__count').textContent : '', clipped: t.scrollWidth > t.clientWidth + 1 }; }).filter(r => r.rows > 1 || r.more || r.clipped);
  const tables = Array.from(document.querySelectorAll('main table')).filter(t => t.getBoundingClientRect().width > 0).map(t => { const region = t.closest('.edify-table-scroll-region') || t.parentElement; const tall = Array.from(t.querySelectorAll('tbody tr')).filter(r => r.getBoundingClientRect().height > 40).length; return { trunc: t.classList.contains('edify-table--truncate'), cut: t.querySelectorAll('[data-edify-title]').length, tallRows: tall, scrolls: t.scrollWidth > region.clientWidth + 1, over: t.scrollWidth - region.clientWidth, cols: (t.querySelector('tbody tr') || {children: []}).children.length }; }).filter(r => r.trunc || r.tallRows || r.scrolls);
  return { rails, tables };
}"""
with sync_playwright() as p:
    b = p.chromium.launch()
    for role in (sys.argv[1:] or ["cd", "pl", "ia", "accountant"]):
        pages = list(dict.fromkeys((["/dashboard?view=operations"] if role in ("cd", "pl") else []) + urls.get(EMAILS[role], [])))
        ctx = b.new_context(viewport={"width": 1440, "height": 900}); ctx.add_cookies([{"name": "sessionid", "value": keys[role], "domain": "localhost", "path": "/"}])
        page = ctx.new_page(); page.set_default_timeout(20000); errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:120]))
        for url in pages:
            try:
                page.goto("http://localhost:8000" + url, wait_until="load"); page.wait_for_timeout(900)
                if "/login" in page.url or "policy" in page.url: continue
                r = page.evaluate(PROBE)
                if r["rails"] or r["tables"] or errors: print(role, url, "| rails", r["rails"], "| tables", r["tables"], "| errors", errors[-2:])
                errors.clear()
                sel = SHOTS.get((role, url))
                if sel:
                    el = page.query_selector(sel)
                    if el: el.screenshot(path=f"{S}/after_{role}_{url.strip('/').replace('/', '_').replace('?', '_').replace('=', '_') or 'home'}.png")
            except Exception as e: print(role, url, "ERR", str(e)[:80])
        ctx.close()
    b.close()
