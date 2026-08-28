#!/usr/bin/env python3
"""Bounded authenticated HTTP load probe for an isolated Edify deployment.

This deliberately exercises read-only journeys. It creates one database-backed
session for an existing test account, then drives real HTTP through the ASGI
server with a fixed concurrency until the requested duration expires.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import http.cookiejar
import http.client
import os
import pathlib
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


def database_cookie(email: str) -> str:
    """Create a session from the target database when run inside the app."""

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.test import Client

    user = get_user_model().objects.filter(email=email, deleted_at__isnull=True).first()
    if user is None:
        raise SystemExit(f"No active local test account found for {email!r}")
    client = Client()
    client.force_login(user)
    session = client.cookies.get("sessionid")
    if session is None:
        raise SystemExit("Django did not issue a session cookie")
    return f"sessionid={session.value}"


def remote_login_cookie(base_url: str, email: str, password: str) -> str:
    """Log in over HTTP so the generator can run outside the target estate."""

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login_url = f"{base_url.rstrip('/')}/login"
    with opener.open(login_url, timeout=20) as response:
        response.read()
    csrf = next((cookie.value for cookie in jar if cookie.name == "csrftoken"), None)
    if csrf is None:
        raise SystemExit("Login page did not issue a CSRF cookie")
    body = urllib.parse.urlencode(
        {
            "csrfmiddlewaretoken": csrf,
            "email": email,
            "password": password,
        }
    ).encode()
    request = urllib.request.Request(
        login_url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": login_url,
            "User-Agent": "edify-staging-probe/1",
        },
    )
    with opener.open(request, timeout=20) as response:
        response.read()
    session = next((cookie.value for cookie in jar if cookie.name == "sessionid"), None)
    if session is None:
        raise SystemExit("HTTP login did not issue a session cookie")
    return f"sessionid={session}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--email", default="domario@edify.org")
    parser.add_argument(
        "--password-env",
        default="EDIFY_PROBE_PASSWORD",
        help="environment variable containing a password for remote HTTP login",
    )
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--concurrency", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--p95-budget-ms", type=float, default=1500)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS))
    args = parser.parse_args()
    if args.duration <= 0 or args.concurrency <= 0 or not args.paths:
        parser.error("duration, concurrency and at least one path are required")

    password = os.environ.get(args.password_env)
    cookie = (
        remote_login_cookie(args.base_url, args.email, password)
        if password
        else database_cookie(args.email)
    )
    next_path = 0
    path_lock = threading.Lock()
    latencies: dict[str, list[float]] = defaultdict(list)
    statuses: Counter[int | str] = Counter()
    result_lock = threading.Lock()
    opener = urllib.request.build_opener(NoRedirect)
    parsed_base = urllib.parse.urlsplit(args.base_url)
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.hostname:
        parser.error("base-url must be an absolute HTTP(S) URL")
    connection_type = (
        http.client.HTTPSConnection
        if parsed_base.scheme == "https"
        else http.client.HTTPConnection
    )
    base_path = parsed_base.path.rstrip("/")

    # Match the scale contract in apps.system_health.test_load_scale: measure
    # steady-state capacity after templates, imports and read-only snapshots
    # have been populated once. Cold-cache latency is a separate deployment
    # concern and must not make every sample in a short pressure window look
    # like a capacity failure.
    for path in args.paths:
        request = urllib.request.Request(
            f"{args.base_url.rstrip('/')}{path}",
            headers={"Cookie": cookie, "User-Agent": "edify-staging-probe/1"},
        )
        try:
            with opener.open(request, timeout=max(args.timeout, 30)) as response:
                response.read()
                if response.status != 200:
                    raise SystemExit(
                        f"Warm-up failed for {path}: HTTP {response.status}"
                    )
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"Warm-up failed for {path}: HTTP {exc.code}") from exc
    print(f"warmup={len(args.paths)} paths complete")
    deadline = time.monotonic() + args.duration

    def worker() -> None:
        nonlocal next_path
        connection = connection_type(
            parsed_base.hostname,
            port=parsed_base.port,
            timeout=args.timeout,
        )
        while time.monotonic() < deadline:
            with path_lock:
                path = args.paths[next_path % len(args.paths)]
                next_path += 1
            started = time.perf_counter()
            status: int | str
            try:
                connection.request(
                    "GET",
                    f"{base_path}{path}",
                    headers={
                        "Cookie": cookie,
                        "User-Agent": "edify-staging-probe/1",
                    },
                )
                response = connection.getresponse()
                try:
                    response.read()
                    status = response.status
                finally:
                    response.close()
            except Exception as exc:  # noqa: BLE001 - every transport failure is evidence
                status = type(exc).__name__
                connection.close()
                connection = connection_type(
                    parsed_base.hostname,
                    port=parsed_base.port,
                    timeout=args.timeout,
                )
            elapsed_ms = (time.perf_counter() - started) * 1000
            with result_lock:
                statuses[status] += 1
                latencies[path].append(elapsed_ms)
        connection.close()

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
