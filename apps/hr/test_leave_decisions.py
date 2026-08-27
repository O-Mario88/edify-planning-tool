"""Leave decisions after the 2026-08-20 HR audit.

Four defects, all of them live:

  C1  Escalating to HR moved the request into a status no approval path
      accepted. HR opened it, clicked Approve, and was told it was "already
      hr_review". Escalation was a one-way trap.
  C2  Reject and Return wrote the status with no lock and no guard, so an
      already-APPROVED leave could be flipped to rejected hours later while
      its coverage assignment stayed active.
  C3  Escalation accepted any status, so an approved leave could be pushed
      back to hr_review — dropping its days out of the approved balance while
      the person was actually away.
  --  `LeaveTypePolicy.approver_role` was written by the policy page and read
      by nothing at all.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import (
    Leave,
    LeaveBalance,
    LeaveTypePolicy,
    StaffProfile,
    StaffSupervisorAssignment,
    TemporaryCoverageAssignment,
    User,
)
from apps.core.exceptions import BadRequest
from apps.hr.leave_services import LeaveApprovalService, LeaveRequestService


def _staff(role, email):
    user = User.objects.create_user(
        email=email,
        password="pw",
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        is_active=True,
    )
    return user, StaffProfile.objects.create(
        user=user, title=role, country="Uganda", onboarding_state="active"
    )


class LeaveDecisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd, cls.cd_sp = _staff("CountryDirector", "cd@ld.test")
        cls.hr, cls.hr_sp = _staff("HumanResources", "hr@ld.test")
        cls.pl, cls.pl_sp = _staff("Program Lead", "pl@ld.test")
        cls.cceo, cls.cceo_sp = _staff("CCEO", "cceo@ld.test")
        cls.cover, cls.cover_sp = _staff("CCEO", "cover@ld.test")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo_sp, supervisor=cls.pl_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.pl_sp, supervisor=cls.cd_sp
        )
        LeaveTypePolicy.objects.update_or_create(
            leave_type="personal_time_off",
            defaults={
                "label": "Personal Time Off",
                "annual_entitlement": 21,
                "approver_role": "Program Lead",
            },
        )
        LeaveTypePolicy.objects.update_or_create(
            leave_type="maternity_leave",
            defaults={
                "label": "Maternity Leave",
                "annual_entitlement": 60,
                # The floor the old code ignored entirely.
                "approver_role": "CountryDirector",
                "requires_attachment": False,
            },
        )

    def _leave(self, *, status="pending", leave_type="personal_time_off", cover=None):
        return Leave.objects.create(
            staff=self.cceo_sp,
            type=leave_type,
            start_date="2026-09-01",
            end_date="2026-09-05",
            days=5,
            days_charged=5,
            status=status,
            covering_staff=cover,
        )

    # ── C1 ───────────────────────────────────────────────────────────────
    def test_hr_can_approve_what_was_escalated_to_them(self):
        leave = self._leave()
        LeaveApprovalService.escalate_to_hr(leave, self.pl)
        leave.refresh_from_db()
        self.assertEqual(leave.status, "hr_review")

        LeaveApprovalService.approve_request(leave.id, self.hr)
        leave.refresh_from_db()
        self.assertEqual(leave.status, "approved")
        self.assertEqual(leave.reviewed_by_user_id, self.hr.id)

    # ── C3 ───────────────────────────────────────────────────────────────
    def test_an_approved_leave_cannot_be_pushed_back_to_hr(self):
        leave = self._leave(status="approved")
        with self.assertRaises(BadRequest) as caught:
            LeaveApprovalService.escalate_to_hr(leave, self.pl)
        self.assertIn("already approved", str(caught.exception))

    # ── C2 ───────────────────────────────────────────────────────────────
    def test_an_approved_leave_cannot_later_be_rejected(self):
        leave = self._leave()
        LeaveApprovalService.approve_request(leave.id, self.pl)
        with self.assertRaises(BadRequest):
            LeaveApprovalService.reject_request(leave.id, self.pl, "changed my mind")
        leave.refresh_from_db()
        self.assertEqual(leave.status, "approved")

    def test_a_rejected_leave_cannot_later_be_returned(self):
        leave = self._leave()
        LeaveApprovalService.reject_request(leave.id, self.pl, "no capacity")
        with self.assertRaises(BadRequest):
            LeaveApprovalService.return_request(leave.id, self.pl, "actually, fix it")

    def test_returning_for_correction_is_audited_like_every_other_decision(self):
        from apps.audit.models import AuditLog

        leave = self._leave()
        LeaveApprovalService.return_request(
            leave.id, self.pl, "Dates clash with a visit"
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="leave.returned", subject_id=leave.id
            ).exists()
        )

    # ── approver_role ────────────────────────────────────────────────────
    def test_a_leave_type_can_demand_a_more_senior_approver(self):
        leave = self._leave(leave_type="maternity_leave")
        # The PL is the CCEO's direct manager, and would have been allowed.
        self.assertFalse(LeaveApprovalService.is_authorized_approver(self.pl, leave))
        with self.assertRaises(BadRequest):
            LeaveApprovalService.approve_request(leave.id, self.pl)

    def test_the_ordinary_floor_still_lets_the_direct_manager_approve(self):
        leave = self._leave()
        self.assertTrue(LeaveApprovalService.is_authorized_approver(self.pl, leave))

    # ── coverage ─────────────────────────────────────────────────────────
    def test_declining_coverage_revokes_the_access_it_granted(self):
        leave = self._leave(cover=self.cover_sp)
        LeaveApprovalService.approve_request(leave.id, self.pl)
        self.assertTrue(
            TemporaryCoverageAssignment.objects.filter(
                leave_request_id=leave.id, status="active"
            ).exists()
        )

        LeaveApprovalService.decline_coverage(leave.id, self.cover)
        leave.refresh_from_db()
        self.assertEqual(leave.coverage_status, "Declined")
        self.assertFalse(
            TemporaryCoverageAssignment.objects.filter(
                leave_request_id=leave.id, status="active"
            ).exists(),
            "the person who refused the cover kept the delegated access",
        )

    def test_approving_does_not_hand_access_to_a_cover_who_declined(self):
        """Approval read `covering_staff` and never `coverage_status`, so a
        cover who had refused was granted the delegated access anyway."""
        leave = self._leave(cover=self.cover_sp)
        LeaveApprovalService.decline_coverage(leave.id, self.cover)

        with self.assertRaises(BadRequest) as caught:
            LeaveApprovalService.approve_request(leave.id, self.pl)
        self.assertIn("declined to cover", str(caught.exception))

        leave.refresh_from_db()
        self.assertEqual(leave.status, "pending")
        self.assertNotEqual(
            leave.coverage_status,
            "Approved",
            "approval overwrote the cover's refusal",
        )
        self.assertFalse(
            TemporaryCoverageAssignment.objects.filter(
                leave_request_id=leave.id,
                covering_staff_id=self.cover_sp.id,
                status="active",
            ).exists(),
            "the person who refused the cover was granted the delegated access",
        )

    def test_a_declined_cover_can_be_replaced_and_the_leave_then_approved(self):
        """The refusal above must not strand the absent person: naming another
        cover is the supervisor's remedy and reopens approval."""
        second_cover, second_sp = _staff("CCEO", "cover3@ld.test")
        leave = self._leave(cover=self.cover_sp)
        LeaveApprovalService.decline_coverage(leave.id, self.cover)

        leave.covering_staff = second_sp
        leave.coverage_status = "Awaiting Acceptance"
        leave.save(update_fields=["covering_staff", "coverage_status"])

        LeaveApprovalService.approve_request(leave.id, self.pl)
        leave.refresh_from_db()
        self.assertEqual(leave.status, "approved")
        live = TemporaryCoverageAssignment.objects.filter(
            leave_request_id=leave.id, status="active"
        )
        self.assertEqual(live.count(), 1)
        self.assertEqual(live.first().covering_staff_id, second_sp.id)

    def test_reassigning_the_cover_moves_the_delegated_access(self):
        """The replaced cover kept full access for the whole window, and the
        new cover got none — and approve_request refuses to re-run, so there
        was no second chance to put it right."""
        second_cover, second_sp = _staff("CCEO", "cover2@ld.test")
        leave = self._leave(cover=self.cover_sp)
        LeaveApprovalService.approve_request(leave.id, self.pl)

        LeaveApprovalService.reassign_coverage(leave, second_sp, self.pl)

        live = TemporaryCoverageAssignment.objects.filter(
            leave_request_id=leave.id, status="active"
        )
        self.assertEqual(live.count(), 1)
        self.assertEqual(live.first().covering_staff_id, second_sp.id)
        self.assertFalse(
            TemporaryCoverageAssignment.objects.filter(
                leave_request_id=leave.id,
                covering_staff_id=self.cover_sp.id,
                status="active",
            ).exists()
        )

    def test_removing_the_cover_entirely_revokes_the_access(self):
        leave = self._leave(cover=self.cover_sp)
        LeaveApprovalService.approve_request(leave.id, self.pl)
        LeaveApprovalService.reassign_coverage(leave, None, self.pl)
        self.assertFalse(
            TemporaryCoverageAssignment.objects.filter(
                leave_request_id=leave.id, status="active"
            ).exists()
        )

    # ── admin ────────────────────────────────────────────────────────────
    def test_admin_holds_no_approval_authority(self):
        admin, _ = _staff("Admin", "admin@ld.test")
        leave = self._leave()
        self.assertFalse(LeaveApprovalService.is_authorized_approver(admin, leave))


class LeaveSubmissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cceo, cls.cceo_sp = _staff("CCEO", "sub@ls.test")
        LeaveTypePolicy.objects.update_or_create(
            leave_type="personal_time_off",
            defaults={"label": "Personal Time Off", "annual_entitlement": 21},
        )

    def _request(self, start, end, leave_type="personal_time_off"):
        return LeaveRequestService.request_leave(
            self.cceo_sp,
            {"type": leave_type, "start_date": start, "end_date": end},
            None,
        )

    def test_overlapping_leave_is_refused(self):
        """Three overlapping requests for the same week were all approvable —
        fifteen days deducted for five days of absence."""
        self._request("2026-09-07", "2026-09-11")
        with self.assertRaises(BadRequest) as caught:
            self._request("2026-09-09", "2026-09-15")
        self.assertIn("already", str(caught.exception))

    def test_leave_either_side_of_an_existing_request_is_fine(self):
        self._request("2026-09-07", "2026-09-11")
        self._request("2026-09-14", "2026-09-18")  # must not raise

    def test_an_undefined_leave_type_cannot_mint_its_own_entitlement(self):
        """`get_or_create` on a free-text field meant posting an unknown type
        created a policy with a full default entitlement and no attachment
        requirement — self-service leave invention."""
        before = LeaveTypePolicy.objects.count()
        with self.assertRaises(BadRequest) as caught:
            self._request("2026-10-01", "2026-10-03", leave_type="sabbatical")
        self.assertIn("not a leave type HR has defined", str(caught.exception))
        self.assertEqual(LeaveTypePolicy.objects.count(), before)

    def test_a_known_type_still_charges_the_balance(self):
        self._request("2026-09-07", "2026-09-11")
        balance = LeaveBalance.objects.get(
            staff=self.cceo_sp, leave_type="personal_time_off", year=2026
        )
        self.assertEqual(balance.pending, 5)
