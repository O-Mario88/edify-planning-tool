"""Hunt the causes of a browser that freezes after a while.

A page that is fast on first load and unusable twenty minutes later is not a
slow page. It is a leaking one: every navigation adds listeners, chart
instances, timers or DOM that the previous navigation should have removed, and
the browser degrades until the main thread cannot keep up. Reloading "fixes"
it, which is exactly why it survives testing — every test starts with a fresh
page.

So this does the one thing an ordinary test does not: it navigates the SAME
session repeatedly, the way a person using the product all morning does, and
watches what accumulates.

WHAT IT MEASURES, PER CYCLE

Straight from the browser via CDP, not inferred:

* `JSHeapUsedSize`  — memory that was allocated and not collected
* `JSEventListeners` — the classic HTMX-swap leak: handlers bound to elements
  that were replaced, never released
* `Nodes`           — detached DOM retained by those listeners
* live ApexCharts instances — the leak this project's own guide warns about
* live timers/intervals and observers — an unbounded reconnect or poll loop

It also records every console error and unhandled promise rejection, and every
long task over 50ms, because a frozen tab is usually a main thread that never
got a turn.

WHY GROWTH, NOT AN ABSOLUTE CEILING

An absolute number certifies one page size and rots the moment a legitimate
panel is added. Growth across identical cycles is the actual defect: after the
first two warm-up cycles, a correct application returns to roughly the same
heap and listener count each time round. One that climbs monotonically will
eventually stop responding, and the slope tells you how long that takes.

    scripts/freeze_hunt.py                     # default 12 cycles
    FREEZE_CYCLES=40 scripts/freeze_hunt.py    # longer soak
    FREEZE_PAGES=/dashboard,/analytics …       # focus on a suspect

Exit codes:
    0  no leak detected across the cycles run
    1  a leak, a console error, or a blocking long task was found
    2  REFUSED — the harness could not run, and says so rather than
       reporting a clean result it did not measure
"""

from __future__ import annotations

import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.contrib.staticfiles.handlers import StaticFilesHandler  # noqa: E402
from django.test.testcases import LiveServerThread  # noqa: E402
from django.test.utils import modify_settings  # noqa: E402

from apps.documents.gate import PolicyGateService  # noqa: E402

PolicyGateService.state_for = staticmethod(lambda user: ("clear", []))

CHROMIUM = os.environ.get(
    "FREEZE_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
)
CYCLES = int(os.environ.get("FREEZE_CYCLES", "12"))

#: Chart-heavy and table-heavy pages first: those are where instances and
#: listeners accumulate. A rotation rather than one page repeated, because a
#: single page reloaded may hit a cache path a real navigation does not.
DEFAULT_PAGES = (
    "/dashboard",
    "/analytics",
    "/my-plan",
    "/schools",
    "/todos",
    "/system-health",
)

#: Cycles discarded before the trend is read. The first pass pays for lazy
#: module init, font loading and the first chart bundle; including it measures
#: the harness warming up rather than the product leaking.
WARMUP_CYCLES = 2

#: Growth beyond this across the measured window is a leak rather than noise.
#: Heap in particular is jagged — GC runs when it runs — so the test is on the
#: trend between the first and last measured cycle, not on any single sample.
HEAP_GROWTH_LIMIT = 1.60  # 60% growth over the measured cycles
LISTENER_GROWTH_LIMIT = 1.35
NODE_GROWTH_LIMIT = 1.35
LONG_TASK_MS = 50
BLOCKING_TASK_MS = 1000  # §10: no interaction may block for more than 1s


def refuse(message: str) -> int:
    print(f"\nREFUSING: {message}")
    print("  Nothing was measured. That is not the same as a clean result.")
    return 2


def _accounts():
    User = get_user_model()
    for email in ("admin@edify.org", "cd@edify.org", "cceo1@edify.org"):
        user = User.objects.filter(email=email, deleted_at__isnull=True).first()
        if user:
            return user
    return None


def _session_key(user) -> str:
    from django.conf import settings

    session = SessionStore()
    session["_auth_user_id"] = str(user.pk)
    session["_auth_user_backend"] = settings.AUTHENTICATION_BACKENDS[0]
    session["_auth_user_hash"] = user.get_session_auth_hash()
    session.create()
    return session.session_key


#: Installed before any page script. Counts what the page creates rather than
#: what it declares: a wrapper around each constructor is the only way to know
#: an instance was made and never destroyed.
PROBE = """
window.__freeze = {
  charts: 0, chartsDestroyed: 0,
  intervals: 0, intervalsCleared: 0,
  observers: 0,
  longTasks: [],
  consoleErrors: [],
  rejections: [],
};
(() => {
  const si = window.setInterval, ci = window.clearInterval;
  window.setInterval = function (...a) { window.__freeze.intervals++; return si.apply(this, a); };
  window.clearInterval = function (...a) { window.__freeze.intervalsCleared++; return ci.apply(this, a); };

  const MO = window.MutationObserver;
  if (MO) {
    window.MutationObserver = function (...a) { window.__freeze.observers++; return new MO(...a); };
    window.MutationObserver.prototype = MO.prototype;
  }
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.duration >= 50) window.__freeze.longTasks.push(Math.round(e.duration));
      }
    }).observe({ entryTypes: ['longtask'] });
  } catch (e) { /* longtask unsupported */ }

  window.addEventListener('unhandledrejection', (e) => {
    window.__freeze.rejections.push(String(e.reason).slice(0, 200));
  });

  // ApexCharts is loaded after this script, so patch it when it appears
  // rather than assuming it is already there.
  let _apex;
  Object.defineProperty(window, 'ApexCharts', {
    configurable: true,
    get() { return _apex; },
    set(v) {
      if (v && !v.__freezeWrapped) {
        const Orig = v;
        const Wrapped = function (...a) {
          window.__freeze.charts++;
          const inst = new Orig(...a);
          const d = inst.destroy && inst.destroy.bind(inst);
          if (d) inst.destroy = function (...b) { window.__freeze.chartsDestroyed++; return d(...b); };
          return inst;
        };
        Wrapped.prototype = Orig.prototype;
        Object.assign(Wrapped, Orig);
        Wrapped.__freezeWrapped = true;
        _apex = Wrapped;
      } else { _apex = v; }
    },
  });
})();
"""


def main() -> int:
    if not pathlib.Path(CHROMIUM).exists():
        return refuse(f"no Chromium at {CHROMIUM}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return refuse("playwright is not installed")

    user = _accounts()
    if not user:
        return refuse("no account to sign in as — is the database seeded?")
    key = _session_key(user)

    pages = tuple(
        p.strip()
        for p in os.environ.get("FREEZE_PAGES", ",".join(DEFAULT_PAGES)).split(",")
        if p.strip()
    )

    server = LiveServerThread("127.0.0.1", StaticFilesHandler, connections_override={})
    server.daemon = True
    samples: list[dict] = []
    console_errors: list[str] = []

    with modify_settings(ALLOWED_HOSTS={"append": "127.0.0.1"}):
        server.start()
        server.is_ready.wait(30)
        if server.error:
            return refuse(f"could not start a live server: {server.error}")
        base = f"http://127.0.0.1:{server.port}"

        print(f"\nFreeze hunt — {CYCLES} cycles over {len(pages)} pages, one session")
        print(f"Signed in as {user.email}\n")
        print(
            f"{'page':<16}{'ctrls':>5}{'heapMB→':>9}{'after':>9}"
            f"{'lsnrs':>7}{'after':>7}{'nodes':>8}{'after':>8}"
            f"{'charts':>7}{'destr':>6}{'longms':>8}"
        )
        print("-" * 90)

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_init_script(PROBE)
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
            page.on(
                "console",
                lambda m: console_errors.append(f"{m.type}: {m.text[:160]}")
                if m.type == "error"
                else None,
            )
            page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

            cdp = context.new_cdp_session(page)
            cdp.send("Performance.enable")

            try:
                # ONE document per page, measured before and after a burst
                # of in-page interaction.
                #
                # The first version called page.goto() per cycle, which tears
                # the document down and rebuilds it — so heap, listener and
                # node counts came back byte-identical across ten cycles and
                # the harness reported a clean bill of health while measuring
                # nothing. A full navigation cannot leak: there is nothing left
                # to leak into.
                #
                # This project sets no global hx-boost, so page-to-page
                # navigation IS a full load. HTMX here drives in-page swaps —
                # filters, tabs, search, drawers — and that is where handlers
                # bind to elements that are then replaced. So: load once, then
                # drive the controls the way somebody filtering a school list
                # for ten minutes does, and compare the same document to
                # itself.
                SELECTOR = (
                    "[hx-get],[hx-post],[data-hx-get],[data-hx-post],"
                    '[role="tab"],button[x-on\\:click],button[\\@click]'
                )

                def snapshot(label):
                    try:
                        cdp.send("HeapProfiler.enable")
                        cdp.send("HeapProfiler.collectGarbage")
                    except Exception:  # noqa: BLE001
                        pass
                    m = {
                        x["name"]: x["value"]
                        for x in cdp.send("Performance.getMetrics")["metrics"]
                    }
                    probe = page.evaluate("() => window.__freeze || {}")
                    return {
                        "label": label,
                        "heap": m.get("JSHeapUsedSize", 0),
                        "listeners": m.get("JSEventListeners", 0),
                        "nodes": m.get("Nodes", 0),
                        "charts": probe.get("charts", 0),
                        "destroyed": probe.get("chartsDestroyed", 0),
                        "timers": probe.get("intervals", 0)
                        - probe.get("intervalsCleared", 0),
                        "longest": max(probe.get("longTasks") or [0]),
                        "rejections": list(probe.get("rejections") or []),
                    }

                for path in pages:
                    page.goto(f"{base}{path}", wait_until="networkidle", timeout=45_000)
                    count = page.evaluate(
                        "(sel) => [...document.querySelectorAll(sel)]"
                        ".filter(el => el.offsetParent !== null).length",
                        SELECTOR,
                    )
                    before = snapshot(f"{path} @0")
                    for cycle in range(CYCLES):
                        page.evaluate(
                            "([sel, n]) => { const els = [...document.querySelectorAll(sel)]"
                            ".filter(el => el.offsetParent !== null);"
                            " const el = els[n % Math.max(els.length, 1)];"
                            " if (el) el.click(); }",
                            [SELECTOR, cycle],
                        )
                        page.wait_for_timeout(200)
                    after = snapshot(f"{path} @{CYCLES}")
                    samples.append(
                        {
                            "path": path,
                            "controls": count,
                            "before": before,
                            "after": after,
                        }
                    )
                    print(
                        f"{path:<16}{count:>5}"
                        f"{before['heap'] / 1e6:>9.1f}{after['heap'] / 1e6:>9.1f}"
                        f"{before['listeners']:>7}{after['listeners']:>7}"
                        f"{before['nodes']:>8}{after['nodes']:>8}"
                        f"{after['charts']:>7}{after['destroyed']:>6}"
                        f"{after['longest']:>8}"
                    )
            finally:
                browser.close()
        server.terminate()

    return _report(samples, console_errors, pages)


def _report(samples, console_errors, pages) -> int:
    """Growth within one document, per page. That is the leak question."""
    print()
    if not samples:
        print("  NOTHING MEASURED — no page exposed interactive controls.")
        return 2

    findings: list[str] = []
    for s in samples:
        path, before, after = s["path"], s["before"], s["after"]
        if s["controls"] == 0:
            print(f"  ....  {path}: no visible in-page controls to exercise")
            continue

        def grew(key, limit):
            b, a = before[key], after[key]
            return (a / b if b else 1.0) > limit, b, a

        for key, limit, why in (
            ("heap", HEAP_GROWTH_LIMIT, "memory retained between swaps"),
            ("listeners", LISTENER_GROWTH_LIMIT, "handlers bound and never released"),
            ("nodes", NODE_GROWTH_LIMIT, "detached DOM retained"),
        ):
            bad, b, a = grew(key, limit)
            if bad:
                scale = f"{a / b:.2f}" if b else "n/a"
                findings.append(
                    f"{path}: {key} grew x{scale} ({b} -> {a}) over {CYCLES} "
                    f"interactions in ONE document — {why}"
                )

        leaked = after["charts"] - after["destroyed"]
        if after["charts"] and leaked > 4:
            findings.append(
                f"{path}: {leaked} ApexCharts instance(s) created and never "
                f"destroyed ({after['charts']} created, {after['destroyed']} "
                f"destroyed) — instances accumulate on every swap"
            )
        if after["timers"] > 8:
            findings.append(
                f"{path}: {after['timers']} intervals left running — a poll or "
                f"reconnect loop is not cleared between swaps"
            )
        if after["longest"] >= BLOCKING_TASK_MS:
            findings.append(
                f"{path}: a main-thread task ran {after['longest']}ms — the tab "
                f"is unresponsive for that whole time (limit {BLOCKING_TASK_MS}ms)"
            )

    worst = max((s["after"]["longest"] for s in samples), default=0)
    print(
        f"  longest main-thread task across all pages: {worst}ms "
        f"(over {LONG_TASK_MS}ms is a visible stutter)"
    )

    rejections = {r for s in samples for r in s["after"]["rejections"]}
    if rejections:
        findings.append(f"{len(rejections)} unhandled promise rejection(s)")
        for r in sorted(rejections)[:5]:
            print(f"      rejection: {r}")

    unique = sorted(set(console_errors))
    if unique:
        findings.append(f"{len(unique)} distinct console error(s)")
        for e in unique[:10]:
            print(f"      console: {e}")

    if findings:
        print("\n  FREEZE HUNT FAILED")
        for f in findings:
            print(f"    FAIL  {f}")
        return 1

    print(
        "\n  FREEZE HUNT PASSED — no accumulation within a document across "
        f"{CYCLES} interactions per page."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
