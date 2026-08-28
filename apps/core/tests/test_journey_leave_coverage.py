"""Journey 9 — Leave and temporary coverage, walked end to end.

Journey 9 of the mandate's twenty-two: Leave request, Approval, Calendar
block, Access transfer, To-Do transfer, Target rephasing, Return, Access
restoration.

This is the platform's only workflow that deliberately hands one person's
authority to another, which makes its last step the one that matters most.
Access transfer is easy to get right and easy to test — the cover either sees
the absent person's portfolio or they do not. **Access restoration** is the
step nothing was watching: if the delegated scope does not actually contract
when the leave ends, a cover keeps the absent person's schools, supervisees
and approval authority indefinitely. That is unauthorized access, which the
mandate lists as a P0 and a stop-the-line condition.

D2 — approving leave granted the portfolio, supervisee scope and approval
authority to a cover who had **declined** — was found and fixed in this audit.
It was a defect in the transfer half. Nothing looked at the other end.

So this asserts the pair: the same query, before, during and after the
coverage window, with the widening required in the middle and gone at both
ends. A test that only checks the grant would pass just as happily against a
system that never revokes anything.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    LeaveTypePolicy,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    TemporaryCoverageAssignment,
    User,
)
from apps.geography.models import District, Region
from apps.hr.leave_services import LeaveApprovalService
from apps.schools.models import School


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


class LeaveCoverageJourneyTest(TestCase):
    """Request → approve → transfer access → return → restore."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="LC Region")
        cls.district = District.objects.create(name="LC District", region=cls.region)
        cls.school = School.objects.create(
            school_id="LC-SCH",
            name="LC School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.pl, cls.pl_sp = _staff("Program Lead", "lc-pl@lc.test")
        cls.absent, cls.absent_sp = _staff("CCEO", "lc-absent@lc.test")
        cls.cover, cls.cover_sp = _staff("CCEO", "lc-cover@lc.test")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.absent_sp, supervisor=cls.pl_sp
        )
        # The absent person's portfolio — the thing that must move and come back.
        StaffSchoolAssignment.objects.create(
            staff=cls.absent_sp, school_id=cls.school.id
        )
        LeaveTypePolicy.objects.update_or_create(
            leave_type="personal_time_off",
            defaults={
                "label": "Personal Time Off",
                "annual_entitlement": 21,
                "approver_role": "Program Lead",
            },
        )

    def _cover_school_ids(self):
        """The covering person's own portfolio, resolved through the real
        scoping the platform uses everywhere else."""
        from apps.core.request_cache import begin, end
        from apps.core.scoping import resolve_user_scope

        # Outside a request the memo store is inert, but resolve_user_scope
        # memoises per user WITHIN one — so each probe opens and closes its own
        # window rather than reading a scope resolved before the clock moved.
        begin()
        try:
            return set(resolve_user_scope(self.cover).own_school_ids)
        finally:
            end()

    def _approved_leave(self, *, start, end_date):
        leave = Leave.objects.create(
            staff=self.absent_sp,
            type="personal_time_off",
            start_date=start,
            end_date=end_date,
            days=3,
            days_charged=3,
            status="pending",
            covering_staff=self.cover_sp,
            coverage_status="Accepted",
        )
        with self.captureOnCommitCallbacks(execute=True):
            LeaveApprovalService.approve_request(leave.id, self.pl)
        leave.refresh_from_db()
        return leave

    def test_covered_access_arrives_with_the_leave_and_leaves_with_it(self):
        # ── 0. Before: the cover owns none of the absent person's schools ──
        self.assertNotIn(
            self.school.id,
            self._cover_school_ids(),
            "the cover already holds the absent person's school before any "
            "leave exists, so nothing below would prove a transfer",
        )

        # ── 1-2. Leave request and approval ───────────────────────────────
        today = timezone.localdate()
        leave = self._approved_leave(
            start=today - datetime.timedelta(days=1),
            end_date=today + datetime.timedelta(days=1),
        )
        self.assertEqual(leave.status, "approved")

        coverage = TemporaryCoverageAssignment.objects.filter(
            leave_request=leave
        ).first()
        self.assertIsNotNone(
            coverage, "approving the leave created no coverage assignment"
        )
        self.assertEqual(coverage.status, "active")
        self.assertEqual(coverage.original_staff_id, self.absent_sp.id)
        self.assertEqual(coverage.covering_staff_id, self.cover_sp.id)

        # ── 4. Access transfer — during the window ────────────────────────
        self.assertIn(
            self.school.id,
            self._cover_school_ids(),
            "the cover cannot reach the absent person's portfolio during the "
            "coverage window, so nobody is holding the work",
        )

        # ── 7-8. Return, and access restoration ───────────────────────────
        # The step nothing was watching. Ending the coverage must contract the
        # delegated scope; if it does not, the cover keeps the absent person's
        # schools and supervisees indefinitely.
        LeaveApprovalService.revoke_coverage(coverage.id, self.pl)
        coverage.refresh_from_db()
        self.assertEqual(coverage.status, "revoked")

        self.assertNotIn(
            self.school.id,
            self._cover_school_ids(),
            "the cover STILL holds the absent person's school after the "
            "coverage was revoked — delegated authority that never comes back "
            "is unauthorized access",
        )

        self.client.force_login(self.pl)
        response = self.client.get("/leave/approvals")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.absent.name)

    def test_access_expires_with_the_window_even_if_nobody_revokes_it(self):
        """The revocation path is not the only way coverage ends.

        Most coverage is never revoked by hand — it simply runs out. If the
        scope only contracts when someone presses a button, every leave that
        ends normally leaves its access behind.
        """
        today = timezone.localdate()
        leave = self._approved_leave(
            start=today - datetime.timedelta(days=3),
            end_date=today + datetime.timedelta(days=1),
        )
        coverage = TemporaryCoverageAssignment.objects.get(leave_request=leave)
        self.assertIn(self.school.id, self._cover_school_ids())

        # The window closes on its own — nothing is revoked, the row stays
        # "active", only the clock moves past end_datetime.
        coverage.end_datetime = timezone.now() - datetime.timedelta(minutes=1)
        coverage.save(update_fields=["end_datetime"])
        self.assertEqual(coverage.status, "active")

        self.assertNotIn(
            self.school.id,
            self._cover_school_ids(),
            "coverage that simply ran out still grants access — the scope "
            "only contracts when somebody revokes by hand, so every leave "
            "that ends normally leaves its access behind",
        )

    def test_a_declined_cover_never_receives_the_portfolio(self):
        """D2, asserted from the scope rather than from the refusal.

        The fix refuses the approval. This checks the consequence that made it
        matter: a cover who said no must never appear holding the work.
        """
        from apps.core.exceptions import BadRequest

        leave = Leave.objects.create(
            staff=self.absent_sp,
            type="personal_time_off",
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + datetime.timedelta(days=2),
            days=3,
            days_charged=3,
            status="pending",
            covering_staff=self.cover_sp,
            coverage_status="Declined",
        )
        with self.assertRaises(BadRequest):
            LeaveApprovalService.approve_request(leave.id, self.pl)

        self.assertFalse(
            TemporaryCoverageAssignment.objects.filter(
                leave_request=leave, status="active"
            ).exists(),
            "a declined cover was given an active coverage assignment",
        )
        self.assertNotIn(
            self.school.id,
            self._cover_school_ids(),
            "a cover who DECLINED is holding the absent person's portfolio",
        )
