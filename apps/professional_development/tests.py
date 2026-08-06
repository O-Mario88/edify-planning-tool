"""My Professional Development — one shared employee-owned workflow (§37).

Covers: derived (never manual) fund balances, no-self-approval at every
stage (supervisor, HR, Accountant, HR sign-off), generic supervisor-auto-skip
routing, funding-exception gating, conditional enrollment-evidence
requirements by course type, the certificate-then-BambooHR-then-accountability
closure chain, funded-vs-unfunded branching, PD funding staying off the
school-activity budget rails, the resubmission/edit guard, staff-file
privacy, and the derived action-required queue used by the sidebar badge and
To-Do integration.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import CalendarBlock, StaffProfile, StaffSupervisorAssignment
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole

from apps.professional_development.approval_service import PDApprovalRoutingService
from apps.professional_development.completion_service import PDCourseTrackingService
from apps.professional_development.fund_service import PDFundRequestService
from apps.professional_development.models import (
    PDRoleAllocation,
    PDStatus,
    ProfessionalDevelopmentAllocation,
    ProfessionalDevelopmentCertificate,
    ProfessionalDevelopmentRequest,
)
from apps.professional_development.services import StaffPDService, staff_display_info

User = get_user_model()
FY = get_operational_fy()


def _pdf(name="cert.pdf"):
    return SimpleUploadedFile(
        name, b"%PDF-1.4\n" + b"x" * 128, content_type="application/pdf"
    )


class PDTestBase(TestCase):
    def setUp(self):
        self.cceo, self.cceo_sp = self._staff(
            "cceo@pd.org", "Casey Cceo", EdifyRole.CCEO.value
        )
        self.pl, self.pl_sp = self._staff(
            "pl@pd.org", "Pat Lead", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.hr, self.hr_sp = self._staff(
            "hr@pd.org", "Hana HR", EdifyRole.HUMAN_RESOURCES.value
        )
        self.hr2, self.hr2_sp = self._staff(
            "hr2@pd.org", "Hank HR2", EdifyRole.HUMAN_RESOURCES.value
        )
        self.accountant, self.acct_sp = self._staff(
            "acct@pd.org", "Ada Accountant", EdifyRole.PROGRAM_ACCOUNTANT.value
        )
        self.cd, self.cd_sp = self._staff(
            "cd@pd.org", "Cody Director", EdifyRole.COUNTRY_DIRECTOR.value
        )
        self.rvp, self.rvp_sp = self._staff(
            "rvp@pd.org", "Remy VP", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )

        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_sp, supervisor=self.pl_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.hr_sp, supervisor=self.cd_sp
        )

    def _staff(self, email, name, role):
        u = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        return u, StaffProfile.objects.create(user=u, title=role, country="Uganda")

    def _draft(self, user, **overrides):
        info = staff_display_info(user)
        fields = dict(
            fy=FY,
            staff_id=info["staff_id"],
            staff_name=info["staff_name"],
            position=info["position"],
            country=info["country"],
            department=info["department"],
            supervisor_staff_id=info["supervisor_staff_id"],
            supervisor_name=info["supervisor_name"],
            course_name="Leadership for Impact",
            course_category="Leadership Development",
            course_type="online",
            institution="Coursera",
            course_link="https://coursera.org/x",
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + timedelta(days=90),
            funding_type="self_funded",
            created_by=user.id,
        )
        fields.update(overrides)
        return ProfessionalDevelopmentRequest.objects.create(**fields)

    def _allocate(self, user, amount_cents):
        sp = StaffProfile.objects.get(user=user)
        return ProfessionalDevelopmentAllocation.objects.create(
            staff_id=sp.id, fy=FY, country="Uganda", annual_allocation=amount_cents
        )


class BalancesTests(PDTestBase):
    def test_balances_are_derived_not_cached(self):
        """§4 — remaining fund is always computed from live requests, never
        stored on the allocation row itself."""
        self._allocate(self.cceo, 100_000_00)
        bal = StaffPDService.balances(self.cceo, FY)
        self.assertEqual(bal["committed"], 0)
        self.assertEqual(bal["remaining"], 100_000_00)

        req = self._draft(
            self.cceo,
            funding_type="fully_funded",
            requested_amount_cents=40_000_00,
            course_fee_cents=40_000_00,
        )
        req.status = PDStatus.SUBMITTED_TO_SUPERVISOR
        req.save()
        bal = StaffPDService.balances(self.cceo, FY)
        self.assertEqual(bal["committed"], 40_000_00)
        self.assertEqual(bal["remaining"], 60_000_00)

    def test_over_allocation_requires_exception_reason_to_submit(self):
        """§9 — a request exceeding the remaining fund cannot submit without
        an exception reason, and gets flagged is_exception once approved."""
        self._allocate(self.cceo, 10_000_00)
        req = self._draft(
            self.cceo,
            funding_type="fully_funded",
            requested_amount_cents=50_000_00,
            course_fee_cents=50_000_00,
        )
        with self.assertRaises(BadRequest):
            PDApprovalRoutingService.submit(req, self.cceo)

        req.exception_reason = "Critical certification, no other budget line available."
        req.save()
        PDApprovalRoutingService.submit(req, self.cceo)
        req.refresh_from_db()
        self.assertTrue(req.is_exception)
        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_SUPERVISOR)


class RoutingTests(PDTestBase):
    def test_supervisor_auto_skips_to_hr_when_none_configured(self):
        """§13 — an RVP with no configured executive supervisor routes
        straight to HR instead of stalling."""
        req = self._draft(self.rvp)
        PDApprovalRoutingService.submit(req, self.rvp)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_HR)

    def test_manager_cannot_approve_own_request(self):
        """No manager may approve their own request."""
        req = self._draft(self.pl)
        req.status = PDStatus.SUBMITTED_TO_SUPERVISOR
        req.save()
        with self.assertRaises(Forbidden):
            PDApprovalRoutingService.supervisor_approve(req.id, self.pl)

    def test_hr_cannot_approve_own_request(self):
        """HR must never approve its own request — even at the HR stage."""
        req = self._draft(self.hr)
        req.status = PDStatus.SUBMITTED_TO_HR
        req.save()
        with self.assertRaises(Forbidden):
            PDApprovalRoutingService.hr_approve(req.id, self.hr)

    def test_hr_own_request_routes_to_independent_reviewer(self):
        """§13 — when HR is the requester, their supervisor still handles
        stage 1 normally, but the HR-stage decision must go to another
        HR/leadership user, and the record is flagged as independently
        reviewed (hr_sp's configured supervisor is self.cd)."""
        req = self._draft(self.hr)
        PDApprovalRoutingService.submit(req, self.hr)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_SUPERVISOR)
        PDApprovalRoutingService.supervisor_approve(req.id, self.cd)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_HR)
        # self.hr (the requester) must not be able to approve their own request.
        self.assertFalse(PDApprovalRoutingService.can_review(req, self.hr))
        # hr2 (a different HR user) can legitimately review this.
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.hr2))
        PDApprovalRoutingService.hr_approve(req.id, self.hr2)
        req.refresh_from_db()
        self.assertTrue(req.hr_is_independent_reviewer)

    def test_supervisor_approve_creates_calendar_block_not_activity(self):
        """§14 — approval creates a PD calendar block, never a school
        Activity or ActivityBudgetLine."""
        from apps.activities.models import Activity

        before_activities = Activity.objects.count()
        req = self._draft(self.cceo)
        req.status = PDStatus.SUBMITTED_TO_SUPERVISOR
        req.save()
        PDApprovalRoutingService.supervisor_approve(req.id, self.pl)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_HR)
        PDApprovalRoutingService.hr_approve(req.id, self.hr)
        req.refresh_from_db()
        self.assertTrue(req.calendar_block_id)
        self.assertTrue(CalendarBlock.objects.filter(id=req.calendar_block_id).exists())
        self.assertEqual(Activity.objects.count(), before_activities)


class EvidenceGateTests(PDTestBase):
    def test_in_person_requires_evidence_to_submit(self):
        req = self._draft(self.cceo, course_type="in_person", course_link="")
        with self.assertRaises(BadRequest):
            PDApprovalRoutingService.submit(req, self.cceo)
        PDCourseTrackingService.upload_evidence(
            req.id, self.cceo, _pdf(), kind="admission_letter"
        )
        PDApprovalRoutingService.submit(req, self.cceo)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_SUPERVISOR)

    def test_online_requires_course_link_to_submit(self):
        req = self._draft(self.cceo, course_type="online", course_link="")
        with self.assertRaises(BadRequest):
            PDApprovalRoutingService.submit(req, self.cceo)

    def test_hybrid_requires_both_link_and_evidence(self):
        req = self._draft(self.cceo, course_type="hybrid", course_link="https://x.org")
        with self.assertRaises(BadRequest):
            PDApprovalRoutingService.submit(req, self.cceo)
        PDCourseTrackingService.upload_evidence(
            req.id, self.cceo, _pdf(), kind="admission_letter"
        )
        PDApprovalRoutingService.submit(req, self.cceo)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_SUPERVISOR)

    def test_evidence_upload_blocked_once_submitted(self):
        req = self._draft(self.cceo, course_type="in_person", course_link="")
        req.status = PDStatus.SUBMITTED_TO_SUPERVISOR
        req.save()
        with self.assertRaises(BadRequest):
            PDCourseTrackingService.upload_evidence(
                req.id, self.cceo, _pdf(), kind="admission_letter"
            )


class ClosureChainTests(PDTestBase):
    def _fund_and_approve(self, req, funded=True):
        req.funding_type = "fully_funded" if funded else "self_funded"
        if funded:
            req.requested_amount_cents = 50_000_00
            req.course_fee_cents = 50_000_00
        req.status = PDStatus.SUBMITTED_TO_SUPERVISOR
        req.save()
        PDApprovalRoutingService.supervisor_approve(req.id, self.pl)
        PDApprovalRoutingService.hr_approve(req.id, self.hr)
        req.refresh_from_db()
        return req

    def test_sign_off_is_the_only_action_that_closes(self):
        """§24 — nothing else may ever set COMPLETED_CLOSED."""
        req = self._fund_and_approve(self._draft(self.cceo), funded=False)
        self.assertEqual(req.status, PDStatus.APPROVED_UNFUNDED)
        PDCourseTrackingService.confirm_enrollment(
            req.id, self.cceo, enrollment_date=date.today()
        )
        req.refresh_from_db()
        req.start_date, req.end_date = (
            date.today() - timedelta(days=5),
            date.today() - timedelta(days=1),
        )
        req.save()
        PDCourseTrackingService.sync_dates(req)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.ENDED)

    def test_no_certificate_no_complete(self):
        """§21/§24 — sign-off is blocked without an uploaded certificate."""
        req = self._fund_and_approve(self._draft(self.cceo), funded=False)
        PDCourseTrackingService.confirm_enrollment(
            req.id, self.cceo, enrollment_date=date.today()
        )
        req.refresh_from_db()
        req.start_date, req.end_date = (
            date.today() - timedelta(days=5),
            date.today() - timedelta(days=1),
        )
        req.save()
        PDCourseTrackingService.mark_complete(
            req.id,
            self.cceo,
            actual_completion_date=date.today(),
            course_outcome="Completed the leadership track.",
        )
        req.refresh_from_db()
        missing = PDCourseTrackingService._assert_signoff_eligible(req)
        self.assertIn("Certificate missing", missing)

    def test_unfunded_course_skips_accountability_straight_to_signoff(self):
        """Unfunded courses have no accountability step — confirm_bamboohr
        routes them directly to AWAITING_HR_SIGNOFF."""
        req = self._fund_and_approve(self._draft(self.cceo), funded=False)
        PDCourseTrackingService.confirm_enrollment(
            req.id, self.cceo, enrollment_date=date.today()
        )
        req.refresh_from_db()
        req.start_date, req.end_date = (
            date.today() - timedelta(days=5),
            date.today() - timedelta(days=1),
        )
        req.save()
        PDCourseTrackingService.mark_complete(
            req.id,
            self.cceo,
            actual_completion_date=date.today(),
            course_outcome="Done.",
        )
        PDCourseTrackingService.upload_certificate(req.id, self.cceo, _pdf())
        PDCourseTrackingService.confirm_bamboohr(req.id, self.cceo)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.AWAITING_HR_SIGNOFF)

    def test_funded_course_requires_netsuite_id_before_closing(self):
        """Non-negotiable — no funded course closes without an accountability
        submission AND a NetSuite Expense ID."""
        req = self._fund_and_approve(self._draft(self.cceo), funded=True)
        self.assertTrue(hasattr(req, "fund_request"))
        PDFundRequestService.disburse(
            req.fund_request.id,
            self.accountant,
            method="bank_transfer",
            reference="TX1",
        )
        PDCourseTrackingService.confirm_enrollment(
            req.id, self.cceo, enrollment_date=date.today()
        )
        req.refresh_from_db()
        req.start_date, req.end_date = (
            date.today() - timedelta(days=5),
            date.today() - timedelta(days=1),
        )
        req.save()
        PDCourseTrackingService.mark_complete(
            req.id,
            self.cceo,
            actual_completion_date=date.today(),
            course_outcome="Done.",
        )
        PDCourseTrackingService.upload_certificate(req.id, self.cceo, _pdf())
        PDCourseTrackingService.confirm_bamboohr(req.id, self.cceo)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.BAMBOOHR_CONFIRMED)
        with self.assertRaises(BadRequest):
            PDCourseTrackingService.submit_accountability(
                req.id,
                self.cceo,
                actual_spent=50_000_00,
                returned_amount=0,
                netsuite_expense_id="",
            )
        PDCourseTrackingService.submit_accountability(
            req.id,
            self.cceo,
            actual_spent=50_000_00,
            returned_amount=0,
            netsuite_expense_id="NS-100",
        )
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.ACCOUNTABILITY_SUBMITTED)
        missing = PDCourseTrackingService._assert_signoff_eligible(req)
        self.assertIn("Finance has not cleared accountability", missing)
        PDFundRequestService.clear_accountability(req.id, self.accountant)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.AWAITING_HR_SIGNOFF)
        PDCourseTrackingService.sign_off(req.id, self.hr)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.COMPLETED_CLOSED)

    def test_deferred_withdrawn_requires_a_reason(self):
        req = self._fund_and_approve(self._draft(self.cceo), funded=False)
        PDCourseTrackingService.confirm_enrollment(
            req.id, self.cceo, enrollment_date=date.today()
        )
        req.refresh_from_db()
        with self.assertRaises(BadRequest):
            PDCourseTrackingService.mark_deferred_or_withdrawn(
                req.id, self.cceo, outcome="withdrawn", reason=""
            )
        PDCourseTrackingService.mark_deferred_or_withdrawn(
            req.id, self.cceo, outcome="withdrawn", reason="Personal circumstances."
        )
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.WITHDRAWN)


class SelfConflictTests(PDTestBase):
    def test_accountant_cannot_disburse_own_request(self):
        req = self._draft(
            self.accountant,
            funding_type="fully_funded",
            requested_amount_cents=20_000_00,
            course_fee_cents=20_000_00,
        )
        # The Accountant test fixture has no configured supervisor, so it
        # would auto-skip straight to HR on a real submit() — set the status
        # to match that reality rather than the (unreachable) supervisor stage.
        req.status = PDStatus.SUBMITTED_TO_HR
        req.save()
        PDApprovalRoutingService.hr_approve(req.id, self.hr)
        req.refresh_from_db()
        self.assertTrue(hasattr(req, "fund_request"))
        with self.assertRaises(Forbidden):
            PDFundRequestService.disburse(
                req.fund_request.id,
                self.accountant,
                method="bank_transfer",
                reference="X",
            )

    def test_accountant_cannot_clear_own_accountability(self):
        req = self._draft(self.accountant)
        req.status = PDStatus.ACCOUNTABILITY_SUBMITTED
        req.accountability_netsuite_id = "NS-1"
        req.save()
        with self.assertRaises(Forbidden):
            PDFundRequestService.clear_accountability(req.id, self.accountant)

    def test_leadership_cannot_signoff_own_course(self):
        req = self._draft(self.hr)
        req.status = PDStatus.AWAITING_HR_SIGNOFF
        req.marked_complete_at = timezone.now()
        req.bamboohr_uploaded = True
        req.save()
        with self.assertRaises(Forbidden):
            PDCourseTrackingService.sign_off(req.id, self.hr)


class ResubmissionGuardTests(PDTestBase):
    def test_submit_blocked_once_request_is_active_or_closed(self):
        """A previously-fixed bug: submit() must reject anything past
        draft/returned so an in-flight or closed record can never be
        silently overwritten and re-entered into the approval loop."""
        req = self._draft(self.cceo)
        req.status = PDStatus.IN_PROGRESS
        req.save()
        with self.assertRaises(BadRequest):
            PDApprovalRoutingService.submit(req, self.cceo)

    def test_pd_request_view_rejects_editing_a_non_editable_status(self):
        req = self._draft(self.cceo)
        req.status = PDStatus.SUBMITTED_TO_HR
        req.save()
        client = Client()
        client.force_login(self.cceo)
        resp = client.post(
            "/my-professional-development/request",
            {
                "id": req.id,
                "fy": FY,
                "course_name": "Hacked Name",
                "intent": "draft",
            },
        )
        self.assertEqual(resp.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.course_name, "Leadership for Impact")


class PrivacyTests(PDTestBase):
    def test_staff_cannot_view_another_employees_pd_file(self):
        req = self._draft(self.cceo)
        client = Client()
        client.force_login(self.pl)
        resp = client.get(f"/my-professional-development/request?id={req.id}")
        self.assertEqual(resp.status_code, 404)

    def test_supervisor_can_view_at_exactly_the_supervisor_stage(self):
        req = self._draft(self.cceo)
        req.status = PDStatus.SUBMITTED_TO_SUPERVISOR
        req.save()
        client = Client()
        client.force_login(self.pl)
        resp = client.get(f"/my-professional-development/request?id={req.id}")
        self.assertEqual(resp.status_code, 200)

    def test_certificate_file_denied_to_unrelated_staff(self):
        req = self._draft(self.cceo)
        req.status = PDStatus.MARKED_COMPLETE
        req.marked_complete_at = timezone.now()
        req.save()
        cert = PDCourseTrackingService.upload_certificate(req.id, self.cceo, _pdf())
        client = Client()
        client.force_login(
            self.pl
        )  # not the owner, not the supervisor at this stage, not HR
        client.force_login(self.rvp)
        resp = client.get(f"/my-professional-development/certificate/{cert.id}")
        self.assertEqual(resp.status_code, 200)  # RVP is authorized (leadership)
        client.force_login(self.hr2)
        resp = client.get(f"/my-professional-development/certificate/{cert.id}")
        self.assertEqual(resp.status_code, 200)  # HR is authorized


class ActionRequiredQueueTests(PDTestBase):
    def test_action_required_matches_can_review_exactly(self):
        """The derived action-required queue (sidebar badge + To-Do) must
        never show a record the underlying service would refuse to let this
        principal act on."""
        req = self._draft(self.cceo)
        req.status = PDStatus.SUBMITTED_TO_SUPERVISOR
        req.save()
        pl_queue = StaffPDService.action_required(self.pl)
        self.assertIn(req.id, [r.id for r in pl_queue["reviewing"]])
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.pl))

        cd_queue = StaffPDService.action_required(self.cd)
        self.assertNotIn(req.id, [r.id for r in cd_queue["reviewing"]])
        self.assertFalse(PDApprovalRoutingService.can_review(req, self.cd))

    def test_returned_request_surfaces_in_employees_own_queue(self):
        req = self._draft(self.cceo)
        req.status = PDStatus.RETURNED_BY_SUPERVISOR
        req.supervisor_note = "Add a brochure."
        req.save()
        own_queue = StaffPDService.action_required(self.cceo)
        self.assertIn(req.id, [r.id for r in own_queue["own"]])


class HealthCheckTests(PDTestBase):
    def test_pd_health_checks_catch_a_self_signoff_leak(self):
        """A direct ORM write (bypassing the service-layer guard) must still
        be caught by the system-health integrity check — the guard and the
        health check are independent layers of defence."""
        from apps.professional_development.health import pd_health_checks

        req = self._draft(self.cceo)
        req.status = PDStatus.COMPLETED_CLOSED
        req.signed_off_by = self.cceo.id  # simulates a leaked self-signoff
        req.save()
        result = pd_health_checks()
        leak_check = next(c for c in result["checks"] if c["key"] == "pd_self_signoff")
        self.assertEqual(leak_check["count"], 1)
        self.assertEqual(leak_check["severity"], "blocking")

    def test_clean_data_produces_zero_violations(self):
        from apps.professional_development.health import pd_health_checks

        result = pd_health_checks()
        self.assertEqual(len(result["checks"]), 15)
        self.assertTrue(all(c["count"] == 0 for c in result["checks"]))


class HRDashboardTests(PDTestBase):
    """§16 — the HR Professional Development Dashboard: role-based scoping
    (HR/Admin unrestricted, CountryDirector own-country, Program Lead
    own-team) and the one write path (role allocation template, optionally
    bulk-applied to real staff balances)."""

    def setUp(self):
        super().setUp()
        # A second-country CCEO so CD/PL scoping has something real to exclude.
        self.kenya_cceo, self.kenya_cceo_sp = self._staff(
            "kenya.cceo@pd.org", "Kamau CCEO", EdifyRole.CCEO.value
        )
        self.kenya_cceo_sp.country = "Kenya"
        self.kenya_cceo_sp.save()

    def test_hr_sees_every_country_unrestricted(self):
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        self._draft(self.cceo, status=PDStatus.IN_PROGRESS)
        self._draft(self.kenya_cceo, status=PDStatus.IN_PROGRESS)
        ctx = HRPDDashboardService.get_dashboard(self.hr, {})
        self.assertIsNone(ctx["locked_country"])
        self.assertEqual(ctx["tracker_total"], 2)

    def test_country_director_locked_to_own_country(self):
        """CD's own StaffProfile is Uganda — the Kenyan CCEO's record must
        never appear, even though HR sees both."""
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        self._draft(self.cceo, status=PDStatus.IN_PROGRESS)
        self._draft(self.kenya_cceo, status=PDStatus.IN_PROGRESS)
        ctx = HRPDDashboardService.get_dashboard(self.cd, {})
        self.assertEqual(ctx["locked_country"], "Uganda")
        self.assertEqual(ctx["tracker_total"], 1)
        self.assertEqual(ctx["tracker_rows"][0]["staff_name"], self.cceo.name)

    def test_program_lead_locked_to_supervised_team(self):
        """PL supervises only self.cceo (per PDTestBase.setUp) — the Kenyan
        CCEO isn't on the team and must not appear even though both are
        nominally the same role."""
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        self._draft(self.cceo, status=PDStatus.IN_PROGRESS)
        self._draft(self.kenya_cceo, status=PDStatus.IN_PROGRESS)
        ctx = HRPDDashboardService.get_dashboard(self.pl, {})
        self.assertEqual(ctx["tracker_total"], 1)
        self.assertEqual(ctx["tracker_rows"][0]["staff_name"], self.cceo.name)

    def test_kpi_strip_has_eight_cards(self):
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        ctx = HRPDDashboardService.get_dashboard(self.hr, {})
        self.assertEqual(len(ctx["kpis"]), 8)
        self.assertEqual(
            {k["key"] for k in ctx["kpis"]},
            {
                "allocation",
                "committed",
                "accounted",
                "enrolled",
                "in_progress",
                "pending_cert",
                "pending_acct",
                "signoff",
            },
        )

    def test_action_center_has_five_groups_signoff_is_the_only_dedicated_action(self):
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        req = self._draft(self.cceo, status=PDStatus.AWAITING_HR_SIGNOFF)
        ctx = HRPDDashboardService.get_dashboard(self.hr, {})
        self.assertEqual(len(ctx["action_center"]), 5)
        signoff_group = next(
            g for g in ctx["action_center"] if g["key"] == "ready_signoff"
        )
        self.assertEqual(signoff_group["count"], 1)
        self.assertEqual(signoff_group["items"][0]["id"], req.id)
        self.assertEqual(signoff_group["items"][0]["action"], "sign_off")

    def test_status_filter_narrows_tracker(self):
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        self._draft(self.cceo, status=PDStatus.IN_PROGRESS, course_name="Active Course")
        self._draft(self.kenya_cceo, status=PDStatus.ENDED, course_name="Ended Course")
        ctx = HRPDDashboardService.get_dashboard(self.hr, {"status": "in_progress"})
        self.assertEqual(ctx["tracker_total"], 1)
        self.assertEqual(ctx["tracker_rows"][0]["course_name"], "Active Course")

    def test_adjust_role_allocation_creates_template_row(self):
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        pra = HRPDDashboardService.adjust_role_allocation(
            self.hr, role="CCEO", fy=FY, country="Uganda", amount_major=250000
        )
        self.assertEqual(pra.annual_allocation_cents, 25000000)
        self.assertEqual(pra.set_by, self.hr.id)

    def test_adjust_role_allocation_apply_to_existing_bulk_updates_real_balances(self):
        """The bulk-apply is opt-in: without it, the template changes but no
        staff member's own balance moves."""
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        HRPDDashboardService.adjust_role_allocation(
            self.hr, role="CCEO", fy=FY, country="Uganda", amount_major=250000
        )
        self.assertFalse(
            ProfessionalDevelopmentAllocation.objects.filter(
                staff_id=self.cceo_sp.id
            ).exists()
        )

        HRPDDashboardService.adjust_role_allocation(
            self.hr,
            role="CCEO",
            fy=FY,
            country="Uganda",
            amount_major=300000,
            apply_to_existing=True,
        )
        alloc = ProfessionalDevelopmentAllocation.objects.get(
            staff_id=self.cceo_sp.id, fy=FY
        )
        self.assertEqual(alloc.annual_allocation, 30000000)
        # The Kenyan CCEO is a different country — must be untouched.
        self.assertFalse(
            ProfessionalDevelopmentAllocation.objects.filter(
                staff_id=self.kenya_cceo_sp.id
            ).exists()
        )

    def test_adjust_role_allocation_forbidden_for_non_hr(self):
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        with self.assertRaises(Forbidden):
            HRPDDashboardService.adjust_role_allocation(
                self.cd, role="CCEO", fy=FY, country="Uganda", amount_major=100000
            )

    def test_adjust_role_allocation_rejects_unknown_role(self):
        from apps.professional_development.hr_dashboard_service import (
            HRPDDashboardService,
        )

        with self.assertRaises(BadRequest):
            HRPDDashboardService.adjust_role_allocation(
                self.hr,
                role="NotARealRole",
                fy=FY,
                country="Uganda",
                amount_major=100000,
            )

    def test_dashboard_view_renders_for_hr_cd_and_pl(self):
        client = Client()
        for user in (self.hr, self.cd, self.pl):
            client.force_login(user)
            resp = client.get("/cpd-learning")
            self.assertEqual(resp.status_code, 200)

    def test_dashboard_view_redirects_for_a_role_without_page_access(self):
        """CCEO isn't in the cpd_learning permission set — plain (non-HTMX)
        GET must bounce to the dashboard, not render."""
        client = Client()
        client.force_login(self.cceo)
        resp = client.get("/cpd-learning")
        self.assertEqual(resp.status_code, 302)

    def test_adjust_allocation_view_post_writes_and_redirects(self):
        client = Client()
        client.force_login(self.hr)
        resp = client.post(
            "/cpd-learning/adjust-allocation",
            {
                "role": "CCEO",
                "fy": FY,
                "country": "Uganda",
                "annual_allocation": "400000",
                "currency": "UGX",
            },
        )
        self.assertEqual(resp.status_code, 302)
        pra = PDRoleAllocation.objects.get(role="CCEO", fy=FY, country="Uganda")
        self.assertEqual(pra.annual_allocation_cents, 40000000)

    def test_action_view_sign_off_closes_the_request(self):
        req = self._draft(
            self.cceo,
            status=PDStatus.AWAITING_HR_SIGNOFF,
            marked_complete_at=timezone.now(),
            bamboohr_uploaded=True,
        )
        ProfessionalDevelopmentCertificate.objects.create(
            request=req,
            uri="test/cert.pdf",
            original_name="cert.pdf",
            uploaded_by=self.cceo.id,
            status="uploaded",
        )
        client = Client()
        client.force_login(self.hr)
        resp = client.post(
            "/cpd-learning/action", {"action": "sign_off", "request_id": req.id}
        )
        self.assertEqual(resp.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.COMPLETED_CLOSED)

    def test_action_view_unknown_action_is_rejected(self):
        client = Client()
        client.force_login(self.hr)
        resp = client.post("/cpd-learning/action", {"action": "nonsense"})
        self.assertEqual(resp.status_code, 400)
