"""The leave approvals queue reads the reviewer's lookups once, not per leave.

The queue asks `is_authorized_approver` of every pending leave in the country
in three loops, and each call read the leave type's policy, the reviewer's
active coverage and one supervisor row: a Programme Lead's queue of 348
requests was 1,130 queries at production scale (2026-09-24 A+ audit).
`approval_lookups()` shares those lookups for the page. These tests hold the
two things that change must never break: the answer for every leave and
reviewer is the answer the unshared rule gives, and the page's query count no
longer grows with the number of pending requests.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    LeaveTypePolicy,
    StaffProfile,
    StaffSupervisorAssignment,
    TemporaryCoverageAssignment,
    User,
)
from apps.hr.leave_services import LeaveApprovalService, approval_lookups


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


class LeaveApprovalQueueQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd, cls.cd_sp = _staff("CountryDirector", "cd@laq.test")
        cls.hr, cls.hr_sp = _staff("HumanResources", "hr@laq.test")
        cls.pl, cls.pl_sp = _staff("Program Lead", "pl@laq.test")
        cls.other_pl, cls.other_pl_sp = _staff("Program Lead", "pl2@laq.test")
        cls.mine = [_staff("CCEO", f"mine{i}@laq.test") for i in range(3)]
        cls.theirs = [_staff("CCEO", f"theirs{i}@laq.test") for i in range(3)]
        for _user, sp in cls.mine:
            StaffSupervisorAssignment.objects.create(
                supervisee=sp, supervisor=cls.pl_sp
            )
        for _user, sp in cls.theirs:
            StaffSupervisorAssignment.objects.create(
                supervisee=sp, supervisor=cls.other_pl_sp
            )
        for sp in (cls.pl_sp, cls.other_pl_sp):
            StaffSupervisorAssignment.objects.create(
                supervisee=sp, supervisor=cls.cd_sp
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
                "approver_role": "CountryDirector",
                "requires_attachment": False,
            },
        )

    def _leave(self, staff, *, leave_type="personal_time_off", status="pending"):
        return Leave.objects.create(
            staff=staff,
            type=leave_type,
            start_date="2026-09-01",
            end_date="2026-09-05",
            days=5,
            days_charged=5,
            status=status,
            reason="Family",
        )

    def _all_leaves(self):
        leaves = []
        for _user, sp in [*self.mine, *self.theirs]:
            leaves.append(self._leave(sp))
            leaves.append(self._leave(sp, leave_type="maternity_leave"))
            leaves.append(self._leave(sp, status="hr_review"))
        leaves.append(self._leave(self.pl_sp))
        leaves.append(self._leave(self.other_pl_sp))
        return leaves

    def test_shared_lookups_give_the_unshared_answer_for_every_leave(self):
        leaves = self._all_leaves()
        # The Programme Lead also stands in for the other lead, so the
        # coverage arm of the rule is exercised through the shared lookups.
        now = timezone.now()
        TemporaryCoverageAssignment.objects.create(
            leave_request=leaves[-1],
            original_staff=self.other_pl_sp,
            covering_staff=self.pl_sp,
            start_datetime=now - timedelta(days=1),
            end_datetime=now + timedelta(days=1),
            status="active",
        )
        reviewers = (
            self.pl,
            self.other_pl,
            self.cd,
            self.hr,
            *[u for u, _ in self.mine],
        )
        for reviewer in reviewers:
            fresh = User.objects.get(pk=reviewer.pk)
            expected = [
                LeaveApprovalService.is_authorized_approver(fresh, lv) for lv in leaves
            ]
            with approval_lookups():
                shared = [
                    LeaveApprovalService.is_authorized_approver(fresh, lv)
                    for lv in leaves
                ]
            with self.subTest(reviewer=reviewer.email):
                self.assertEqual(shared, expected)
        # The coverage arm is what lets this lead act on the other team.
        self.assertTrue(
            LeaveApprovalService.is_authorized_approver(
                User.objects.get(pk=self.pl.pk), leaves[3 * len(self.mine)]
            )
        )

    def test_the_scope_closes_so_decisions_read_live_rows(self):
        with approval_lookups():
            pass
        leave = self._leave(self.mine[0][1])
        self.assertTrue(LeaveApprovalService.is_authorized_approver(self.pl, leave))
        StaffSupervisorAssignment.objects.filter(supervisor=self.pl_sp).delete()
        self.assertFalse(LeaveApprovalService.is_authorized_approver(self.pl, leave))

    def _queue_queries(self):
        self.client.force_login(self.pl)
        self.client.get("/leave/approvals")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/leave/approvals")
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_queue_query_count_does_not_grow_with_pending_requests(self):
        for _user, sp in self.theirs:
            self._leave(sp)
        before = self._queue_queries()
        # Thirty more requests the lead does not approve: each one used to
        # cost three more queries per loop over the queue.
        for _ in range(10):
            for _user, sp in self.theirs:
                self._leave(sp)
        after = self._queue_queries()
        self.assertLessEqual(after, before)
