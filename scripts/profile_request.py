#!/usr/bin/env python3
"""Explain where one page's time goes: repeated SQL by call site, and CPU.

The route sweep says which page is slow and whether a statement repeats. This
says why. For one request as one account it reports:

* every normalised SQL statement executed more than once, with the count, total
  time and the application frame (``apps/...:line in function``) that issued
  it — the line an N+1 fix has to change;
* the top functions by cumulative CPU time (cProfile), restricted to
  application code so framework plumbing does not bury the answer.

Run it against a disposable database; the request is a real GET.

    scripts/profile_request.py --email cd@edify.org --path /core-schools
    scripts/profile_request.py --email pl1@edify.org --path /my-plan --cprofile 30
"""

from __future__ import annotations

import argparse
import cProfile
import os
import pathlib
import pstats
import re
import sys
import time
import traceback
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.loadtest")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402

_LITERAL = re.compile(r"('(?:[^']|'')*'|\b\d+\b|%s)")
_APP_FRAME = re.compile(r"/(apps|config)/")
# Middleware and decorators wrap every view; their cumulative time is the whole
# request and says nothing about where it went.
WRAPPER_FILES = (
    "middleware.py",
    "concurrency.py",
    "detection.py",
    "school_identity_middleware.py",
)


def app_frame() -> str:
    for frame in reversed(traceback.extract_stack()[:-3]):
        if _APP_FRAME.search(frame.filename) and "/scripts/" not in frame.filename:
            path = frame.filename.split(str(ROOT) + "/", 1)[-1]
            return f"{path}:{frame.lineno} in {frame.name}"
    return "(framework)"


class Recorder:
    def __init__(self):
        self.by_statement = defaultdict(
            lambda: {"n": 0, "s": 0.0, "sites": defaultdict(int)}
        )
        self.count = 0
        self.seconds = 0.0

    def __call__(self, execute, sql, params, many, context):
        started = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            took = time.perf_counter() - started
            key = _LITERAL.sub("?", sql)[:220]
            entry = self.by_statement[key]
            entry["n"] += 1
            entry["s"] += took
            entry["sites"][app_frame()] += 1
            self.count += 1
            self.seconds += took


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--cprofile", type=int, default=25, help="rows of CPU profile")
    parser.add_argument("--warm", type=int, default=1)
    parser.add_argument(
        "--time",
        type=int,
        default=0,
        help="instead of profiling, report the median of N unprofiled requests",
    )
    args = parser.parse_args()

    user = get_user_model().objects.get(email=args.email)
    client = Client(raise_request_exception=True)
    client.force_login(user)
    for _ in range(args.warm):
        client.get(args.path)

    if args.time:
        samples = []
        for _ in range(args.time):
            started = time.perf_counter()
            response = client.get(args.path)
            samples.append((time.perf_counter() - started) * 1000)
        samples.sort()
        print(
            f"{args.email} GET {args.path} -> {response.status_code}  "
            f"median {samples[len(samples) // 2]:.0f} ms, min {samples[0]:.0f} ms, "
            f"max {samples[-1]:.0f} ms over {len(samples)} unprofiled requests"
        )
        return 0

    recorder = Recorder()
    profiler = cProfile.Profile()
    started = time.perf_counter()
    with connection.execute_wrapper(recorder):
        profiler.enable()
        response = client.get(args.path)
        profiler.disable()
    wall = (time.perf_counter() - started) * 1000

    body = b"" if getattr(response, "streaming", False) else response.content
    print(
        f"\n{args.email} GET {args.path} -> {response.status_code}  "
        f"{wall:.0f} ms wall (profiled), {recorder.count} queries, "
        f"{recorder.seconds * 1000:.0f} ms in SQL, {len(body) / 1024:.0f} KiB"
    )
    repeated = sorted(
        ((k, v) for k, v in recorder.by_statement.items() if v["n"] > 1),
        key=lambda kv: -kv[1]["n"],
    )
    print(f"\nRepeated statements ({len(repeated)}):")
    for sql, info in repeated[:15]:
        print(f"  x{info['n']:<5} {info['s'] * 1000:7.1f} ms  {sql[:150]}")
        for site, n in sorted(info["sites"].items(), key=lambda kv: -kv[1])[:3]:
            print(f"           {n:>5} from {site}")

    stats = pstats.Stats(profiler)
    stats.sort_stats("cumulative")
    print(f"\nTop {args.cprofile} application functions by cumulative time:")
    rows = []
    for (filename, line, name), (cc, nc, tt, ct, _callers) in stats.stats.items():
        if (
            "/apps/" in filename
            and "/migrations/" not in filename
            and not filename.endswith(WRAPPER_FILES)
            and name not in ("_wrapped_view", "_view_wrapper")
        ):
            rows.append((ct, nc, filename.split("/apps/", 1)[1], line, name))
    for ct, calls, filename, line, name in sorted(rows, reverse=True)[: args.cprofile]:
        print(f"  {ct * 1000:8.1f} ms {calls:>7} calls  apps/{filename}:{line} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
