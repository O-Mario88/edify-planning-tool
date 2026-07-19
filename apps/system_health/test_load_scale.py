"""Load / scale gate: does the platform hold up at 15,000 schools?

Production is sized for roughly 15,000 client schools. Every measurement we
had before this file was taken against a dev database of ~700, which is small
enough that an N+1 query -- the failure mode that actually kills Django
dashboards -- stays invisible. 700 extra queries return in a few hundred
milliseconds; 15,000 do not.

So this seeds a full-size estate once (setUpTestData, so the cost is paid a
single time for the whole class) and then measures the pages that aggregate
across the entire school population. Two things are asserted per page:

  * a QUERY CEILING -- the real N+1 detector. A page that issues a bounded
    number of queries at 15,000 schools is bounded, full stop. A page that
    loops will blow through any sane ceiling by orders of magnitude, and the
    failure message prints the actual count so the regression is obvious.

  * a LATENCY CEILING -- generous, and deliberately secondary. Wall time on a
    developer laptop under `manage.py test` is not production wall time, and
    treating it as a precise SLO would make this test flaky. It is here to
    catch the catastrophic case (a page that takes 30s at scale), not to
    police a 200ms budget.

The ceilings are recorded per page rather than shared, because these pages do
legitimately different amounts of work. They are set above the measured value
with headroom, so ordinary changes do not trip them but a structural
regression does.

Run just this gate:

    python manage.py test apps.system_health.test_load_scale
"""

from __future__ import annotations

import time

from django.contrib.auth import get_user_model
from django.db import connection, reset_queries
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.geography.models import Region, District, SubCounty
from apps.geography.subregions import SUBREGIONS
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


# Production target. Named rather than inlined so the number in the failure
# message and the number in the docstring can never drift apart.
TARGET_SCHOOLS = 15_000

# Roughly one SSA per five schools, matching the observed ratio in the dev
# estate (702 schools / ~140 SSA records). Enough rows that the sub-region
# roll-up has real work to do without tripling fixture build time.
SSA_EVERY_NTH = 5


class ScaleGateTest(TestCase):
    """Measures the whole-population pages against a 15,000-school estate."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()

        cls.user = User.objects.create(
            id="scale-cceo",
            email="scale-cceo@edify.org",
            name="Scale CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.user.set_password("pass123")
        cls.user.save()
        cls.profile = StaffProfile.objects.create(
            id="scale-staff-cceo", user=cls.user, title="CCEO"
        )

        # Geography mirrors the real shape: the 135 UBOS districts spread over
        # their true regions, so the sub-region roll-up groups the same way it
        # will in production rather than collapsing into one bucket.
        regions: dict[str, Region] = {}
        districts: list[District] = []
        for _subregion, (region_name, district_names) in sorted(SUBREGIONS.items()):
            region = regions.get(region_name)
            if region is None:
                region = Region.objects.create(name=region_name)
                regions[region_name] = region
            for district_name in district_names:
                districts.append(District(name=district_name, region=region))
        District.objects.bulk_create(districts)
        districts = list(District.objects.select_related("region").order_by("name"))
        cls.districts = districts
        cls.regions = regions

        SubCounty.objects.bulk_create(
            [
                SubCounty(name=f"{d.name} Central", district=d)
                for d in districts
            ]
        )
        sub_counties = list(SubCounty.objects.order_by("name"))

        Cluster.objects.bulk_create(
            [
                Cluster(
                    name=f"{d.name} Cluster",
                    region=d.region,
                    district=d,
                    status="active",
                )
                for d in districts
            ]
        )
        clusters = list(Cluster.objects.order_by("name"))

        # Schools, spread evenly across districts. bulk_create deliberately
        # bypasses School.save(), which nulls cluster_id -- the assignment
        # below is the point of the fixture, so it must survive.
        schools = []
        for i in range(TARGET_SCHOOLS):
            district = districts[i % len(districts)]
            schools.append(
                School(
                    school_id=f"SCALE-{i:06d}",
                    name=f"Scale School {i:06d}",
                    region=district.region,
                    district=district,
                    sub_county=sub_counties[i % len(sub_counties)],
                    # cluster_id is a plain CharField, not an FK -- the clusters
                    # app owns the relationship from its side.
                    cluster_id=clusters[i % len(clusters)].id,
                    school_type="client",
                    current_fy_ssa_status="not_done",
                    planning_readiness="ready",
                )
            )
        School.objects.bulk_create(schools, batch_size=2000)
        cls.schools = list(School.objects.order_by("school_id"))

        # Put the CCEO over a realistic slice rather than the whole country:
        # a portfolio page that is fast only because its owner has no schools
        # would prove nothing.
        StaffSchoolAssignment.objects.bulk_create(
            [
                StaffSchoolAssignment(staff=cls.profile, school_id=s.id)
                for s in cls.schools[:500]
            ],
            batch_size=1000,
        )

        fy = get_operational_fy()
        cls.fy = fy

        ssa_records = [
            SsaRecord(
                school=s,
                fy=fy,
                quarter="Q1",
                date_of_ssa=timezone.localdate(),
                # Vary the score so weighted sub-region averages differ per
                # bucket; a constant would hide an aggregation bug.
                average_score=40 + (idx % 55),
                new_enrollment=100 + (idx % 400),
                verification_status="confirmed",
                collector_type="staff",
            )
            for idx, s in enumerate(cls.schools[::SSA_EVERY_NTH])
        ]
        SsaRecord.objects.bulk_create(ssa_records, batch_size=2000)
        saved_records = list(SsaRecord.objects.order_by("id"))

        # One intervention score per record keeps the SsaScore join non-empty
        # without multiplying fixture size by eight.
        SsaScore.objects.bulk_create(
            [
                SsaScore(
                    ssa_record=r,
                    intervention="Government Requirements",
                    score=40 + (i % 55),
                )
                for i, r in enumerate(saved_records)
            ],
            batch_size=2000,
        )

        # ANALYZE after bulk loading, or every timing below is measuring a
        # planner with no statistics. bulk_create does not trigger autovacuum,
        # so Postgres would estimate every table at its default size and pick
        # nested loops over hash joins -- turning a millisecond aggregate into
        # a multi-second sequential scan. Production has autovacuum running, so
        # measuring the unanalyzed state would report a bottleneck that does
        # not exist and hide any that does.
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE")

    def setUp(self):
        self.client.force_login(self.user)

    # ── measurement helper ────────────────────────────────────────────────
    def _measure(self, url, *, max_queries, max_seconds, allow_statuses=(200,)):
        """Fetch `url`, asserting it works and stays bounded at full scale.

        Query count is the load-bearing assertion; see the module docstring
        for why wall time is the softer of the two.
        """
        reset_queries()
        with CaptureQueriesContext(connection) as ctx:
            started = time.perf_counter()
            response = self.client.get(url)
            elapsed = time.perf_counter() - started

        self.assertIn(
            response.status_code,
            allow_statuses,
            f"{url} returned {response.status_code} at {TARGET_SCHOOLS:,} schools",
        )
        query_count = len(ctx.captured_queries)
        self.assertLessEqual(
            query_count,
            max_queries,
            f"{url} issued {query_count} queries at {TARGET_SCHOOLS:,} schools "
            f"(ceiling {max_queries}). A count that scales with the school "
            f"population is an N+1 -- batch the lookup rather than raising "
            f"this ceiling.",
        )
        self.assertLess(
            elapsed,
            max_seconds,
            f"{url} took {elapsed:.2f}s at {TARGET_SCHOOLS:,} schools "
            f"(ceiling {max_seconds}s).",
        )
        return {"url": url, "queries": query_count, "seconds": elapsed}

    # ── the estate is actually full size ──────────────────────────────────
    def test_fixture_reaches_production_scale(self):
        """Guards the gate itself: every ceiling below is meaningless if the
        fixture quietly shrank."""
        self.assertEqual(School.objects.count(), TARGET_SCHOOLS)
        self.assertEqual(
            SsaRecord.objects.count(), len(range(0, TARGET_SCHOOLS, SSA_EVERY_NTH))
        )
        # Districts must be spread, not piled into one bucket, or the
        # sub-region roll-up is measured against a degenerate shape.
        self.assertGreaterEqual(District.objects.count(), 130)

    # ── the whole-population pages ────────────────────────────────────────
    @override_settings(DEBUG=False)
    def test_analytics_page_bounded_at_scale(self):
        """/analytics carries the sub-region roll-up and the map -- the
        heaviest aggregation in the product."""
        self._measure("/analytics", max_queries=220, max_seconds=25.0)

    @override_settings(DEBUG=False)
    def test_cceo_dashboard_does_not_scale_with_school_count(self):
        """The CCEO dashboard issues a lot of queries (~670 at the time of
        writing) but the number that matters is whether it GROWS.

        An absolute ceiling here would be arbitrary: the page legitimately
        assembles many independent panels, and no single one dominates -- the
        most-repeated query shape accounts for well under a tenth of the total.
        What would actually break production is a count proportional to the
        school population, so this measures at 15,000 schools, adds 3,000 more,
        and measures again. Anything that grows is an N+1 no matter how small
        the starting number.
        """
        before = self._measure("/dashboard", max_queries=10_000, max_seconds=25.0)

        district = self.districts[0]
        School.objects.bulk_create(
            [
                School(
                    school_id=f"GROWTH-{i:06d}",
                    name=f"Growth School {i:06d}",
                    region=district.region,
                    district=district,
                    school_type="client",
                    current_fy_ssa_status="not_done",
                    planning_readiness="ready",
                )
                for i in range(3_000)
            ],
            batch_size=2000,
        )
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE")

        after = self._measure("/dashboard", max_queries=10_000, max_seconds=25.0)

        # A small constant slack absorbs warm-up differences; anything
        # proportional to the 3,000 rows added is the failure being hunted.
        self.assertLessEqual(
            after["queries"],
            before["queries"] + 4,
            f"/dashboard went from {before['queries']} to {after['queries']} "
            f"queries when 3,000 schools were added -- the page is doing "
            f"per-school work.",
        )

    @override_settings(DEBUG=False)
    def test_schools_list_bounded_at_scale(self):
        """The largest single table in the product."""
        self._measure("/schools", max_queries=160, max_seconds=25.0)

    @override_settings(DEBUG=False)
    def test_closure_queue_bounded_at_scale(self):
        """Closure evaluates a checklist per row, so it is the most likely
        place for per-row work to hide."""
        self._measure(
            # Trailing slash is required: an earlier "activities/<activity_id>"
            # pattern shadows the slash-less form and 404s on it.
            "/activities/closure/",
            max_queries=260,
            max_seconds=25.0,
        )
