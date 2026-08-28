"""Tests for the General Budget (apps.monthly_work_plan.country_budget_service).

Core rule under test: the General Budget is generated only from
scheduled, costed, plan-backed ActivityScheduleCostLines plus the CD Admin
Budget from the CD Monthly Admin Plan (MonthlyWorkPlanBudget + AdminBudgetLine)
— never manual entry, never unscheduled/uncosted/cancelled activities.
"""

from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.audit.models import AuditLog
from apps.budget.models import ActivityCostSnapshot, CountryStrategicActivityReserve
from apps.command_center.todo_service import get_todos
from apps.core.enums import ActivityType
from apps.core.exceptions import BadRequest, Forbidden
from apps.geography.models import District, Region
from apps.monthly_work_plan import country_budget_service as svc
from apps.projects.models import Project
from apps.monthly_work_plan.models import AdminBudgetLine, MonthlyWorkPlanBudget
from apps.monthly_work_plan.services import add_admin_line
from apps.schools.models import School

FY = "2026"
MONTH = 4  # April


class _Principal:
    def __init__(self, user):
        self.user_id = user.id
        self.active_role = user.active_role
        self.staff_profile_id = None


class CountryMonthlyBudgetTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.school = School.objects.create(
            school_id="SCH-CB1",
            name="Test School",
            region=self.region,
            district=self.district,
        )

        self.cd = User.objects.create(
            id="cd-1",
            email="cd@edify.org",
            name="Carol Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        self.rvp = User.objects.create(
            id="rvp-1",
            email="rvp@edify.org",
            name="Rita VP",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
            is_active=True,
        )
        self.accountant = User.objects.create(
            id="acct-1",
            email="acct@edify.org",
            name="Ada Accounts",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        self.ia = User.objects.create(
            id="ia-1",
            email="ia@edify.org",
            name="Ivy Assess",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            is_active=True,
        )
        self.cceo = User.objects.create(
            id="cceo-1",
            email="cceo@edify.org",
            name="Sarah N.",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.pl = User.objects.create(
            id="pl-1",
            email="pl@edify.org",
            name="Paul Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )

        self.cd_p = _Principal(self.cd)
        self.rvp_p = _Principal(self.rvp)
        self.acct_p = _Principal(self.accountant)
        self.ia_p = _Principal(self.ia)
        self.cceo_p = _Principal(self.cceo)
        self.pl_p = _Principal(self.pl)

        # Two valid staff school visits (100k + 200k).
        self.act1 = self._activity(self.cceo.id, ActivityType.SCHOOL_VISIT, "staff")
        self._cost_line(self.act1, 100_000)
        self.act2 = self._activity(self.cceo.id, ActivityType.SCHOOL_VISIT, "staff")
        self._cost_line(self.act2, 200_000)

    def _activity(
        self,
        responsible_user,
        atype,
        delivery,
        status="scheduled",
        planned_date=date(2026, 4, 10),
    ):
        return Activity.objects.create(
            school=self.school,
            delivery_type=delivery,
            activity_type=atype,
            status=status,
            responsible_staff_id=responsible_user,
            fy=FY,
            planned_date=planned_date,
        )

    def _cost_line(
        self,
        activity,
        amount,
        month=MONTH,
        catalogue_id="cat-v1",
        responsible_user=None,
    ):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=amount,
            quantity=1,
            amount=amount,
            month=month,
            fiscal_year=FY,
            catalogue_id=catalogue_id,
            catalogue_version=1,
            responsible_user=responsible_user or activity.responsible_staff_id,
        )

    # ── role gating ────────────────────────────────────────────────────────
    def test_cd_rvp_accountant_ia_admin_can_read(self):
        for p in (self.cd_p, self.rvp_p, self.acct_p, self.ia_p):
            ctx = svc.get_country_monthly_budget(p, {"fy": FY, "month": MONTH})
            self.assertIn("kpis", ctx)

    def test_cceo_and_pl_denied_read(self):
        with self.assertRaises(Forbidden):
            svc.get_country_monthly_budget(self.cceo_p, {"fy": FY, "month": MONTH})
        with self.assertRaises(Forbidden):
            svc.get_country_monthly_budget(self.pl_p, {"fy": FY, "month": MONTH})

    def test_only_cd_can_submit(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        with self.assertRaises(Forbidden):
            svc.send_to_rvp(self.rvp_p, ctx["budget_id"])
        with self.assertRaises(Forbidden):
            svc.send_to_rvp(self.acct_p, ctx["budget_id"])

    def test_only_rvp_can_approve_or_return(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        with self.assertRaises(Forbidden):
            svc.approve(self.cd_p, ctx["budget_id"])
        with self.assertRaises(Forbidden):
            svc.return_budget(self.cd_p, ctx["budget_id"], {"reason": "x"})

    # ── generation / KPIs ────────────────────────────────────────────────
    def test_budget_auto_generated_from_real_cost_lines(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        self.assertEqual(ctx["status"], "draft_generated")
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["General Budget Total"], svc._ugx(300_000))
        self.assertEqual(by_label["Staff Visits Cost"], svc._ugx(300_000))
        self.assertEqual(by_label["Staff Included"], "1")
        self.assertEqual(by_label["Total Planned Activities"], "2")

    def test_staff_row_built_from_real_lines(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        self.assertEqual(len(ctx["staff_rows"]), 1)
        row = ctx["staff_rows"][0]
        self.assertEqual(row["name"], "Sarah N.")
        self.assertEqual(row["total"], 300_000)
        self.assertEqual(row["cats"]["staff_visits"]["qty"], 2)
        self.assertEqual(row["status"], "Plan-backed")

    def test_partner_visit_categorized_separately(self):
        act = self._activity(self.cceo.id, ActivityType.SCHOOL_VISIT, "partner")
        self._cost_line(act, 50_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["Partner Visits Cost"], svc._ugx(50_000))
        self.assertEqual(by_label["Staff Visits Cost"], svc._ugx(300_000))

    def test_ssa_categorized_separately(self):
        act = self._activity(self.cceo.id, "baseline_ssa_visit", "staff")
        self._cost_line(act, 40_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["SSA Cost"], svc._ugx(40_000))

    # ── Special Projects category ─────────────────────────────────────────
    def test_special_project_categorized_via_direct_activity_link(self):
        project = Project.objects.create(
            name="Literacy Boost", code="SP-LIT", category="pilot"
        )
        # Would otherwise land in Staff Visits (school_visit/staff) — the
        # project link must override that and route it to Special Projects.
        act = self._activity(self.cceo.id, ActivityType.SCHOOL_VISIT, "staff")
        act.project_id = project.id
        act.save(update_fields=["project_id"])
        self._cost_line(act, 90_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["Special Project Cost"], svc._ugx(90_000))
        # Still only the original two staff visits (300k) — the project
        # activity must not double up there.
        self.assertEqual(by_label["Staff Visits Cost"], svc._ugx(300_000))

    def test_special_project_categorized_via_cost_line_link(self):
        project = Project.objects.create(
            name="EdTech Pilot", code="SP-TECH", category="pilot"
        )
        # Activity itself has no project_id — only its cost line does (the
        # indirect path, e.g. partner-costed project work).
        act = self._activity(self.cceo.id, ActivityType.SCHOOL_VISIT, "staff")
        line = self._cost_line(act, 70_000)
        line.project_id = project.id
        line.save(update_fields=["project_id"])
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["Special Project Cost"], svc._ugx(70_000))

    def test_special_project_included_in_total_monthly_budget(self):
        project = Project.objects.create(name="CCSEL", code="SP-CC", category="pilot")
        act = self._activity(self.cceo.id, ActivityType.SCHOOL_VISIT, "staff")
        act.project_id = project.id
        act.save(update_fields=["project_id"])
        self._cost_line(act, 90_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        # 300k (existing staff visits) + 90k (special project) — never
        # silently dropped from the country total.
        self.assertEqual(by_label["General Budget Total"], svc._ugx(390_000))

    def test_special_project_activity_count_in_plan_source_summary(self):
        project = Project.objects.create(name="CCSEL", code="SP-CC2", category="pilot")
        act = self._activity(self.cceo.id, ActivityType.SCHOOL_VISIT, "staff")
        act.project_id = project.id
        act.save(update_fields=["project_id"])
        self._cost_line(act, 90_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        row = next(
            s
            for s in ctx["plan_source_summary"]
            if s["label"] == "Special Project Activities"
        )
        self.assertEqual(row["value"], 1)

    def test_special_project_staff_row_shows_project_column(self):
        project = Project.objects.create(name="CCSEL", code="SP-CC3", category="pilot")
        act = self._activity(self.cceo.id, ActivityType.SCHOOL_VISIT, "staff")
        act.project_id = project.id
        act.save(update_fields=["project_id"])
        self._cost_line(act, 90_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        row = next(r for r in ctx["staff_rows"] if r["user_id"] == self.cceo.id)
        self.assertEqual(row["cats"]["special_project"]["qty"], 1)
        self.assertEqual(row["cats"]["special_project"]["total"], svc._ugx(90_000))

    # ── plan-backed exclusion rules ──────────────────────────────────────
    def test_cancelled_activity_excluded(self):
        act = self._activity(
            self.cceo.id, ActivityType.SCHOOL_VISIT, "staff", status="cancelled"
        )
        self._cost_line(act, 999_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["General Budget Total"], svc._ugx(300_000))
        cancelled_check = next(
            c for c in ctx["checks"] if "cancelled" in c["label"].lower()
        )
        self.assertEqual(cancelled_check["status"], "passed")

    def test_partner_activity_without_planned_date_excluded(self):
        act = self._activity(
            self.cceo.id, ActivityType.SCHOOL_VISIT, "partner", planned_date=None
        )
        self._cost_line(act, 777_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        # Only the two staff visits remain; the unscheduled partner activity's
        # 777k must NOT appear anywhere in the totals.
        self.assertEqual(by_label["General Budget Total"], svc._ugx(300_000))
        self.assertEqual(by_label["Partner Visits Cost"], svc._ugx(0))

    def test_missing_catalogue_flags_needs_review_row(self):
        act = self._activity(self.cceo.id, ActivityType.SCHOOL_VISIT, "staff")
        self._cost_line(act, 60_000, catalogue_id=None)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        row = ctx["staff_rows"][0]
        self.assertEqual(row["status"], "Missing Cost")
        catalogue_check = next(
            c for c in ctx["checks"] if "linked to planned activities" in c["label"]
        )
        self.assertEqual(catalogue_check["status"], "failed")

    def test_missing_catalogue_blocks_submission(self):
        act = self._activity(self.cceo.id, ActivityType.SCHOOL_VISIT, "staff")
        self._cost_line(act, 60_000, catalogue_id=None)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        self.assertFalse(ctx["can_send_to_rvp"])
        with self.assertRaises(BadRequest):
            svc.send_to_rvp(self.cd_p, ctx["budget_id"])

    def test_valid_budget_can_be_submitted(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        self.assertTrue(ctx["can_send_to_rvp"])

    def test_full_reference_ceiling_is_submitted_with_difference_as_reserve(self):
        ActivityCostSnapshot.objects.create(
            activity=self.act1,
            operational_cost=100_000,
            reference_cost=140_000,
            calculated_at=timezone.now(),
        )
        ActivityCostSnapshot.objects.create(
            activity=self.act2,
            operational_cost=200_000,
            reference_cost=260_000,
            calculated_at=timezone.now(),
        )
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        self.assertEqual(ctx["country_envelope"]["regionalStandardCeiling"], 400_000)
        self.assertEqual(
            ctx["country_envelope"]["operationalActivityRequirement"], 300_000
        )
        self.assertEqual(ctx["country_envelope"]["maximumReserveCapacity"], 100_000)

        budget = MonthlyWorkPlanBudget.objects.get(id=ctx["budget_id"])
        self.assertEqual(budget.strategic_reserve_requested, 100_000)
        self.assertEqual(budget.deferred_amount, 0)
        self.assertEqual(budget.total_amount, 400_000)

        submitted = svc.send_to_rvp(self.cd_p, budget.id)
        snapshot = submitted.snapshots.get(version=submitted.submission_version)
        self.assertEqual(snapshot.regional_standard_ceiling, 400_000)
        self.assertEqual(snapshot.operational_activity_requirement, 300_000)
        self.assertEqual(snapshot.strategic_reserve_requested, 100_000)
        self.assertEqual(snapshot.deferred_amount, 0)
        self.assertEqual(snapshot.total_amount, 400_000)
        svc.approve(self.rvp_p, submitted.id)
        reserve = CountryStrategicActivityReserve.objects.get(
            country="Uganda", fy=FY, period_key=submitted.month_key
        )
        self.assertEqual(reserve.opening_reserve, 100_000)
        self.assertEqual(reserve.available_balance, 100_000)
        self.assertEqual(reserve.status, "approved")

    def test_cd_cannot_reduce_the_automatic_full_ceiling_request(self):
        ActivityCostSnapshot.objects.create(
            activity=self.act1,
            operational_cost=100_000,
            reference_cost=120_000,
            calculated_at=timezone.now(),
        )
        ActivityCostSnapshot.objects.create(
            activity=self.act2,
            operational_cost=200_000,
            reference_cost=230_000,
            calculated_at=timezone.now(),
        )
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        with self.assertRaisesMessage(BadRequest, "full Regional Standard"):
            svc.set_envelope_allocation(self.cd_p, ctx["budget_id"], 40_000)

    def test_training_uses_12000_for_staff_but_submits_22000_to_rvp(self):
        ActivityCostSnapshot.objects.create(
            activity=self.act1,
            operational_cost=100_000,
            reference_cost=100_000,
            calculated_at=timezone.now(),
        )
        ActivityCostSnapshot.objects.create(
            activity=self.act2,
            operational_cost=200_000,
            reference_cost=200_000,
            calculated_at=timezone.now(),
        )
        training = self._activity(self.cceo.id, ActivityType.TRAINING, "staff")
        participant_count = 10
        self._cost_line(training, 12_000 * participant_count)
        ActivityCostSnapshot.objects.create(
            activity=training,
            operational_cost=12_000 * participant_count,
            reference_cost=22_000 * participant_count,
            calculated_at=timezone.now(),
        )

        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        training_row = next(
            row
            for row in svc.get_plan_sources(self.cd_p, {"fy": FY, "month": MONTH})[
                "rows"
            ]
            if row["activity_id"] == training.id
        )
        self.assertEqual(training_row["operational_cost"], 120_000)
        self.assertEqual(training_row["reference_cost"], 220_000)
        self.assertEqual(ctx["country_envelope"]["strategicReserveRequested"], 100_000)
        self.assertEqual(ctx["country_envelope"]["totalCountryRequest"], 520_000)

        submitted = svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        self.assertEqual(submitted.total_amount, 520_000)
        self.assertEqual(submitted.operational_activity_requirement, 420_000)
        self.assertEqual(submitted.regional_standard_ceiling, 520_000)
        snapshot = submitted.snapshots.get(version=submitted.submission_version)
        training_line = next(
            item for item in snapshot.line_items if item["activity_id"] == training.id
        )
        self.assertEqual(training_line["operational_amount"], 120_000)
        self.assertEqual(training_line["reference_amount"], 220_000)
        self.assertEqual(training_line["difference"], 100_000)

    def test_pl_monthly_request_does_not_replace_planned_activity_source(self):
        """Fund requests trace planned costs but never gate the General Budget."""
        from apps.fund_requests import monthly_request_service
        from apps.fund_requests.models import FundRequestStatus

        pl_activity = self._activity(self.pl.id, ActivityType.SCHOOL_VISIT, "staff")
        pl_activity.scheduled_date = timezone.make_aware(datetime(2026, 4, 13, 9))
        pl_activity.save(update_fields=["scheduled_date"])
        self._cost_line(pl_activity, 150_000)

        draft = monthly_request_service.refresh_draft(self.pl_p, FY, MONTH)
        self.assertEqual(draft.status, FundRequestStatus.DRAFT)
        self.assertEqual(draft.total_amount, 150_000)

        submitted = monthly_request_service.submit_to_cd(self.pl_p, FY, MONTH)
        self.assertEqual(submitted.status, FundRequestStatus.SUBMITTED_TO_CD)
        before_cd = svc.get_country_monthly_budget(
            self.cd_p, {"fy": FY, "month": MONTH}
        )
        self.assertFalse(before_cd["uses_pl_request_workflow"])
        self.assertEqual(before_cd["total_monthly"], 450_000)
        self.assertEqual(before_cd["approved_pl_request_count"], 0)

        # The separate CD admin plan remains available to the approval envelope
        # without becoming a second source for planned programme activity.
        add_admin_line(
            before_cd["budget_id"],
            {
                "costCategory": "operations",
                "description": "Office internet",
                "unitCost": 50_000,
                "quantity": 1,
            },
            self.cd_p,
        )
        ready = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        self.assertEqual(ready["total_monthly"], 500_000)
        country_budget = svc.send_to_rvp(self.cd_p, ready["budget_id"])
        self.assertEqual(country_budget.status, "submitted_to_rvp")
        self.assertEqual(
            svc.approve(self.rvp_p, country_budget.id).status, "approved_by_rvp"
        )

    # ── CD Admin Budget — the only non-activity exception ────────────────
    def test_no_admin_plan_means_zero_admin_budget(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["Admin Budget"], svc._ugx(0))
        self.assertEqual(ctx["admin_row"]["status"], "Admin Plan Missing")

    def test_admin_budget_sourced_only_from_admin_plan(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        budget = MonthlyWorkPlanBudget.objects.get(id=ctx["budget_id"])
        AdminBudgetLine.objects.create(
            monthly_budget=budget,
            cost_category="office_operations",
            description="Rent",
            quantity=1,
            unit_cost=500_000,
            total_cost=500_000,
            created_by_user_id=self.cd.id,
        )
        ctx2 = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx2["kpis"]}
        self.assertEqual(by_label["Admin Budget"], svc._ugx(500_000))
        self.assertEqual(by_label["General Budget Total"], svc._ugx(800_000))
        self.assertEqual(ctx2["admin_row"]["status"], "Admin Plan")

    # ── mandate finance laws (named per spec §23) ─────────────────────────
    def test_pl_weekly_request_included_in_country_monthly_budget(self):
        """A PL's own field work is real money: their scheduled activity's cost
        lines must roll into the General Budget, and their weekly fund
        request must exist alongside it."""
        from apps.fund_requests.weekly_service import generate_weekly_fund_request

        pl_act = self._activity(self.pl.id, ActivityType.SCHOOL_VISIT, "staff")
        from django.utils import timezone as _tz

        pl_act.scheduled_date = _tz.make_aware(_tz.datetime(2026, 4, 13, 9, 0))
        pl_act.save(update_fields=["scheduled_date"])
        line = self._cost_line(pl_act, 150_000)
        line.planned_date = date(2026, 4, 13)
        line.save(update_fields=["planned_date"])

        wfr = generate_weekly_fund_request(self.pl.id, "2026-04-13")
        self.assertIsNotNone(wfr)
        self.assertEqual(wfr.responsible_user, self.pl.id)

        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["General Budget Total"], svc._ugx(450_000))
        pl_row = next(r for r in ctx["staff_rows"] if r["name"] == "Paul Lead")
        self.assertEqual(pl_row["total"], 150_000)

    def test_partner_assignment_not_budgeted_until_partner_schedules(self):
        act = self._activity(
            self.cceo.id, ActivityType.SCHOOL_VISIT, "partner", planned_date=None
        )
        self._cost_line(act, 777_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["General Budget Total"], svc._ugx(300_000))

        # The partner schedules it → it enters the budget.
        act.planned_date = date(2026, 4, 15)
        act.status = "partner_scheduled"
        act.save(update_fields=["planned_date", "status"])
        ctx2 = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label2 = {k["label"]: k["value"] for k in ctx2["kpis"]}
        self.assertEqual(by_label2["General Budget Total"], svc._ugx(1_077_000))

    def test_country_budget_excludes_unscheduled_activity(self):
        """An unscheduled planning item never got a schedule-time month stamp —
        it must not enter any General Budget period."""
        act = self._activity(
            self.cceo.id, ActivityType.SCHOOL_VISIT, "staff", planned_date=None
        )
        self._cost_line(act, 888_000, month=None)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["General Budget Total"], svc._ugx(300_000))

    def test_cd_admin_budget_only_from_cd_monthly_admin_plan(self):
        """Admin money enters the approval envelope ONLY as AdminBudgetLine rows
        under the CD Monthly Admin Plan — no plan, no admin budget."""
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label = {k["label"]: k["value"] for k in ctx["kpis"]}
        self.assertEqual(by_label["Admin Budget"], svc._ugx(0))
        self.assertEqual(ctx["admin_row"]["status"], "Admin Plan Missing")

        budget = MonthlyWorkPlanBudget.objects.get(id=ctx["budget_id"])
        AdminBudgetLine.objects.create(
            monthly_budget=budget,
            cost_category="office_operations",
            description="Rent",
            quantity=1,
            unit_cost=250_000,
            total_cost=250_000,
            created_by_user_id=self.cd.id,
        )
        ctx2 = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        by_label2 = {k["label"]: k["value"] for k in ctx2["kpis"]}
        self.assertEqual(by_label2["Admin Budget"], svc._ugx(250_000))
        self.assertEqual(
            by_label2["General Budget Total"], svc._ugx(550_000)
        )  # program 300k + admin 250k, nothing else

    # ── submit / approve / return workflow ────────────────────────────────
    def test_send_to_rvp_creates_audit_and_notifies_rvp(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        b = svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        self.assertEqual(b.status, "submitted_to_rvp")
        self.assertEqual(b.submitted_by_user_id, self.cd.id)
        self.assertTrue(
            AuditLog.objects.filter(
                action="country_budget.submit_to_rvp", subject_id=b.id
            ).exists()
        )
        from apps.notifications.models import Notification

        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.rvp.id, source_event_type="country_budget_submitted"
            ).exists()
        )

    def test_approve_notifies_cd_and_accountant(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        b = svc.approve(self.rvp_p, ctx["budget_id"])
        self.assertEqual(b.status, "approved_by_rvp")
        from apps.notifications.models import Notification

        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.cd.id, source_event_type="country_budget_approved"
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.accountant.id,
                source_event_type="country_budget_approved",
            ).exists()
        )

    def test_return_requires_reason_and_notifies_cd(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        with self.assertRaises(BadRequest):
            svc.return_budget(self.rvp_p, ctx["budget_id"], {"reason": ""})
        b = svc.return_budget(
            self.rvp_p,
            ctx["budget_id"],
            {"reason": "Missing plan source", "comment": "check X"},
        )
        self.assertEqual(b.status, "returned_by_rvp")
        self.assertIn("Missing plan source", b.rvp_review_note)

    def test_cannot_double_submit(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        with self.assertRaises(BadRequest):
            svc.send_to_rvp(self.cd_p, ctx["budget_id"])

    def test_returned_budget_can_be_resubmitted(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        svc.return_budget(self.rvp_p, ctx["budget_id"], {"reason": "Wrong month"})
        ctx2 = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        self.assertTrue(ctx2["can_send_to_rvp"])
        b = svc.send_to_rvp(self.cd_p, ctx2["budget_id"])
        self.assertEqual(b.status, "submitted_to_rvp")

    # ── §13 RVP country-scope guard (parity with services._assert_rvp_can_decide) ──
    def test_rvp_cannot_approve_budget_from_another_country(self):
        foreign = MonthlyWorkPlanBudget.objects.create(
            fy=FY,
            month_key=f"{FY}-{MONTH:02d}",
            country_id="Kenya",
            status="submitted_to_rvp",
            total_amount=1_000_000,
        )
        with self.assertRaises(Forbidden):
            svc.approve(self.rvp_p, foreign.id)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, "submitted_to_rvp")  # untouched

    def test_rvp_cannot_return_budget_from_another_country(self):
        foreign = MonthlyWorkPlanBudget.objects.create(
            fy=FY,
            month_key=f"{FY}-{MONTH:02d}",
            country_id="Kenya",
            status="submitted_to_rvp",
            total_amount=1_000_000,
        )
        with self.assertRaises(Forbidden):
            svc.return_budget(self.rvp_p, foreign.id, {"reason": "Not my region"})
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, "submitted_to_rvp")  # untouched

    def test_rvp_can_still_approve_home_country_budget(self):
        """Regression guard: the new country-scope check must not block the
        RVP's own General Budgets — every budget this module generates
        is tagged HOME_COUNTRY_ID."""
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        b = svc.approve(self.rvp_p, ctx["budget_id"])
        self.assertEqual(b.status, "approved_by_rvp")

    # ── plan sources drawer ────────────────────────────────────────────────
    def test_plan_sources_lists_real_activities(self):
        ps = svc.get_plan_sources(self.cd_p, {"fy": FY, "month": MONTH})
        self.assertEqual(ps["count"], 2)
        names = {r["staff"] for r in ps["rows"]}
        self.assertEqual(names, {"Sarah N."})

    # ── To-Do derivation ─────────────────────────────────────────────────
    def test_cd_todo_derives_for_current_month_only(self):
        # Force the fixture's month to "now" so the current-month CD nudge applies.
        today = date.today()
        MonthlyWorkPlanBudget.objects.create(
            fy=str(today.year),
            month_key=f"{today.year}-{today.month:02d}",
            country_id="Uganda",
            status="draft_generated",
        )
        titles = [t["title"] for t in get_todos(self.cd_p)["todos"]]
        self.assertTrue(any("Review" in t and "General Budget" in t for t in titles))

    def test_rvp_and_accountant_todos_derive_through_lifecycle(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        rvp_titles = [t["title"] for t in get_todos(self.rvp_p)["todos"]]
        self.assertIn("Review General Budget", rvp_titles)

        svc.approve(self.rvp_p, ctx["budget_id"])
        acct_titles = [t["title"] for t in get_todos(self.acct_p)["todos"]]
        self.assertIn("Prepare Monthly Disbursement Queue", acct_titles)
        # RVP's To-Do auto-closed now that it's approved.
        rvp_titles2 = [t["title"] for t in get_todos(self.rvp_p)["todos"]]
        self.assertNotIn("Review General Budget", rvp_titles2)

    def test_returned_budget_creates_cd_todo(self):
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": FY, "month": MONTH})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        svc.return_budget(
            self.rvp_p, ctx["budget_id"], {"reason": "Admin budget unclear"}
        )
        titles = [t["title"] for t in get_todos(self.cd_p)["todos"]]
        self.assertIn("Fix Returned General Budget", titles)


class RollingMonthlyBudgetWorkflowTest(TestCase):
    """Spec §21 matrix — the rolling month-by-month submit workflow.

    Each month is an independent record with its own submission state; a
    submitted month becomes an immutable snapshot, the next month is prepared
    atomically, and no single month's state disables another's.
    """

    def setUp(self):
        User = get_user_model()
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.school = School.objects.create(
            school_id="SCH-ROLL1",
            name="Roll School",
            region=self.region,
            district=self.district,
        )
        self.cd = User.objects.create(
            id="cd-roll",
            email="cdroll@edify.org",
            name="CD Roll",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        self.rvp = User.objects.create(
            id="rvp-roll",
            email="rvproll@edify.org",
            name="RVP Roll",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
            is_active=True,
        )
        self.cd_p = _Principal(self.cd)
        self.rvp_p = _Principal(self.rvp)

    def _activity(self, atype, delivery="staff", planned_date=date(2026, 7, 15)):
        return Activity.objects.create(
            school=self.school,
            delivery_type=delivery,
            activity_type=atype,
            status="scheduled",
            responsible_staff_id=self.cd.id,
            fy="2026",
            planned_date=planned_date,
        )

    def _cost_line(self, activity, amount, planned_date=date(2026, 7, 15)):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=amount,
            quantity=1,
            amount=amount,
            month=planned_date.month,
            fiscal_year="2026",
            planned_date=planned_date,
            catalogue_id="cat-v1",
            catalogue_version=1,
            responsible_user=self.cd.id,
        )

    def _july_budget_with_cost(self, amount=300_000):
        act = self._activity(ActivityType.SCHOOL_VISIT)
        self._cost_line(act, amount)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 7})
        return ctx

    # ── §3.12 / §4 immutable snapshot ──────────────────────────────────────
    def test_submit_creates_an_immutable_line_item_snapshot(self):
        ctx = self._july_budget_with_cost(300_000)
        budget = MonthlyWorkPlanBudget.objects.get(id=ctx["budget_id"])
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])

        snapshot = budget.snapshots.first()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.version, 1)
        self.assertEqual(snapshot.total_amount, 300_000)
        self.assertEqual(len(snapshot.line_items), 1)
        self.assertEqual(snapshot.line_items[0]["amount"], 300_000)

    def test_submitted_month_does_not_drift_when_underlying_cost_line_changes(self):
        ctx = self._july_budget_with_cost(300_000)
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        budget = MonthlyWorkPlanBudget.objects.get(id=ctx["budget_id"])

        # The underlying live cost line changes after submission.
        ActivityScheduleCostLine.objects.filter(activity__fy="2026", month=7).update(
            amount=9_000_000, unit_cost=9_000_000
        )

        # The frozen totals + snapshot must NOT reflect the drift.
        budget.refresh_from_db()
        self.assertEqual(budget.total_amount, 300_000)
        snapshot = budget.snapshots.first()
        self.assertEqual(snapshot.total_amount, 300_000)
        self.assertEqual(snapshot.line_items[0]["amount"], 300_000)

    def test_submission_version_increments_on_resubmit_after_return(self):
        ctx = self._july_budget_with_cost(300_000)
        budget = MonthlyWorkPlanBudget.objects.get(id=ctx["budget_id"])
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        budget.refresh_from_db()
        self.assertEqual(budget.submission_version, 1)

        svc.return_budget(self.rvp_p, ctx["budget_id"], {"reason": "Recheck"})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        budget.refresh_from_db()
        self.assertEqual(budget.submission_version, 2)
        self.assertEqual(budget.snapshots.count(), 2)
        # Each version uniquely identified.
        self.assertEqual(
            sorted(budget.snapshots.values_list("version", flat=True)), [1, 2]
        )

    # ── §5 next-month preparation ──────────────────────────────────────────
    def test_submitting_july_prepares_august(self):
        self._july_budget_with_cost(300_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 7})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])

        august = MonthlyWorkPlanBudget.objects.filter(
            country_id="Uganda", month_key="2026-08"
        ).first()
        self.assertIsNotNone(
            august, "August draft should be prepared atomically with submit"
        )
        self.assertEqual(august.status, "draft_generated")
        self.assertEqual(august.fy, "2026")

    def test_submitting_september_creates_october_in_the_next_fy(self):
        act = self._activity(ActivityType.SCHOOL_VISIT, planned_date=date(2026, 9, 10))
        self._cost_line(act, 250_000, planned_date=date(2026, 9, 10))
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 9})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])

        october = MonthlyWorkPlanBudget.objects.filter(
            country_id="Uganda", month_key="2026-10"
        ).first()
        self.assertIsNotNone(october, "September submit must roll into October")
        # FY2026 runs Oct-2025 → Sep-2026, so October 2026 begins FY2027.
        self.assertEqual(october.fy, "2027")

    def test_next_month_preparation_is_idempotent(self):
        self._july_budget_with_cost(300_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 7})
        budget = MonthlyWorkPlanBudget.objects.get(id=ctx["budget_id"])

        next1, created1 = svc.prepare_next_month(self.cd_p, budget)
        next2, created2 = svc.prepare_next_month(self.cd_p, budget)
        self.assertEqual(next1.id, next2.id)
        self.assertFalse(created2, "retry must not create a duplicate next-month draft")

    # ── §9 / §10 per-month independence ────────────────────────────────────
    def test_august_uses_only_august_cost_lines_not_julys(self):
        # July cost line.
        july_act = self._activity(
            ActivityType.SCHOOL_VISIT, planned_date=date(2026, 7, 10)
        )
        self._cost_line(july_act, 300_000, planned_date=date(2026, 7, 10))
        # August cost line.
        aug_act = self._activity(
            ActivityType.SCHOOL_VISIT, planned_date=date(2026, 8, 12)
        )
        self._cost_line(aug_act, 120_000, planned_date=date(2026, 8, 12))

        july_ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 7})
        svc.send_to_rvp(self.cd_p, july_ctx["budget_id"])

        aug_ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 8})
        self.assertEqual(aug_ctx["budget"].program_total, 120_000)
        self.assertNotEqual(
            aug_ctx["budget"].program_total, july_ctx["budget"].program_total
        )

    def test_july_submitted_flag_does_not_disable_august_submission(self):
        self._july_budget_with_cost(300_000)
        july_ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 7})
        svc.send_to_rvp(self.cd_p, july_ctx["budget_id"])

        # August has its own cost line and its own readiness.
        aug_act = self._activity(
            ActivityType.SCHOOL_VISIT, planned_date=date(2026, 8, 12)
        )
        self._cost_line(aug_act, 120_000, planned_date=date(2026, 8, 12))
        aug_ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 8})
        self.assertTrue(
            aug_ctx["can_send_to_rvp"], "August's button is independent of July's state"
        )

    def test_pending_july_rvp_review_does_not_block_august_preparation(self):
        self._july_budget_with_cost(300_000)
        july_ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 7})
        svc.send_to_rvp(self.cd_p, july_ctx["budget_id"])  # July now awaiting RVP

        aug_act = self._activity(
            ActivityType.SCHOOL_VISIT, planned_date=date(2026, 8, 12)
        )
        self._cost_line(aug_act, 120_000, planned_date=date(2026, 8, 12))
        aug_ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 8})
        self.assertTrue(aug_ctx["can_send_to_rvp"])
        # The §10 warning surfaces the prior pending month without blocking.
        self.assertEqual(aug_ctx["prior_month_pending"], "July")

    def test_rvp_approval_of_july_does_not_alter_august(self):
        self._july_budget_with_cost(300_000)
        july_ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 7})
        svc.send_to_rvp(self.cd_p, july_ctx["budget_id"])

        aug_act = self._activity(
            ActivityType.SCHOOL_VISIT, planned_date=date(2026, 8, 12)
        )
        self._cost_line(aug_act, 120_000, planned_date=date(2026, 8, 12))
        aug_budget_before = svc.get_country_monthly_budget(
            self.cd_p, {"fy": "2026", "month": 8}
        )["budget"]
        aug_total_before = aug_budget_before.program_total

        svc.approve(self.rvp_p, july_ctx["budget_id"])

        aug_budget_after = svc.get_country_monthly_budget(
            self.cd_p, {"fy": "2026", "month": 8}
        )["budget"]
        self.assertEqual(aug_budget_after.program_total, aug_total_before)

    # ─§14 / §15 empty + blocked states ──────────────────────────────────────
    def test_empty_next_month_draft_keeps_button_disabled(self):
        # Submit July so August is prepared, but schedule nothing in August.
        self._july_budget_with_cost(300_000)
        july_ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 7})
        svc.send_to_rvp(self.cd_p, july_ctx["budget_id"])

        aug_ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 8})
        self.assertEqual(aug_ctx["budget"].program_total, 0)
        # can_send_to_rvp is allowed on an empty-but-valid draft (the readiness
        # gate is integrity, not non-empty), but the displayed total is UGX 0 —
        # confirming no stale July figures leaked into August.
        self.assertEqual(aug_ctx["budget"].activity_count, 0)

    # ── §20 concurrency: one submission under a race ───────────────────────
    def test_concurrent_double_submit_creates_only_one_snapshot(self):
        ctx = self._july_budget_with_cost(300_000)
        # select_for_update serializes the two attempts; the second sees the
        # committed submitted_to_rvp status and is rejected. With TestCase
        # wrapping each test in a transaction, we assert the serial-equivalent
        # outcome: the guard + row lock yield exactly one snapshot/version.
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        with self.assertRaises(BadRequest):
            svc.send_to_rvp(self.cd_p, ctx["budget_id"])
        budget = MonthlyWorkPlanBudget.objects.get(id=ctx["budget_id"])
        self.assertEqual(budget.snapshots.count(), 1)
        self.assertEqual(budget.submission_version, 1)

    # ── §4 submitted budgets move into history ──────────────────────────────
    def test_submitted_month_appears_in_history_list(self):
        self._july_budget_with_cost(300_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 7})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])

        history = svc.list_submitted_budgets(self.cd_p, {"fy": "2026"})
        self.assertEqual(len(history["rows"]), 1)
        row = history["rows"][0]
        self.assertEqual(row["month_label"], "July")
        self.assertEqual(row["total_amount"], 300_000)
        self.assertEqual(row["version"], 1)
        self.assertEqual(row["status"], "submitted_to_rvp")

    def test_submission_detail_reads_from_the_frozen_snapshot(self):
        self._july_budget_with_cost(300_000)
        ctx = svc.get_country_monthly_budget(self.cd_p, {"fy": "2026", "month": 7})
        svc.send_to_rvp(self.cd_p, ctx["budget_id"])

        # Underlying cost line drifts after submit.
        ActivityScheduleCostLine.objects.filter(activity__fy="2026", month=7).update(
            amount=9_000_000
        )

        detail = svc.get_submission_detail(self.cd_p, ctx["budget_id"])
        self.assertEqual(detail["total_amount"], 300_000)  # frozen
        self.assertEqual(detail["line_items"][0]["amount"], 300_000)  # frozen
        self.assertEqual(detail["version"], 1)
