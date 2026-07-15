from datetime import date, timedelta

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.hr.models import (
    ComplianceRequirement,
    PerformanceReview,
    Vacancy,
)


class HCOSWorkspaceViewTestCase(TestCase):
    """The HR navigation must resolve to live, model-backed workspaces."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            email="hcos-admin@edify.org",
            password="password123",
            name="HCOS Admin",
            roles=["Admin"],
            active_role="Admin",
        )
        staff_user = User.objects.create_user(
            email="hcos-staff@edify.org",
            password="password123",
            name="Visible Team Member",
            roles=["CCEO"],
            active_role="CCEO",
        )
        self.staff = StaffProfile.objects.create(
            user=staff_user,
            title="CCEO",
            department="Program Operations",
            country="Uganda",
            onboarding_state="active",
        )
        Vacancy.objects.create(
            country="Uganda",
            department="Program Operations",
            role="Program Officer",
            status="Open",
        )
        PerformanceReview.objects.create(
            staff=self.staff,
            period="FY 2026/27",
            due_date=date.today() + timedelta(days=14),
            status="Manager Review Pending",
            score=72,
        )
        ComplianceRequirement.objects.create(
            country="Uganda", name="Safeguarding policy", is_mandatory=True
        )
        self.client.force_login(self.admin)

    def test_every_hcos_navigation_page_is_a_real_workspace(self):
        paths = (
            "/org-structure",
            "/workforce-planning",
            "/recruitment",
            "/candidate-pipeline",
            "/onboarding",
            "/succession-planning",
            "/performance-reviews",
            "/recovery-plans",
            "/culture-engagement",
            "/employee-relations",
            "/wellness",
            "/compensation-benefits",
            "/payroll-readiness",
            "/compliance-register",
            "/policies",
            "/offboarding",
            "/hr-analytics",
            "/hr-audit-log",
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "pages/hr/module_workspace.html")
                self.assertNotContains(response, "currently in development")

    def test_workspaces_show_live_records_not_fabricated_examples(self):
        recruitment = self.client.get("/recruitment")
        self.assertContains(recruitment, "Program Officer")
        self.assertContains(recruitment, "Open")

        performance = self.client.get("/performance-reviews")
        self.assertContains(performance, "Visible Team Member")
        self.assertContains(performance, "72%")

        policies = self.client.get("/policies")
        self.assertContains(policies, "Safeguarding policy")

