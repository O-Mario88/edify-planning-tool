"""Workforce continuity: an escalation must escalate, and coverage must expire.

Three defects the audit proved. Escalating a leave request made it *less*
visible than leaving it alone. Every coverage assignment ever created read
"active" on the two pages built to audit delegated access. And an RVP could
approve leave for anyone, anywhere, because that arm was a bare `return True`.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    TemporaryCoverageAssignment,
    User,
)
from apps.core.rbac import EdifyRole
from apps.hr.leave_services import LeaveApprovalService


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
    )


class EscalatedLeaveIsActionableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = _user("esc-staff@t.org", "Staffer", EdifyRole.CCEO.value)
        cls.sp = StaffProfile.objects.create(user=cls.staff, country="Uganda")
        cls.hr = _user("esc-hr@t.org", "HR One", "HumanResources")
        cls.hr_sp = StaffProfile.objects.create(user=cls.hr, country="Uganda")

    def _leave(self, status="hr_review"):
        return Leave.objects.create(
            staff=self.sp,
            type="personal_time_off",
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=6),
            days=2,
            status=status,
        )

    def test_hr_can_act_on_an_escalated_request(self):
        leave = self._leave()
        self.assertTrue(
            LeaveApprovalService.is_authorized_approver(self.hr, leave),
            "escalating to HR pointed at a role that could not act",
        )

    def test_hr_still_cannot_approve_their_own_escalated_leave(self):
        own = Leave.objects.create(
            staff=self.hr_sp,
            type="personal_time_off",
            start_date=date.today(),
            end_date=date.today(),
            days=1,
            status="hr_review",
        )
        self.assertFalse(LeaveApprovalService.is_authorized_approver(self.hr, own))

    def test_hr_is_not_an_approver_for_an_ordinary_pending_request(self):
        """The escalation arm must not become a general HR approval grant."""
        leave = self._leave(status="pending")
        self.assertFalse(LeaveApprovalService.is_authorized_approver(self.hr, leave))

    def test_escalated_requests_stay_in_the_todo_queue(self):
        import inspect

        from apps.command_center import todo_service

        source = inspect.getsource(todo_service._leave_todos)
        self.assertIn(
            'status__in=("pending", "hr_review")',
            source,
            "an escalated request vanished from every queue on the platform",
        )

    def test_escalation_notifies_and_audits(self):
        import inspect

        source = inspect.getsource(LeaveApprovalService.escalate_to_hr)
        self.assertIn("leave_escalated_to_hr", source)
        self.assertIn("_audit_leave", source)


class CoverageLivenessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        a = _user("cov-a@t.org", "Away", EdifyRole.CCEO.value)
        b = _user("cov-b@t.org", "Cover", EdifyRole.CCEO.value)
        cls.sp_a = StaffProfile.objects.create(user=a, country="Uganda")
        cls.sp_b = StaffProfile.objects.create(user=b, country="Uganda")
        cls.leave = Leave.objects.create(
            staff=cls.sp_a,
            type="personal_time_off",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
            days=2,
            status="approved",
        )

    def _coverage(self, start_offset, end_offset, status="active"):
        now = timezone.now()
        return TemporaryCoverageAssignment.objects.create(
            leave_request=self.leave,
            original_staff=self.sp_a,
            covering_staff=self.sp_b,
            start_datetime=now + timedelta(days=start_offset),
            end_datetime=now + timedelta(days=end_offset),
            status=status,
        )

    def test_a_current_window_is_live(self):
        self.assertTrue(self._coverage(-1, 1).is_live)

    def test_a_closed_window_is_not_live_despite_its_status(self):
        past = self._coverage(-30, -20)
        self.assertEqual(past.status, "active", "nothing ever writes 'expired'")
        self.assertFalse(
            past.is_live,
            "the two pages built to audit delegated access showed every "
            "historical grant as active",
        )

    def test_a_future_window_is_not_live_yet(self):
        self.assertFalse(self._coverage(5, 10).is_live)

    def test_a_revoked_assignment_is_not_live(self):
        self.assertFalse(self._coverage(-1, 1, status="revoked").is_live)


class RvpLeaveScopeTests(TestCase):
    """The RVP arm was a bare `return True` while the CD arm beside it
    correctly required a country match."""

    def test_rvp_scope_is_evaluated_not_assumed(self):
        import inspect

        source = inspect.getsource(LeaveApprovalService.is_authorized_approver)
        self.assertNotIn(
            'if rev_role == "rvp":\n                return True',
            source,
            "an RVP could approve any PC/IA/Accountant/HR/CD leave anywhere",
        )
        self.assertIn("_rvp_covers", source)
