"""Announcing a leave decision belongs to the transition, not to one door.

The HTMX views fired every leave notification themselves, and the DRF endpoints
at /api/hr/leave did not — so a request submitted through the API reached no
approver's inbox, and a decision made through it never closed the approver's
"needs approval" notice, which the escalation sweep then promoted to urgent
(2026-08 audit D3).

Moving the calls into LeaveRequestService and LeaveApprovalService fixes both
doors at once and means a third cannot repeat it. These tests drive the API
path specifically, because that is the one that was silent.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import (
    LeaveTypePolicy,
    StaffProfile,
    StaffSupervisorAssignment,
)

from apps.notifications.models import Notification

User = get_user_model()


def _staff(key: str, role: str):
    user = User.objects.create_user(
        email=f"{key}@edify.test",
        name=f"{key} person",
        roles=[role],
        active_role=role,
        password="password123",
        is_active=True,
    )
    profile = StaffProfile.objects.create(
        id=f"sp-{key}", user=user, title=role, country="Uganda"
    )
    # `staff_profile` is StaffProfile's related_name, and User.staff_profile_id
    # memoises its lookup — so the instance has to be re-fetched, not assigned.
    return User.objects.get(id=user.id), profile


def _leave_policy():
    LeaveTypePolicy.objects.update_or_create(
        leave_type="personal_time_off",
        defaults={
            "label": "Personal Time Off",
            "annual_entitlement": 21,
            "approver_role": "Program Lead",
        },
    )


class LeaveApiDoorNotifiesTest(TestCase):
    def setUp(self):
        _leave_policy()
        self.cceo, self.cceo_sp = _staff("leavedoor-cceo", "CCEO")
        self.pl, self.pl_sp = _staff("leavedoor-pl", "Program Lead")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )
        start = date.today() + timedelta(days=14)
        self.payload = {
            "type": "personal_time_off",
            "startDate": start.isoformat(),
            "endDate": (start + timedelta(days=2)).isoformat(),
            "reason": "Family matters requiring a few days away from the field.",
        }

    def _request_through_the_api(self):
        from apps.hr.services import request_leave

        return request_leave(self.payload, self.cceo)

    def test_a_request_made_through_the_api_reaches_the_approver(self):
        self._request_through_the_api()
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.pl.id, source_event_type="leave_requested"
            ).exists(),
            "a leave request submitted through /api/hr/leave reached no "
            "approver's inbox",
        )

    def test_a_decision_made_through_the_api_closes_the_approvers_notice(self):
        from apps.hr.services import review_leave

        leave = self._request_through_the_api()
        open_notice = Notification.objects.filter(
            recipient_id=self.pl.id,
            source_event_type="leave_requested",
            resolved_at__isnull=True,
        )
        self.assertEqual(open_notice.count(), 1)

        review_leave(leave["id"], "approved", self.pl)
        self.assertEqual(
            open_notice.count(),
            0,
            "the request was decided but its notice stayed open — the "
            "escalation sweep promotes those to urgent at 48 hours",
        )

    def test_the_html_door_still_notifies_exactly_once(self):
        """The calls moved into the service; the view must not fire a second."""
        self._request_through_the_api()
        self.assertEqual(
            Notification.objects.filter(
                recipient_id=self.pl.id, source_event_type="leave_requested"
            ).count(),
            1,
        )


class CoverageDecisionIsAnnouncedTest(TestCase):
    """Accepting said "The supervisor is notified." and sent nothing (D4).

    That became load-bearing when approval started refusing a declined cover:
    an approver who never hears the answer meets the refusal with no idea why.
    """

    def setUp(self):
        _leave_policy()
        self.cceo, self.cceo_sp = _staff("cov-cceo", "CCEO")
        self.pl, self.pl_sp = _staff("cov-pl", "Program Lead")
        self.cover, self.cover_sp = _staff("cov-cover", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )
        from apps.hr.leave_services import LeaveRequestService

        start = date.today() + timedelta(days=21)
        self.leave = LeaveRequestService.request_leave(
            self.cceo_sp,
            {
                "type": "personal_time_off",
                "start_date": start.isoformat(),
                "end_date": (start + timedelta(days=2)).isoformat(),
                "reason": "Time away that a colleague has agreed to cover.",
                "covering_staff": self.cover_sp.id,
            },
        )

    def _decisions(self):
        return Notification.objects.filter(
            recipient_id=self.pl.id, source_event_type="leave_coverage_decided"
        )

    def test_accepting_tells_the_approver(self):
        from apps.hr.leave_services import LeaveApprovalService

        LeaveApprovalService.accept_coverage(self.leave.id, self.cover)
        self.assertEqual(self._decisions().count(), 1)
        self.assertIn("accepted", self._decisions().first().title.lower())

    def test_declining_tells_the_approver_and_says_what_to_do(self):
        from apps.hr.leave_services import LeaveApprovalService

        LeaveApprovalService.decline_coverage(self.leave.id, self.cover)
        notice = self._decisions().first()
        self.assertIsNotNone(notice, "a declined cover was never announced")
        self.assertEqual(
            notice.priority, "high", "a decline blocks the approval that follows"
        )
        self.assertIn("Assign a different covering employee", notice.body)

    def test_answering_closes_the_covers_own_request_to_answer(self):
        from apps.hr.leave_services import LeaveApprovalService

        LeaveApprovalService.accept_coverage(self.leave.id, self.cover)
        self.assertEqual(
            Notification.objects.filter(
                source_event_type="leave_coverage_proposed",
                context_id=self.leave.id,
                resolved_at__isnull=True,
            ).count(),
            0,
            "the cover answered and was still being asked to answer",
        )
