"""Phase 2 — decisions become state.

Three loops were severed:
  • decide → enforce (RVP project decisions changed nothing);
  • approve → execute → reconcile (the country envelope never closed);
  • observe → act (no forecast against the annual ceiling).
"""

from __future__ import annotations

from datetime import date, timedelta

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
        self.rvp = _user("rvp-life@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
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
        project_services.apply_decision(self.project, "scale", self.rvp, "Strong impact")
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
