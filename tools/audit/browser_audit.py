"""Browser-side audit: console errors, failed requests, long tasks, timings.

For every role's sidebar pages (plus dashboard views) at 1440x900: page
errors and console errors, network responses >= 400, long tasks over 50ms
(main-thread freezes), and navigation timing (TTFB, DOMContentLoaded, load).
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
SCRATCH = Path(__file__).resolve().parent / "out"
EMAILS = {
    "superuser": "edwin.omario@gmail.com",
    "cd": "cd@edify.org",
    "pl": "pl1@edify.org",
    "ia": "ia@edify.org",
    "accountant": "accountant@edify.org",
}
EXTRA = {
    "cd": ["/dashboard?view=map", "/dashboard?view=operations"],
    "pl": [
        "/dashboard?view=map",
        "/dashboard?view=operations",
        "/analytics/program-lead",
    ],
    "ia": ["/ia/dashboard/?view=map", "/ia/dashboard/?view=operations"],
    "accountant": ["/accounts", "/accounts?view=map"],
    "superuser": [
        "/dashboard?view=map",
        "/analytics/verification-quality",
        "/analytics/people",
        "/reports",
        "/team-targets",
    ],
}
INIT = """
window.__edifyLong = []; window.__edifyErrors = [];
try { new PerformanceObserver(list => { for (const e of list.getEntries()) window.__edifyLong.push(Math.round(e.duration)); }).observe({ type: 'longtask', buffered: true }); } catch (e) {}
window.addEventListener('error', e => window.__edifyErrors.push(String(e.message).slice(0, 160)));
window.addEventListener('unhandledrejection', e => window.__edifyErrors.push('unhandled: ' + String(e.reason).slice(0, 160)));
"""
TIMING = """
(() => { const n = performance.getEntriesByType('navigation')[0]; return { ttfb: n ? Math.round(n.responseStart - n.requestStart) : null, dcl: n ? Math.round(n.domContentLoadedEventEnd) : null, load: n ? Math.round(n.loadEventEnd) : null, transfer: n ? Math.round(n.transferSize / 1024) : null, long: window.__edifyLong || [], errors: window.__edifyErrors || [], resources: performance.getEntriesByType('resource').length }; })()
"""


def main():
    wanted = sys.argv[1:] or list(EMAILS)
    keys = json.loads((SCRATCH / "sessions.json").read_text())
    urls = json.loads((SCRATCH / "role_urls.json").read_text())
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for role in wanted:
            pages = list(
                dict.fromkeys(EXTRA.get(role, []) + urls.get(EMAILS[role], []))
            )
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_cookies(
                [
                    {
                        "name": "sessionid",
                        "value": keys[role],
                        "domain": "localhost",
                        "path": "/",
                    }
                ]
            )
            ctx.add_init_script(INIT)
            page = ctx.new_page()
            page.set_default_timeout(25000)
            console = []
            failed = []
            page.on(
                "console",
                lambda m: console.append((m.type, m.text[:200]))
                if m.type in ("error", "warning")
                else None,
            )
            page.on(
                "response",
                lambda r: failed.append((r.status, r.url.replace(BASE, "")[:120]))
                if r.status >= 400
                else None,
            )
            for url in pages:
                console.clear()
                failed.clear()
                rec = {"role": role, "url": url}
                try:
                    page.goto(BASE + url, wait_until="load")
                    page.wait_for_timeout(1500)
                    if "/login" in page.url or "/policy-agreement" in page.url:
                        rec["skipped"] = "gated"
                    else:
                        rec.update(page.evaluate(TIMING))
                        rec["console"] = [c for c in console if c[0] == "error"][:6]
                        rec["warnings"] = len([c for c in console if c[0] == "warning"])
                        rec["failed"] = failed[:6]
                except Exception as exc:  # noqa: BLE001
                    rec["error"] = str(exc)[:200]
                results.append(rec)
                flag = ""
                if rec.get("console"):
                    flag += " CONSOLE"
                if rec.get("failed"):
                    flag += " FAILED"
                if any(d >= 100 for d in rec.get("long", [])):
                    flag += " LONGTASK"
                if (rec.get("dcl") or 0) > 1500:
                    flag += " SLOW"
                print(
                    role,
                    url,
                    rec.get("ttfb"),
                    rec.get("dcl"),
                    rec.get("load"),
                    "long=" + str(sorted(rec.get("long", []), reverse=True)[:3]),
                    flag,
                    flush=True,
                )
            ctx.close()
        browser.close()
    (SCRATCH / ("browser_audit_%s.json" % "_".join(wanted))).write_text(
        json.dumps(results, indent=1)
    )
    print("done", len(results))


if __name__ == "__main__":
    main()
