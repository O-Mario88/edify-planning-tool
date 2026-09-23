#!/usr/bin/env python3
"""Time every argument-free GET route as every role, and flag N+1 shapes.

The latency budget script measures a curated handful of pages. This sweeps the
whole routed surface instead: every URL pattern with no path parameters, once
per role account, in-process through Django's test client so each response
carries its exact query count, database time and body size.

It also reports the most-repeated normalised SQL statement per request. A
statement executed 40 times with only its literals changing is an N+1 whatever
the total query count looks like, and that is the regression this is for.

Run it against a disposable copy of a seeded database, never production:
some legacy GET routes still write (last-seen stamps, read receipts).

    SWEEP_ROLES=pl,cd scripts/route_timing_sweep.py --out /tmp/sweep.json
    SWEEP_REPEAT=3 scripts/route_timing_sweep.py      # median of three samples

Output is JSON lines per (role, route) plus a ranked summary on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import statistics
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import URLPattern, URLResolver, get_resolver  # noqa: E402

ROLE_ACCOUNTS = {
    "cceo": "cceo1@edify.org",
    "pl": "pl1@edify.org",
    "cd": "cd@edify.org",
    "ia": "ia@edify.org",
    "accountant": "accountant@edify.org",
    "hr": "hr@edify.org",
    "coordinator": "coordinator@edify.org",
    "partner_admin": "partner-admin@edify.org",
    "partner": "partner@edify.org",
    "bt": "business-transformation@edify.org",
    "mfi_admin": "mfi-admin@edify.org",
    "mfi_officer": "mfi-officer@edify.org",
    "regional_lead": "regional-lead@edify.org",
    "rvp": "rvp@edify.org",
    "admin": "admin@edify.org",
}

# Routes that end the session or are not pages. Everything else is swept.
SKIP = re.compile(
    r"(logout|sign-?out|impersonat|/stream|realtime|^admin/|^static/|^media/|"
    r"service-worker|manifest\.json|favicon|robots\.txt|__debug__|healthz?)",
    re.I,
)

_LITERAL = re.compile(r"('(?:[^']|'')*'|\b\d+\b|%s)")


def normalise(sql: str) -> str:
    return _LITERAL.sub("?", sql)[:400]


def argument_free_routes() -> list[str]:
    found: list[str] = []

    def walk(patterns, prefix=""):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, prefix + str(pattern.pattern))
            elif isinstance(pattern, URLPattern):
                route = prefix + str(pattern.pattern)
                if "<" in route or "(?P" in route or "^" in route or "$" in route:
                    continue
                if SKIP.search(route):
                    continue
                found.append("/" + route)

    walk(get_resolver().url_patterns)
    return sorted(set(found))


class QueryTimer:
    def __init__(self):
        self.count = 0
        self.seconds = 0.0
        self.statements: Counter[str] = Counter()

    def __call__(self, execute, sql, params, many, context):
        started = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.seconds += time.perf_counter() - started
            self.count += 1
            self.statements[normalise(sql)] += 1


def sample(client: Client, url: str) -> dict:
    timer = QueryTimer()
    started = time.perf_counter()
    with connection.execute_wrapper(timer):
        response = client.get(url, HTTP_ACCEPT="text/html")
    elapsed = (time.perf_counter() - started) * 1000
    body = b"" if getattr(response, "streaming", False) else response.content
    top_sql, top_count = (timer.statements.most_common(1) or [("", 0)])[0]
    return {
        "status": response.status_code,
        "location": response.get("Location", ""),
        "ms": round(elapsed, 1),
        "queries": timer.count,
        "db_ms": round(timer.seconds * 1000, 1),
        "bytes": len(body),
        "max_repeat": top_count,
        "max_repeat_sql": top_sql if top_count >= 5 else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "scratch" / "route_sweep.jsonl"))
    parser.add_argument("--only", default="", help="regex filter on route")
    args = parser.parse_args()

    repeat = max(1, int(os.environ.get("SWEEP_REPEAT", "1")))
    wanted = [r for r in os.environ.get("SWEEP_ROLES", "").split(",") if r]
    roles = {k: v for k, v in ROLE_ACCOUNTS.items() if not wanted or k in wanted}
    routes = argument_free_routes()
    if args.only:
        routes = [r for r in routes if re.search(args.only, r)]

    User = get_user_model()
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    with out_path.open("w") as sink:
        for role, email in roles.items():
            user = User.objects.filter(email=email).first()
            if user is None:
                print(f"skip {role}: no account {email}", file=sys.stderr)
                continue
            client = Client(raise_request_exception=False)
            client.force_login(user)
            for route in routes:
                try:
                    client.get(route, HTTP_ACCEPT="text/html")  # warm
                    samples = [sample(client, route) for _ in range(repeat)]
                except Exception as exc:  # noqa: BLE001
                    samples = [{"status": "EXC", "error": repr(exc)[:300], "ms": 0}]
                row = dict(samples[-1])
                row["ms"] = round(statistics.median(s["ms"] for s in samples), 1)
                row.update(role=role, route=route)
                rows.append(row)
                sink.write(json.dumps(row) + "\n")
                sink.flush()

    ok = [r for r in rows if r["status"] == 200]
    print(f"\n{len(rows)} requests, {len(ok)} HTTP 200, output: {out_path}")
    errors = [r for r in rows if r["status"] not in (200, 301, 302, 403, 404, 405)]
    print(f"\nNon-success statuses ({len(errors)}):")
    for r in errors[:40]:
        print(f"  {r['status']} {r['role']:<14} {r['route']} {r.get('error', '')}")
    print("\nSlowest 40 (HTTP 200):")
    print(
        f"  {'ms':>8} {'queries':>7} {'db_ms':>7} {'KiB':>6} {'rep':>4}  role / route"
    )
    for r in sorted(ok, key=lambda r: -r["ms"])[:40]:
        print(
            f"  {r['ms']:>8.0f} {r['queries']:>7} {r['db_ms']:>7.0f} "
            f"{r['bytes'] / 1024:>6.0f} {r['max_repeat']:>4}  {r['role']:<14} {r['route']}"
        )
    print("\nMost repeated statement per request (>= 10 repeats):")
    for r in sorted(ok, key=lambda r: -r["max_repeat"])[:30]:
        if r["max_repeat"] < 10:
            break
        print(f"  x{r['max_repeat']:<4} {r['role']:<14} {r['route']}")
        print(f"         {r['max_repeat_sql'][:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
