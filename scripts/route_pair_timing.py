#!/usr/bin/env python3
"""Re-time exact (role, route) pairs: the median of N requests each.

`route_timing_sweep.py` takes one sample of every route for every role, which
is the right tool for finding slow pages and the wrong one for proving a
before/after difference: a single sample of a page with a 30 s analytics
cache lands on a hit or a miss by chance. This re-times a fixed list of pairs
— typically the slow cohort from a sweep — N times each, one request at a
time, after one warm-up request, so two builds can be compared on copies of
the same database.

    SWEEP_REPEAT=3 scripts/route_pair_timing.py pairs.jsonl out.jsonl
    # pairs.jsonl: one {"role": "cd", "route": "/ssa"} per line; roles are
    # the keys of route_timing_sweep.ROLE_ACCOUNTS

Run it against a disposable copy of a seeded database, never production.
"""

from __future__ import annotations

import json
import os
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import route_timing_sweep as sweep  # noqa: E402  (sets up Django)

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402


def main() -> int:
    pairs_file, out_file = sys.argv[1], sys.argv[2]
    repeat = max(1, int(os.environ.get("SWEEP_REPEAT", "3")))
    pairs = [json.loads(line) for line in open(pairs_file) if line.strip()]
    user_model = get_user_model()
    clients: dict[str, Client] = {}
    with open(out_file, "w") as sink:
        for pair in pairs:
            role, route = pair["role"], pair["route"]
            client = clients.get(role)
            if client is None:
                client = Client(raise_request_exception=False)
                client.force_login(
                    user_model.objects.get(email=sweep.ROLE_ACCOUNTS[role])
                )
                clients[role] = client
            client.get(route, HTTP_ACCEPT="text/html")  # warm
            samples = [sweep.sample(client, route) for _ in range(repeat)]
            row = dict(samples[-1])
            row["ms"] = round(statistics.median(s["ms"] for s in samples), 1)
            row["samples_ms"] = [s["ms"] for s in samples]
            row.update(role=role, route=route)
            sink.write(json.dumps(row) + "\n")
            sink.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
