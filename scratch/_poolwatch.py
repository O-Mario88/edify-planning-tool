"""Samples, every two seconds while a load test runs: PgBouncer's pool
(clients active / waiting, server connections active / idle, longest wait),
Postgres's own session count, and each web process's report of its pool.
Audit tooling.  python scratch/_poolwatch.py <app port> <seconds> <out.json>"""

import json
import subprocess
import sys
import time
import urllib.request

port, seconds, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
samples = []
deadline = time.time() + seconds


def psql(target, query):
    result = subprocess.run(
        ["psql", target, "-Atc", query], capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()


while time.time() < deadline:
    row = {"t": round(time.time() - (deadline - seconds), 1)}
    try:
        pool = (
            psql("host=127.0.0.1 port=6543 dbname=pgbouncer user=edify", "show pools")
            .splitlines()[0]
            .split("|")
        )
        # database|user|cl_active|cl_waiting|cl_active_cancel_req|cl_waiting_cancel_req|sv_active|sv_active_cancel|sv_being_canceled|sv_idle|sv_used|sv_tested|sv_login|maxwait|maxwait_us|pool_mode
        row.update(
            cl_active=int(pool[2]),
            cl_waiting=int(pool[3]),
            sv_active=int(pool[6]),
            sv_idle=int(pool[9]),
            sv_used=int(pool[10]),
            maxwait=int(pool[13]),
        )
        row["pg_sessions"] = int(
            psql(
                "host=127.0.0.1 port=5432 dbname=edify_perf user=edify",
                "select count(*) from pg_stat_activity where datname='edify_perf' and pid <> pg_backend_pid()",
            )
        )
    except Exception as error:  # noqa: BLE001
        row["error"] = str(error)[:80]
    reports = []
    for _ in range(6):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health/ready", timeout=5
            ) as response:
                body = json.loads(response.read())
            if "db_pool" in body:
                reports.append(body["db_pool"])
            row["db"] = body.get("db")
        except Exception as error:  # noqa: BLE001
            row["ready_error"] = str(error)[:60]
    if reports:
        row["app_open_max"] = max(r["open"] for r in reports)
        row["app_waiting_max"] = max(r["waiting"] for r in reports)
    samples.append(row)
    time.sleep(2)

json.dump(samples, open(out, "w"))
keys = [
    "cl_active",
    "cl_waiting",
    "sv_active",
    "sv_idle",
    "maxwait",
    "pg_sessions",
    "app_open_max",
    "app_waiting_max",
]
print(
    {k: max((s.get(k, 0) for s in samples), default=0) for k in keys},
    "samples",
    len(samples),
    "ready errors",
    sum(1 for s in samples if "ready_error" in s),
    "db not up",
    sum(1 for s in samples if s.get("db") not in ("up", None)),
)
