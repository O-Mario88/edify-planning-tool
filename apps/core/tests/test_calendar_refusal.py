"""A door that only asks the calendar in order to refuse does not read it
while the calendar cannot refuse.

Since the owner lifted the calendar restrictions (2026-09-30) a Sunday, a
holiday, a blackout date and a staff member's leave are warnings
(`CALENDAR_BLOCKS_REFUSE` off). Create, reschedule, a partner's date and a
visit joining a day still read all of it, seven statements a time and two to
four times a save, to learn that nothing was refused. `refusal` answers them
without reading; with the switch on it is `check`, as before.
"""

from __future__ import annotations

from datetime import date
from unittest import mock

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.core import calendar_policy
from apps.core.calendar_policy import SchedulingPolicyService
from apps.core.rbac import EdifyRole

SUNDAY = date(2026, 8, 2)
MONDAY = date(2026, 8, 3)


class RefusalTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="refusal@test.com",
            name="Refusal Officer",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            user=cls.user, title="CCEO", country="Uganda"
        )

    def test_while_the_calendar_only_warns_nothing_is_read(self):
        self.assertFalse(calendar_policy.CALENDAR_BLOCKS_REFUSE)
        with self.assertNumQueries(0):
            self.assertEqual(SchedulingPolicyService.refusal(self.staff.id, SUNDAY), [])
            self.assertEqual(SchedulingPolicyService.refusal(None, SUNDAY), [])

    def test_when_the_calendar_refuses_it_says_what_check_says(self):
        with mock.patch.object(calendar_policy, "CALENDAR_BLOCKS_REFUSE", True):
            said = SchedulingPolicyService.check(self.user, SUNDAY)
            self.assertEqual(said["status"], "blocked")
            self.assertEqual(
                SchedulingPolicyService.refusal(self.staff.id, SUNDAY),
                said["blockers"],
            )
            self.assertEqual(
                SchedulingPolicyService.refusal(self.user.id, SUNDAY),
                said["blockers"],
            )
            self.assertEqual(SchedulingPolicyService.refusal(self.staff.id, MONDAY), [])

    def test_a_sunday_is_still_refused_at_the_door_when_the_switch_is_on(self):
        from apps.core.exceptions import BadRequest
        from apps.daily_visit_batches import services as batches

        activity = mock.Mock(
            responsible_staff_id=self.staff.id,
            monitored_by_staff_id=None,
        )
        activity.school.district_id = "district-1"
        with mock.patch.object(calendar_policy, "CALENDAR_BLOCKS_REFUSE", True):
            with self.assertRaises(BadRequest) as refused:
                batches._day_to_join(
                    activity=activity,
                    new_date=SUNDAY,
                    reason="",
                    principal=self.user,
                    lock=False,
                )
        self.assertIn("Scheduling blocked", str(refused.exception.detail))
        self.assertIn("Sunday", str(refused.exception.detail))
