"""A screen-by-screen check of the web app, every role at three sizes.

    SWEEP_PASSWORD=<local seed password> python platform/tools/ui-sweep/sweep.py \\
        --base http://127.0.0.1:3000 --out "<folder>" [--roles CCEO,Admin] [--pages 60]

Signs in to the LOCAL web app only (the base must be a localhost address) as
each role's seeded account, opens every page its menu links to at phone
(390x844), tablet (768x1024) and desktop (1440x900), and records what is
wrong with each in the browser's own measurements, not by eye:

  page-scrolls-sideways   the page is wider than the screen
  card-in-card            a phone card drawn inside another card
  desktop-rail-on-phone   the existing web's tab rail inside the phone layout
  rail-overflows          a tab rail or switch wider than its card
  text-cut-off            visible text cut short with an ellipsis
  words-run-together      "8 past dueFinish": two parts with no space between
  not-drawn               a part the web cannot draw yet
  empty-card              a card with nothing in it
  small-tap-target        on a phone, a button or link under 32px tall
  page-error              the page answered with an error or did not load

Writes report.json (every finding) and report.md (counts by check, then the
pages with findings) to --out. Nothing is sent anywhere else.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
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
SIZES = {"phone": (390, 844), "tablet": (768, 1024), "desktop": (1440, 900)}
LOCAL = {"127.0.0.1", "localhost", "::1"}
#: Links that are not pages to look at.
SKIP = re.compile(
    r"^/(logout|login|auth|static|media|api|exports?|.*\.(csv|xlsx|pdf))(/|$)"
)
#: How long a page may take to settle.
SETTLE_MS = 1200

#: The checks, run in the page. Each returns a list of short examples (what
#: was found, where), so the report can say what to look at.
CHECKS = r"""(size) => {
  const vis = (e) => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const main = document.querySelector('main') || document.body;
  const say = (e) => (e.getAttribute('aria-label') || e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60);
  const ph = [...document.querySelectorAll('[data-ph=blocks]')].find(vis);
  const inPh = (sel) => (ph ? [...ph.querySelectorAll(sel)].filter(vis) : []);
  const out = {};
  out['page-scrolls-sideways'] = document.documentElement.scrollWidth > innerWidth + 1
    ? [`${document.documentElement.scrollWidth}px wide in ${innerWidth}px`] : [];
  out['card-in-card'] = inPh('[data-ph=card] [data-ph=card]').map(say);
  out['desktop-rail-on-phone'] = inPh('[data-edify-tablist]').map(say);
  out['rail-overflows'] = inPh('[data-ph=switch], [data-ph=rail], [data-edify-tablist]')
    .filter((e) => e.scrollWidth > e.clientWidth + 1).map(say);
  if (!ph) {
    out['rail-overflows'].push(...[...main.querySelectorAll('[data-edify-tablist]')].filter(vis)
      .filter((e) => e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'auto').map(say));
  }
  out['text-cut-off'] = [...main.querySelectorAll('*')].filter((e) => {
    if (!vis(e) || e.closest('select, input, textarea, [role=listbox], [data-ph=tile-value]')) return false;
    const cs = getComputedStyle(e);
    if (cs.textOverflow !== 'ellipsis' && cs.webkitLineClamp === 'none') return false;
    return e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1;
  }).map(say).slice(0, 8);
  const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
  const runTogether = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!el || !vis(el) || el.closest('script, style, code, svg')) continue;
    const m = n.textContent.match(/\b[a-z]{2,}[a-z][A-Z][a-z]{2,}\b/);
    if (m) runTogether.push(`${m[0]} in "${n.textContent.trim().slice(0, 60)}"`);
  }
  out['words-run-together'] = runTogether.slice(0, 8);
  out['not-drawn'] = [...main.querySelectorAll('[data-block=not-drawn]')].filter(vis).map(say);
  out['empty-card'] = inPh('[data-ph=card]').filter((e) => !e.textContent.trim() && !e.querySelector('img, svg, canvas, input, select')).map(() => 'a card with nothing in it');
  out['small-tap-target'] = size !== 'phone' ? [] : [...main.querySelectorAll('button, a[href], [role=button]')]
    .filter((e) => vis(e) && !e.closest('p, td, li, [data-ph=panel-field], [data-ph=fact]'))
    .filter((e) => { const r = e.getBoundingClientRect(); return r.height > 0 && r.height < 32; })
    .map((e) => `${say(e)} (${Math.round(e.getBoundingClientRect().height)}px)`).slice(0, 8);
  return out;
}"""


def sign_in(page, base: str, email: str, password: str) -> str:
    page.goto(base + "/login", wait_until="domcontentloaded")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('form[action="/auth/sign-in"] button[type="submit"]')
    page.wait_for_load_state("networkidle")
    return urlparse(page.url).path


def destinations(page, limit: int) -> list[str]:
    hrefs = page.eval_on_selector_all(
        "aside a[href], nav a[href]", "els => els.map(e => e.getAttribute('href'))"
    )
    out: list[str] = []
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
    return out[:limit]


def check(page, base: str, path: str, size: str) -> dict:
    found: dict = {"path": path, "size": size}
    try:
        response = page.goto(base + path, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(SETTLE_MS)
        status = response.status if response else None
        found["landed"] = urlparse(page.url).path
        findings = page.evaluate(CHECKS, size)
        if status and status >= 400:
            findings["page-error"] = [f"answered {status}"]
    except Exception as exc:  # noqa: BLE001 - a page that fails is a finding, not fatal
        findings = {"page-error": [str(exc).splitlines()[0][:200]]}
    found["findings"] = {name: items for name, items in findings.items() if items}
    return found


def report(rows: list[dict]) -> str:
    counts = Counter(name for row in rows for name in row["findings"])
    lines = [
        "# UI sweep",
        "",
        f"{len(rows)} page loads.",
        "",
        "| Check | Page loads |",
        "|---|---|",
    ]
    lines += [f"| {name} | {count} |" for name, count in counts.most_common()]
    lines += ["", "## Pages with findings", ""]
    for row in rows:
        if not row["findings"]:
            continue
        lines.append(f"- **{row['role']} · {row['size']} · {row['path']}**")
        for name, items in row["findings"].items():
            lines.append(f"  - {name}: {'; '.join(items[:3])}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:3000")
    parser.add_argument("--out", required=True)
    parser.add_argument("--pages", type=int, default=60)
    parser.add_argument("--roles", default="")
    parser.add_argument("--sizes", default=",".join(SIZES))
    args = parser.parse_args()
    if urlparse(args.base).hostname not in LOCAL:
        print(
            "sweep.py signs in to a local development application only", file=sys.stderr
        )
        return 2
    password = os.environ.get("SWEEP_PASSWORD", "")
    if not password:
        print("set SWEEP_PASSWORD to the local seed password", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    roles = [r for r in args.roles.split(",") if r] or list(ACCOUNTS)
    sizes = [s for s in args.sizes.split(",") if s in SIZES]
    rows: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for role in roles:
            paths: list[str] | None = None
            for size in sizes:
                width, height = SIZES[size]
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    is_mobile=size == "phone",
                    has_touch=size == "phone",
                )
                page = context.new_page()
                try:
                    landing = sign_in(page, args.base, ACCOUNTS[role], password)
                except Exception as exc:  # noqa: BLE001 - an account that cannot sign in is reported
                    rows.append(
                        {
                            "role": role,
                            "size": size,
                            "path": "/login",
                            "findings": {
                                "page-error": [
                                    f"sign-in: {str(exc).splitlines()[0][:160]}"
                                ]
                            },
                        }
                    )
                    context.close()
                    continue
                if paths is None:
                    paths = [landing] + [
                        p for p in destinations(page, args.pages) if p != landing
                    ]
                for path in paths:
                    row = check(page, args.base, path, size)
                    row["role"] = role
                    rows.append(row)
                    print(
                        role, size, path, ",".join(row["findings"]) or "ok", flush=True
                    )
                context.close()
        browser.close()
    (out / "report.json").write_text(
        json.dumps(
            {"base": args.base, "taken": time.strftime("%Y-%m-%d %H:%M"), "rows": rows},
            indent=1,
        ),
        encoding="utf-8",
    )
    (out / "report.md").write_text(report(rows), encoding="utf-8")
    print(f"{len(rows)} page loads; report in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
