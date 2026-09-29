"""Country Planning Oversight at 50,000 schools (owner spec §24.4, §26.11).

Built like apps.system_health.test_load_scale: the assertion that matters is
SCALE-INVARIANCE — the page, the Lead and officer expansions, the school
drill-down and a filter change issue the same number of queries at 50,000
schools as at a few hundred — plus a catastrophic wall-time bound. Laptop wall
time under the test runner is not production wall time, so the timings are
printed for the report rather than asserted against the P95 targets.

    python manage.py test apps.planning.test_country_oversight_scale --tag=scale
    EDIFY_CPO_SCALE_SCHOOLS=20000 python manage.py test ... --tag=scale
"""

from __future__ import annotations

import os
import time
from datetime import timedelta

from django.db import connection
from django.test import Client, TestCase, override_settings, tag
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.core.fy import get_fy_date_range, get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School


def _size(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else default


SCHOOLS = _size("EDIFY_CPO_SCALE_SCHOOLS", 50_000)
LEADS = 10
OFFICERS_PER_LEAD = 9
CATASTROPHIC_SECONDS = 30.0
FY = get_operational_fy()
FY_START = get_fy_date_range(FY)[0].date()


@tag("scale")
class CountryOversightScaleTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Scale Region", country="Uganda")
        cls.district = District.objects.create(name="Scale District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(
            name="Scale SC", district=cls.district
        )
        cls.cd_user = User.objects.create(
            email="scale-cd@cpo.test",
            name="Scale Director",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            is_active=True,
        )
        StaffProfile.objects.create(user=cls.cd_user, title="CD", country="Uganda")
        cls.leads, cls.officers = [], []
        for lead_index in range(LEADS):
            lead_user = User.objects.create(
                email=f"scale-pl{lead_index}@cpo.test",
                name=f"Lead {lead_index:02d}",
                roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
                active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
                is_active=True,
            )
            lead = StaffProfile.objects.create(
                user=lead_user, title="PL", country="Uganda"
            )
            cls.leads.append(lead)
            for officer_index in range(OFFICERS_PER_LEAD):
                user = User.objects.create(
                    email=f"scale-cceo{lead_index}-{officer_index}@cpo.test",
                    name=f"Officer {lead_index:02d}-{officer_index}",
                    roles=[EdifyRole.CCEO.value],
                    active_role=EdifyRole.CCEO.value,
                    is_active=True,
                )
                officer = StaffProfile.objects.create(
                    user=user, title="CCEO", country="Uganda"
                )
                StaffSupervisorAssignment.objects.create(
                    supervisee=officer, supervisor=lead
                )
                cls.officers.append(officer)
        cls.partners = [
            Partner.objects.create(name=f"Scale Partner {n}", active_status=True)
            for n in range(6)
        ]
        cls.clusters = Cluster.objects.bulk_create(
            [
                Cluster(
                    name=f"Scale Cluster {n}",
                    region=cls.region,
                    district=cls.district,
                    sub_county=cls.sub_county,
                    status="active",
                )
                for n in range(200)
            ]
        )
        cls.grow(SCHOOLS)

    @classmethod
    def grow(cls, count: int, *, prefix: str = "S"):
        """`count` schools across the officers, with a year of planning."""
        start = School.objects.count()
        holders = cls.officers + cls.leads
        schools = []
        for index in range(count):
            n = start + index
            schools.append(
                School(
                    school_id=f"SCALE-{prefix}-{n:06d}",
                    name=f"Scale School {n:06d}",
                    school_type="core"
                    if n % 6 == 0
                    else ("champion" if n % 97 == 0 else "client"),
                    region=cls.region,
                    district=cls.district,
                    account_owner_id=holders[n % len(holders)].id,
                    account_owner_status="matched",
                    cluster_id=cls.clusters[n % len(cls.clusters)].id
                    if n % 3
                    else None,
                    cluster_status="clustered" if n % 3 else "unclustered",
                )
            )
        School.objects.bulk_create(schools, batch_size=5000)
        created = (
            School.objects.filter(school_id__startswith=f"SCALE-{prefix}-")
            .only("id", "school_type", "account_owner_id")
            .order_by("school_id")
        )
        activities, handovers = [], []
        for position, school in enumerate(created.iterator(chunk_size=5000)):
            planned = FY_START + timedelta(days=position % 330)
            kind = "core_visit" if school.school_type == "core" else "school_visit"
            if position % 2 == 0:
                activities.append(
                    Activity(
                        activity_type=kind,
                        school_id=school.id,
                        fy=FY,
                        quarter="Q1",
                        planned_date=planned,
                        status="scheduled" if position % 5 else "ia_verified",
                        responsible_staff_id=school.account_owner_id,
                        delivery_type="staff",
                    )
                )
            if position % 9 == 0:
                activities.append(
                    Activity(
                        activity_type=kind,
                        school_id=school.id,
                        fy=FY,
                        quarter="Q2",
                        planned_date=planned + timedelta(days=10),
                        status="partner_scheduled",
                        delivery_type="partner",
                        assigned_partner_id=cls.partners[
                            position % len(cls.partners)
                        ].id,
                    )
                )
            elif position % 11 == 0:
                handovers.append(
                    PartnerAssignment(
                        school_id=school.id,
                        partner=cls.partners[position % len(cls.partners)],
                        status="assigned",
                        support_type="visit" if school.school_type == "core" else None,
                        expected_activity_type=None
                        if school.school_type == "core"
                        else "school_visit",
                    )
                )
        Activity.objects.bulk_create(activities, batch_size=5000)
        PartnerAssignment.objects.bulk_create(handovers, batch_size=5000)
        sessions = Activity.objects.bulk_create(
            [
                Activity(
                    activity_type="cluster_meeting" if n % 2 else "cluster_training",
                    cluster=cls.clusters[n % len(cls.clusters)],
                    fy=FY,
                    quarter="Q3",
                    planned_date=FY_START + timedelta(days=200 + n % 60),
                    status="scheduled",
                    responsible_staff_id=cls.officers[n % len(cls.officers)].id,
                )
                for n in range(max(10, count // 250))
            ]
        )
        roster = []
        for session in sessions:
            members = School.objects.filter(cluster_id=session.cluster_id).values_list(
                "id", flat=True
            )[:20]
            roster += [
                ClusterActivityAttendance(activity=session, school_id=pk, invited=True)
                for pk in members
            ]
        ClusterActivityAttendance.objects.bulk_create(
            roster, batch_size=5000, ignore_conflicts=True
        )
        _analyze()

    def measure(self, client, url):
        with CaptureQueriesContext(connection) as context:
            started = time.perf_counter()
            response = client.get(url, HTTP_HX_REQUEST="true")
            elapsed = time.perf_counter() - started
        self.assertEqual(response.status_code, 200, url)
        queries = [q for q in context.captured_queries if not _bookkeeping(q["sql"])]
        return len(queries), elapsed, len(response.content)

    def test_the_page_costs_the_same_at_fifty_thousand_schools(self):
        client = Client()
        client.force_login(self.cd_user)
        lead, officer = self.leads[0], self.officers[0]
        urls = {
            "initial page": "/country-planning-oversight/",
            "filter update": f"/country-planning-oversight/?program_lead={lead.id}&planning_status=partial",
            "PL expansion": f"/country-planning-oversight/rows?level=lead&key={lead.id}",
            "CCEO expansion": f"/country-planning-oversight/rows?level=owner&key={officer.id}",
            "school drill-down": f"/country-planning-oversight/schools?owner={officer.id}&gap=unallocated",
        }
        if os.environ.get("EDIFY_CPO_SCALE_PROFILE"):
            with CaptureQueriesContext(connection) as context:
                client.get(urls["initial page"], HTTP_HX_REQUEST="true")
            slow = sorted(context.captured_queries, key=lambda q: -float(q["time"]))[:6]
            for query in slow[:3]:
                print(f"\n--- {query['time']}s\n{query['sql'][:300]}")
                with connection.cursor() as cursor:
                    cursor.execute("EXPLAIN (ANALYZE, BUFFERS OFF) " + query["sql"])
                    print("\n".join(row[0] for row in cursor.fetchall()[:40]))
            import cProfile
            import pstats

            profiler = cProfile.Profile()
            profiler.enable()
            client.get(urls["initial page"], HTTP_HX_REQUEST="true")
            profiler.disable()
            pstats.Stats(profiler).sort_stats("cumulative").print_stats(35)
        first = {name: self.measure(client, url) for name, url in urls.items()}
        report = [
            f"Country Planning Oversight at {School.objects.count():,} schools (cold, no cache):"
        ]
        for name, (queries, seconds, size) in first.items():
            report.append(
                f"  {name:18s} {queries:4d} queries  {seconds * 1000:8.0f} ms  {size / 1024:7.1f} KB"
            )
            self.assertLess(seconds, CATASTROPHIC_SECONDS, name)
            self.assertLess(queries, 150, name)

        # Production's steady state: the scheduler's warmer has built the
        # year, and readers are served from it. Each sample is a request the
        # cache has not answered before — a new filter, another Lead, another
        # officer — so the P95 is of real work, not of repeated cache hits.
        report.append(self.steady_state(client))
        print("\n" + "\n".join(report))

        # The initial response never carries the officers or the schools.
        body = Client()
        body.force_login(self.cd_user)
        html = body.get("/country-planning-oversight/").content.decode()
        # The CCEO filter lists the officers by name; their rows are not here.
        self.assertNotIn('data-level="2"', html)
        self.assertNotIn("Scale School 000", html)

        # Grow the estate and ask again: nothing may scale with it. The
        # allowance covers the handful of lookups whose count depends on which
        # people and Partners hold the new schools, not on how many there are.
        shapes = {}
        if os.environ.get("EDIFY_CPO_SCALE_PROFILE"):
            shapes = {name: _query_shapes(client, url) for name, url in urls.items()}
        self.grow(2_000, prefix="G")
        second = {name: self.measure(client, url) for name, url in urls.items()}
        for name, before in shapes.items():
            after = _query_shapes(client, urls[name])
            grown = after - before
            if grown:
                print(f"\n=== {name}: queries added at the larger estate")
                for shape, count in grown.most_common():
                    print(f"  +{count}  {shape[:240]}")
        for name in urls:
            with self.subTest(view=name):
                self.assertLessEqual(
                    second[name][0], first[name][0] + 6, (first[name], second[name])
                )

    def test_the_execution_tab_costs_the_same_at_fifty_thousand_schools(self):
        """Country Execution & Completion Oversight (owner, 2026-09-28): the
        same gates as the planning tab — no query that grows with the estate,
        and the steady state served from the warmer's build."""
        from django.core.cache import cache

        from apps.planning.country_execution import service as esvc
        from apps.planning.country_oversight import service as svc

        client = Client()
        client.force_login(self.cd_user)
        lead, officer = self.leads[0], self.officers[0]
        year = "view=execution&period=fy"
        urls = {
            "initial page": "/country-planning-oversight/?view=execution",
            "annual view": f"/country-planning-oversight/?{year}",
            "filter update": f"/country-planning-oversight/?{year}&program_lead={lead.id}&channel=staff",
            "PL expansion": f"/country-planning-oversight/execution/rows?level=lead&key={lead.id}&{year}",
            "CCEO expansion": f"/country-planning-oversight/execution/rows?level=owner&key={officer.id}&{year}",
            "overdue drill-down": f"/country-planning-oversight/execution/drawer?kind=activities&stage=overdue&{year}",
            "school completion": f"/country-planning-oversight/execution/table?table=school&{year}",
        }
        first = {name: self.measure(client, url) for name, url in urls.items()}
        report = [
            f"Country Execution & Completion Oversight at {School.objects.count():,} "
            f"schools, {Activity.objects.count():,} activities (cold, no cache):"
        ]
        for name, (queries, seconds, size) in first.items():
            report.append(
                f"  {name:18s} {queries:4d} queries  {seconds * 1000:8.0f} ms  {size / 1024:7.1f} KB"
            )
            self.assertLess(seconds, CATASTROPHIC_SECONDS, name)
            self.assertLess(queries, 150, name)

        stages = ("overdue", "due", "verified", "not_started")
        channels = ("staff", "partner")
        samples: dict[str, list] = {name: [] for name in urls if name != "initial page"}
        with override_settings(DASHBOARD_CACHE_SECONDS=300):
            cache.clear()
            started = time.perf_counter()
            svc.warm()
            esvc.warm()
            warm_seconds = time.perf_counter() - started
            for n in range(20):
                lead = self.leads[n % LEADS]
                officer = self.officers[n % len(self.officers)]
                sample = {
                    "annual view": f"/country-planning-oversight/?{year}",
                    "filter update": (
                        f"/country-planning-oversight/?{year}&program_lead={lead.id}"
                        f"&channel={channels[n % 2]}"
                    ),
                    "PL expansion": f"/country-planning-oversight/execution/rows?level=lead&key={lead.id}&{year}",
                    "CCEO expansion": f"/country-planning-oversight/execution/rows?level=owner&key={officer.id}&{year}",
                    "overdue drill-down": (
                        f"/country-planning-oversight/execution/drawer?kind=activities"
                        f"&stage={stages[n % 4]}&page={n % 3 + 1}&{year}"
                    ),
                    "school completion": (
                        f"/country-planning-oversight/execution/table?table=school&page={n % 3 + 1}"
                        f"&program_lead={lead.id}&{year}"
                    ),
                }
                for name, url in sample.items():
                    samples[name].append(self.measure(client, url))
            export = self.measure(
                client, f"/country-planning-oversight/execution/export?{year}"
            )
            cache.clear()
        report.append(
            f"Steady state (both stages warmed in {warm_seconds * 1000:.0f} ms; 20 distinct requests each):"
        )
        for name, rows in samples.items():
            times = sorted(seconds for _, seconds, _ in rows)
            p95 = times[max(0, int(round(0.95 * len(times))) - 1)]
            report.append(
                f"  {name:18s} P50 {times[len(times) // 2] * 1000:6.0f} ms  "
                f"P95 {p95 * 1000:6.0f} ms  max {times[-1] * 1000:6.0f} ms  "
                f"queries ≤ {max(q for q, _, _ in rows)}"
            )
            self.assertLess(p95, CATASTROPHIC_SECONDS, name)
        queries, seconds, size = export
        report.append(
            f"  {'export (.xlsx)':18s} {seconds * 1000:8.0f} ms  {size / 1024:8.0f} KB  {queries} queries"
        )
        print("\n" + "\n".join(report))

        self.grow(2_000, prefix="G")
        second = {name: self.measure(client, url) for name, url in urls.items()}
        for name in urls:
            with self.subTest(view=name):
                self.assertLessEqual(
                    second[name][0], first[name][0] + 6, (first[name], second[name])
                )

    def steady_state(self, client) -> str:
        from django.core.cache import cache

        from apps.planning.country_oversight import service as svc

        statuses = ("full", "partial", "none", "awaiting")
        samples: dict[str, list] = {
            "initial page": [],
            "filter update": [],
            "PL expansion": [],
            "CCEO expansion": [],
            "school drill-down": [],
            "country gap list": [],
        }
        with override_settings(DASHBOARD_CACHE_SECONDS=300):
            cache.clear()
            started = time.perf_counter()
            svc.warm()
            warm_seconds = time.perf_counter() - started
            for n in range(20):
                lead = self.leads[n % LEADS]
                officer = self.officers[n % len(self.officers)]
                urls = {
                    "initial page": "/country-planning-oversight/",
                    "filter update": (
                        f"/country-planning-oversight/?program_lead={lead.id}"
                        f"&planning_status={statuses[n % len(statuses)]}"
                    ),
                    "PL expansion": f"/country-planning-oversight/rows?level=lead&key={lead.id}",
                    "CCEO expansion": f"/country-planning-oversight/rows?level=owner&key={officer.id}",
                    "school drill-down": (
                        f"/country-planning-oversight/schools?owner={officer.id}"
                        f"&gap={('unallocated', 'staff_gap', 'partner_gap', 'training_gap')[n % 4]}"
                    ),
                    "country gap list": (
                        "/country-planning-oversight/schools?gap="
                        f"{('staff_gap', 'partner_gap', 'unclustered', 'no_visit')[n % 4]}&page={n % 3 + 1}"
                    ),
                }
                for name, url in urls.items():
                    samples[name].append(self.measure(client, url))
            # The one export: every school, one row each, as a workbook.
            export = self.measure(client, "/country-planning-oversight/coverage-export")
            if os.environ.get("EDIFY_CPO_SCALE_PROFILE"):
                import cProfile
                import pstats

                for url in (
                    f"/country-planning-oversight/schools?owner={self.officers[3].id}&gap=staff_gap&page=2",
                    "/country-planning-oversight/schools?gap=training_gap&page=2",
                ):
                    profiler = cProfile.Profile()
                    profiler.enable()
                    client.get(url, HTTP_HX_REQUEST="true")
                    profiler.disable()
                    print(f"\n=== {url}")
                    pstats.Stats(profiler).sort_stats("cumulative").print_stats(22)
            cache.clear()
        lines = [
            f"Steady state (warmed in {warm_seconds * 1000:.0f} ms; 20 distinct requests each):"
        ]
        for name, rows in samples.items():
            times = sorted(seconds for _, seconds, _ in rows)
            p95 = times[max(0, int(round(0.95 * len(times))) - 1)]
            lines.append(
                f"  {name:18s} P50 {times[len(times) // 2] * 1000:6.0f} ms  "
                f"P95 {p95 * 1000:6.0f} ms  max {times[-1] * 1000:6.0f} ms  "
                f"queries ≤ {max(q for q, _, _ in rows)}"
            )
            self.assertLess(p95, CATASTROPHIC_SECONDS, name)
        queries, seconds, size = export
        lines.append(
            f"  {'export (.xlsx)':18s} {seconds * 1000:8.0f} ms  {size / 1024:8.0f} KB  "
            f"{queries} queries"
        )
        return "\n".join(lines)


#: The session touch and the Who's Online beat, written by the first request
#: of each minute whatever it asks for (apps.core.middleware
#: SlidingSessionMiddleware): not the page's cost, and it lands on whichever
#: measured request crosses the minute.
_BOOKKEEPING = ('"django_session"', '"last_seen_at"', '"presence_time"')


def _bookkeeping(sql: str) -> bool:
    return any(marker in sql for marker in _BOOKKEEPING)


def _query_shapes(client, url):
    """The queries a request makes, literals removed, counted by shape."""
    import re
    from collections import Counter

    with CaptureQueriesContext(connection) as context:
        client.get(url, HTTP_HX_REQUEST="true")
    literal = re.compile(r"'[^']*'|\b\d+\b")
    return Counter(
        re.sub(r"\((?:%s|\?)(?:, (?:%s|\?))*\)", "(…)", literal.sub("?", q["sql"]))
        for q in context.captured_queries
        if not _bookkeeping(q["sql"])
    )


def _analyze():
    """Planner statistics for the bulk-loaded tables, as autovacuum keeps them
    in production (the reasoning in apps.system_health.test_load_scale._analyze:
    unanalysed, Postgres picks nested loops and every timing is fiction)."""
    from django.db.utils import OperationalError

    for table in (
        "school",
        "activity",
        "partner_assignment",
        "cluster_activity_attendance",
        "cluster",
        "staff_profile",
        "staff_supervisor_assignment",
        "core_activity_slot",
    ):
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"ANALYZE {table}")  # nosec B608 - fixed literals
        except OperationalError:
            continue
