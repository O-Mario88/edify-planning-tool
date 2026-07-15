"""Issue 4 of the audit — CD/PL/RVP analytics N+1 query fixes.

`district_heatmap`/`regional_summary` (CD), `district_performance`/
`cluster_performance` (PL), and `region_ranking` (RVP) used to run several
queries PER ROW (per district / per region) — up to ~5 queries x 136
districts for the CD heatmap alone. They now batch-fetch every ingredient
ONCE per call and group in Python, so query count no longer scales with the
number of districts/regions/clusters in scope.

Fixture: 2 regions (North with districts D1/D2, South with district D3), 3
schools (one per district) each with two confirmed annual SSA cycles, 2 PLs
(PL-North supervising CCEOs in D1+D2, PL-South supervising a CCEO in D3),
and completed+SF-ID'd activities so exec/verified/SF rates are non-trivial.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity
from apps.analytics.cd_analytics_service import CDAnalyticsService, resolve_cd_scope
from apps.analytics.pl_analytics_service import PLAnalyticsService, resolve_pl_scope
from apps.analytics.rvp_dashboard_service import (
    RVPDashboardService,
    _country_activities,
)
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

User = get_user_model()
FY, PREV = "2026", "2025"


class AnalyticsQueryPerformanceTest(TestCase):
    def setUp(self):
        self.north = Region.objects.create(name="North Region")
        self.south = Region.objects.create(name="South Region")
        self.d1 = District.objects.create(name="D1", region=self.north)
        self.d2 = District.objects.create(name="D2", region=self.north)
        self.d3 = District.objects.create(name="D3", region=self.south)

        self.pl_n, self.pl_n_sp = self._staff(
            "pln@t.org", "PL North", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.c1, self.c1_sp = self._staff("c1@t.org", "CCEO One", EdifyRole.CCEO.value)
        self.c2, self.c2_sp = self._staff("c2@t.org", "CCEO Two", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_n_sp, supervisee=self.c1_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_n_sp, supervisee=self.c2_sp
        )

        self.pl_s, self.pl_s_sp = self._staff(
            "pls@t.org", "PL South", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.c3, self.c3_sp = self._staff(
            "c3@t.org", "CCEO Three", EdifyRole.CCEO.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_s_sp, supervisee=self.c3_sp
        )

        self.sch_1 = self._school("S1", self.d1, ssa_done=True)
        self.sch_2 = self._school(
            "S2", self.d1, ssa_done=False
        )  # no SSA -> coverage < 100%
        self.sch_3 = self._school("S3", self.d2, ssa_done=True)
        self.sch_4 = self._school("S4", self.d3, ssa_done=True)
        StaffSchoolAssignment.objects.create(staff=self.c1_sp, school_id=self.sch_1.id)
        StaffSchoolAssignment.objects.create(staff=self.c1_sp, school_id=self.sch_2.id)
        StaffSchoolAssignment.objects.create(staff=self.c2_sp, school_id=self.sch_3.id)
        StaffSchoolAssignment.objects.create(staff=self.c3_sp, school_id=self.sch_4.id)

        # Two confirmed annual SSA cycles per SSA'd school (D1's sch_1 has a
        # DIFFERENT leadership score than its overall average -- exercises the
        # multi-intervention grouping, not just a single flat number).
        self._ssa(self.sch_1, PREV, 5.0, {"leadership": 4.0, "enrolment": 6.0})
        self._ssa(self.sch_1, FY, 7.0, {"leadership": 6.0, "enrolment": 8.0})
        self._ssa(self.sch_3, PREV, 6.0, {"leadership": 6.0})
        self._ssa(self.sch_3, FY, 6.0, {"leadership": 6.0})
        self._ssa(self.sch_4, PREV, 4.0, {"leadership": 4.0})
        self._ssa(self.sch_4, FY, 8.0, {"leadership": 8.0})
        # An UNCONFIRMED record with a wild score -- must never be counted.
        self._ssa(self.sch_1, FY, 0.5, {"leadership": 0.5}, status="pending")

        self._act(self.c1_sp.id, self.sch_1, "completed", sf="SF-1")
        self._act(self.c1_sp.id, self.sch_2, "completed", sf="")  # no SF id
        self._act(self.c2_sp.id, self.sch_3, "completed", sf="SF-3")
        self._act(self.c3_sp.id, self.sch_4, "completed", sf="SF-4")

    def _staff(self, email, name, role):
        u = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        return u, StaffProfile.objects.create(user=u, title=role)

    def _school(self, sid, district, ssa_done):
        return School.objects.create(
            school_id=f"S-{sid}",
            name=f"School {sid}",
            region=district.region,
            district=district,
            enrollment=100,
            current_fy_ssa_status="done" if ssa_done else "not_done",
        )

    def _ssa(self, school, fy, avg, scores, status="confirmed"):
        rec = SsaRecord.objects.create(
            school=school,
            fy=fy,
            quarter="Q1",
            average_score=avg,
            verification_status=status,
            date_of_ssa=date(int(fy) - 1, 11, 1),
            uploaded_by="test",
        )
        for interv, sc in scores.items():
            SsaScore.objects.create(ssa_record=rec, intervention=interv, score=sc)
        return rec

    def _act(self, sp_id, school, status, sf=""):
        return Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="staff",
            status=status,
            responsible_staff_id=sp_id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            evidence_status="accepted",
            salesforce_activity_id=sf,
        )

    # ── 1. CD region ranking ─────────────────────────────────────────────────
    def test_cd_region_ranking_query_count_is_bounded(self):
        cd = resolve_cd_scope(FY)
        with CaptureQueriesContext(connection) as ctx:
            rows = CDAnalyticsService.regional_summary(cd)["rows"]
        self.assertEqual({r["name"] for r in rows}, {"North Region", "South Region"})
        self.assertLessEqual(
            len(ctx.captured_queries),
            12,
            f"regional_summary ran {len(ctx.captured_queries)} queries for 2 regions -- "
            "should be a small constant, not O(regions).",
        )

    # ── 2. CD district ranking ───────────────────────────────────────────────
    def test_cd_district_ranking_query_count_is_bounded(self):
        cd = resolve_cd_scope(FY)
        with CaptureQueriesContext(connection) as ctx:
            rows = CDAnalyticsService.district_heatmap(cd)["rows"]
        self.assertEqual({r["id"] for r in rows}, {self.d1.id, self.d2.id, self.d3.id})
        queries_for_3 = len(ctx.captured_queries)
        self.assertLessEqual(
            queries_for_3,
            12,
            f"district_heatmap ran {queries_for_3} queries for 3 districts -- "
            "should be a small constant, not O(districts).",
        )

        # Stronger proof: triple the district count and confirm the query
        # count does NOT grow (the pre-fix code ran ~5 queries PER district).
        d4 = District.objects.create(name="D4", region=self.north)
        d5 = District.objects.create(name="D5", region=self.north)
        d6 = District.objects.create(name="D6", region=self.south)
        for i, d in enumerate((d4, d5, d6), start=5):
            s = self._school(f"S{i}", d, ssa_done=True)
            self._ssa(s, FY, 6.0, {"leadership": 6.0})
        cd2 = resolve_cd_scope(FY)
        with CaptureQueriesContext(connection) as ctx2:
            rows2 = CDAnalyticsService.district_heatmap(cd2)["rows"]
        self.assertEqual(len(rows2), 6)
        self.assertEqual(
            len(ctx2.captured_queries),
            queries_for_3,
            "query count grew when the district count doubled -- district_heatmap "
            "is still querying per-district somewhere.",
        )

    # ── 3. PL "region" (cluster-tier) ranking ────────────────────────────────
    def test_pl_region_ranking_query_count_is_bounded(self):
        """PL Analytics has no region-level view (a PL's team sits below a
        region) -- cluster_performance is the PL's other geographic ranking
        table (clusters, the tier above district within a team) and had the
        same per-row N+1 shape, so it's the PL-scope analogue tested here."""
        from apps.clusters.models import Cluster

        Cluster.objects.create(
            id="cl-1", name="Cluster 1", region=self.north, district=self.d1
        )
        School.objects.filter(id__in=[self.sch_1.id, self.sch_2.id]).update(
            cluster_id="cl-1",
            cluster_status="clustered",
        )
        pls = resolve_pl_scope(self.pl_n)
        with CaptureQueriesContext(connection) as ctx:
            rows = PLAnalyticsService.cluster_performance(pls, FY, None, {})["rows"]
        self.assertEqual([r["id"] for r in rows], ["cl-1"])
        self.assertLessEqual(
            len(ctx.captured_queries),
            12,
            f"cluster_performance ran {len(ctx.captured_queries)} queries for 1 cluster.",
        )

    # ── 4. PL district ranking ───────────────────────────────────────────────
    def test_pl_district_ranking_query_count_is_bounded(self):
        pls = resolve_pl_scope(self.pl_n)  # supervises CCEOs in D1 + D2
        with CaptureQueriesContext(connection) as ctx:
            rows = PLAnalyticsService.district_performance(pls, FY, None, {})["rows"]
        self.assertEqual({r["id"] for r in rows}, {self.d1.id, self.d2.id})
        self.assertLessEqual(
            len(ctx.captured_queries),
            12,
            f"district_performance ran {len(ctx.captured_queries)} queries for 2 districts.",
        )

    # ── 5. RVP country (region) ranking ──────────────────────────────────────
    def test_rvp_country_ranking_query_count_is_bounded(self):
        cd = resolve_cd_scope(FY)
        acts = _country_activities(cd)
        with CaptureQueriesContext(connection) as ctx:
            rows = RVPDashboardService.region_ranking(cd, acts, FY)
        self.assertEqual({r["name"] for r in rows}, {"North Region", "South Region"})
        self.assertLessEqual(
            len(ctx.captured_queries),
            12,
            f"region_ranking ran {len(ctx.captured_queries)} queries for 2 regions -- "
            "should be a small constant, not O(regions).",
        )

    # ── 6. Aggregations don't duplicate rows ─────────────────────────────────
    def test_analytics_aggregations_do_not_duplicate_rows(self):
        """D1 has 2 schools, only 1 with confirmed SSA -- coverage must read
        exactly '1 of 2', not inflated by a school somehow being counted
        twice (the batched rewrite groups by dict-of-sets, which naturally
        dedupes; a bug here would double-count)."""
        cd = resolve_cd_scope(FY)
        rows = {r["id"]: r for r in CDAnalyticsService.district_heatmap(cd)["rows"]}
        d1_row = rows[self.d1.id]
        self.assertEqual(d1_row["coverage"], "1 of 2")
        self.assertEqual(d1_row["coverage_pct"], 50)

    # ── 7. Totals match the real underlying records ──────────────────────────
    def test_analytics_totals_match_source_records(self):
        """The batched Python-side mean() must exactly match a hand-computed
        average of the real SsaRecord rows -- not an approximation."""
        cd = resolve_cd_scope(FY)
        rows = {r["id"]: r for r in CDAnalyticsService.district_heatmap(cd)["rows"]}
        # D2 has exactly one confirmed FY2026 record (sch_3, avg_score=6.0).
        expected_avg = round(6.0 * 10, 1)  # _norm scales 0-10 -> 0-100
        self.assertEqual(rows[self.d2.id]["avg"], expected_avg)

        regional_rows = {
            r["id"]: r for r in CDAnalyticsService.regional_summary(cd)["rows"]
        }
        # South region's only confirmed FY2026 record is sch_4, avg_score=8.0.
        self.assertEqual(regional_rows[self.south.id]["avg_ssa"], round(8.0 * 10, 1))

        # Cross-check against a raw DB aggregate, independent of the service.
        from django.db.models import Avg

        raw = SsaRecord.objects.filter(
            school_id=self.sch_4.id,
            verification_status="confirmed",
            fy=FY,
        ).aggregate(a=Avg("average_score"))["a"]
        self.assertEqual(regional_rows[self.south.id]["avg_ssa"], round(raw * 10, 1))

    # ── 8. Scope narrowing survives the batched rewrite ──────────────────────
    def test_analytics_scope_is_preserved_after_optimization(self):
        """Filtering the CD scope to district D1 must still narrow every
        batched aggregation to D1 only -- the rewrite fetches from
        cd.school_ids, so a scope leak would mean it started reading beyond
        that set."""
        cd_all = resolve_cd_scope(FY)
        cd_d1 = resolve_cd_scope(FY, filters={"district": self.d1.id})

        heatmap_all = {
            r["id"] for r in CDAnalyticsService.district_heatmap(cd_all)["rows"]
        }
        heatmap_d1 = {
            r["id"] for r in CDAnalyticsService.district_heatmap(cd_d1)["rows"]
        }
        self.assertEqual(heatmap_all, {self.d1.id, self.d2.id, self.d3.id})
        self.assertEqual(heatmap_d1, {self.d1.id})

        regional_all = {
            r["id"] for r in CDAnalyticsService.regional_summary(cd_all)["rows"]
        }
        regional_d1 = {
            r["id"] for r in CDAnalyticsService.regional_summary(cd_d1)["rows"]
        }
        self.assertEqual(regional_all, {self.north.id, self.south.id})
        self.assertEqual(
            regional_d1, {self.north.id}
        )  # South never appears once scoped to D1

        acts_d1 = _country_activities(cd_d1)
        region_ranking_d1 = {
            r["name"]: r["schools"]
            for r in RVPDashboardService.region_ranking(cd_d1, acts_d1, FY)
        }
        self.assertEqual(region_ranking_d1, {"North Region": 2})  # only D1's 2 schools
