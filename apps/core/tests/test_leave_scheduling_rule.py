"""Nothing is planned onto a person's leave — except by whoever is covering.

The block itself already existed in the REG-02 gate. What these tests pin is
the whole rule the way it is actually used: the person on leave cannot be given
work, the person covering for them can take that work, and the work then
belongs to the coverer — so it appears on the coverer's calendar and never on
the calendar of the person who is away.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.accounts.models import Leave, StaffProfile, User
from apps.core.calendar_policy import SchedulingPolicyService
from apps.core.rbac import EdifyRole


def _user(email: str, name: str) -> User:
    return User.objects.create_user(
        email=email,
        password="password123",
        name=name,
        roles=[EdifyRole.CCEO.value],
        active_role=EdifyRole.CCEO.value,
        is_active=True,
    )


class LeaveSchedulingRuleTest(TestCase):
    def setUp(self):
        self.away = _user("away@leave.test", "Ada Away")
        self.away_staff = StaffProfile.objects.create(user=self.away, title="CCEO")
        self.cover = _user("cover@leave.test", "Cory Cover")
        self.cover_staff = StaffProfile.objects.create(user=self.cover, title="CCEO")

        # A Wednesday, so the Sunday rule never explains a result on its own.
        self.during = dt.date(2026, 7, 15)
        Leave.objects.create(
            staff=self.away_staff,
            covering_staff=self.cover_staff,
            type="annual",
            status="approved",
            start_date="2026-07-13",
            end_date="2026-07-17",
            days=5,
        )

    def test_the_person_on_leave_cannot_be_given_work(self):
        result = SchedulingPolicyService.check(self.away, self.during)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(
            any("approved leave" in b for b in result["blockers"]),
            result["blockers"],
        )

    def test_the_block_names_who_is_covering(self):
        """A dead-end refusal makes the user hunt for who can take it."""
        result = SchedulingPolicyService.check(self.away, self.during)
        self.assertTrue(
            any("Cory Cover" in b for b in result["blockers"]),
            f"the coverer should be named: {result['blockers']}",
        )

    def test_the_person_covering_may_be_scheduled_on_those_days(self):
        result = SchedulingPolicyService.check(self.cover, self.during)
        self.assertNotEqual(
            result["status"],
            "blocked",
            f"the coverer is working those days: {result['blockers']}",
        )

    def test_the_block_lifts_the_day_after_the_leave_ends(self):
        after = dt.date(2026, 7, 20)  # Monday following
        result = SchedulingPolicyService.check(self.away, after)
        self.assertFalse(
            any("approved leave" in b for b in result["blockers"]),
            result["blockers"],
        )

    def test_pending_leave_warns_rather_than_blocks(self):
        """An unapproved request is not yet an absence."""
        other = _user("pending@leave.test", "Pia Pending")
        staff = StaffProfile.objects.create(user=other, title="CCEO")
        Leave.objects.create(
            staff=staff,
            type="annual",
            status="pending",
            start_date="2026-07-13",
            end_date="2026-07-17",
            days=5,
        )
        result = SchedulingPolicyService.check(other, self.during)
        self.assertNotEqual(result["status"], "blocked")
        self.assertTrue(any("pending leave" in w for w in result["warnings"]))


class CoveredWorkOwnershipTest(TestCase):
    """Work the coverer takes on belongs to the coverer.

    That is what puts it on their calendar and keeps it off the calendar of the
    person who is away — both surfaces read ownership, so nothing else needs a
    special case for leave.
    """

    def setUp(self):
        self.away = _user("away2@leave.test", "Ada Away")
        self.away_staff = StaffProfile.objects.create(user=self.away, title="CCEO")
        self.cover = _user("cover2@leave.test", "Cory Cover")
        self.cover_staff = StaffProfile.objects.create(user=self.cover, title="CCEO")
        Leave.objects.create(
            staff=self.away_staff,
            covering_staff=self.cover_staff,
            type="annual",
            status="approved",
            start_date="2026-07-13",
            end_date="2026-07-17",
            days=5,
        )

    def test_an_activity_owned_by_the_coverer_is_not_blocked(self):
        result = SchedulingPolicyService.check(self.cover, dt.date(2026, 7, 15))
        self.assertNotEqual(result["status"], "blocked")

    def test_reassigning_the_same_date_to_the_absent_staff_is_refused(self):
        """The exception is the coverer doing the work, not the date opening up."""
        allowed = SchedulingPolicyService.check(self.cover, dt.date(2026, 7, 15))
        refused = SchedulingPolicyService.check(self.away, dt.date(2026, 7, 15))
        self.assertNotEqual(allowed["status"], "blocked")
        self.assertEqual(refused["status"], "blocked")
