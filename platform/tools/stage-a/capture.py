"""Stage A (docs/migration/177): real screenshots of the existing application.

    STAGE_A_PASSWORD=<local seed password> python platform/tools/stage-a/capture.py \\
        --base http://127.0.0.1:8010 --out "<folder>" [--pages 12] [--roles CCEO,Admin]

Signs in to the LOCAL development application only (the base must be a
localhost address) as each role's seeded account, and for its landing page
and the first sidebar destinations takes a full-page screenshot at phone
(375×812), tablet (768×1024) and desktop (1440×900) widths. Beside each it
records what the browser measured for that load (time to first byte, DOM
ready, load, largest contentful paint, layout shift) and the page's size, in
index.json. Nothing is sent anywhere else and nothing is written to any
database beyond the sign-ins the application records itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ACCOUNTS = {
    "CCEO": "cceo1@edify.org",
    "Program Lead": "pl1@edify.org",
    "CountryDirector": "cd@edify.org",
    "ImpactAssessment": "ia@edify.org",
    "Accountant": "accountant@edify.org",
    "RegionalVicePresident": "rvp@edify.org",
    "RegionalProgramLead": "regional-lead@edify.org",
    "HumanResources": "hr@edify.org",
    "BusinessTransformationOfficer": "business-transformation@edify.org",
    "ProjectCoordinator": "coordinator@edify.org",
    "Admin": "admin@edify.org",
    "PartnerAdmin": "partner-admin@edify.org",
    "PartnerFieldOfficer": "partner@edify.org",
    "MfiPartnerAdmin": "mfi-admin@edify.org",
    "MfiLoanOfficer": "mfi-officer@edify.org",
    "ClusterLeader": "cluster-leader@edify.org",
}
VIEWPORTS = {"phone": (375, 812), "tablet": (768, 1024), "desktop": (1440, 900)}
LOCAL = {"127.0.0.1", "localhost", "::1"}
#: Links that are not pages to look at.
SKIP = re.compile(r"^/(logout|login|static|media|api|exports?|.*\.(csv|xlsx|pdf))(/|$)")

MEASURE = """() => {
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const lcp = (window.__stageA && window.__stageA.lcp) || null;
  const cls = (window.__stageA && window.__stageA.cls) || 0;
  return {
    ttfb_ms: nav.responseStart ? Math.round(nav.responseStart) : null,
    dom_ready_ms: nav.domContentLoadedEventEnd ? Math.round(nav.domContentLoadedEventEnd) : null,
    load_ms: nav.loadEventEnd ? Math.round(nav.loadEventEnd) : null,
    lcp_ms: lcp ? Math.round(lcp) : null,
    cls: Math.round(cls * 1000) / 1000,
    transfer_kb: nav.transferSize ? Math.round(nav.transferSize / 1024) : null,
    height_px: document.documentElement.scrollHeight,
  };
}"""

OBSERVE = """
window.__stageA = {lcp: null, cls: 0};
new PerformanceObserver((list) => { for (const e of list.getEntries()) window.__stageA.lcp = e.startTime; })
  .observe({type: 'largest-contentful-paint', buffered: true});
new PerformanceObserver((list) => { for (const e of list.getEntries()) if (!e.hadRecentInput) window.__stageA.cls += e.value; })
  .observe({type: 'layout-shift', buffered: true});
"""


def slug(path: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    return s or "landing"


def sign_in(page, base: str, email: str, password: str) -> str:
    page.goto(base + "/login", wait_until="domcontentloaded")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    return urlparse(page.url).path


def destinations(page, limit: int) -> list[str]:
    hrefs = page.eval_on_selector_all(
        "aside a[href], nav a[href]", "els => els.map(e => e.getAttribute('href'))"
    )
    out = []
    for href in hrefs:
        if (
            not href
            or not href.startswith("/")
            or href.startswith("//")
            or SKIP.match(href)
        ):
            continue
        path = href.split("#")[0]
        if path and path not in out:
            out.append(path)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--out", required=True)
    parser.add_argument("--pages", type=int, default=12)
    parser.add_argument("--roles", default="")
    args = parser.parse_args()
    if urlparse(args.base).hostname not in LOCAL:
        print(
            "capture.py signs in to a local development application only",
            file=sys.stderr,
        )
        return 2
    password = os.environ.get("STAGE_A_PASSWORD", "")
    if not password:
        print("set STAGE_A_PASSWORD to the local seed password", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    roles = [r for r in args.roles.split(",") if r] or list(ACCOUNTS)
    index = {"base": args.base, "taken": time.strftime("%Y-%m-%d %H:%M"), "shots": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for role in roles:
            email = ACCOUNTS[role]
            folder = out / slug(role)
            folder.mkdir(exist_ok=True)
            paths: list[str] | None = None
            for name, (width, height) in VIEWPORTS.items():
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    is_mobile=name == "phone",
                    has_touch=name == "phone",
                )
                context.add_init_script(OBSERVE)
                page = context.new_page()
                landing = sign_in(page, args.base, email, password)
                if paths is None:
                    paths = [landing] + [
                        p for p in destinations(page, args.pages) if p != landing
                    ]
                    paths = paths[: args.pages + 1]
                for path in paths:
                    shot = {"role": role, "viewport": name, "path": path}
                    try:
                        response = page.goto(
                            args.base + path, wait_until="networkidle", timeout=60000
                        )
                        page.wait_for_timeout(400)
                        shot["status"] = response.status if response else None
                        shot["landed"] = urlparse(page.url).path
                        shot.update(page.evaluate(MEASURE))
                        file = folder / f"{slug(path)}-{name}.jpg"
                        page.screenshot(
                            path=str(file), full_page=True, type="jpeg", quality=70
                        )
                        shot["file"] = str(file.relative_to(out))
                    except Exception as exc:  # noqa: BLE001 - a page that fails is recorded, not fatal
                        shot["error"] = str(exc)[:300]
                    index["shots"].append(shot)
                    print(
                        role,
                        name,
                        path,
                        shot.get("status"),
                        shot.get("load_ms"),
                        flush=True,
                    )
                context.close()
        browser.close()
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"{len(index['shots'])} shots in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
