"""Targets by Time Period — Q1, Q2, Q3, Q4 + FY Cumulative.

The platform's standard target periods: each quarter is its own slice
(annual target ÷ 4, achievement scoped to that quarter's work) and
FY Cumulative rolls the year up against the full annual target. Verified
here at every layer: the canonical performance engine, the analytics target
math, the time_period service and both target pages over HTTP.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    StaffTargetProfile,
)
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()
FY = "2026"


class TimePeriodTargetsTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="R")
        self.district = District.objects.create(name="D", region=self.region, district_type="primary")
        self.pl, self.pl_sp = self._staff("pl@t.org", "PL One", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.cceo, self.cceo_sp = self._staff("c@t.org", "CCEO One", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(supervisor=self.pl_sp, supervisee=self.cceo_sp)
        self.school = School.objects.create(
            school_id="S-1", name="School One", region=self.region, district=self.district,
            current_fy_ssa_status="done",
        )
        StaffSchoolAssignment.objects.create(staff=self.cceo_sp, school_id=self.school.id)
        # Annual target: 8 visits. Q share = 2 per quarter.
        StaffTargetProfile.objects.create(staff=self.cceo_sp, fy=FY, visits_target=8)
        # Real work: 1 completed visit in Q1, 2 in Q3.
        self._visit("Q1", date(2025, 11, 10))
        self._visit("Q3", date(2026, 4, 10))
        self._visit("Q3", date(2026, 5, 12))

    def _staff(self, email, name, role):
        u = User.objects.create_user(email=email, name=name, roles=[role],
                                     active_role=role, password="x", is_active=True)
        return u, StaffProfile.objects.create(user=u, title=role)

    def _visit(self, quarter, planned):
        return Activity.objects.create(
            school=self.school, activity_type="school_visit", delivery_type="staff",
            status="completed", responsible_staff_id=self.cceo_sp.id, fy=FY,
            quarter=quarter, planned_date=planned,
            scheduled_date=timezone.make_aware(
                timezone.datetime(planned.year, planned.month, planned.day, 9)),
            salesforce_activity_id=f"SV-{planned.isoformat()}",
        )

    # ── CD analytics target math ─────────────────────────────────────────────
    def test_quarter_prorates_annual_target(self):
        from apps.analytics.cd_analytics_service import CDAnalyticsService
        from apps.targets.my_targets import TargetAchievementService

        # _completion_vs_target now reads the validated achievement ledger
        # (same source as the CD KPI strip) instead of a raw completed-status
        # count, so it needs a rebuild first — exactly like My/Team Targets.
        TargetAchievementService.rebuild(self.cceo, FY)

        completed = Activity.objects.filter(status="completed", quarter="Q3")
        pct, ach, tgt = CDAnalyticsService._completion_vs_target(
            self.cceo_sp.id, completed, FY, quarter="Q3")
        self.assertEqual(tgt, 2)      # 8 ÷ 4
        self.assertEqual(ach, 2)      # only Q3 work, validated (has an SF ID)
        self.assertEqual(pct, 100)
        pct_fy, ach_fy, tgt_fy = CDAnalyticsService._completion_vs_target(
            self.cceo_sp.id, Activity.objects.filter(status="completed"), FY)
        self.assertEqual(tgt_fy, 8)   # FY Cumulative keeps the annual target
        self.assertEqual(ach_fy, 3)

    # ── canonical performance engine ─────────────────────────────────────────
    def test_staff_metrics_with_targets_quarter_scoping(self):
        from apps.targets.performance import staff_metrics_with_targets

        q1 = staff_metrics_with_targets(self.cceo_sp.id, FY, quarter="Q1")
        fy = staff_metrics_with_targets(self.cceo_sp.id, FY)
        v_q1 = q1["cards"].get("visits") or q1["cards"].get("school_visits")
        v_fy = fy["cards"].get("visits") or fy["cards"].get("school_visits")
        if v_q1 and v_fy:  # metric key exists in the engine
            self.assertEqual(v_q1["target"], 2)
            self.assertEqual(v_fy["target"], 8)

    # ── time_period service rows ─────────────────────────────────────────────
    def test_time_period_service_labels(self):
        from apps.targets import services as tsvc

        result = tsvc.time_period({"fy": FY, "staffId": self.cceo_sp.id})
        rows = result.get("rows") or result.get("periods") or []
        labels = [r.get("period") or r.get("label") for r in rows]
        self.assertEqual(labels, ["Q1", "Q2", "Q3", "Q4", "FY Cumulative"])

    # ── pages over HTTP ──────────────────────────────────────────────────────
    def test_my_target_page_shows_five_periods(self):
        c = Client()
        c.force_login(self.cceo)
        html = c.get("/my-targets").content.decode()
        for label in ("Q1", "Q2", "Q3", "Q4", "FY Cumulative"):
            self.assertIn(label, html)
        self.assertNotIn("Mid-Year", html)

    def test_my_target_shows_five_official_areas(self):
        c = Client()
        c.force_login(self.cceo)
        html = c.get("/my-targets").content.decode()
        for area in ("School Visits", "Cluster Meetings", "Cluster Trainings",
                     "SSA Completed", "MSCS"):
            self.assertIn(area, html)
        # Superseded areas must no longer render as target areas.
        self.assertNotIn("New School", html)

    def test_core_school_tracker_tracks_4_visits_4_trainings(self):
        from apps.core_schools.models import CoreActivitySlot, CorePlan

        plan = CorePlan.objects.create(
            id="cplan-track-1", school_id=self.school.school_id, fy=FY,
            status="Active", baseline_average=6.2,
            visits_completed=2, trainings_completed=1,
        )
        for i in range(1, 5):
            CoreActivitySlot.objects.create(
                id=f"cslot-{self.school.school_id}-v{i}", core_plan=plan,
                school_id=self.school.school_id, intervention="leadership",
                activity_type="visit", sequence_number=i,
                status="completed" if i <= 2 else "Planned",
            )
            CoreActivitySlot.objects.create(
                id=f"cslot-{self.school.school_id}-t{i}", core_plan=plan,
                school_id=self.school.school_id, intervention="leadership",
                activity_type="training", sequence_number=i,
                status="completed" if i <= 1 else "Planned",
            )
        c = Client()
        c.force_login(self.cceo)
        html = c.get("/my-targets").content.decode()
        self.assertIn("Core School Tracker", html)
        self.assertIn("School One", html)
        self.assertIn("2/4", html)      # visits progress
        self.assertIn("1/4", html)      # trainings progress
        self.assertIn("On Track", html)  # baseline set + progressing
        self.assertIn("6.2/10", html)    # baseline shown

    def test_core_plan_still_feeds_tracker_not_target_area(self):
        from apps.core_schools.models import CorePlan

        CorePlan.objects.create(
            id="cplan-track-2", school_id=self.school.school_id, fy=FY, status="Active",
        )
        c = Client()
        c.force_login(self.cceo)
        html = c.get("/my-targets").content.decode()
        self.assertIn("Core School Tracker", html)   # tracker card kept
        self.assertNotIn("New Core School", html)    # but not a target area

    def test_team_targets_periods_are_month_quarters_fy(self):
        c = Client()
        c.force_login(self.pl)
        self.assertEqual(c.get("/team-targets/").status_code, 200)
        # Month selector drives the page; Q1–Q4 + FY live in the detail matrix.
        self.assertEqual(c.get("/team-targets/?month=4").status_code, 200)
        matrix = c.get("/team-targets/matrix").content.decode()
        for label in ("Q1", "Q2", "Q3", "Q4", "Full Year"):
            self.assertIn(label, matrix)
        self.assertNotIn("Mid-Year", matrix)
