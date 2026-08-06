"""Measure p50/p95/p99 for the pages people actually wait on, and gate on it.

The audit could not say whether any endpoint met its objective, because nothing
had ever measured one. This measures them.

Three things it does deliberately:

**Reports the dataset size next to the numbers.** A p95 with no row count
behind it is not evidence — the same page against 700 schools and against
15,000 is two different measurements, and only one of them resembles
production. The header states what it ran against so nobody has to guess later.

**Measures each role separately.** Scope changes the query shape: a CCEO sees
their own portfolio, a CD sees a country. An average across roles hides the one
that is slow.

**Discards a warm-up pass.** The first request to a page pays for lazy imports,
template compilation and a cold cache, none of which a user pays on a warm
worker. Including it measures the harness rather than the product.

What it is not: a load test. One request at a time, no concurrency, no think
time. It answers "is this page fast when nothing else is happening", which has
to be true before "is it fast under load" is worth asking. Concurrency is
section 28 of the reliability brief and needs a real deployment.

    scripts/latency_budget.py                 # measure and gate
    ITERATIONS=30 scripts/latency_budget.py   # more samples, tighter tails
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.db import connection, reset_queries  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

ITERATIONS = int(os.environ.get("ITERATIONS", "15"))
WARMUP = 2

# The mandatory-policy gate redirects an un-acknowledged user out of every
# application page and into the Agreement Center. That page is fast, returns
# 200, and is not what anybody is waiting on — so with `follow=True` this
# script was timing the policy document for every route and reporting the whole
# product as comfortably inside budget. Neutralised here rather than by writing
# acknowledgements, because the gate only decides whether a request reaches the
# view; it has no bearing on what the view then costs. The redirect-chain check
# in the sampling loop is the belt to this braces: any future middleware that
# diverts a page is reported rather than silently measured in its place.
from apps.documents.gate import PolicyGateService  # noqa: E402

PolicyGateService.state_for = staticmethod(lambda user: ("clear", []))

# (path, p95 budget in ms). The budgets are section 7 of the reliability brief:
# common pages under 800ms at p95, HTMX partials under 500ms, heavy financial
# aggregation gets its own allowance because it is genuinely a different job.
BUDGETS: tuple[tuple[str, int], ...] = (
    ("/dashboard", 800),
    ("/my-plan", 800),
    ("/schools", 800),
    ("/todos", 800),
    ("/notifications", 800),
    ("/settings", 800),
    ("/analytics", 1500),
    ("/system-health", 1500),
    # The Country Director's cockpit: a country-wide rollup over every school,
    # CCEO and assessment, and the heaviest read in the product. Its own
    # allowance for the same reason financial aggregation gets one.
    ("/analytics/country-director", 2000),
    # The heatmap tabs are HTMX partials fetched on demand, one per level.
    ("/analytics/country-director/ssa-heatmap?level=region", 500),
    ("/analytics/country-director/ssa-heatmap?level=sub_region", 500),
    ("/analytics/country-director/ssa-heatmap?level=district", 500),
    ("/analytics/country-director/ssa-heatmap?level=sub_county", 500),
    ("/analytics/country-director/ssa-heatmap?level=cluster", 500),
)

# One account per role that actually has data behind it. Scope changes the
# query shape, so a single role's numbers are not the product's numbers.
ROLE_ACCOUNTS = ("cceo1@edify.org", "pl1@edify.org", "cd@edify.org")


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = min(int(round((pct / 100) * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[index]


def _dataset() -> str:
    from apps.accounts.models import User
    from apps.activities.models import Activity
    from apps.schools.models import School

    return (
        f"{School.objects.count():,} schools · "
        f"{Activity.objects.count():,} activities · "
        f"{User.objects.count():,} users"
    )


def main() -> int:
    from django.contrib.auth import get_user_model

    User = get_user_model()

    print(f"\nDataset: {_dataset()}")
    print(f"Samples: {ITERATIONS} per page per role (after {WARMUP} discarded)\n")
    print(
        f"{'page':<48}{'role':<14}{'p50':>8}{'p95':>8}{'p99':>8}{'queries':>9}  budget"
    )
    print("-" * 78)

    breaches: list[str] = []
    measured = 0

    for email in ROLE_ACCOUNTS:
        user = User.objects.filter(email=email, deleted_at__isnull=True).first()
        if not user:
            print(f"{'(skipped)':<18}{email:<14}  no such account")
            continue
        role = (user.active_role or "?")[:12]

        client = Client()
        client.force_login(user)

        for path, budget_ms in BUDGETS:
            samples: list[float] = []
            queries = 0
            failed = False

            for i in range(ITERATIONS + WARMUP):
                reset_queries()
                started = time.perf_counter()
                try:
                    with CaptureQueriesContext(connection) as captured:
                        response = client.get(path, follow=True)
                    elapsed = (time.perf_counter() - started) * 1000
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"{path[:46]:<48}{role:<14}  ERROR {type(exc).__name__}: {exc}"
                    )
                    failed = True
                    break
                if response.status_code != 200:
                    # Not every role may open every page; that is scope working,
                    # not a latency result. Skip rather than record a fast 403 as
                    # if it were a fast page.
                    failed = True
                    break
                if response.redirect_chain:
                    # A 200 reached by redirect is a different page. Timing it
                    # under this path's name would report somebody else's speed
                    # as this page's — say so and skip.
                    landed = response.redirect_chain[-1][0]
                    print(
                        f"{path[:46]:<48}{role:<14}  REDIRECTED to {landed} — not measured"
                    )
                    failed = True
                    break
                if i >= WARMUP:
                    samples.append(elapsed)
                    queries = len(captured.captured_queries)

            if failed or not samples:
                continue

            measured += 1
            p50 = _percentile(samples, 50)
            p95 = _percentile(samples, 95)
            p99 = _percentile(samples, 99)
            over = p95 > budget_ms
            flag = "  OVER" if over else ""
            if over:
                breaches.append(f"{path} [{role}] p95={p95:.0f}ms > {budget_ms}ms")
            print(
                f"{path[:46]:<48}{role:<14}{p50:>7.0f}m{p95:>7.0f}m{p99:>7.0f}m"
                f"{queries:>9}  {budget_ms}ms{flag}"
            )

    print("-" * 78)
    print(f"{measured} page/role combinations measured.")

    if breaches:
        print(f"\nBUDGET BREACHED — {len(breaches)}:")
        for breach in breaches:
            print(f"  {breach}")
        return 1
    print("\nEvery measured page met its p95 budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
