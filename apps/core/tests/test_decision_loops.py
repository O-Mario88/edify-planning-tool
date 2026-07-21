"""Phase 2 — decisions become state.

Three loops were severed:
  • decide → enforce (RVP project decisions changed nothing);
  • approve → execute → reconcile (the country envelope never closed);
  • observe → act (no forecast against the annual ceiling).
"""

from __future__ import annotations

from datetime import date

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.monthly_work_plan import reconciliation_service as recon
from apps.monthly_work_plan.models import (
    CountryAnnualBudget,
    MonthlyWorkPlanBudget,
    MonthlyWorkPlanBudgetStatus,
)
from apps.projects import services as project_services
from apps.projects.models import Project, ProjectCategory, ProjectStatus


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


class ProjectLifecycleTests(TestCase):
    """An RVP decision must change what the project is, not just log that a
    decision happened."""

    def setUp(self):
        self.rvp = _user(
            "rvp-life@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )
        StaffProfile.objects.create(user=self.rvp, title="RVP", country="Uganda")
        self.project = Project.objects.create(
            name="SP-EDTECH",
            category=ProjectCategory.PILOT.value,
            target_interventions=["leadership"],
        )

    def test_new_projects_default_to_active(self):
        self.assertEqual(self.project.status, ProjectStatus.ACTIVE.value)
        self.assertTrue(self.project.accepts_new_work)

    def test_close_moves_the_project_out_of_working_state(self):
        changed = project_services.apply_decision(
            self.project, "close", self.rvp, "Objectives met"
        )
        self.assertTrue(changed)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, ProjectStatus.CLOSED.value)
        self.assertFalse(self.project.accepts_new_work)
        self.assertFalse(self.project.is_live)
        self.assertEqual(self.project.status_reason, "Objectives met")
        self.assertEqual(self.project.status_changed_by, self.rvp.id)
        self.assertIsNotNone(self.project.status_changed_at)

    def test_pause_stops_new_work_but_keeps_the_project_visible(self):
        project_services.apply_decision(self.project, "pause", self.rvp, "Overspend")
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, ProjectStatus.PAUSED.value)
        self.assertFalse(self.project.accepts_new_work)
        self.assertTrue(self.project.is_live, "a paused project stays visible")

    def test_scale_and_redesign_move_status(self):
        project_services.apply_decision(
            self.project, "scale", self.rvp, "Strong impact"
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, ProjectStatus.SCALING.value)
        self.assertTrue(self.project.accepts_new_work)

        project_services.apply_decision(self.project, "redesign", self.rvp, "Rework")
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, ProjectStatus.UNDER_REVIEW.value)

    def test_advisory_decisions_do_not_change_status(self):
        for advisory in ("measure", "increase_budget", "reduce_budget"):
            changed = project_services.apply_decision(
                self.project, advisory, self.rvp, "note"
            )
            self.assertFalse(changed, f"{advisory} must stay advisory")
            self.project.refresh_from_db()
            self.assertEqual(self.project.status, ProjectStatus.ACTIVE.value)

    def test_paused_project_refuses_new_school_assignment(self):
        project_services.apply_decision(self.project, "pause", self.rvp, "Overspend")
        self.project.refresh_from_db()
        with self.assertRaises(BadRequest) as ctx:
            project_services.assert_accepts_new_work(self.project)
        self.assertIn("paused", str(ctx.exception).lower())

    def test_closed_project_refuses_new_school_assignment(self):
        project_services.apply_decision(self.project, "close", self.rvp, "Done")
        self.project.refresh_from_db()
        with self.assertRaises(BadRequest):
            project_services.assert_accepts_new_work(self.project)


class ProjectCreationTests(TestCase):
    """No creation path existed — the New Project affordance pointed nowhere."""

    def setUp(self):
        self.cd = _user("cd-create@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=self.cd, title="CD", country="Uganda")

    def test_creates_a_proposed_project(self):
        result = project_services.create_project(
            {
                "name": "SP-LITERACY",
                "category": ProjectCategory.PILOT.value,
                "targetInterventions": ["teaching_environment"],
                "budgetCeilingUgx": 50_000_000,
            },
            self.cd,
        )
        self.assertEqual(result["status"], ProjectStatus.PROPOSED.value)
        self.assertEqual(result["budgetCeilingUgx"], 50_000_000)
        self.assertTrue(Project.objects.filter(name="SP-LITERACY").exists())

    def test_requires_a_target_intervention(self):
        with self.assertRaises(BadRequest) as ctx:
            project_services.create_project(
                {"name": "SP-VAGUE", "category": ProjectCategory.PILOT.value}, self.cd
            )
        self.assertIn("target SSA intervention", str(ctx.exception))

    def test_rejects_unknown_intervention(self):
        with self.assertRaises(BadRequest):
            project_services.create_project(
                {
                    "name": "SP-BAD",
                    "category": ProjectCategory.PILOT.value,
                    "targetInterventions": ["not_a_real_intervention"],
                },
                self.cd,
            )

    def test_rejects_unknown_category(self):
        with self.assertRaises(BadRequest):
            project_services.create_project(
                {
                    "name": "SP-BAD2",
                    "category": "nonsense",
                    "targetInterventions": ["leadership"],
                },
                self.cd,
            )

    def test_rejects_duplicate_code(self):
        project_services.create_project(
            {
                "name": "SP-ONE",
                "code": "SP-1",
                "category": ProjectCategory.PILOT.value,
                "targetInterventions": ["leadership"],
            },
            self.cd,
        )
        with self.assertRaises(BadRequest):
            project_services.create_project(
                {
                    "name": "SP-TWO",
                    "code": "SP-1",
                    "category": ProjectCategory.PILOT.value,
                    "targetInterventions": ["leadership"],
                },
                self.cd,
            )

    def test_creation_is_audited(self):
        from apps.audit.models import AuditLog

        result = project_services.create_project(
            {
                "name": "SP-AUDITED",
                "category": ProjectCategory.PILOT.value,
                "targetInterventions": ["leadership"],
            },
            self.cd,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="project_create", subject_id=result["id"]
            ).exists()
        )


class EnvelopeReconciliationTests(TestCase):
    """The envelope dead-ended at approved_by_rvp and never met reality."""

    def setUp(self):
        self.cd = _user("cd-recon@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=self.cd, title="CD", country="Uganda")
        self.budget = MonthlyWorkPlanBudget.objects.create(
            fy="2026",
            month_key="2026-05",
            country_id="Uganda",
            status=MonthlyWorkPlanBudgetStatus.SENT_TO_ACCOUNTANT,
            program_total=8_000_000,
            admin_total=2_000_000,
            total_amount=10_000_000,
        )

    def test_reconciliation_reports_plan_against_actual(self):
        rec = recon.reconcile_month(self.budget)
        self.assertEqual(rec["approvedTotal"], 10_000_000)
        self.assertEqual(rec["disbursedTotal"], 0)
        self.assertEqual(rec["variance"], 10_000_000)
        self.assertFalse(rec["isOverspend"])

    def test_cannot_mark_disbursed_without_money_movement(self):
        with self.assertRaises(BadRequest) as ctx:
            recon.mark_disbursed(self.budget.id, self.cd)
        self.assertIn("No disbursement", str(ctx.exception))

    def test_cannot_close_before_disbursed(self):
        with self.assertRaises(BadRequest):
            recon.close_month(self.budget.id, self.cd)

    def test_system_a_vs_b_delta_is_surfaced(self):
        """The discrepancy that was previously invisible: the field accounted
        for money that NetSuite never booked."""
        self.assertEqual(recon._ab_status(0, 0), "no_data")
        self.assertEqual(recon._ab_status(5_000_000, 5_000_000), "matched")
        self.assertEqual(recon._ab_status(5_000_000, 1_000_000), "unbooked")
        self.assertEqual(recon._ab_status(1_000_000, 5_000_000), "overbooked")
        self.assertEqual(recon._ab_status(1_000_000, 1_005_000), "within_tolerance")

    def test_settlement_state_explains_the_blocker(self):
        state = recon.settlement_state(self.budget)
        self.assertFalse(state["canMarkDisbursed"])
        self.assertIsNotNone(state["blockingReason"])


class ReconciliationCountryScopeTests(TestCase):
    """A country-tagged envelope must not reconcile against another country's
    money — and must never silently drop money it cannot place."""

    def setUp(self):
        from apps.geography.models import District, Region
        from apps.schools.models import School

        self.budget = MonthlyWorkPlanBudget.objects.create(
            fy="2026",
            month_key="2026-12",
            country_id="Uganda",
            status=MonthlyWorkPlanBudgetStatus.SENT_TO_ACCOUNTANT,
            total_amount=10_000_000,
        )
        region = Region.objects.create(name="Recon Region")
        district = District.objects.create(name="Recon District", region=region)
        self.school = School.objects.create(
            name="Recon Primary",
            school_id="RP-1",
            region_id=region.id,
            district_id=district.id,
        )

    def _staff(self, email, country):
        user = _user(email, email.split("@")[0], EdifyRole.CCEO.value)
        StaffProfile.objects.create(user=user, title="CCEO", country=country)
        return user

    def _advance(self, owner_id, amount):
        """An advance owned by `owner_id`, dated inside the envelope's month."""
        from apps.activities.models import Activity, ActivityScheduleCostLine
        from apps.fund_requests.models import AdvanceRequest

        when = timezone.make_aware(timezone.datetime(2026, 12, 10, 9, 0))
        activity = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="scheduled",
            fy="2026",
            quarter="Q2",
            responsible_staff_id=owner_id,
            planned_date=when,
        )
        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=amount,
            amount=amount,
        )
        return AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            fy="2026",
            quarter="Q2",
            planned_date=when,
            status="disbursed",
            amount=amount,
            disbursed_amount=amount,
            responsible_user_id=owner_id,
        )

    def test_single_country_deployment_counts_everything(self):
        """With one country in play there is nothing to separate, and the join
        is skipped entirely."""
        owner = self._staff("ug-only@t.org", "Uganda")
        self._advance(owner.id, 4_000_000)
        rec = recon.reconcile_month(self.budget)
        self.assertEqual(rec["disbursedTotal"], 4_000_000)
        self.assertEqual(rec["unattributedTotal"], 0)

    def test_another_countrys_money_is_excluded(self):
        ug = self._staff("ug@t.org", "Uganda")
        ke = self._staff("ke@t.org", "Kenya")
        self._advance(ug.id, 1_000_000)
        self._advance(ke.id, 55_000_000)

        rec = recon.reconcile_month(self.budget)
        self.assertEqual(
            rec["disbursedTotal"],
            1_000_000,
            "Kenya's disbursement must not inflate Uganda's envelope",
        )

    def test_unplaceable_money_is_reported_not_dropped(self):
        """An owner with no country recorded must surface, not vanish —
        money disappearing from a reconciliation is the worse failure."""
        self._staff("ug2@t.org", "Uganda")
        self._staff("ke2@t.org", "Kenya")  # makes the deployment multi-country
        orphan = _user("orphan@t.org", "Orphan", EdifyRole.CCEO.value)
        StaffProfile.objects.create(user=orphan, title="CCEO", country="")
        self._advance(orphan.id, 7_000_000)

        rec = recon.reconcile_month(self.budget)
        self.assertEqual(rec["disbursedTotal"], 0)
        self.assertEqual(rec["unattributedTotal"], 7_000_000)
        self.assertEqual(rec["unattributedCount"], 1)


class QuarterForecastTests(TestCase):
    """No forecast of any kind existed; quarterly_phasing was dead data."""

    def test_returns_none_without_an_annual_budget(self):
        self.assertIsNone(recon.quarter_forecast("2026", "Uganda"))

    def test_returns_none_when_phasing_is_unset(self):
        CountryAnnualBudget.objects.create(
            fy="2026", country_id="Uganda", quarterly_phasing=[]
        )
        self.assertIsNone(
            recon.quarter_forecast("2026", "Uganda"),
            "an unconfigured ceiling must read as 'not configured', never as a "
            "fabricated projection",
        )

    def test_projects_against_the_configured_ceiling(self):
        CountryAnnualBudget.objects.create(
            fy="2026",
            country_id="Uganda",
            quarterly_phasing=[100_000_000, 100_000_000, 100_000_000, 100_000_000],
        )
        forecast = recon.quarter_forecast("2026", "Uganda")
        self.assertIsNotNone(forecast)
        self.assertEqual(forecast["ceiling"], 100_000_000)
        self.assertIn("projectedTotal", forecast)
        self.assertIn("willOverspend", forecast)
        self.assertGreaterEqual(forecast["pctElapsed"], 0)
        self.assertLessEqual(forecast["pctElapsed"], 100)

    def test_fy_quarters_cover_every_month_of_an_oct_to_sep_year(self):
        expected = {
            10: "Q1",
            11: "Q1",
            12: "Q1",
            1: "Q2",
            2: "Q2",
            3: "Q2",
            4: "Q3",
            5: "Q3",
            6: "Q3",
            7: "Q4",
            8: "Q4",
            9: "Q4",
        }
        for month, quarter in expected.items():
            self.assertEqual(recon._fy_quarter(month), quarter, f"month {month}")

    def test_quarter_window_always_contains_today(self):
        """The year arithmetic straddles a calendar boundary for Q1 (Oct-Dec);
        a quarter whose window excludes today would silently report zero
        spend."""
        for month in range(1, 13):
            today = date(2026, month, 15)
            quarter = recon._fy_quarter(month)
            _spent, elapsed, total = recon._quarter_spend("2026", quarter, today)
            self.assertGreater(total, 88, f"{quarter} window is implausibly short")
            self.assertGreaterEqual(elapsed, 1)
            self.assertLessEqual(
                elapsed, total, f"{quarter}: today falls outside its own window"
            )

    def test_early_quarter_projection_is_withheld_not_fabricated(self):
        """Dividing by 1/92 turns one ordinary payment into a catastrophic
        projection. An alarm that cries wolf gets ignored, so the run rate is
        withheld until the divisor stops dominating."""
        CountryAnnualBudget.objects.create(
            fy="2026",
            country_id="Uganda",
            quarterly_phasing=[100_000_000] * 4,
        )
        forecast = recon.quarter_forecast("2026", "Uganda")
        self.assertIsNotNone(forecast)
        self.assertIn("isReliable", forecast)
        if not forecast["isReliable"]:
            self.assertIsNone(forecast["projectedTotal"])
            self.assertIsNone(forecast["projectedOverspend"])
            self.assertFalse(forecast["willOverspend"])
            # Spend-to-date is still reported — withholding the projection
            # must not withhold the facts.
            self.assertIsNotNone(forecast["spentToDate"])
        else:
            self.assertIsNotNone(forecast["projectedTotal"])

    def test_month_bounds_are_half_open_with_no_gap_or_overlap(self):
        dec_start, dec_end = recon._aware_bounds("2026-12")
        jan_start, _jan_end = recon._aware_bounds("2027-01")
        self.assertEqual(
            dec_end,
            jan_start,
            "a payment at the month boundary must land in exactly one envelope",
        )

    def test_malformed_month_key_is_rejected(self):
        with self.assertRaises(BadRequest):
            recon._month_bounds("not-a-month")


class CountryBudgetPageExecutionTests(TestCase):
    """The CD's own page must show how the last approval executed."""

    def setUp(self):
        self.cd = _user("cd-page@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=self.cd, title="CD", country="Uganda")
        self.client = Client()
        self.client.force_login(self.cd)

    def test_page_carries_reconciliation_and_forecast_keys(self):
        from apps.monthly_work_plan.country_budget_service import (
            get_country_monthly_budget,
        )

        ctx = get_country_monthly_budget(self.cd, {})
        self.assertIn("reconciliation", ctx)
        self.assertIn("forecast", ctx)
        self.assertIn("can_send_to_accountant", ctx)
        self.assertIn("can_mark_disbursed", ctx)
        self.assertIn("can_close_month", ctx)

    def test_page_renders(self):
        self.assertEqual(self.client.get("/country-budget/").status_code, 200)
