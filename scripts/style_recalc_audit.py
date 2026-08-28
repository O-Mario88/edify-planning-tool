#!/usr/bin/env python
"""FREEZE-01 — measure what one DOM mutation costs, per page.

WHY THIS EXISTS

A tab that locks up for six seconds is usually blamed on "too much
JavaScript". On this application it is not. The browser's own counters, taken
across a real `/analytics` load, put **6,245ms in RecalcStyleDuration — 49% of
wall clock — against 298ms of layout**. The freeze is style resolution.

Style resolution is not paid once. It is paid every time something dirties an
element and something else then reads geometry, because the read has to flush
the pending style first. A component that appends an element and measures it,
in a loop, therefore pays the flush once per iteration. ApexCharts does exactly
that about ninety times while it renders — which is ordinary, and costs 0.14ms
per flush on a blank page.

Here it costs up to 93ms per flush, so ninety of them is six frozen seconds.

WHAT MAKES A FLUSH COST 93ms

Not the chart, and not the page's size on its own. Measured, and each of these
ruled a suspect out rather than in:

* the same chart on a blank page in the same browser: 20ms, 0.14ms per flush;
* the same chart, same options, same page, rendered after load: 136ms;
* the map SVG removed from the document entirely: no change;
* `getComputedStyle`: 158 calls, 0ms total;
* web fonts: still `loading` after the cost had already collapsed;
* `:has()`: removing all 55 such rules changes nothing (98%).

What does move it is where the mutation happens. The same one-element append:

    inside <main>   93.50ms        inside <body>   0.10ms

`<body>` is outside the scope every heavy selector in `consistency.css` is
rooted at. Those selectors — `main :where(...)[data-...]`,
`[class*="grid"]:has(> :is(...))`, `[class*="-card"]:not([class*="-card-"])` —
cannot be indexed per element the way a class selector can, so a mutation under
`main` re-resolves against a large share of the ~11,000 selectors this
application ships across 17 stylesheets. Disabling that one sheet halves the
cost; disabling every `*`/`[attr]` rule takes it from 78ms to 6.7ms.

No single rule is responsible. That was tested directly: binary-searching 967
candidate rules, disabling any one of them alone leaves the cost unchanged at
~77ms. It is the aggregate, which is why the fix is a budget rather than a
patch.

WHAT THIS MEASURES

Per page, in a real browser, on a real signed-in session:

* `mutation_ms` — append one element inside `<main>`, read its geometry,
  median of 11. This is the number a user feels, because it is what every
  chart render, table swap and drawer open pays per step.
* `full_recalc_ms` — invalidate at the root and flush, median of 9. The
  ceiling: what a theme switch costs.
* `selectors`, `elements` — the two factors the cost scales with.

WHY A BUDGET AND NOT A PASS/FAIL CONSTANT

16ms is one frame at 60Hz. A mutation that costs more than a frame means any
loop over it drops frames, and a loop of ninety means the tab stops answering.
So the budget is one frame, and pages over it are named as open defects rather
than folded into an allowance — a page at 93ms is not "slow", it is a page
where a hundred-step interaction freezes for nine seconds.

    scripts/style_recalc_audit.py                    # measure, compare, report
    STYLE_WRITE_BASELINE=1 scripts/style_recalc_audit.py    # re-record

Exit codes:
    0  every page is inside its recorded baseline
    1  a page got worse than its baseline, or is over budget
    2  REFUSED — could not measure, and says so rather than reporting a
       clean result it never took
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.contrib.staticfiles.handlers import StaticFilesHandler  # noqa: E402
from django.test.testcases import LiveServerThread  # noqa: E402
from django.test.utils import modify_settings  # noqa: E402

from apps.documents.gate import PolicyGateService  # noqa: E402

# The document gate is a different concern and would redirect every page.
PolicyGateService.state_for = staticmethod(lambda user: ("clear", []))

CHROMIUM = os.environ.get(
    "STYLE_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
)
BASELINE = REPO / "docs" / "style-recalc-baseline.json"

#: One frame at 60Hz. A mutation dearer than this drops a frame every time,
#: and components mutate in loops.
BUDGET_MS = 16.0

#: How much worse than its recorded value a page may drift before this fails.
#: Wide enough to absorb a loaded machine, tight enough that a real regression
#: cannot hide inside it.
TOLERANCE = 1.35

#: The pages people actually sit on. `/analytics` and `/schools` are the two
#: that carry the defect; the others are here so a regression that spreads it
#: to a currently-healthy page fails on the day it lands.
DEFAULT_PAGES = (
    "/analytics",
    "/schools",
    "/dashboard",
    "/todos",
    "/my-plan",
    "/system-health",
)

MEASURE = r"""
() => {
  const median = (t) => {
    t.sort((a, b) => a - b);
    return +t[Math.floor(t.length / 2)].toFixed(2);
  };

  // What every chart render, table swap and drawer open pays per step:
  // append one element, then read geometry, which flushes pending style.
  const mutationCost = (host) => {
    if (!host) return null;
    const t = [];
    for (let i = 0; i < 11; i++) {
      const n = document.createElement('span');
      n.textContent = 'x';
      host.appendChild(n);
      const t0 = performance.now();
      n.offsetHeight;
      t.push(performance.now() - t0);
      n.remove();
    }
    return median(t);
  };

  // The ceiling: invalidate at the root so the whole document must be
  // re-resolved. This is what a theme switch costs.
  const fullRecalc = () => {
    const t = [];
    const root = document.documentElement;
    for (let i = 0; i < 9; i++) {
      root.style.setProperty('--style-audit-probe', String(i));
      const t0 = performance.now();
      document.body.offsetHeight;
      t.push(performance.now() - t0);
    }
    root.style.removeProperty('--style-audit-probe');
    return median(t);
  };

  let selectors = 0, rules = 0;
  for (const sheet of document.styleSheets) {
    let list;
    try { list = sheet.cssRules; } catch (e) { continue; }
    const walk = (l) => {
      for (const r of l) {
        rules++;
        if (r.selectorText) selectors += r.selectorText.split(',').length;
        if (r.cssRules) walk(r.cssRules);
      }
    };
    walk(list);
  }

  const main = document.querySelector('main');
  return {
    // Reported so a run that silently measured the wrong container cannot
    // be read as a fast page. `<main>` is the scope the heavy selectors are
    // rooted at; without it the number means nothing.
    found_main: !!main,
    mutation_ms: mutationCost(main),
    mutation_outside_main_ms: mutationCost(document.body),
    full_recalc_ms: fullRecalc(),
    selectors,
    rules,
    sheets: document.styleSheets.length,
    elements: document.getElementsByTagName('*').length,
  };
}
"""


def refuse(message: str) -> int:
    print(f"\nREFUSING: {message}")
    print("  Nothing was measured. That is not the same as a clean result.")
    return 2


def _account():
    User = get_user_model()
    for email in ("admin@edify.org", "cd@edify.org", "cceo1@edify.org"):
        user = User.objects.filter(email=email, deleted_at__isnull=True).first()
        if user:
            return user
    return None


def _session_key(user) -> str:
    session = SessionStore()
    session["_auth_user_id"] = str(user.pk)
    # The project authenticates through a lockout-enforcing backend; naming
    # ModelBackend here silently redirects every page to /login and the audit
    # then measures the login screen.
    session["_auth_user_backend"] = settings.AUTHENTICATION_BACKENDS[0]
    session["_auth_user_hash"] = user.get_session_auth_hash()
    session.create()
    return session.session_key


def _load_baseline() -> dict:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text(encoding="utf-8")).get("pages", {})


def _write_baseline(measured: dict) -> None:
    BASELINE.write_text(
        json.dumps(
            {
                "_comment": (
                    "FREEZE-01. Cost in milliseconds of appending ONE element "
                    "inside <main> and reading its geometry, which flushes "
                    "pending style. A RATCHET: these may go down and never up. "
                    "Budget is 16ms, one frame — a page over it freezes for "
                    "(steps x cost) whenever a component mutates in a loop. "
                    "Regenerate with STYLE_WRITE_BASELINE=1 "
                    "scripts/style_recalc_audit.py only after making a page "
                    "faster, never to absorb a page that got slower."
                ),
                "budget_ms": BUDGET_MS,
                "pages": {k: measured[k] for k in sorted(measured)},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if not pathlib.Path(CHROMIUM).exists():
        return refuse(f"no Chromium at {CHROMIUM}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return refuse("playwright is not installed")

    user = _account()
    if not user:
        return refuse("no account to sign in as — is the database seeded?")
    key = _session_key(user)

    pages = tuple(
        p.strip()
        for p in os.environ.get("STYLE_PAGES", ",".join(DEFAULT_PAGES)).split(",")
        if p.strip()
    )
    writing = os.environ.get("STYLE_WRITE_BASELINE") == "1"
    baseline = _load_baseline()

    server = LiveServerThread("127.0.0.1", StaticFilesHandler, connections_override={})
    server.daemon = True
    measured: dict[str, float] = {}
    detail: dict[str, dict] = {}

    with modify_settings(ALLOWED_HOSTS={"append": "127.0.0.1"}):
        server.start()
        server.is_ready.wait(30)
        if server.error:
            return refuse(f"could not start a live server: {server.error}")
        base = f"http://127.0.0.1:{server.port}"

        print(f"\nStyle recalculation audit — {len(pages)} pages")
        print(f"Signed in as {user.email}")
        print(f"Budget: {BUDGET_MS:.0f}ms per mutation (one frame at 60Hz)\n")

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_cookies(
                [
                    {
                        "name": "sessionid",
                        "value": key,
                        "domain": "127.0.0.1",
                        "path": "/",
                    }
                ]
            )
            page = context.new_page()
            print(
                f"  {'page':<16}{'elements':>10}{'selectors':>11}"
                f"{'mutation':>11}{'outside':>10}{'full':>10}"
            )
            print("  " + "-" * 68)
            for path in pages:
                page.goto(base + path, wait_until="load", timeout=180000)
                page.wait_for_timeout(2500)
                landed = page.evaluate("location.pathname")
                if landed != path:
                    browser.close()
                    return refuse(
                        f"{path} redirected to {landed} — the audit would have "
                        f"measured the wrong page and called it fast"
                    )
                r = page.evaluate(MEASURE)
                if not r["found_main"] or r["mutation_ms"] is None:
                    browser.close()
                    return refuse(
                        f"{path} has no <main> — the number would not be the "
                        f"one this audit is about"
                    )
                measured[path] = r["mutation_ms"]
                detail[path] = r
                print(
                    f"  {path:<16}{r['elements']:>10,}{r['selectors']:>11,}"
                    f"{r['mutation_ms']:>10.2f}ms{r['mutation_outside_main_ms']:>9.2f}ms"
                    f"{r['full_recalc_ms']:>9.2f}ms"
                )
            browser.close()

    if writing:
        _write_baseline(measured)
        print(f"\nWrote {BASELINE.relative_to(REPO)}.")
        print("Check the numbers are the ones you meant before committing them.")
        return 0

    failures: list[str] = []
    over_budget: list[str] = []
    print("\n  against the recorded baseline:")
    for path in pages:
        got = measured[path]
        was = baseline.get(path)
        if was is None:
            failures.append(f"{path}: no baseline entry — nothing is gating it")
            print(f"  {path:<16}{got:>10.2f}ms   NO BASELINE")
            continue
        limit = was * TOLERANCE
        verdict = "ok" if got <= limit else "WORSE"
        if got > limit:
            failures.append(
                f"{path}: {got:.2f}ms against a baseline of {was:.2f}ms "
                f"(limit {limit:.2f}ms)"
            )
        if got > BUDGET_MS:
            over_budget.append(f"{path}: {got:.2f}ms")
        print(f"  {path:<16}{got:>10.2f}ms   was {was:>8.2f}ms   {verdict}")

    if over_budget:
        print(f"\n  OVER BUDGET ({BUDGET_MS:.0f}ms) — FREEZE-01 is open on:")
        for line in over_budget:
            print(f"    {line}")
        print(
            "\n  On these pages one DOM mutation inside <main> costs more than a\n"
            "  frame. A component that mutates and measures in a loop — every\n"
            "  chart render does — multiplies that into a frozen tab. This is\n"
            "  not a slow page; it is an unresponsive one."
        )

    if failures:
        print("\n  FAILED:")
        for line in failures:
            print(f"    {line}")
        return 1

    print("\n  No page regressed against its baseline.")
    if over_budget:
        print("  But FREEZE-01 remains open: see OVER BUDGET above.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
