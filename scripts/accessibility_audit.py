"""Run axe-core against the real pages, signed in, in a real browser.

§4 asks for accessibility tooling. The ledger recorded it as "Not configured in
this repository", which was accurate: there was no browser harness, no axe, and
no measurement of any kind. Every accessibility claim in the documentation was
a claim about intent.

WHAT THIS DOES DIFFERENTLY FROM THE OBVIOUS VERSION

**It signs in, and proves it.** The obvious version points a browser at eight
URLs and scores what comes back. An anonymous browser is redirected to
`/login`, which is a small, clean, largely accessible page — so the obvious
version reports the login form eight times and calls the product accessible.
That is not hypothetical: `scripts/restore_smoke.py` shipped with exactly that
defect and certified eight renderings of the login form as "8 pages served".
Here every page asserts it LANDED on the path it asked for, and the run fails
if it did not.

**It proves axe actually ran.** A scan that silently failed to inject axe, or
injected it and evaluated nothing, reports zero violations — which is the same
output as a perfect page. So each page asserts a floor on the rules evaluated
and on the DOM it evaluated them against. Zero violations on eleven rules over
four nodes is not a pass; it is a scan that did not happen.

**It is a ratchet, not a pass/fail on zero.** A real application has
violations, and a gate that demands zero on day one gets switched off in week
one. The count is measured, written down, and may only go down. New violations
fail on the day they are introduced, which is when they are cheap.

    scripts/accessibility_audit.py              # measure and gate
    A11Y_WRITE_BASELINE=1 scripts/…            # record a new (lower) ceiling
    A11Y_PAGES=/dashboard,/schools scripts/…   # a subset, while fixing one

Exit codes:
    0  PASSED       no new serious or critical violations
    1  FAILED       new violations, or a page that could not be scanned
    2  REFUSED      the harness could not run, and says so rather than
                    reporting a clean sheet it did not measure
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

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.contrib.staticfiles.handlers import StaticFilesHandler  # noqa: E402
from django.test.testcases import LiveServerThread  # noqa: E402
from django.test.utils import modify_settings  # noqa: E402

from apps.documents.gate import PolicyGateService  # noqa: E402

# The mandatory-policy gate redirects an un-acknowledged user into the
# Agreement Center. Left alone, this harness would scan that one page eight
# times over -- the same shape of mistake as scanning the login form, and
# indistinguishable from success in the output. Neutralised rather than worked
# around by writing acknowledgements: the gate decides whether a request
# reaches the view, and has no bearing on the view's markup.
PolicyGateService.state_for = staticmethod(lambda user: ("clear", []))

AXE = REPO / "node_modules" / "axe-core" / "axe.min.js"
BASELINE = REPO / "docs" / "accessibility-baseline.json"

CHROMIUM = os.environ.get(
    "A11Y_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
)

#: The surfaces people spend their day on. Same list the latency budget and the
#: restore smoke test use, so the three gates talk about the same product.
DEFAULT_PAGES = (
    "/dashboard",
    "/my-plan",
    "/schools",
    "/todos",
    "/analytics",
    "/notifications",
    "/settings",
    "/system-health",
)

#: Every theme a user can actually select, from templates/base.html:
#: system | light | blue | dark. "system" resolves to light or dark by
#: prefers-color-scheme and so adds no palette of its own.
#:
#: Scanning only the default was scanning one of three palettes. Colour
#: contrast is most of what axe checks and it is entirely a property of the
#: palette, so a clean light theme says nothing whatsoever about the other two
#: — and DARK-01 established that this project's dark theme has carried real
#: contrast failures before.
THEMES = ("light", "dark", "blue")

#: Only these two block. `minor` and `moderate` are recorded and reported, so
#: the trend is visible, but they do not fail a release on their own.
BLOCKING = ("critical", "serious")

#: Floors that distinguish "this page is clean" from "this scan did nothing".
#: A login form evaluates far fewer rules over far fewer nodes than any real
#: application page, so these also catch a signed-out scan that slipped past
#: the landing-path assertion.
MIN_RULES_EVALUATED = 40
MIN_NODES_IN_PAGE = 150


def refuse(message: str) -> int:
    print(f"\nREFUSING: {message}")
    print("  The harness did not run. That is not the same as a clean result,")
    print("  and it will not be reported as one.")
    return 2


def _pages() -> tuple[str, ...]:
    override = os.environ.get("A11Y_PAGES", "").strip()
    if override:
        return tuple(p.strip() for p in override.split(",") if p.strip())
    return DEFAULT_PAGES


def _themes() -> tuple[str, ...]:
    override = os.environ.get("A11Y_THEMES", "").strip()
    if override:
        return tuple(t.strip() for t in override.split(",") if t.strip())
    return THEMES


def _load_baseline() -> dict:
    if not BASELINE.exists():
        return {}
    return json.loads(BASELINE.read_text(encoding="utf-8")).get("pages", {})


def _accounts():
    """One account per role, so a page nobody can reach is reported as such."""
    User = get_user_model()
    emails = (
        "admin@edify.org",
        "cd@edify.org",
        "cceo1@edify.org",
        "pl1@edify.org",
        "accountant@edify.org",
    )
    found = []
    for email in emails:
        user = User.objects.filter(email=email, deleted_at__isnull=True).first()
        if user:
            found.append(user)
    return found


def _session_cookie(user) -> str:
    """A real server-side session, handed to the browser as a real cookie.

    The backend is read from settings rather than hard-coded. This project
    authenticates through `LockoutEnforcingModelBackend`, and a session naming
    a backend that is not in AUTHENTICATION_BACKENDS is rejected by
    `django.contrib.auth.get_user` — silently, as an anonymous request. Written
    the obvious way with `ModelBackend`, every page in this harness redirected
    to `/login` and the run would have scored the login form eight times if the
    landing-path assertion had not caught it.
    """
    from django.conf import settings

    session = SessionStore()
    session["_auth_user_id"] = str(user.pk)
    session["_auth_user_backend"] = settings.AUTHENTICATION_BACKENDS[0]
    session["_auth_user_hash"] = user.get_session_auth_hash()
    session.create()
    return session.session_key


def main() -> int:
    if not AXE.exists():
        return refuse(f"axe-core is not installed at {AXE}. Run `npm ci`.")
    if not pathlib.Path(CHROMIUM).exists():
        return refuse(f"no Chromium at {CHROMIUM}. Set A11Y_CHROMIUM.")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return refuse("playwright is not installed in this environment.")

    accounts = _accounts()
    if not accounts:
        return refuse("no account exists to sign in as — is the database seeded?")

    axe_source = AXE.read_text(encoding="utf-8")
    baseline = _load_baseline()
    pages = _pages()

    # StaticFilesHandler, so the browser gets the real stylesheet. Colour
    # contrast is most of what axe checks, and it is a property of the CSS: a
    # run with the stylesheet 404ing scores unstyled black-on-white, which
    # passes contrast everywhere and measures nothing about the product.
    server = LiveServerThread("127.0.0.1", StaticFilesHandler, connections_override={})
    server.daemon = True
    with modify_settings(ALLOWED_HOSTS={"append": "127.0.0.1"}):
        server.start()
        server.is_ready.wait(30)
        if server.error:
            return refuse(f"could not start a live server: {server.error}")
        base = f"http://127.0.0.1:{server.port}"

        print(f"\nAccessibility audit — axe-core against {base}")
        print(f"Signed in as one of: {', '.join(a.email for a in accounts)}\n")
        print(f"Themes: {', '.join(_themes())}\n")
        print(
            f"{'page':<20}{'role':<16}{'crit':>6}{'serious':>9}"
            f"{'mod':>6}{'minor':>7}{'rules':>7}{'nodes':>8}  verdict"
        )
        print("-" * 92)

        failures: list[str] = []
        measured: dict[str, int] = {}

        # Sessions are created HERE, before Playwright starts. Its sync API
        # runs the caller inside a greenlet that Django treats as an async
        # context, so any ORM call from inside the browser block raises
        # SynchronousOnlyOperation. Doing the database work first is simpler
        # and more honest than wrapping each query in sync_to_async.
        signed_in = [(account, _session_cookie(account)) for account in accounts]

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=CHROMIUM, args=["--no-sandbox"]
                )
                try:
                    for theme in _themes():
                        print(f"\n  -- {theme} theme --")
                        for path in pages:
                            result = _scan_page(
                                browser,
                                base,
                                path,
                                signed_in,
                                axe_source,
                                failures,
                                theme,
                            )
                            if result is not None:
                                measured[f"{theme}:{path}"] = result
                finally:
                    browser.close()
        finally:
            server.terminate()

    return _report(measured, baseline, failures, pages)


def _scan_page(
    browser, base, path, signed_in, axe_source, failures, theme="light"
) -> int | None:
    """Scan one page as the first account that can actually reach it."""
    last_detail = "no account was served this page"
    for account, session_key in signed_in:
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        try:
            # base.html reads localStorage['edify_theme'] in a blocking script
            # in <head>, before first paint. An init script runs before any
            # page script, so the palette is already chosen by the time
            # anything renders — no flash, and no race with axe.
            context.add_init_script(
                f"try {{ localStorage.setItem('edify_theme', '{theme}'); }} "
                f"catch (e) {{}}"
            )
            context.add_cookies(
                [
                    {
                        "name": "sessionid",
                        "value": session_key,
                        "domain": "127.0.0.1",
                        "path": "/",
                    }
                ]
            )
            page = context.new_page()
            page.goto(f"{base}{path}", wait_until="networkidle", timeout=30_000)

            # The assertion that stops this scanning the login form eight times.
            landed = page.url[len(base) :].split("?")[0]
            if landed != path:
                last_detail = f"redirected to {landed}"
                if landed.startswith("/login"):
                    last_detail += " — SIGNED OUT"
                continue

            applied = page.evaluate("document.documentElement.dataset.theme")
            if applied != theme:
                # Without this the run scans the default palette three times
                # and reports three clean themes, which is the same shape of
                # lie as scanning the login form eight times.
                failures.append(
                    f"{theme}:{path}: asked for the {theme} theme, page "
                    f"rendered {applied!r} — the palette under test was not "
                    f"the palette measured"
                )
                context.close()
                return None

            node_count = page.evaluate("document.querySelectorAll('*').length")
            page.add_script_tag(content=axe_source)
            # No `resultTypes` filter. Passing resultTypes: ['violations']
            # makes axe TRUNCATE the other three arrays, so the rule count
            # computed from them undercounts — this script read 28 to 38 rules
            # on pages where the real figure is far higher, and reported every
            # page as "scan too thin". The floor exists to catch a scan that
            # did not happen; it has to be fed the real number or it is just a
            # second way to be wrong.
            report = page.evaluate(
                "async () => await axe.run(document, "
                "{runOnly: {type: 'tag', values: "
                "['wcag2a','wcag2aa','wcag21a','wcag21aa']}})"
            )
        finally:
            context.close()

        counts = {level: 0 for level in ("critical", "serious", "moderate", "minor")}
        for violation in report["violations"]:
            impact = violation.get("impact") or "minor"
            if impact in counts:
                counts[impact] += len(violation["nodes"])
        # Every rule axe reached a verdict on, of any kind. `inapplicable` is
        # included deliberately: a rule that found nothing to check still ran,
        # and excluding it would make a clean page look like a thin scan.
        rules = sum(
            len(report.get(bucket, ()))
            for bucket in ("violations", "passes", "incomplete", "inapplicable")
        )
        # resultTypes limits the detail returned, not the rules run; axe still
        # reports which rules did not apply, and that is the honest count of
        # what was evaluated.
        blocking = sum(counts[level] for level in BLOCKING)

        thin = []
        if rules < MIN_RULES_EVALUATED:
            thin.append(f"only {rules} rules evaluated")
        if node_count < MIN_NODES_IN_PAGE:
            thin.append(f"only {node_count} DOM nodes")
        verdict = "scanned"
        if thin:
            verdict = "SCAN TOO THIN: " + ", ".join(thin)
            failures.append(f"{path}: {verdict}")

        print(
            f"{path:<20}{(account.active_role or '?')[:14]:<16}"
            f"{counts['critical']:>6}{counts['serious']:>9}"
            f"{counts['moderate']:>6}{counts['minor']:>7}"
            f"{rules:>7}{node_count:>8}  {verdict}"
        )
        _print_worst(report["violations"])
        return blocking

    print(
        f"{path:<20}{'(unreachable)':<16}{'':>6}{'':>9}{'':>6}{'':>7}{'':>7}{'':>8}  {last_detail}"
    )
    failures.append(f"{path}: not scanned — {last_detail}")
    return None


def _print_worst(violations) -> None:
    blocking = [v for v in violations if (v.get("impact") or "") in BLOCKING]
    for violation in sorted(blocking, key=lambda v: -len(v["nodes"]))[:3]:
        print(
            f"      {violation['impact']:<9}{violation['id']:<32}"
            f"{len(violation['nodes'])} node(s)  {violation['help'][:44]}"
        )


def _report(measured, baseline, failures, pages) -> int:
    print()
    if os.environ.get("A11Y_WRITE_BASELINE") == "1":
        BASELINE.write_text(
            json.dumps(
                {
                    "_comment": (
                        "Serious + critical axe violations per page. A RATCHET: "
                        "these may go down and never up. Regenerate with "
                        "A11Y_WRITE_BASELINE=1 scripts/accessibility_audit.py "
                        "only after fixing violations, never to absorb new ones."
                    ),
                    "pages": measured,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"  wrote {BASELINE.relative_to(REPO)} — {sum(measured.values())} total")
        return 0

    regressions = []
    for path, count in sorted(measured.items()):
        allowed = baseline.get(path)
        if allowed is None:
            regressions.append(f"{path}: {count} blocking violation(s), no baseline")
        elif count > allowed:
            regressions.append(f"{path}: {count} blocking, baseline allows {allowed}")

    for line in failures + regressions:
        print(f"  FAIL  {line}")

    if failures or regressions:
        print("\n  ACCESSIBILITY AUDIT FAILED")
        return 1
    improved = [
        f"{p} {baseline[p]}->{c}" for p, c in measured.items() if c < baseline.get(p, c)
    ]
    if improved:
        print(f"  improved since the baseline: {', '.join(improved)}")
        print("  lower the baseline with A11Y_WRITE_BASELINE=1 to lock the gain in.")
    print(
        f"  ACCESSIBILITY AUDIT PASSED — {len(measured)} page(s) scanned, "
        f"{sum(measured.values())} blocking violation(s), none new."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
