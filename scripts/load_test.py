#!/usr/bin/env python3
"""Role-weighted concurrent load test for an isolated Edify deployment.

`concurrent_read_probe.py` hammers a few pages with no pause between requests.
Real freezes happen under a different shape: many people, each with their own
session, moving through their role's pages with a few seconds between clicks,
while filters, searches and small writes land on the same workers. This models
that shape so a saturation point means something.

Each virtual user (VU) is one account with its own session and keep-alive
connection. It walks a weighted journey for its role — full pages, HTMX partial
refreshes (search, pagination), a school's detail page, and a harmless CSRF-
protected write — with a random think time between steps. Load is applied in
stages (``--stages 25:120,50:120,100:120`` = 25 users for 120 s, then 50, then
100), and every request is recorded with its stage.

A monitor thread samples the things a freeze is made of every two seconds:
Postgres connections by state and lock waiters, server process RSS and CPU
(``--server-pattern`` matches the worker command line), and Redis clients and
memory when ``--redis-url`` is given.

Never point this at production. It creates sessions and performs writes.

    scripts/load_test.py --base-url http://127.0.0.1:8000 \\
        --stages 25:90,50:90,100:90 --out /tmp/load.json
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import pathlib
import random
import re
import statistics
import sys
import threading
import time
import urllib.parse
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Share of virtual users per role. Field staff dominate a real morning.
ROLE_MIX = {
    "cceo": 45,
    "pl": 12,
    "ia": 7,
    "accountant": 5,
    "partner": 6,
    "coordinator": 4,
    "hr": 4,
    "cd": 3,
    "bt": 3,
    "mfi": 3,
    "rvp": 2,
    "regional_lead": 2,
}

ROLE_ACCOUNTS = {
    "cceo": [f"cceo{i}@edify.org" for i in range(1, 20)] + ["cceo@edify.org"],
    "pl": ["pl1@edify.org", "pl2@edify.org", "pl3@edify.org", "pl4@edify.org"],
    "ia": ["ia@edify.org"],
    "accountant": ["accountant@edify.org"],
    "partner": ["partner@edify.org", "partner-admin@edify.org"],
    "coordinator": ["coordinator@edify.org"],
    "hr": ["hr@edify.org"],
    "cd": ["cd@edify.org"],
    "bt": ["business-transformation@edify.org"],
    "mfi": ["mfi-admin@edify.org", "mfi-officer@edify.org"],
    "rvp": ["rvp@edify.org"],
    "regional_lead": ["regional-lead@edify.org"],
}

# (path, weight, kind). kind: page | htmx | school | write. `{q}` is a search
# term; `school` visits one of the account's own schools.
JOURNEYS = {
    "cceo": [
        ("/dashboard", 10, "page"),
        ("/my-plan", 14, "page"),
        ("/my-plan?q={q}", 4, "htmx:#my-plan-workspace"),
        ("/schools", 6, "page"),
        ("/schools?q={q}", 5, "htmx:#school-directory-results"),
        ("SCHOOL", 8, "school"),
        ("/planning", 8, "page"),
        ("/planning?q={q}", 3, "htmx:#planning-workspace"),
        ("/today/panel", 3, "page"),
        ("/todos", 3, "page"),
        ("/notifications", 3, "page"),
        ("/my-targets", 3, "page"),
        ("/calendar", 2, "page"),
        ("/evidence/", 2, "page"),
        ("/notifications/mark-all-read", 1, "write"),
    ],
    "pl": [
        ("/dashboard", 8, "page"),
        ("/team-planning-oversight/", 8, "page"),
        ("/planning", 6, "page"),
        ("/cluster-oversight/", 3, "page"),
        ("/team-targets", 4, "page"),
        ("/fund-requests/weekly", 3, "page"),
        ("/my-plan", 4, "page"),
        ("/schools?q={q}", 3, "htmx:#school-directory-results"),
        ("/analytics", 2, "page"),
        ("/ssa", 2, "page"),
        ("/notifications", 2, "page"),
    ],
    "ia": [
        ("/ia/dashboard/", 6, "page"),
        ("/ia/returned/", 3, "page"),
        ("/ia/history/", 2, "page"),
        ("/evidence/", 4, "page"),
        ("/ssa", 3, "page"),
        ("/activities/closure", 3, "page"),
        ("/analytics/verification-quality", 2, "page"),
        ("/core-schools", 2, "page"),
        ("/notifications", 1, "page"),
    ],
    "accountant": [
        ("/disbursements", 6, "page"),
        ("/accounts/weekly-requests", 4, "page"),
        ("/accounts/accountability", 3, "page"),
        ("/fund-requests/weekly", 3, "page"),
        ("/budget", 3, "page"),
        ("/budgets/overview", 2, "page"),
        ("/activities/closure", 2, "page"),
        ("/notifications", 1, "page"),
    ],
    "partner": [
        ("/partner/assigned-schools", 5, "page"),
        ("/partner/assigned-activities", 4, "page"),
        ("/partner/activities", 3, "page"),
        ("/my-plan", 3, "page"),
        ("/partner/evidence", 2, "page"),
        ("/todos", 1, "page"),
    ],
    "coordinator": [
        ("/dashboard", 4, "page"),
        ("/projects", 4, "page"),
        ("/projects/my-plan", 3, "page"),
        ("/projects/planning", 3, "page"),
        ("/my-plan", 2, "page"),
    ],
    "hr": [
        ("/hr-today", 5, "page"),
        ("/dashboard", 3, "page"),
        ("/leave/approvals", 3, "page"),
        ("/performance-reviews", 2, "page"),
        ("/hr-analytics", 2, "page"),
        ("/org-structure", 1, "page"),
    ],
    "cd": [
        ("/dashboard", 6, "page"),
        ("/analytics", 4, "page"),
        ("/ssa", 3, "page"),
        ("/country-planning-oversight/", 3, "page"),
        ("/planning", 2, "page"),
        ("/core-schools", 2, "page"),
        ("/budget", 2, "page"),
        ("/team-targets", 2, "page"),
    ],
    "bt": [
        ("/business-transformation", 4, "page"),
        ("/business-transformation/overview", 3, "page"),
        ("/loans", 4, "page"),
        ("/business-transformation/impact-reports", 2, "page"),
    ],
    "mfi": [("/mfi-portal", 5, "page"), ("/loans", 4, "page")],
    "rvp": [
        ("/dashboard", 5, "page"),
        ("/analytics", 3, "page"),
        ("/ssa", 2, "page"),
        ("/budgets/overview", 2, "page"),
    ],
    "regional_lead": [
        ("/dashboard", 5, "page"),
        ("/team-targets", 3, "page"),
        ("/schools", 2, "page"),
        ("/analytics", 2, "page"),
    ],
}

#: The approved 50-active-user workload (2026-09-24 mission brief §6): the
#: field team planning and submitting evidence, leads approving, IA
#: verifying, finance, leadership, HR, BT and the lending partner.
ROLE_MIX_SPEC50 = {
    "cceo": 18,
    "pl": 8,
    "ia": 5,
    "partner": 4,
    "accountant": 3,
    "cd": 2,
    "rvp": 1,
    "hr": 3,
    "bt": 3,
    "mfi": 3,
}

#: Governed state changes a real session performs, drawn from a pool of
#: records that are genuinely in the state the action needs, so each
#: transition happens once. `integrity_report` checks that it did.
WRITE_STEPS = {
    "cceo": [("EVIDENCE", 2, "evidence_upload")],
    "pl": [("PLCONFIRM", 2, "pl_confirm")],
    "ia": [("IAVERIFY", 2, "ia_verify")],
}

# A 1×1 PNG: the smallest file the evidence validator accepts as an image.
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201"
    "a5f6c3fd0000000049454e44ae426082"
)


def journeys_for(mix: str) -> dict:
    if mix != "spec50":
        return JOURNEYS
    steps = {role: list(paths) for role, paths in JOURNEYS.items()}
    for role, writes in WRITE_STEPS.items():
        steps[role] = steps[role] + writes
    return steps


SEARCH_TERMS = [
    "mukono",
    "primary",
    "hill",
    "st ",
    "umea",
    "kira",
    "nama",
    "gulu",
    "1005",
]


def percentile(samples, pct):
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def django_setup():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.loadtest")
    import django

    django.setup()


def database_session(email):
    """A real session row for the account, without paying bcrypt per VU."""
    from django.contrib.auth import get_user_model
    from django.test import Client

    user = get_user_model().objects.get(email=email)
    client = Client()
    client.force_login(user)
    return client.cookies["sessionid"].value


#: Activity states the officer's evidence upload acts on.
EVIDENCE_READY = ("in_progress", "evidence_uploaded")


def spec50_accounts(role: str) -> list[str]:
    """The role's accounts that hold records its governed write acts on.

    A realistic dataset spreads the work over many officers, and the demo
    accounts may hold nothing in the state a write needs. A write step with
    nothing to act on is skipped silently and measures nothing, so the
    officers and leads are chosen from the ones who have work waiting. Roles
    without a governed write keep their fixed accounts.
    """
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
    from apps.activities.models import Activity

    base = Activity.objects.filter(deleted_at__isnull=True, delivery_type="staff")
    if role == "cceo":
        owners = set(
            base.filter(status__in=EVIDENCE_READY).values_list(
                "responsible_staff_id", flat=True
            )
        )
        emails = set(
            StaffProfile.objects.filter(id__in=owners).values_list(
                "user__email", flat=True
            )
        ) | set(User.objects.filter(id__in=owners).values_list("email", flat=True))
    elif role == "pl":
        owners = set(
            base.filter(status="submitted_to_pl").values_list(
                "responsible_staff_id", flat=True
            )
        )
        emails = set(
            StaffSupervisorAssignment.objects.filter(
                supervisee_id__in=owners
            ).values_list("supervisor__user__email", flat=True)
        ) | set(
            StaffSupervisorAssignment.objects.filter(
                supervisee__user_id__in=owners
            ).values_list("supervisor__user__email", flat=True)
        )
    else:
        return ROLE_ACCOUNTS[role]
    return sorted(e for e in emails if e) or ROLE_ACCOUNTS[role]


def schools_for(email):
    from apps.accounts.models import StaffSchoolAssignment, User

    user = User.objects.get(email=email)
    staff_id = getattr(user, "staff_profile_id", None)
    if not staff_id:
        return []
    return list(
        StaffSchoolAssignment.objects.filter(staff_id=staff_id).values_list(
            "school_id", flat=True
        )[:200]
    )


class WritePools:
    """Records each account may act on once, shared by that account's VUs."""

    def __init__(self):
        self.lock = threading.Lock()
        self.pools: dict[tuple[str, str], list[str]] = {}

    def load(self, role: str, email: str) -> None:
        key = (role, email)
        if key in self.pools or role not in WRITE_STEPS:
            return
        from apps.accounts.models import StaffSupervisorAssignment, User
        from apps.activities.models import Activity

        user = User.objects.get(email=email)
        ids = [i for i in (user.id, getattr(user, "staff_profile_id", None)) if i]
        base = Activity.objects.filter(deleted_at__isnull=True, delivery_type="staff")
        if role == "cceo":
            rows = base.filter(responsible_staff_id__in=ids, status__in=EVIDENCE_READY)
        elif role == "pl":
            team = list(
                StaffSupervisorAssignment.objects.filter(
                    supervisor_id=user.staff_profile_id
                ).values_list("supervisee_id", "supervisee__user_id")
            )
            members = {i for pair in team for i in pair if i}
            rows = base.filter(
                responsible_staff_id__in=members, status="submitted_to_pl"
            )
        else:  # ia
            rows = base.filter(status="awaiting_ia_verification")
        if role == "ia":
            pool = self._verifiable(rows.order_by("id")[:2000], limit=400)
        else:
            pool = list(rows.order_by("id").values_list("id", flat=True)[:400])
        random.Random(hash(email) & 0xFFFF).shuffle(pool)
        self.pools[key] = pool

    @staticmethod
    def _verifiable(candidates, limit):
        """Work IA's own preconditions accept. The verify view reports a
        refusal as a message on a redirect, which a load test cannot see, so
        a refused verification would look like a lost one."""
        from apps.activities.ia_services import (
            _assert_verifiable,
            assert_ssa_visit_is_verifiable,
        )

        accepted = []
        for activity in candidates:
            try:
                _assert_verifiable(activity)
                assert_ssa_visit_is_verifiable(activity)
            except Exception:  # noqa: BLE001 - refused work is left out
                continue
            accepted.append(activity.id)
            if len(accepted) >= limit:
                break
        return accepted

    def take(self, role: str, email: str) -> str | None:
        with self.lock:
            pool = self.pools.get((role, email)) or []
            return pool.pop() if pool else None


class VirtualUser(threading.Thread):
    def __init__(self, harness, index, role, email, session, schools, login):
        super().__init__(daemon=True)
        self.h = harness
        self.index = index
        self.role = role
        self.email = email
        self.session = session
        self.schools = schools
        self.login = login
        self.csrf = None
        self.conn = None
        self.rng = random.Random(index * 7919)
        self.stop = threading.Event()
        steps = harness.journeys[role]
        self.paths = [s for s in steps]
        self.weights = [s[1] for s in steps]

    def _connection(self):
        if self.conn is None:
            self.conn = http.client.HTTPConnection(
                self.h.host, self.h.port, timeout=self.h.timeout
            )
        return self.conn

    def request(
        self, method, path, label, *, headers=None, body=None, subject="", fresh=False
    ):
        """One request on the VU's kept-alive connection; `fresh` sends it on a
        new connection of its own, as a second tab or a double-click does."""
        headers = {
            "Accept-Encoding": "gzip",
            "User-Agent": "edify-load-test/1",
            "Accept": "text/html",
            **(headers or {}),
        }
        cookies = []
        if self.session:
            cookies.append(f"sessionid={self.session}")
        if self.csrf:
            cookies.append(f"csrftoken={self.csrf}")
        if cookies:
            headers["Cookie"] = "; ".join(cookies)
        started = time.perf_counter()
        status, size, queue_wait, error = 0, 0, 0.0, ""
        # A browser silently retries an idempotent request whose kept-alive
        # socket the server had already closed; Uvicorn closes idle ones after
        # five seconds, which is shorter than the think time. Do the same once,
        # so a stale socket is not reported as a server failure.
        for attempt in (1, 2):
            reused = not fresh and self.conn is not None
            try:
                if fresh:
                    conn = http.client.HTTPConnection(
                        self.h.host, self.h.port, timeout=self.h.timeout
                    )
                else:
                    conn = self._connection()
                conn.request(method, path, body=body, headers=headers)
                response = conn.getresponse()
                raw = response.read()
                status = response.status
                size = len(raw)
                queue_wait = float(response.getheader("X-Edify-Queue-Wait") or 0)
                if fresh:
                    conn.close()
                    error = ""
                    break
                for value in response.headers.get_all("Set-Cookie") or []:
                    match = re.match(r"(sessionid|csrftoken)=([^;]*)", value)
                    if match and match.group(2):
                        if match.group(1) == "sessionid":
                            self.session = match.group(2)
                        else:
                            self.csrf = match.group(2)
                if response.getheader("Connection", "").lower() == "close":
                    self._reset()
                error = ""
                break
            except (
                http.client.RemoteDisconnected,
                BrokenPipeError,
                ConnectionResetError,
            ) as exc:
                if not fresh:
                    self._reset()
                error = type(exc).__name__
                if reused and attempt == 1:
                    started = time.perf_counter()
                    continue
                break
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                error = type(exc).__name__
                if not fresh:
                    self._reset()
                break
        elapsed = (time.perf_counter() - started) * 1000
        self.h.record(
            {
                "t": time.time(),
                "stage": self.h.stage,
                "role": self.role,
                "label": label,
                "method": method,
                "status": status,
                "ms": round(elapsed, 1),
                "bytes": size,
                "queue_wait": queue_wait,
                "error": error,
                "subject": subject,
            }
        )
        return status

    def _reset(self):
        try:
            if self.conn:
                self.conn.close()
        finally:
            self.conn = None

    def do_login(self):
        self.request("GET", "/login", "/login GET")
        body = urllib.parse.urlencode(
            {
                "email": self.email,
                "password": self.h.password,
                "csrfmiddlewaretoken": self.csrf or "",
            }
        )
        self.request(
            "POST",
            "/login",
            "/login POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"http://{self.h.host}:{self.h.port}/login",
                "X-CSRFToken": self.csrf or "",
            },
            body=body,
        )

    def governed_write(self, kind):
        activity_id = self.h.pools.take(self.role, self.email)
        if activity_id is None:
            return
        referer = f"http://{self.h.host}:{self.h.port}/dashboard"
        headers = {"X-CSRFToken": self.csrf or "", "Referer": referer}
        if kind == "evidence_upload":
            boundary = f"edifyload{self.index}{self.rng.randrange(10**9)}"
            parts = [
                (
                    f"--{boundary}\r\nContent-Disposition: form-data; "
                    'name="csrfmiddlewaretoken"\r\n\r\n'
                    f"{self.csrf or ''}\r\n"
                ).encode(),
                (
                    f"--{boundary}\r\nContent-Disposition: form-data; "
                    'name="evidence_kind"\r\n\r\nphoto\r\n'
                ).encode(),
                (
                    f"--{boundary}\r\nContent-Disposition: form-data; "
                    'name="evidence_file"; filename="site-photo.png"\r\n'
                    "Content-Type: image/png\r\n\r\n"
                ).encode()
                + PNG_1X1
                + b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            self.request(
                "POST",
                f"/activities/{activity_id}/evidence/action",
                "/activities/<id>/evidence/action [write]",
                headers=headers,
                body=b"".join(parts),
                subject=f"{kind}:{activity_id}",
            )
            return
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        if kind == "pl_confirm":
            path = f"/pl/review-queue/{activity_id}/confirm"
            label = "/pl/review-queue/<id>/confirm [write]"
            fields = {}
        else:
            path = f"/ia/verification/{activity_id}/verify"
            label = "/ia/verification/<id>/verify [write]"
            fields = dict.fromkeys(
                (
                    "evidence_exists",
                    "attendance_valid",
                    "ssa_uploaded",
                    "correct_school",
                    "correct_cluster",
                    "correct_intervention",
                    "sf_id_entered",
                    "duplicate_check_passed",
                    "analytics_ready",
                ),
                "on",
            )
        fields["csrfmiddlewaretoken"] = self.csrf or ""
        body = urllib.parse.urlencode(fields)
        subject = f"{kind}:{activity_id}"
        twin = None
        if self.rng.random() < self.h.double_submit:
            # The same decision, at the same moment, from a second connection:
            # a double-click or a second tab. Exactly one may apply.
            twin = threading.Thread(
                target=self.request,
                args=("POST", path, label.replace("[write]", "[double]")),
                kwargs={
                    "headers": dict(headers),
                    "body": body,
                    "subject": subject,
                    "fresh": True,
                },
                daemon=True,
            )
            twin.start()
        self.request("POST", path, label, headers=headers, body=body, subject=subject)
        if twin is not None:
            twin.join(timeout=self.h.timeout + 5)

    def run(self):
        if self.login:
            self.session = None
            self.do_login()
        # Pick up a CSRF cookie the way a browser would, from its first page.
        self.request("GET", "/dashboard", "/dashboard")
        while not self.stop.is_set() and not self.h.done.is_set():
            path, _weight, kind = self.rng.choices(self.paths, weights=self.weights)[0]
            if kind == "school":
                if not self.schools:
                    continue
                path = f"/schools/{self.rng.choice(self.schools)}"
                self.request("GET", path, "/schools/<id>")
            elif kind.startswith("htmx"):
                target = kind.split(":", 1)[1]
                concrete = path.format(
                    q=urllib.parse.quote(self.rng.choice(SEARCH_TERMS))
                )
                self.request(
                    "GET",
                    concrete,
                    path.replace("{q}", "…") + " [htmx]",
                    headers={"HX-Request": "true", "HX-Target": target.lstrip("#")},
                )
            elif kind in ("evidence_upload", "pl_confirm", "ia_verify"):
                self.governed_write(kind)
            elif kind == "write":
                self.request(
                    "POST",
                    path,
                    path + " [write]",
                    headers={
                        "X-CSRFToken": self.csrf or "",
                        "Referer": f"http://{self.h.host}:{self.h.port}/notifications",
                        "HX-Request": "true",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    body="",
                )
            else:
                self.request("GET", path, path)
            self.stop.wait(self.rng.uniform(self.h.think_min, self.h.think_max))
        self._reset()


class Monitor(threading.Thread):
    def __init__(self, harness, database_url, server_pattern, redis_url):
        super().__init__(daemon=True)
        self.h = harness
        self.database_url = database_url
        self.server_pattern = server_pattern
        self.redis_url = redis_url
        self.samples = []
        self.ticks = os.sysconf("SC_CLK_TCK")
        self.page = os.sysconf("SC_PAGE_SIZE")
        self.last_cpu = {}

    def _processes(self):
        found = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ")
            except OSError:
                continue
            if self.server_pattern.encode() in cmd and b"load_test" not in cmd:
                found.append(int(pid))
        return found

    def _database_pids(self):
        found = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                cmd = open(f"/proc/{pid}/cmdline", "rb").read()
            except OSError:
                continue
            if cmd.startswith(b"postgres") or b"/postgres" in cmd.split(b"\0")[0]:
                found.append(int(pid))
        return found

    def _proc_stats(self, now, pids=None):
        rss_total, cpu_total = 0, 0.0
        for pid in self._processes() if pids is None else pids:
            try:
                stat = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
                rss = int(open(f"/proc/{pid}/statm").read().split()[1]) * self.page
            except (OSError, IndexError, ValueError):
                continue
            jiffies = int(stat[11]) + int(stat[12])
            previous = self.last_cpu.get(pid)
            self.last_cpu[pid] = (now, jiffies)
            if previous:
                dt = now - previous[0]
                if dt > 0:
                    cpu_total += (jiffies - previous[1]) / self.ticks / dt * 100
            rss_total += rss
        return rss_total, cpu_total

    def run(self):
        import psycopg

        conn = (
            psycopg.connect(self.database_url, autocommit=True)
            if self.database_url
            else None
        )
        redis_client = None
        if self.redis_url:
            import redis

            redis_client = redis.Redis.from_url(self.redis_url, socket_timeout=1)
        while not self.h.done.is_set():
            now = time.monotonic()
            sample = {"t": time.time(), "stage": self.h.stage}
            if conn:
                try:
                    rows = conn.execute(
                        "select state, wait_event_type, count(*) from pg_stat_activity "
                        "where datname = current_database() and pid <> pg_backend_pid() "
                        "group by 1, 2"
                    ).fetchall()
                    sample["db_connections"] = sum(r[2] for r in rows)
                    sample["db_active"] = sum(r[2] for r in rows if r[0] == "active")
                    sample["db_idle_in_tx"] = sum(
                        r[2]
                        for r in rows
                        if (r[0] or "").startswith("idle in transaction")
                    )
                    sample["db_lock_waits"] = sum(r[2] for r in rows if r[1] == "Lock")
                    sample["db_total_server"] = conn.execute(
                        "select count(*) from pg_stat_activity where backend_type = 'client backend'"
                    ).fetchone()[0]
                except Exception as exc:  # noqa: BLE001
                    sample["db_error"] = type(exc).__name__
            rss, cpu = self._proc_stats(now)
            sample["server_rss_mb"] = round(rss / 1048576, 1)
            sample["server_cpu_pct"] = round(cpu, 1)
            _db_rss, db_cpu = self._proc_stats(now, self._database_pids())
            sample["db_cpu_pct"] = round(db_cpu, 1)
            if redis_client:
                try:
                    info = redis_client.info()
                    sample["redis_clients"] = info.get("connected_clients")
                    sample["redis_mb"] = round(info.get("used_memory", 0) / 1048576, 1)
                except Exception as exc:  # noqa: BLE001
                    sample["redis_error"] = type(exc).__name__
            self.samples.append(sample)
            self.h.done.wait(2)


class Harness:
    def __init__(self, args):
        parsed = urllib.parse.urlsplit(args.base_url)
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.timeout = args.timeout
        self.think_min = args.think_min
        self.think_max = args.think_max
        self.password = os.environ.get(args.password_env, "")
        self.results = []
        self.lock = threading.Lock()
        self.stage = "warmup"
        self.done = threading.Event()
        self.journeys = journeys_for(args.mix)
        self.pools = WritePools()
        self.double_submit = args.double_submit if args.mix == "spec50" else 0.0

    def record(self, row):
        with self.lock:
            self.results.append(row)


def summarise(rows, seconds):
    ms = [r["ms"] for r in rows]
    ok = [r for r in rows if 200 <= r["status"] < 400]
    busy = [r for r in rows if r["status"] == 503]
    errors = [r for r in rows if r["status"] >= 500 or r["error"]]
    return {
        "requests": len(rows),
        "rps": round(len(rows) / seconds, 2) if seconds else 0,
        "p50": round(percentile(ms, 50)),
        "p95": round(percentile(ms, 95)),
        "p99": round(percentile(ms, 99)),
        "max": round(max(ms)) if ms else 0,
        "ok": len(ok),
        "busy_503": len(busy),
        "errors_5xx_or_transport": len(errors),
        "error_rate_pct": round(len(errors) / len(rows) * 100, 2) if rows else 0,
        "timeouts": sum(1 for r in rows if r["error"] in ("TimeoutError", "timeout")),
        "queue_wait_p95": round(percentile([r["queue_wait"] for r in rows], 95), 1),
        "statuses": dict(Counter(str(r["status"] or r["error"]) for r in rows)),
    }


#: The audit entry each governed write leaves behind, by write kind.
WRITE_AUDIT = {
    "evidence_upload": "upload_evidence",
    "pl_confirm": "pl_approve_completion",
    "ia_verify": "ia_verify_completion",
}


def integrity_report(started_at: float, results: list[dict]) -> dict:
    """What the governed writes did to the database during the run.

    A load test that only times responses cannot see a double submission or
    a write that silently failed. For each write kind this compares the
    records the virtual users were told were accepted (2xx/3xx) with the
    audit entries the action writes:

    - ``lost``: accepted, never audited — a submission the user believes landed;
    - ``applied_unseen``: audited though the user saw no success (a timeout
      or 5xx after the commit) — the case where a retry would duplicate;
    - ``duplicated``: audited more than once — a double submission applied twice.

    Each pool hands a record out once, so any repeat comes from the deliberate
    double submissions, of which exactly one may apply.
    """
    from datetime import datetime, timezone

    from apps.audit.models import AuditLog
    from apps.evidence.models import EvidenceRecord

    since = datetime.fromtimestamp(started_at, tz=timezone.utc)
    report: dict = {}
    for kind, action in WRITE_AUDIT.items():
        rows = [r for r in results if r.get("subject", "").startswith(kind + ":")]
        accepted = {
            r["subject"].split(":", 1)[1] for r in rows if 200 <= r["status"] < 400
        }
        audited = Counter(
            AuditLog.objects.filter(action=action, created_at__gte=since).values_list(
                "subject_id", flat=True
            )
        )
        report[kind] = {
            "requests": len(rows),
            "double_submits": sum(1 for r in rows if "[double]" in r["label"]),
            "accepted": sum(1 for r in rows if 200 <= r["status"] < 400),
            "rejected_4xx": sum(1 for r in rows if 400 <= r["status"] < 500),
            "busy_503": sum(1 for r in rows if r["status"] == 503),
            "failed_5xx_or_transport": sum(
                1
                for r in rows
                if (r["status"] >= 500 and r["status"] != 503) or r["error"]
            ),
            "subjects_accepted": len(accepted),
            "subjects_audited": len(audited),
            "lost": sorted(accepted - set(audited))[:20],
            "applied_unseen": sorted(set(audited) - accepted)[:20],
            "duplicated": sorted((s, n) for s, n in audited.items() if n > 1)[:20],
        }
    uploads = report["evidence_upload"]
    uploads["evidence_records_created"] = EvidenceRecord.objects.filter(
        created_at__gte=since, original_name="site-photo.png"
    ).count()
    report["ok"] = (
        all(
            not v["lost"]
            and not v["duplicated"]
            and not v["applied_unseen"]
            and not v["failed_5xx_or_transport"]
            for v in report.values()
            if isinstance(v, dict)
        )
        and uploads["evidence_records_created"] == uploads["accepted"]
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--stages", default="25:90,50:90,100:90")
    parser.add_argument("--think-min", type=float, default=3.0)
    parser.add_argument("--think-max", type=float, default=12.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--login-fraction", type=float, default=0.0)
    parser.add_argument("--password-env", default="EDIFY_LOAD_PASSWORD")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--redis-url", default="")
    parser.add_argument("--server-pattern", default="gunicorn")
    parser.add_argument(
        "--recovery", type=int, default=30, help="seconds at 1 VU after load"
    )
    parser.add_argument("--out", default="")
    parser.add_argument(
        "--mix",
        default="legacy",
        choices=("legacy", "spec50"),
        help="legacy: the 2026-09-23 role mix, reads plus one write; spec50: the "
        "approved 50-user workload with governed writes and an integrity check",
    )
    parser.add_argument(
        "--double-submit",
        type=float,
        default=0.1,
        help="spec50: share of PL/IA decisions sent twice at once",
    )
    args = parser.parse_args()

    django_setup()
    stages = [
        (int(u), int(s)) for u, s in (x.split(":") for x in args.stages.split(","))
    ]
    peak = max(u for u, _ in stages)
    harness = Harness(args)

    mix = ROLE_MIX_SPEC50 if args.mix == "spec50" else ROLE_MIX
    roles = []
    for role, weight in mix.items():
        roles.extend([role] * weight)
    rng = random.Random(42)
    plan = [roles[i % len(roles)] for i in rng.sample(range(len(roles)), len(roles))]
    while len(plan) < peak:
        plan.extend(plan)
    plan = plan[:peak]

    school_cache = {}
    print(f"preparing {peak} virtual users …", flush=True)
    vus = []
    spec_accounts: dict[str, list[str]] = {}
    role_seen: Counter = Counter()
    for index, role in enumerate(plan):
        if args.mix == "spec50":
            # One account per VU while the role has enough of them.
            if role not in spec_accounts:
                spec_accounts[role] = spec50_accounts(role)
            accounts = spec_accounts[role]
            email = accounts[role_seen[role] % len(accounts)]
            role_seen[role] += 1
        else:
            accounts = ROLE_ACCOUNTS[role]
            email = accounts[index % len(accounts)]
        login = rng.random() < args.login_fraction
        session = None if login else database_session(email)
        if email not in school_cache:
            school_cache[email] = schools_for(email)
        if args.mix == "spec50":
            harness.pools.load(role, email)
        vus.append(
            VirtualUser(
                harness, index, role, email, session, school_cache[email], login
            )
        )

    run_started = time.time()
    monitor = Monitor(harness, args.database_url, args.server_pattern, args.redis_url)
    monitor.start()
    started = []
    stage_windows = []
    for users, seconds in stages:
        harness.stage = f"{users}u"
        begin = time.time()
        # Ramp new users in over the first fifth of the stage, as people arrive.
        pending = vus[len(started) : users]
        ramp = max(1.0, seconds / 5)
        for i, vu in enumerate(pending):
            vu.start()
            started.append(vu)
            time.sleep(ramp / max(1, len(pending)))
        remaining = seconds - (time.time() - begin)
        if remaining > 0:
            time.sleep(remaining)
        stage_windows.append((harness.stage, begin, time.time()))
        print(f"stage {harness.stage} done", flush=True)
    for vu in started[1:]:
        vu.stop.set()
    harness.stage = "recovery"
    begin = time.time()
    time.sleep(args.recovery)
    stage_windows.append(("recovery", begin, time.time()))
    harness.done.set()
    for vu in started:
        vu.join(timeout=args.timeout + 5)
    monitor.join(timeout=5)

    report = {
        "mix": args.mix,
        "stages": {},
        "by_route": {},
        "by_role": {},
        "monitor": {},
    }
    if args.mix == "spec50":
        report["integrity"] = integrity_report(run_started, harness.results)
    for name, begin, end in stage_windows:
        rows = [r for r in harness.results if r["stage"] == name]
        report["stages"][name] = summarise(rows, end - begin)
        samples = [s for s in monitor.samples if s["stage"] == name]

        def peak_of(key, samples=samples):
            values = [s[key] for s in samples if key in s]
            return max(values) if values else None

        def mean_of(key, samples=samples):
            values = [s[key] for s in samples if key in s]
            return round(statistics.mean(values), 1) if values else None

        report["monitor"][name] = {
            "db_connections_max": peak_of("db_connections"),
            "db_total_server_max": peak_of("db_total_server"),
            "db_active_max": peak_of("db_active"),
            "db_idle_in_tx_max": peak_of("db_idle_in_tx"),
            "db_lock_waits_max": peak_of("db_lock_waits"),
            "server_rss_mb_max": peak_of("server_rss_mb"),
            "server_cpu_pct_mean": mean_of("server_cpu_pct"),
            "db_cpu_pct_mean": mean_of("db_cpu_pct"),
            "redis_clients_max": peak_of("redis_clients"),
        }
    loaded = [r for r in harness.results if r["stage"] not in ("warmup", "recovery")]
    per_route = defaultdict(list)
    per_role = defaultdict(list)
    for r in loaded:
        per_route[r["label"]].append(r)
        per_role[r["role"]].append(r)
    for label, rows in per_route.items():
        report["by_route"][label] = summarise(rows, 0)
    for role, rows in per_role.items():
        report["by_role"][role] = summarise(rows, 0)

    print(
        "\nstage        req    rps    p50    p95    p99    max  503  err%   dbconn lockw  rssMB  cpu%  dbcpu%"
    )
    for name in report["stages"]:
        s, m = report["stages"][name], report["monitor"][name]
        print(
            f"{name:<10}{s['requests']:>6}{s['rps']:>7}{s['p50']:>7}{s['p95']:>7}{s['p99']:>7}"
            f"{s['max']:>7}{s['busy_503']:>5}{s['error_rate_pct']:>6}"
            f"{m['db_total_server_max'] or 0:>8}{m['db_lock_waits_max'] or 0:>6}"
            f"{m['server_rss_mb_max'] or 0:>7}{m['server_cpu_pct_mean'] or 0:>6}"
            f"{m['db_cpu_pct_mean'] or 0:>8}"
        )
    if "integrity" in report:
        print("\nintegrity:", json.dumps(report["integrity"]))
    print("\nslowest routes under load (p95):")
    for label, s in sorted(report["by_route"].items(), key=lambda kv: -kv[1]["p95"])[
        :20
    ]:
        print(f"  {s['p95']:>7} ms p95 {s['p50']:>6} p50 n={s['requests']:<5} {label}")
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps({**report, "samples": monitor.samples}, indent=1)
        )
        print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
