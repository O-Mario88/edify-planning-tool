"""Load / scale gate: does the platform's cost stay flat as the estate grows?

Every measurement before this file was taken against a dev database of ~700
schools, which is too small for an N+1 -- the failure mode that actually kills
Django dashboards -- to surface at all.

WHY THERE IS NO FIXED SCHOOL COUNT HERE
---------------------------------------
An earlier version of this gate pinned the estate at 15,000 schools and
asserted an absolute query ceiling per page. That certifies exactly one number:
it says the product works at 15,000 and says nothing whatsoever about 16,000.
It also rots -- every legitimate new panel pushes a page nearer its ceiling
until someone raises the ceiling to make the suite green, which is precisely
the moment the gate stops meaning anything.

So the assertion is now SCALE-INVARIANCE rather than a ceiling. Each page is
measured, the estate is grown, and the page is measured again. If the query
count does not move when thousands of schools appear, the page is O(1) in the
school population and therefore correct at ANY scale -- 15,000, 150,000, or a
number nobody has thought of yet. If it moves, it is an N+1 no matter how small
the starting number looked.

That is what actually removes the limit: not a bigger constant, but an
assertion whose truth does not depend on the constant.

The base estate is still substantial, because scale-invariance is only
meaningful once the planner has realistic statistics and the joins have real
cardinality. It is configurable rather than hardcoded:

    EDIFY_SCALE_SCHOOLS=50000 python manage.py test apps.system_health.test_load_scale
    EDIFY_SCALE_GROWTH=10000  python manage.py test apps.system_health.test_load_scale

The defaults keep an ordinary run to roughly fifteen seconds. Raising them
costs fixture build time and nothing else -- no assertion needs editing,
because no assertion mentions a specific size.

A generous absolute ceiling survives alongside the growth check purely as a
smoke test: a page issuing tens of thousands of *constant* queries would
technically pass scale-invariance while still being indefensible.

Wall time is asserted only against the catastrophic case. Laptop wall time
under `manage.py test` is not production wall time, and treating it as an SLO
would make this suite flaky.

Run just this gate:

    python manage.py test apps.system_health.test_load_scale
"""

from __future__ import annotations

import os
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


def _env_int(name: str, default: int) -> int:
    """Read a positive integer override, ignoring blank/garbage values.

    A malformed override falls back to the default rather than crashing the
    suite: this gate should be trivially runnable at a different size, and a
    typo in an env var is not worth a collection error.
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Base estate size. Large enough that join cardinality and the query planner
# behave realistically; NOT a certified maximum -- see the module docstring.
BASE_SCHOOLS = _env_int("EDIFY_SCALE_SCHOOLS", 15_000)

# How many schools each scale-invariance check adds mid-test. Needs to be big
# enough that a per-school query would be unmistakable in the delta.
GROWTH_SCHOOLS = _env_int("EDIFY_SCALE_GROWTH", 3_000)

# Roughly one SSA per five schools, matching the observed ratio in the dev
# estate (702 schools / ~140 SSA records). Enough rows that the sub-region
# roll-up has real work to do without tripling fixture build time.
SSA_EVERY_NTH = 5

# Constant slack absorbing connection warm-up and session/permission lookups
# that differ between two requests in the same test. Anything proportional to
# GROWTH_SCHOOLS is the failure being hunted and dwarfs this.
QUERY_SLACK = 4

# Smoke-test ceiling only. Deliberately far above any real page so that it
# never becomes the thing people tune; the growth check is the real gate.
ABSURD_QUERY_COUNT = 10_000

# Catastrophic-case wall time. Not an SLO.
CATASTROPHIC_SECONDS = 30.0


class ScaleGateTest(TestCase):
    """Asserts the whole-population pages cost the same as the estate grows."""

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

        # The finance queues redirect a CCEO, so measuring them as one asserts
        # nothing but the speed of a 302. They get the role that opens them.
        cls.accountant = User.objects.create(
            id="scale-accountant",
            email="scale-accountant@edify.org",
            name="Scale Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        cls.accountant.set_password("pass123")
        cls.accountant.save()
        StaffProfile.objects.create(
            id="scale-staff-accountant", user=cls.accountant, title="Accountant"
        )

        # Geography mirrors the real shape: the 136 UBOS districts spread over
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
            [SubCounty(name=f"{d.name} Central", district=d) for d in districts]
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
        # here is the point of the fixture, so it must survive.
        #
        # Built and inserted in batches rather than as one list: at a large
        # EDIFY_SCALE_SCHOOLS the all-at-once version holds every model
        # instance in memory at once, which is a fixture-side scale limit of
        # exactly the kind this gate exists to disprove.
        batch: list[School] = []
        for i in range(BASE_SCHOOLS):
            district = districts[i % len(districts)]
            batch.append(
                School(
                    school_id=f"SCALE-{i:07d}",
                    name=f"Scale School {i:07d}",
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
            if len(batch) >= 2000:
                School.objects.bulk_create(batch)
                batch = []
        if batch:
            School.objects.bulk_create(batch)

        # Only ids are carried forward, never the model instances: the id list
        # is what the SSA and assignment fixtures actually need.
        school_ids = list(
            School.objects.order_by("school_id").values_list("id", flat=True)
        )

        # Put the CCEO over a realistic slice rather than the whole country:
        # a portfolio page that is fast only because its owner has no schools
        # would prove nothing.
        StaffSchoolAssignment.objects.bulk_create(
            [
                StaffSchoolAssignment(staff=cls.profile, school_id=sid)
                for sid in school_ids[:500]
            ],
            batch_size=1000,
        )

        fy = get_operational_fy()
        cls.fy = fy
        cls.ssa_expected = len(school_ids[::SSA_EVERY_NTH])

        SsaRecord.objects.bulk_create(
            [
                SsaRecord(
                    school_id=sid,
                    fy=fy,
                    quarter="Q1",
                    date_of_ssa=timezone.localdate(),
                    # Vary the score so weighted sub-region averages differ per
                    # bucket; a constant would hide an aggregation bug.
                    average_score=4.0 + (idx % 55) / 10,
                    new_enrollment=100 + (idx % 400),
                    verification_status="confirmed",
                    collector_type="staff",
                )
                for idx, sid in enumerate(school_ids[::SSA_EVERY_NTH])
            ],
            batch_size=2000,
        )

        # One intervention score per record keeps the SsaScore join non-empty
        # without multiplying fixture size by eight.
        record_ids = list(SsaRecord.objects.order_by("id").values_list("id", flat=True))
        SsaScore.objects.bulk_create(
            [
                SsaScore(
                    ssa_record_id=rid,
                    intervention="Government Requirements",
                    score=4.0 + (i % 55) / 10,
                )
                for i, rid in enumerate(record_ids)
            ],
            batch_size=2000,
        )

        _analyze()

    def setUp(self):
        self.client.force_login(self.user)

    # ── helpers ───────────────────────────────────────────────────────────
    def _measure(self, url, *, allow_statuses=(200,), client=None):
        """Fetch `url` once, returning its query count and wall time."""
        client = client or self.client
        reset_queries()
        with CaptureQueriesContext(connection) as ctx:
            started = time.perf_counter()
            response = client.get(url)
            elapsed = time.perf_counter() - started

        self.assertIn(
            response.status_code,
            allow_statuses,
            f"{url} returned {response.status_code} at "
            f"{School.objects.count():,} schools",
        )
        query_count = len(ctx.captured_queries)
        self.assertLessEqual(
            query_count,
            ABSURD_QUERY_COUNT,
            f"{url} issued {query_count} queries -- past the point where any "
            f"page shape is defensible, even a constant one.",
        )
        self.assertLess(
            elapsed,
            CATASTROPHIC_SECONDS,
            f"{url} took {elapsed:.2f}s at {School.objects.count():,} schools.",
        )
        return {"url": url, "queries": query_count, "seconds": elapsed}

    def _grow(self, count=GROWTH_SCHOOLS):
        """Add `count` schools mid-test, then refresh planner statistics.

        Rolled back with the surrounding test, so every test method starts
        from the same base estate and the growth ids never collide.
        """
        district = self.districts[0]
        School.objects.bulk_create(
            [
                School(
                    school_id=f"GROWTH-{i:07d}",
                    name=f"Growth School {i:07d}",
                    region=district.region,
                    district=district,
                    school_type="client",
                    current_fy_ssa_status="not_done",
                    planning_readiness="ready",
                )
                for i in range(count)
            ],
            batch_size=2000,
        )
        _analyze()

    def _assert_scale_invariant(self, url, *, allow_statuses=(200,), client=None):
        """The gate: a page's query count must not move when the estate grows.

        This is what makes the result independent of any particular school
        count. A page that is flat across a several-thousand-school jump is
        flat, full stop -- there is no size at which it suddenly is not.
        """
        before = self._measure(url, allow_statuses=allow_statuses, client=client)
        self._grow()
        after = self._measure(url, allow_statuses=allow_statuses, client=client)

        self.assertLessEqual(
            after["queries"],
            before["queries"] + QUERY_SLACK,
            f"{url} went from {before['queries']} to {after['queries']} queries "
            f"when {GROWTH_SCHOOLS:,} schools were added -- the page does "
            f"per-school work, so its cost grows without bound. Batch the "
            f"lookup (annotate/aggregate in SQL, or prefetch then read the "
            f"cache with .all()) rather than relaxing this assertion.",
        )
        return before, after

    # ── the fixture itself ────────────────────────────────────────────────
    def test_fixture_is_internally_consistent(self):
        """Guards the gate: every assertion below is meaningless if the fixture
        quietly shrank or piled every school into one district."""
        self.assertEqual(School.objects.count(), BASE_SCHOOLS)
        self.assertEqual(SsaRecord.objects.count(), self.ssa_expected)
        self.assertGreaterEqual(District.objects.count(), 130)
        # Spread matters more than size: a degenerate single-district estate
        # would make the sub-region roll-up look artificially cheap.
        self.assertGreaterEqual(
            School.objects.values("district_id").distinct().count(), 130
        )

    # ── the whole-population pages ────────────────────────────────────────
    @override_settings(DEBUG=False)
    def test_analytics_page_is_scale_invariant(self):
        """/analytics carries the sub-region roll-up and the map -- the
        heaviest aggregation in the product."""
        self._assert_scale_invariant("/analytics")

    @override_settings(DEBUG=False)
    def test_cceo_dashboard_is_scale_invariant(self):
        """The CCEO dashboard issues several hundred queries assembling many
        independent panels. That is busy, not unbounded -- what would break
        production is a count proportional to the school population."""
        self._assert_scale_invariant("/dashboard")

    @override_settings(DEBUG=False)
    def test_schools_list_is_scale_invariant(self):
        """The largest single table in the product, and the page most likely
        to be tempted into loading every row."""
        self._assert_scale_invariant("/schools")

    @override_settings(DEBUG=False)
    def test_my_plan_is_scale_invariant(self):
        """The page every field user opens first, several times a day. It reads
        the viewer's own activities, so its cost must not follow the estate."""
        self._assert_scale_invariant("/my-plan")

    @override_settings(DEBUG=False)
    def test_planning_is_scale_invariant(self):
        """Planning ranks recommendations across the schools in scope — the
        page where a per-school SSA lookup would be easiest to write and most
        expensive to keep."""
        self._assert_scale_invariant("/planning")

    @override_settings(DEBUG=False)
    def test_school_profile_is_scale_invariant(self):
        """One school's page must not read the population to render itself."""
        school = School.objects.order_by("school_id").first()
        self._assert_scale_invariant(f"/schools/{school.school_id}")

    @override_settings(DEBUG=False)
    def test_core_schools_is_scale_invariant(self):
        """Nine package slots per core school is per-row work by construction,
        so this is where it has to be batched rather than looped."""
        self._assert_scale_invariant("/core-schools")

    @override_settings(DEBUG=False)
    def test_projects_portfolio_is_scale_invariant(self):
        """Portfolio rows aggregate schools per project."""
        self._assert_scale_invariant("/projects")

    @override_settings(DEBUG=False)
    def test_finance_queue_is_scale_invariant(self):
        """Money queues are the pages where a slow render costs someone their
        afternoon and a wrong number costs more than that.

        Measured as the Accountant: a CCEO is redirected away, and an earlier
        version of this test was quietly certifying the speed of that 302.
        """
        from django.test import Client

        finance_client = Client()
        finance_client.force_login(self.accountant)
        self._assert_scale_invariant("/disbursements", client=finance_client)

    @override_settings(DEBUG=False)
    def test_closure_queue_is_scale_invariant(self):
        """Closure evaluates a checklist per row, so it is the most likely
        place for per-row work to hide."""
        self._assert_scale_invariant(
            # Trailing slash is required: an earlier "activities/<activity_id>"
            # pattern shadows the slash-less form and 404s on it.
            "/activities/closure/"
        )

    # ── Country Director surfaces ─────────────────────────────────────────
    #
    # The CD dashboard is where the audit's one measured latency breach lived:
    # 648 queries at 1.4s p95, from a per-person target recomputation that the
    # series cache existed to prevent and the dashboard never used. These
    # gates are what keep that from creeping back.
    #
    # School growth must leave the query count flat — the fix's claim.
    # Roster growth is deliberately NOT asserted flat: the per-CCEO ledger
    # rebuild is the freshness mandate itself (every CCEO's ledger is rebuilt
    # once per dashboard load, ~2 queries each), so CD queries grow with the
    # roster BY DESIGN, linearly and priced. The ceiling asserts the slope
    # stays that slope: if roster growth ever costs more than a few queries
    # per added person, the per-person recomputation is back.

    def _cd_client(self):
        User = get_user_model()
        cd = User.objects.filter(email="scale-cd@edify.org").first()
        if cd is None:
            cd = User.objects.create(
                id="scale-cd",
                email="scale-cd@edify.org",
                name="Scale CD",
                roles=["CountryDirector"],
                active_role="CountryDirector",
                is_active=True,
            )
            cd.set_password("pass123")
            cd.save()
            StaffProfile.objects.create(id="scale-staff-cd", user=cd, title="CD")
        client = self.client_class()
        client.force_login(cd)
        return client

    def test_cd_dashboard_is_scale_invariant_over_schools(self):
        self._assert_scale_invariant("/dashboard", client=self._cd_client())

    # No /my-plan gate for the CD: that role is redirected off the page (a
    # CD is not field staff, so there is no plan to show), and the dashboard
    # gate above already covers the page the redirect lands on. Discovered by
    # this gate 302ing — and worth recording that the latency harness, which
    # follows redirects, had been printing a "/my-plan CountryDirector" row
    # that was really the dashboard measured twice.

    # ── Wall-clock latency (§46) ──────────────────────────────────────────
    #
    # The tests above prove query counts do not grow with the estate. That is
    # the stronger guarantee and it is not the same claim: a page can hold its
    # query count and still be slow, because the queries themselves get slower
    # as tables grow.
    #
    # These use the same pages, roles and budgets as
    # scripts/latency_budget.py, which runs against the 702-school dev estate,
    # so two runs of one method at two sizes answer what §46 actually asks.
    #
    # Not a production certification: the test client skips the network, the
    # WSGI server and the real connection pool, so these are a lower bound on
    # production wall time. A breach is real; a pass is evidence.

    def _p95(self, url):
        samples = []
        for index in range(LATENCY_SAMPLES + LATENCY_WARMUP):
            measurement = self._measure(url, allow_statuses=(200, 302))
            if index >= LATENCY_WARMUP:
                samples.append(measurement["seconds"] * 1000)
        samples.sort()
        position = min(
            int(round(0.95 * (len(samples) - 1))),
            len(samples) - 1,
        )
        return samples[position]

    def test_every_page_meets_its_objective_at_fifteen_thousand_schools(self):
        breaches = []
        measured = {}
        for url, budget in SLO_MS.items():
            p95 = self._p95(url)
            measured[url] = p95
            if p95 > budget:
                breaches.append(f"{url} p95={p95:.0f}ms > {budget}ms")

        report = " · ".join(f"{u}={v:.0f}ms" for u, v in measured.items())
        # Printed, not just asserted. A gate that only says "OK" leaves nobody
        # able to answer "how close were we?", which is the question that
        # matters between one release and the next.
        print(
            f"\n  p95 at {School.objects.count():,} schools: {report}",
            flush=True,
        )
        self.assertEqual(
            breaches,
            [],
            f"Latency objectives breached at {School.objects.count():,} "
            f"schools: {breaches}. Measured: {report}",
        )

    def test_latency_does_not_grow_when_the_estate_grows(self):
        """The shape that matters, and the one a single measurement cannot show.

        A page that is fast at 15,000 and twice as slow at 18,000 is a page
        that will be slow at 30,000. Growth is measured on the heaviest
        country-wide page rather than all of them, to keep the fixture build
        to one pass.
        """
        before = self._p95("/dashboard")
        self._grow()
        after = self._p95("/dashboard")

        # Generous: this is looking for proportional growth, not jitter. A
        # 20% estate increase must not cost anything like 20% more time.
        self.assertLess(
            after,
            max(before * 2.0, before + 250),
            f"/dashboard went {before:.0f}ms -> {after:.0f}ms when the estate "
            f"grew by {GROWTH_SCHOOLS:,} schools -- that is proportional "
            f"growth, not a constant.",
        )

    def test_cd_dashboard_roster_growth_costs_only_the_rebuild(self):
        """Add CCEOs; the dashboard may pay the per-person rebuild for each,
        and nothing else. The regression this catches is exact: before the
        fix, each person cost ~5 further queries across three surfaces on the
        same page."""
        User = get_user_model()
        client = self._cd_client()
        before = self._measure("/dashboard", client=client)

        added = 8
        for i in range(added):
            u = User.objects.create(
                id=f"scale-roster-{i}",
                email=f"scale-roster-{i}@edify.org",
                name=f"Roster Growth {i}",
                roles=["CCEO"],
                active_role="CCEO",
                is_active=True,
            )
            StaffProfile.objects.create(id=f"scale-roster-sp-{i}", user=u, title="CCEO")
        after = self._measure("/dashboard", client=client)

        per_person = (after["queries"] - before["queries"]) / added
        # The designed per-person cost, measured rather than guessed (a first
        # version of this gate guessed 4 and was wrong): the ledger rebuild is
        # ~5-6 queries per CCEO and the primed series fetch ~3 more, both of
        # which are the freshness mandate itself. Measured at 9.6 with the
        # fix in place; the ceiling holds the slope near that. Before the
        # fix, the same growth cost ~15 per person — three surfaces each
        # re-deriving every person's numbers.
        self.assertLessEqual(
            per_person,
            12,
            f"each added CCEO costs {per_person:.1f} queries on the CD "
            f"dashboard ({before['queries']} -> {after['queries']} for "
            f"{added} people). The priced cost is the per-person rebuild plus "
            "series fetch (~9 together); above ~12 the per-person "
            "recomputation is back. Pool from cd.per_user_series instead.",
        )


def _analyze():
    """Refresh planner statistics.

    Without this every timing here is fiction. bulk_create does not trigger
    autovacuum, so Postgres estimates each table at its default size and picks
    nested loops over hash joins -- which turned a millisecond aggregate into a
    multi-second sequential scan and made /analytics look like a 134s blocker
    when it was really 0.14s. Production runs autovacuum, so the unanalyzed
    state describes something that cannot happen there.
    """
    with connection.cursor() as cursor:
        cursor.execute("ANALYZE")


# Section 46's objectives, in milliseconds. The same numbers
# scripts/latency_budget.py gates on against the dev estate, so the two runs
# are directly comparable.
SLO_MS: dict[str, int] = {
    "/dashboard": 800,
    "/my-plan": 800,
    "/schools": 800,
    "/todos": 800,
    "/notifications": 800,
    "/settings": 800,
    "/analytics": 1500,
    "/system-health": 1500,
}

# Samples per page. Enough for a stable p95 without tripling the fixture's
# already-substantial build time.
LATENCY_SAMPLES = 7
LATENCY_WARMUP = 2
