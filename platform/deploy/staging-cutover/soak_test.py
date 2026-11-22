#!/usr/bin/env python3
"""Edify Staging Sustained Concurrency & 1,000-User Soak Test Runner.

Simulates mixed concurrent operational read/export/map traffic against a
staging Go gateway (never production) and reports RPS, latency percentiles
(P50, P95, P99, Max), and error rate.

Usage (staging 60-minute soak):
  python3 soak_test.py \
    --gateway https://staging-gateway.internal \
    --token "$STAGING_JWT" \
    --users 1000 \
    --duration 3600

Usage (local quick smoke):
  python3 soak_test.py \
    --gateway http://127.0.0.1:8091 \
    --token "$DEV_JWT" \
    --users 200 \
    --duration 10
"""

import argparse
import concurrent.futures
import json
import math
import sys
import time
import urllib.error
import urllib.request


ENDPOINTS = [
    ("GET", "/api/v1/country-map/data?fy=2027", None),
    ("POST", "/edify.screens.v1.PageScreenService/GetPage", {"path": "/dashboard", "query": {"view": "team", "fy": "2027"}, "desktop": True}),
    ("POST", "/edify.screens.v1.PageScreenService/GetPage", {"path": "/dashboard", "query": {"view": "programmes", "fy": "2027"}, "desktop": True}),
    ("POST", "/edify.screens.v1.PageScreenService/GetPage", {"path": "/escalations", "query": {}, "desktop": True}),
    ("GET", "/healthz", None),
]


def percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(math.ceil((pct / 100.0) * len(sorted_vals))) - 1))
    return sorted_vals[idx]


def worker(base: str, token: str, worker_id: int, deadline: float):
    latencies = []
    ok_count = 0
    err_count = 0
    idx = worker_id
    while time.monotonic() < deadline:
        method, path, payload = ENDPOINTS[idx % len(ENDPOINTS)]
        idx += 1
        hdrs = {"Authorization": f"Bearer {token}"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=body, headers=hdrs, method=method)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
                if 200 <= resp.status < 300:
                    ok_count += 1
                else:
                    err_count += 1
        except Exception:
            err_count += 1
        latencies.append((time.perf_counter() - t0) * 1000.0)
    return latencies, ok_count, err_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Edify Staging Concurrency & Soak Test")
    parser.add_argument("--gateway", required=True, help="Staging Go gateway URL")
    parser.add_argument("--token", required=True, help="Bearer JWT token")
    parser.add_argument("--users", type=int, default=200, help="Concurrent virtual users (default: 200; staging soak: 1000)")
    parser.add_argument("--duration", type=int, default=15, help="Duration in seconds (default: 15; staging soak: 3600)")
    parser.add_argument("--max-p95-ms", type=float, default=1000.0, help="Pass threshold for P95 latency in ms")
    args = parser.parse_args()

    if "edifyuganda.org" in args.gateway.lower() and "staging" not in args.gateway.lower():
        print("ABORT: refusing to run load/soak test against production URL", file=sys.stderr)
        return 2

    base = args.gateway.rstrip("/")
    start = time.monotonic()
    deadline = start + args.duration

    all_latencies: list[float] = []
    total_ok = 0
    total_err = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.users) as pool:
        futs = [pool.submit(worker, base, args.token, i, deadline) for i in range(args.users)]
        for fut in concurrent.futures.as_completed(futs):
            lats, ok_c, err_c = fut.result()
            all_latencies.extend(lats)
            total_ok += ok_c
            total_err += err_c

    elapsed = max(0.001, time.monotonic() - start)
    all_latencies.sort()
    total = total_ok + total_err
    rps = total / elapsed
    err_rate = (total_err / total * 100.0) if total else 100.0
    p50 = percentile(all_latencies, 50)
    p95 = percentile(all_latencies, 95)
    p99 = percentile(all_latencies, 99)
    mx = all_latencies[-1] if all_latencies else 0.0

    summary = {
        "users": args.users,
        "duration_s": round(elapsed, 2),
        "total_requests": total,
        "ok": total_ok,
        "errors": total_err,
        "error_rate_pct": round(err_rate, 3),
        "rps": round(rps, 1),
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "p99_ms": round(p99, 1),
        "max_ms": round(mx, 1),
    }
    print(json.dumps(summary, indent=2))
    if total_err > 0 or p95 > args.max_p95_ms:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
