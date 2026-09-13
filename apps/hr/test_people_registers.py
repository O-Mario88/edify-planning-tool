"""People registers aligned with the Regional HR Director's role (2026-09-13).

Organization Structure now shows reporting lines, Workforce Planning counts
vacancies, leavers and turnover inside the director's countries, Performance
Reviews reads the review stage rather than legacy strings, and Recovery Plans
can be recommended, authorised and closed from the screen.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.hr.models import (
    EmployeeRelationsCase,
    OffboardingPlan,
    PerformanceImprovementPlan,
    PerformanceReview,
    Vacancy,
)


def _person(email, role="CCEO", country="Uganda", department="Programmes"):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].replace("-", " ").title(),
        roles=[role],
        active_role=role,
        password="pwd",
        is_active=True,
        status="active",
    )
    profile = StaffProfile.objects.create(
        user=user,
        staff_number=email.split("@")[0].upper(),
        country=country,
        department=department,
        onboarding_state="active",
    )
    return user, profile


def _metrics(response):
    return {m["label"]: str(m["value"]) for m in response.context["metrics"]}


class PeopleRegistersTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr, cls.hr_sp = _person("pr-hr@edify.test", "HumanResources", department="HR")
        cls.lead, cls.lead_sp = _person("pr-lead@edify.test", "Program Lead")
        cls.officer, cls.officer_sp = _person("pr-officer@edify.test")
        cls.kenyan, cls.kenyan_sp = _person("pr-kenyan@edify.test", country="Kenya")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.officer_sp, supervisor=cls.lead_sp
        )

    def setUp(self):
        self.client.force_login(self.hr)

    def test_org_structure_names_reporting_lines_and_the_gaps(self):
        page = self.client.get("/org-structure")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Pr Lead")
        metrics = _metrics(page)
        # The officer reports to the lead; the lead and the director have no
        # recorded line. The Kenyan officer is outside the reach.
        self.assertEqual(metrics["No reporting line"], "2")
        self.assertNotContains(page, "Pr Kenyan")

    def test_workforce_planning_counts_roles_leavers_and_turnover_in_reach(self):
        Vacancy.objects.create(
            country="Uganda", department="Programmes", role="CCEO", status="open"
        )
        Vacancy.objects.create(
            country="Kenya", department="Programmes", role="CCEO", status="open"
        )
        Vacancy.objects.create(
            country="Uganda",
            department="Programmes",
            role="CCEO",
            status="pending_approval",
        )
        OffboardingPlan.objects.create(
            staff=self.officer_sp,
            last_working_day=date.today() + timedelta(days=30),
            exit_reason="resignation",
        )
        page = self.client.get("/workforce-planning")
        metrics = _metrics(page)
        self.assertEqual(metrics["Open roles"], "1")
        self.assertEqual(metrics["Leaving in 90 days"], "1")
        self.assertEqual(metrics["Headcount"], "3")
        self.assertContains(page, 'hx-get="/recruitment/new"')

    def test_performance_reviews_read_the_stage(self):
        from apps.core.fy import get_operational_fy

        fy = get_operational_fy()
        PerformanceReview.objects.create(
            staff=self.officer_sp,
            period="FY",
            fy=fy,
            stage="calibration",
            manager_rating="met",
            due_date=date.today() + timedelta(days=5),
        )
        PerformanceReview.objects.create(
            staff=self.lead_sp,
            period="FY",
            fy=fy,
            stage="priorities_draft",
            due_date=date.today() - timedelta(days=2),
        )
        PerformanceReview.objects.create(
            staff=self.hr_sp,
            period="FY",
            fy=fy,
            stage="closed",
            rating="exceeds",
            due_date=date.today() - timedelta(days=30),
        )
        page = self.client.get("/performance-reviews")
        metrics = _metrics(page)
        self.assertEqual(metrics["Reviews"], "3")
        self.assertEqual(metrics["Completed"], "1")
        self.assertEqual(metrics["Overdue"], "1")
        self.assertEqual(metrics["Awaiting calibration"], "1")
        self.assertContains(page, "Met Priority")
        self.assertContains(page, "Exceeds Priority")
        self.assertNotContains(page, "priorities_draft")

    def test_a_formal_plan_is_recommended_authorised_and_closed_from_the_screen(self):
        self.client.post(
            "/recovery-plans/recommend",
            {
                "staff_id": self.officer_sp.id,
                "cause": "skill",
                "reason": "Missed three reporting deadlines despite coaching.",
            },
        )
        plan = PerformanceImprovementPlan.objects.get(staff=self.officer_sp)
        self.assertEqual(plan.status, "draft")
        metrics = _metrics(self.client.get("/recovery-plans"))
        self.assertEqual(metrics["Awaiting authorisation"], "1")

        drawer = self.client.get(f"/recovery-plans/{plan.id}")
        self.assertContains(drawer, "Authorise the plan")
        self.client.post(
            f"/recovery-plans/{plan.id}/activate",
            {"action_plan": "Weekly reporting check-ins with the Programme Lead."},
        )
        plan.refresh_from_db()
        self.assertEqual(plan.status, "active")
        self.assertEqual(plan.milestones.count(), 3)

        self.client.post(
            f"/recovery-plans/{plan.id}/outcome",
            {"outcome": "escalated", "note": "No improvement at the 90-day review."},
        )
        plan.refresh_from_db()
        self.assertEqual(plan.status, "escalated")
        case = EmployeeRelationsCase.objects.get(id=plan.escalated_case_id)
        self.assertEqual(case.severity, "high", "opened through the case service")
        self.assertEqual(case.subject_staff_id, self.officer_sp.id)

    def test_recovery_plans_outside_the_reach_do_not_exist(self):
        plan = PerformanceImprovementPlan.objects.create(
            staff=self.kenyan_sp,
            action_plan="x",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=30),
        )
        self.assertEqual(self.client.get(f"/recovery-plans/{plan.id}").status_code, 404)
        self.client.post(
            "/recovery-plans/recommend",
            {"staff_id": self.kenyan_sp.id, "cause": "skill", "reason": "x"},
        )
        self.assertEqual(
            PerformanceImprovementPlan.objects.filter(staff=self.kenyan_sp).count(), 1
        )


class PeopleDirectoryTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr, cls.hr_sp = _person("pd-hr@edify.test", "HumanResources", department="HR")
        cls.lead, cls.lead_sp = _person("pd-lead@edify.test", "Program Lead")
        cls.officer, cls.officer_sp = _person("pd-officer@edify.test")
        cls.kenyan, _ = _person("pd-kenyan@edify.test", country="Kenya")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.officer_sp, supervisor=cls.lead_sp
        )
        StaffProfile.objects.filter(id=cls.kenyan.staff_profile.id).update(
            onboarding_state="pending"
        )

    def test_the_directory_is_the_directors_people_with_roles_and_lines(self):
        self.client.force_login(self.hr)
        page = self.client.get("/staff")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "People Directory")
        self.assertNotContains(page, "Human Resource Dashboard")
        self.assertContains(page, "Programme Lead")
        self.assertContains(page, "reports to Pd Lead")
        self.assertContains(page, "pd-officer@edify.test")
        self.assertNotContains(page, "Pd Kenyan")
        self.assertEqual(page.context["kpis"]["total_active"], 3)
        # The Kenyan officer's pending profile is outside the reach.
        self.assertEqual(page.context["kpis"]["pending_onboarding"], 0)

    def test_an_rvp_reads_the_directory_without_email_addresses(self):
        rvp, _ = _person("pd-rvp@edify.test", "RegionalVicePresident")
        self.client.force_login(rvp)
        page = self.client.get("/staff")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "pd-officer@edify.test")
