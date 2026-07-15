from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import (
    Leave,
    LeaveBalance,
    LeaveTypePolicy,
    StaffProfile,
    User,
)
from apps.hr.models import (
    Vacancy,
    OnboardingPlan,
    PerformanceReview,
    ComplianceRequirement,
    EmployeeComplianceRecord,
    PayrollReadinessRecord,
)
from apps.accounts.hr_dashboard_service import HRDashboardService


class HRModelTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test_manager@edify.org",
            password="testpassword123",
            name="Test Manager",
            roles=["HumanResources"],
            active_role="HumanResources",
        )
        self.staff_user = User.objects.create_user(
            email="employee@edify.org",
            password="testpassword123",
            name="Employee One",
            roles=["CCEO"],
            active_role="CCEO",
        )
        self.staff_profile = StaffProfile.objects.create(
            user=self.staff_user, title="CCEO"
        )

    def test_create_vacancy(self):
        vacancy = Vacancy.objects.create(
            country="Uganda",
            department="Program Operations",
            role="CCEO",
            reporting_manager=self.user,
            status="Open",
        )
        self.assertEqual(vacancy.country, "Uganda")
        self.assertEqual(vacancy.status, "Open")

    def test_create_onboarding_plan(self):
        plan = OnboardingPlan.objects.create(
            staff=self.staff_profile, status="Not Started"
        )
        self.assertEqual(plan.staff, self.staff_profile)
        self.assertEqual(plan.status, "Not Started")

    def test_create_performance_review(self):
        review = PerformanceReview.objects.create(
            staff=self.staff_profile,
            period="FY 2024/25",
            review_type="Quarterly Review",
            status="Not Started",
            due_date="2026-10-15",
            rating="Strong (70-100%)",
            score=85.0,
        )
        self.assertEqual(review.staff, self.staff_profile)
        self.assertEqual(review.rating, "Strong (70-100%)")
        self.assertEqual(review.score, 85.0)

    def test_create_compliance(self):
        req = ComplianceRequirement.objects.create(
            country="Uganda", name="National ID", is_mandatory=True
        )
        record = EmployeeComplianceRecord.objects.create(
            staff=self.staff_profile, requirement=req, status="Compliant"
        )
        self.assertEqual(record.status, "Compliant")
        self.assertEqual(record.requirement.name, "National ID")


class HRDashboardServiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="hr@edify.org",
            password="password123",
            name="HR Admin",
            roles=["HumanResources"],
            active_role="HumanResources",
        )
        self.staff_user = User.objects.create_user(
            email="staff@edify.org",
            password="password123",
            name="Staff Member",
            roles=["CCEO"],
            active_role="CCEO",
        )
        self.staff_profile = StaffProfile.objects.create(
            user=self.staff_user, title="CCEO"
        )

        # Create vacancies
        Vacancy.objects.create(
            country="Uganda", department="Operations", role="CCEO", status="Open"
        )
        Vacancy.objects.create(
            country="Rwanda", department="Operations", role="CCEO", status="Approved"
        )

        # Create compliance records
        self.req = ComplianceRequirement.objects.create(
            country="Uganda", name="Policy A", is_mandatory=True
        )
        EmployeeComplianceRecord.objects.create(
            staff=self.staff_profile, requirement=self.req, status="Compliant"
        )

    def test_dashboard_service_payload(self):
        data = HRDashboardService.get_dashboard(self.user)
        self.assertIn("kpi_strip_items", data)
        self.assertIn("workforce_overview", data)
        self.assertIn("workforce_by_country", data)
        self.assertIn("headcount_by_department", data)
        self.assertIn("upcoming_reviews", data)
        self.assertIn("compliance_status", data)

        # Verify values
        open_positions = next(
            item["value"]
            for item in data["kpi_strip_items"]
            if item["label"] == "Open Positions"
        )
        self.assertEqual(
            open_positions, "1"
        )  # Since we created 1 Open and 1 Approved vacancy


class HRDashboardViewTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.hr_user = User.objects.create_user(
            email="hr_director@edify.org",
            password="password123",
            name="HR Director",
            roles=["HumanResources"],
            active_role="HumanResources",
        )
        self.cceo_user = User.objects.create_user(
            email="cceo@edify.org",
            password="password123",
            name="CCEO User",
            roles=["CCEO"],
            active_role="CCEO",
        )

    def test_dashboard_access_for_hr(self):
        self.client.force_login(self.hr_user)
        response = self.client.get(reverse("frontend:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/dashboards/hr.html")

    def test_dashboard_htmx_partial_for_hr(self):
        self.client.force_login(self.hr_user)
        response = self.client.get(
            reverse("frontend:dashboard"), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/dashboards/hr/body.html")

    def test_quick_action_links_do_not_404(self):
        """Regression for the Phase 1 punch-list item: 4 of the 6 HR
        Dashboard Quick Action links pointed at unwired sub-paths
        (/recruitment/create-vacancy, /onboarding/start,
        /performance-reviews/create, /cpd-learning/assign) that had no
        matching URL pattern and 404'd. Every quick-action url must resolve
        to a registered route."""
        self.client.force_login(self.hr_user)
        data = HRDashboardService.get_dashboard(self.hr_user)
        for qa in data["quick_actions"]:
            response = self.client.get(qa["url"])
            self.assertNotEqual(
                response.status_code,
                404,
                f"Quick Action '{qa['label']}' links to {qa['url']} which does not resolve.",
            )


class HRDashboardNoMockDataTestCase(TestCase):
    """No mock data rule (project memory: edify-no-mock-data-rule) — the HR
    dashboard must never present a hardcoded "or <number>" fallback, a
    hardcoded percentage with no query, or fabricated employees as if they
    were real. Regression coverage for the hr_dashboard_service.py fix."""

    def setUp(self):
        self.hr_user = User.objects.create_user(
            email="hr_no_data@edify.org",
            password="password123",
            name="HR No Data",
            roles=["HumanResources"],
            active_role="HumanResources",
        )

    def test_kpis_are_honest_zeros_with_no_hr_data_seeded(self):
        """With zero Vacancy/OnboardingPlan/PerformanceReview/PIP/CPD/Payroll
        rows in the DB, every KPI must be a real 0 — never a fabricated
        fallback such as 412, 18, 14, 12, 16, 72, 96, 68 or 95."""
        data = HRDashboardService.get_dashboard(self.hr_user)
        by_label = {k["label"]: k["value"] for k in data["kpi_strip_items"]}

        # Previously "<real query> or <hardcoded number>".
        self.assertEqual(by_label["Open Positions"], "0")
        self.assertEqual(by_label["New Hires Onboarding"], "0")
        self.assertEqual(by_label["High-Risk Staff"], "0")
        self.assertEqual(by_label["Performance Reviews Due"], "0")
        # Previously a bare literal with no query at all.
        self.assertEqual(by_label["Staff On Track"], "0%")
        self.assertEqual(by_label["Payroll Readiness"], "0%")
        # Previously fell back to a hardcoded percentage when empty.
        self.assertEqual(by_label["Compliance Completion"], "0%")
        self.assertEqual(by_label["CPD Completion"], "0%")

        # Previously entirely-fabricated data structures must now be honest
        # empty states, not fictional content.
        self.assertEqual(data["upcoming_reviews"], [])
        self.assertEqual(data["compliance_status"], [])
        self.assertEqual(data["job_levels"], [])
        self.assertTrue(all(row["count"] == 0 for row in data["recruitment_funnel"]))
        self.assertEqual(data["workforce_by_country"], [])

        # Leadership-attention banner values must also be real, not the old
        # "4"/"2"/"16"/"5"/"27"/"8" static HTML.
        self.assertEqual(data["open_positions"], 0)
        self.assertEqual(data["reviews_due"], 0)
        self.assertEqual(data["documents_expiring"], 0)
        self.assertEqual(data["high_risk_countries"], [])

    def test_upcoming_reviews_reflects_real_staff_not_fictional_employees(self):
        """A real, not-completed PerformanceReview for a real staff member
        must appear by name, replacing the 5 fictional employees
        (Daniel Otieno, Sarah Mutesi, Abebe Tesfaye, Grace Namura, Peter
        Mwangi) that used to be hardcoded here with stale 2025 dates."""
        staff_user = User.objects.create_user(
            email="real_reviewee@edify.org",
            password="x",
            name="Real Reviewee",
            roles=["CCEO"],
            active_role="CCEO",
        )
        staff_profile = StaffProfile.objects.create(
            user=staff_user, title="CCEO", country="Kenya"
        )
        due = date.today() + timedelta(days=3)
        PerformanceReview.objects.create(
            staff=staff_profile,
            period="FY 2025/26",
            review_type="Quarterly Review",
            status="Manager Review Pending",
            due_date=due,
        )

        data = HRDashboardService.get_dashboard(self.hr_user)

        self.assertEqual(len(data["upcoming_reviews"]), 1)
        row = data["upcoming_reviews"][0]
        self.assertEqual(row["name"], "Real Reviewee")
        self.assertEqual(row["country"], "Kenya")
        self.assertEqual(row["status"], "Due Soon")
        for fake_name in (
            "Daniel Otieno",
            "Sarah Mutesi",
            "Abebe Tesfaye",
            "Grace Namura",
            "Peter Mwangi",
        ):
            self.assertNotEqual(row["name"], fake_name)

    def test_payroll_readiness_pct_is_computed_from_real_records(self):
        """hr_dashboard_service.py:112 used to hardcode 95% with no query at
        all (PayrollReadinessRecord was imported but never referenced)."""
        u1 = User.objects.create_user(
            email="payroll1@edify.org",
            password="x",
            name="Payroll One",
            roles=["CCEO"],
            active_role="CCEO",
        )
        sp1 = StaffProfile.objects.create(user=u1, title="CCEO")
        u2 = User.objects.create_user(
            email="payroll2@edify.org",
            password="x",
            name="Payroll Two",
            roles=["CCEO"],
            active_role="CCEO",
        )
        sp2 = StaffProfile.objects.create(user=u2, title="CCEO")
        period = date.today().strftime("%Y-%m")
        PayrollReadinessRecord.objects.create(
            staff=sp1, payroll_period=period, is_payroll_ready=True
        )
        PayrollReadinessRecord.objects.create(
            staff=sp2, payroll_period=period, is_payroll_ready=False
        )

        data = HRDashboardService.get_dashboard(self.hr_user)
        by_label = {k["label"]: k["value"] for k in data["kpi_strip_items"]}
        self.assertEqual(by_label["Payroll Readiness"], "50%")

    def test_workforce_by_country_and_department_reflect_real_staffprofile_fields(self):
        """workforce_by_country / headcount_by_department used to be fully
        fake arrays (Uganda 156, Rwanda 94, ... / 182/86/64/34/24/22) despite
        StaffProfile.country and .department already existing for real."""
        u1 = User.objects.create_user(
            email="dept1@edify.org",
            password="x",
            name="Dept One",
            roles=["CCEO"],
            active_role="CCEO",
        )
        StaffProfile.objects.create(
            user=u1, title="CCEO", country="Kenya", department="Program Operations"
        )
        u2 = User.objects.create_user(
            email="dept2@edify.org",
            password="x",
            name="Dept Two",
            roles=["CCEO"],
            active_role="CCEO",
        )
        StaffProfile.objects.create(
            user=u2, title="CCEO", country="Kenya", department="Program Operations"
        )

        data = HRDashboardService.get_dashboard(self.hr_user)

        country_row = next(
            r for r in data["workforce_by_country"] if r["country"] == "Kenya"
        )
        self.assertEqual(country_row["headcount"], 2)

        labels = data["headcount_by_department"]["labels"]
        self.assertIn("Program Operations", labels)
        self.assertEqual(
            data["headcount_by_department"]["counts"][
                labels.index("Program Operations")
            ],
            2,
        )


class HrLeaveReviewEndpointSelfApprovalTestCase(TestCase):
    """Phase 1 punch-list HIGH SECURITY item: /api/hr/leave/<id>/approve
    (services.review_leave) unconditionally set leave.status = decision for
    any LEAVE_PLANNER_VIEW holder, letting HR self-approve their own PTO or
    approve/reject leave outside the supervisory hierarchy. This must be
    blocked the same way the main UI path (LeaveApprovalService) already
    blocks it."""

    def setUp(self):
        self.client = Client()
        self.hr_user = User.objects.create_user(
            email="hr_reviewer@edify.org",
            password="password123",
            name="HR Reviewer",
            roles=["HumanResources"],
            active_role="HumanResources",
        )
        self.hr_profile = StaffProfile.objects.create(
            user=self.hr_user, title="HumanResources"
        )

        self.leave = Leave.objects.create(
            staff=self.hr_profile,
            type="annual",
            start_date="2026-08-01",
            end_date="2026-08-03",
            days=3,
            status="pending",
        )

    def test_hr_cannot_self_approve_own_leave_via_api_endpoint(self):
        self.client.force_login(self.hr_user)
        response = self.client.post(f"/api/hr/leave/{self.leave.id}/approve")
        self.assertEqual(response.status_code, 400)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, "pending")
        self.assertIsNone(self.leave.reviewed_by_user_id)

    def test_hr_cannot_self_reject_own_leave_via_api_endpoint(self):
        self.client.force_login(self.hr_user)
        response = self.client.post(f"/api/hr/leave/{self.leave.id}/reject")
        self.assertEqual(response.status_code, 400)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, "pending")

    def test_unrelated_hr_staff_without_hierarchy_cannot_approve(self):
        """Even a different HR staffer (no supervisor relationship, not
        CD/RVP/Admin) must not be able to approve another employee's leave
        just by holding LEAVE_PLANNER_VIEW."""
        other_hr_user = User.objects.create_user(
            email="other_hr@edify.org",
            password="password123",
            name="Other HR",
            roles=["HumanResources"],
            active_role="HumanResources",
        )
        self.client.force_login(other_hr_user)
        response = self.client.post(f"/api/hr/leave/{self.leave.id}/approve")
        self.assertEqual(response.status_code, 400)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, "pending")


class HrLeaveRequestEndpointDelegatesToServiceTestCase(TestCase):
    """Phase 1 punch-list item: POST /api/hr/leave (services.request_leave)
    wrote a Leave row directly via Leave.objects.create(), bypassing
    LeaveRequestService.request_leave entirely -- so this parallel endpoint
    skipped the leave-balance sufficiency check and the
    LeaveTypePolicy.requires_attachment check that the main UI path already
    enforces. Both must now be enforced the same way here."""

    def setUp(self):
        self.client = Client()
        self.requester = User.objects.create_user(
            email="leave_requester@edify.org",
            password="password123",
            name="Leave Requester",
            roles=["HumanResources"],
            active_role="HumanResources",
        )
        self.staff_profile = StaffProfile.objects.create(
            user=self.requester, title="HumanResources"
        )
        self.client.force_login(self.requester)

    def test_rejects_request_exceeding_leave_balance(self):
        LeaveTypePolicy.objects.create(
            leave_type="short_leave",
            label="Short Leave",
            annual_entitlement=1,
            weekends_count=False,
            public_holidays_count=False,
        )
        response = self.client.post(
            "/api/hr/leave",
            {
                "type": "short_leave",
                # 5 consecutive weekdays -> 5 working days charged, only 1 available.
                "startDate": "2026-08-03",
                "endDate": "2026-08-07",
                "reason": "Too much time off",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Leave.objects.filter(reason="Too much time off").exists())

    def test_rejects_missing_required_attachment(self):
        LeaveTypePolicy.objects.create(
            leave_type="needs_doc",
            label="Needs Doc",
            annual_entitlement=21,
            requires_attachment=True,
        )
        response = self.client.post(
            "/api/hr/leave",
            {
                "type": "needs_doc",
                "startDate": "2026-08-03",
                "endDate": "2026-08-04",
                "reason": "No attachment provided",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Leave.objects.filter(reason="No attachment provided").exists())

    def test_accepts_valid_request_with_required_attachment_and_charges_balance(self):
        LeaveTypePolicy.objects.create(
            leave_type="needs_doc",
            label="Needs Doc",
            annual_entitlement=21,
            requires_attachment=True,
        )
        attachment = SimpleUploadedFile(
            "medical_note.pdf", b"%PDF-1.4", content_type="application/pdf"
        )
        response = self.client.post(
            "/api/hr/leave",
            {
                "type": "needs_doc",
                "startDate": "2026-08-03",
                "endDate": "2026-08-04",
                "reason": "Documented leave",
                "attachment": attachment,
            },
        )
        self.assertEqual(response.status_code, 201)
        leave = Leave.objects.get(reason="Documented leave")
        self.assertEqual(leave.status, "pending")
        # Real server-computed fields the old bypass never set.
        self.assertIsNotNone(leave.days_charged)
        self.assertIsNotNone(leave.hours_covered)
        balance = LeaveBalance.objects.get(
            staff=self.staff_profile, leave_type="needs_doc", year=2026
        )
        self.assertLess(balance.remaining, 21)
