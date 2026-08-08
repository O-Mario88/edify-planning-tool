#!/usr/bin/env python3
"""Bounded authenticated HTTP load probe for an isolated Edify deployment.

This deliberately exercises read-only journeys. It creates one database-backed
session for an existing test account, then drives real HTTP through the ASGI
server with a fixed concurrency until the requested duration expires.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import pathlib
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402

DEFAULT_PATHS = (
    "/dashboard",
    "/my-plan",
    "/schools",
    "/todos",
    "/notifications",
    "/settings",
    "/analytics",
    "/system-health",
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Expose redirects as non-200 results instead of timing the destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def percentile(samples: list[float], pct: float) -> float:
    ordered = sorted(samples)
    if not ordered:
        return 0.0
    return ordered[min(round((len(ordered) - 1) * pct / 100), len(ordered) - 1)]


def authenticated_cookie(email: str) -> str:
    user = get_user_model().objects.filter(email=email, deleted_at__isnull=True).first()
    if user is None:
        raise SystemExit(f"No active local test account found for {email!r}")
    client = Client()
    client.force_login(user)
    session = client.cookies.get("sessionid")
    if session is None:
        raise SystemExit("Django did not issue a session cookie")
    return f"sessionid={session.value}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--email", default="domario@edify.org")
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--concurrency", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--p95-budget-ms", type=float, default=1500)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS))
    args = parser.parse_args()
    if args.duration <= 0 or args.concurrency <= 0 or not args.paths:
        parser.error("duration, concurrency and at least one path are required")

    cookie = authenticated_cookie(args.email)
    deadline = time.monotonic() + args.duration
    next_path = 0
    path_lock = threading.Lock()
    latencies: dict[str, list[float]] = defaultdict(list)
    statuses: Counter[int | str] = Counter()
    result_lock = threading.Lock()
    opener = urllib.request.build_opener(NoRedirect)

    def worker() -> None:
        nonlocal next_path
        while time.monotonic() < deadline:
            with path_lock:
                path = args.paths[next_path % len(args.paths)]
                next_path += 1
            request = urllib.request.Request(
                f"{args.base_url.rstrip('/')}{path}",
                headers={"Cookie": cookie, "User-Agent": "edify-staging-probe/1"},
            )
            started = time.perf_counter()
            status: int | str
            try:
                with opener.open(request, timeout=args.timeout) as response:
                    response.read()
                    status = response.status
            except urllib.error.HTTPError as exc:
                status = exc.code
            except Exception as exc:  # noqa: BLE001 - every transport failure is evidence
                status = type(exc).__name__
            elapsed_ms = (time.perf_counter() - started) * 1000
            with result_lock:
                statuses[status] += 1
                latencies[path].append(elapsed_ms)

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.concurrency
    ) as executor:
        futures = [executor.submit(worker) for _ in range(args.concurrency)]
        for future in futures:
            future.result()
    elapsed = time.monotonic() - started

    total = sum(statuses.values())
    successes = statuses[200]
    errors = total - successes
    error_rate = errors / total if total else 1.0
    all_samples = [sample for values in latencies.values() for sample in values]

    print(
        f"duration={elapsed:.1f}s concurrency={args.concurrency} "
        f"requests={total} throughput={total / elapsed:.2f}rps"
    )
    print(
        f"success={successes} errors={errors} error_rate={error_rate:.3%} "
        f"statuses={dict(statuses)}"
    )
    print(f"{'path':<22}{'n':>7}{'p50':>10}{'p95':>10}{'p99':>10}{'max':>10}")
    for path in args.paths:
        values = latencies[path]
        print(
            f"{path:<22}{len(values):>7}"
            f"{percentile(values, 50):>9.0f}m"
            f"{percentile(values, 95):>9.0f}m"
            f"{percentile(values, 99):>9.0f}m"
            f"{max(values, default=0):>9.0f}m"
        )
    print(
        f"overall p50={statistics.median(all_samples):.0f}ms "
        f"p95={percentile(all_samples, 95):.0f}ms "
        f"p99={percentile(all_samples, 99):.0f}ms"
    )

    slow_paths = [
        path
        for path, values in latencies.items()
        if percentile(values, 95) > args.p95_budget_ms
    ]
    if error_rate > args.max_error_rate or slow_paths:
        print(
            "LOAD PROBE FAILED: "
            f"error budget {'breached' if error_rate > args.max_error_rate else 'met'}; "
            f"slow paths={slow_paths}"
        )
        return 1
    print("LOAD PROBE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
