"""CD / HR / RVP role dashboards — scope, queues and action tests.

The CD command dashboard is country-wide and oversight-only (approve/return,
review, escalate — never field execution). HR sees the real leave workflow.
RVP sees the country-budget approval chain. All three render over HTTP for
their role.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from freezegun import freeze_time

from apps.accounts.models import Leave, PublicHoliday, StaffProfile
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import WeeklyFundRequest
from apps.monthly_work_plan.models import MonthlyWorkPlanBudget

from apps.accounts.hr_dashboard_service import HRDashboardService
from apps.analytics.cd_dashboard_service import CDDashboardService
from apps.analytics.rvp_dashboard_service import RVPDashboardService

User = get_user_model()
FY = "2026"


def _staff(email, name, role):
    u = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    return u, StaffProfile.objects.create(user=u, title=role)


class RoleDashboardsTest(TestCase):
    def setUp(self):
        self.cd, _ = _staff("cd@t.org", "CD", EdifyRole.COUNTRY_DIRECTOR.value)
        self.rvp, _ = _staff(
            "rvp@t.org", "RVP", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )
        self.hr, self.hr_sp = _staff("hr@t.org", "HR", EdifyRole.HUMAN_RESOURCES.value)
        self.pl, self.pl_sp = _staff(
            "pl@t.org", "PL One", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cceo, self.cceo_sp = _staff("c@t.org", "CCEO One", EdifyRole.CCEO.value)

    # ── CD command dashboard ─────────────────────────────────────────────────
    def test_cd_dashboard_surfaces_escalated_requests_and_approves(self):
        wfr = WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 7, 13),
            week_end_date=date(2026, 7, 19),
            responsible_user=self.pl.id,
            total_amount=250_000,
            status="submitted_to_cd",
        )
        d = CDDashboardService.get_dashboard(self.cd, fy=FY)
        by = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        self.assertEqual(d["finance_snapshot"]["pending_count"], 1)
        self.assertEqual(d["finance_snapshot"]["pending_rows"][0]["team"], "PL One")
        # Approve through the dashboard endpoint (the guarded service path).
        c = Client()
        c.force_login(self.cd)
        resp = c.post(f"/dashboard/cd-approve?id={wfr.id}&fy={FY}")
        self.assertEqual(resp.status_code, 200)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "confirmed_for_advance")
        d2 = CDDashboardService.get_dashboard(self.cd, fy=FY)
        self.assertEqual(
            d2["finance_snapshot"]["pending_count"], 0
        )  # queue auto-clears

    def test_cd_dashboard_budget_stage_reads_monthly_budget(self):
        MonthlyWorkPlanBudget.objects.create(
            fy=FY,
            month_key="2026-08",
            status="submitted_to_rvp",
            total_amount=5_000_000,
        )
        d = CDDashboardService.get_dashboard(self.cd, fy=FY)
        self.assertEqual(d["budget_stage"]["label"], "With RVP")
        self.assertEqual(d["budget_stage"]["month"], "2026-08")

    def test_cd_dashboard_has_no_field_execution_actions(self):
        d = CDDashboardService.get_dashboard(self.cd, fy=FY)
        banned = ("schedule visit", "start activity", "upload evidence", "enter sf")
        for q in d["quick_actions"]:
            self.assertFalse(any(b in q["label"].lower() for b in banned), q["label"])

    def test_only_cd_can_use_cd_approve_endpoint(self):
        c = Client()
        c.force_login(self.pl)
        self.assertEqual(c.post("/dashboard/cd-approve?id=x").status_code, 403)

    # ── HR dashboard ─────────────────────────────────────────────────────────
    @freeze_time("2026-08-03")  # fixed Monday, mid-FY2026 — REG-02 §1.1
    def test_hr_dashboard_counts_real_leave_workflow(self):
        Leave.objects.create(
            staff=self.cceo_sp,
            type="annual",
            status="pending",
            days=3,
            start_date=(date.today() + timedelta(days=3)).isoformat(),
            end_date=(date.today() + timedelta(days=5)).isoformat(),
        )
        Leave.objects.create(
            staff=self.pl_sp,
            type="annual",
            status="approved",
            days=1,
            start_date=date.today().isoformat(),
            end_date=date.today().isoformat(),
        )
        PublicHoliday.objects.create(
            name="Independence Day", date=date.today() + timedelta(days=30)
        )
        d = HRDashboardService.get_dashboard(self.hr)
        by = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        self.assertEqual(by["Pending Leave Approvals"], "1")
        self.assertEqual(by["On Leave Today"], "1")
        self.assertEqual(d["holidays"][0]["name"], "Independence Day")
        self.assertTrue(any(r["count"] for r in d["roles"]))

    @freeze_time("2026-08-03")  # fixed Monday, mid-FY2026 — REG-02 §1.1
    def test_hr_coverage_clash_requires_scheduled_work(self):
        from django.utils import timezone as tz
        from apps.activities.models import Activity
        from apps.geography.models import District, Region
        from apps.schools.models import School

        region = Region.objects.create(name="R")
        district = District.objects.create(
            name="D", region=region, district_type="primary"
        )
        school = School.objects.create(
            school_id="S-1", name="S1", region=region, district=district
        )
        lv_start = date.today() + timedelta(days=2)
        Leave.objects.create(
            staff=self.cceo_sp,
            type="annual",
            status="approved",
            days=2,
            start_date=lv_start.isoformat(),
            end_date=(lv_start + timedelta(days=1)).isoformat(),
        )
        d = HRDashboardService.get_dashboard(self.hr)
        self.assertEqual(
            {k["label"]: k["value"] for k in d["kpi_strip_items"]}[
                "Coverage Clashes (7d)"
            ],
            "0",
        )  # leave alone is not a clash
        Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            responsible_staff_id=self.cceo_sp.id,
            fy=FY,
            quarter="Q4",
            planned_date=lv_start,
            scheduled_date=tz.make_aware(
                tz.datetime(lv_start.year, lv_start.month, lv_start.day, 9)
            ),
        )
        d2 = HRDashboardService.get_dashboard(self.hr)
        self.assertEqual(
            {k["label"]: k["value"] for k in d2["kpi_strip_items"]}[
                "Coverage Clashes (7d)"
            ],
            "1",
        )

    # ── RVP dashboard ────────────────────────────────────────────────────────
    def test_rvp_dashboard_queues_submitted_budgets(self):
        MonthlyWorkPlanBudget.objects.create(
            fy=FY,
            month_key="2026-08",
            status="submitted_to_rvp",
            program_total=4_000_000,
            admin_total=1_000_000,
            total_amount=5_000_000,
            activity_count=40,
        )
        MonthlyWorkPlanBudget.objects.create(
            fy=FY,
            month_key="2026-07",
            status="approved_by_rvp",
            total_amount=3_000_000,
        )
        d = RVPDashboardService.get_dashboard(self.rvp, fy=FY)
        by = {k["label"]: k for k in d["kpi_strip_items"]}
        # The KPI headline is the pending amount; the count lives in the helper.
        pending = by["Monthly Budget Pending Approval"]
        self.assertIn("5.0M", pending["value"])
        self.assertIn("1 budget", pending["helper"])
        self.assertEqual(len(d["awaiting_rows"]), 1)
        self.assertEqual(d["awaiting_rows"][0]["month"], "2026-08")
        approved = [r for r in d["budget_snapshot"]["recent_decisions"]]
        self.assertEqual(d["budget_snapshot"]["approved_fy_count"], 1)

    def test_rvp_dashboard_rebuilds_stale_target_ledger(self):
        """RVP rolls up CDAnalyticsService._weighted_overall — the achievement
        ledger must be fresh before that read, exactly like the CD dashboard
        (mandate §7: RVP inherits the CD staleness gap since it reuses the
        same rollup)."""
        from django.utils import timezone as tz

        from apps.accounts.models import (
            StaffSchoolAssignment,
            StaffSupervisorAssignment,
            StaffTargetProfile,
        )
        from apps.activities.models import Activity
        from apps.geography.models import District, Region
        from apps.schools.models import School
        from apps.targets.models import TargetAchievementLedger

        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )
        region = Region.objects.create(name="R-RVP")
        district = District.objects.create(
            name="D-RVP", region=region, district_type="primary"
        )
        school = School.objects.create(
            school_id="S-RVP",
            name="RVP School",
            region=region,
            district=district,
            current_fy_ssa_status="done",
        )
        StaffSchoolAssignment.objects.create(staff=self.cceo_sp, school_id=school.id)
        StaffTargetProfile.objects.create(staff=self.cceo_sp, fy=FY, visits_target=2)
        Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="staff",
            # IA-verified so it credits the target ledger (§8).
            status="ia_verified",
            responsible_staff_id=self.cceo_sp.id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            scheduled_date=tz.make_aware(tz.datetime(2026, 4, 10, 9, 0)),
            salesforce_activity_id="SV-RVP-1",
        )

        # Never called TargetAchievementService.rebuild() manually.
        self.assertFalse(
            TargetAchievementLedger.objects.filter(user_id=self.cceo.id).exists()
        )
        d = RVPDashboardService.get_dashboard(self.rvp, fy=FY)
        self.assertTrue(
            TargetAchievementLedger.objects.filter(
                user_id=self.cceo.id, fy=FY, validation_status="validated"
            ).exists()
        )
        by = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        # 1 validated of 2 targeted visits → 50%, computed from the freshly
        # rebuilt ledger, not silently read as 0 from a never-built one.
        self.assertEqual(by["Regional Target Achievement"], "50%")

    # ── HTTP smoke for all three roles ───────────────────────────────────────
    def test_dashboards_render_over_http_for_each_role(self):
        c = Client()
        for user, marker in [
            (self.cd, "Country Director Dashboard"),
            (self.hr, "HR Director Dashboard"),
            (self.rvp, "Regional Vice President Dashboard"),
        ]:
            c.force_login(user)
            resp = c.get("/dashboard")
            self.assertEqual(resp.status_code, 200, user.email)
            self.assertIn(marker, resp.content.decode())
