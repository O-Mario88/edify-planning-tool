"""Work finished before its planned day (owner, 2026-10-14).

"As long as the activity is completed, it should be counted irrespective of
when they were planned", then: "the activities finished early should be taken
off the calendar and on My Plan tables, planning oversight marked complete so
we can be able to track" — off the calendar entirely, the plan date and the
money left as they were. Then, the same day: "All completed activities should
be off the calendar completely" — early or not.

Seen in production: a core visit planned for Tuesday 20 October, verified on
the 14th, still drawn on the officer's calendar on the 20th.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.completion_columns import (
    FINISHED_EARLY,
    completion_columns,
    completion_fields,
    early_day,
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.geography.models import District, Region
from apps.schools.models import School


def _at(day, hour=10):
    return timezone.make_aware(datetime.combine(day, time(hour, 0)))


class FinishedEarlyWorld(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.ahead = cls.today + timedelta(days=6)
        cls.fy = get_operational_fy(cls.today)
        cls.user = User.objects.create_user(
            email="early-cceo@example.com",
            name="Early Officer",
            roles=["CCEO"],
            active_role="CCEO",
        )
        cls.staff = StaffProfile.objects.create(user=cls.user, title="CCEO")
        region = Region.objects.create(name="Early Region")
        district = District.objects.create(name="Early District", region=region)
        cls.school = School.objects.create(
            school_id="EARLY-001",
            name="Divine Hope Christian School",
            region=region,
            district=district,
            school_type="client",
            account_owner_id=cls.staff.id,
        )
        StaffSchoolAssignment.objects.create(staff=cls.staff, school_id=cls.school.id)
        # Planned six days ahead, done today, verified.
        cls.early = cls.work(
            cls.ahead,
            status="ia_verified",
            salesforce_activity_id="SVE-267594",
            execution_started_at=_at(cls.today),
        )
        # Planned and done today.
        cls.on_day = cls.work(
            cls.today,
            status="submitted_to_pl",
            salesforce_activity_id="SV-51548",
            execution_started_at=_at(cls.today),
        )
        # Still to do, six days ahead.
        cls.upcoming = cls.work(cls.ahead)

    @classmethod
    def work(cls, day, *, status="scheduled", **extra):
        return Activity.objects.create(
            activity_type="school_visit",
            school=cls.school,
            fy=get_operational_fy(day),
            quarter=get_quarter_for_date(day),
            planned_date=day,
            scheduled_date=_at(day, 9),
            responsible_staff_id=cls.staff.id,
            delivery_type="staff",
            status=status,
            **extra,
        )


class WhatFinishedEarlyMeans(FinishedEarlyWorld):
    def test_the_day_done_is_the_recorded_delivery_date_or_the_day_complete_was_pressed(
        self,
    ):
        before = self.ahead - timedelta(days=2)
        self.assertEqual(early_day(self.ahead, None, before, None), before)
        self.assertEqual(early_day(self.ahead, None, None, _at(before)), before)
        # The recorded delivery date wins over the press of Complete.
        self.assertEqual(early_day(self.ahead, None, self.ahead, _at(before)), None)
        # No planned date: the scheduled day is the plan.
        self.assertEqual(early_day(None, _at(self.ahead), None, _at(before)), before)
        # On its day, or after it, is not early; nothing done is not early.
        self.assertIsNone(early_day(self.ahead, None, self.ahead, None))
        self.assertIsNone(early_day(self.ahead, None, None, None))

    def test_only_complete_work_done_before_its_day_is_finished_early(self):
        columns = completion_columns(
            (a.id, a.activity_type) for a in (self.early, self.on_day, self.upcoming)
        )
        early = completion_fields(self.early.status, columns[self.early.id])
        self.assertTrue(early["finished_early"])
        self.assertEqual(early["early_on"], self.today)
        on_day = completion_fields(self.on_day.status, columns[self.on_day.id])
        self.assertFalse(on_day["finished_early"])
        upcoming = completion_fields(self.upcoming.status, columns[self.upcoming.id])
        self.assertFalse(upcoming["finished_early"])

    def test_without_its_salesforce_id_it_says_what_is_missing_instead(self):
        Activity.objects.filter(id=self.early.id).update(salesforce_activity_id="")
        columns = completion_columns([(self.early.id, "school_visit")])
        fields = completion_fields("ia_verified", columns[self.early.id])
        self.assertFalse(fields["finished_early"])
        self.assertTrue(fields["completion_gap"])

    def test_returned_work_is_not_finished(self):
        columns = completion_columns([(self.early.id, "school_visit")])
        fields = completion_fields("returned_by_pl", columns[self.early.id])
        self.assertFalse(fields["finished_early"])


class TheCalendarLeavesCompletedWorkOff(FinishedEarlyWorld):
    def setUp(self):
        self.client.force_login(self.user)

    def _drawn(self, path="/calendar"):
        """The activities the month of the planned day draws: each one links
        to its record."""
        month = self.ahead
        response = self.client.get(f"{path}?year={month.year}&month={month.month}")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        return {
            a.id
            for a in (self.early, self.on_day, self.upcoming)
            if f"/my-plan/{a.id}" in html
        }

    def test_the_calendar_draws_only_work_still_to_do(self):
        drawn = self._drawn()
        # Finished early, and finished on its day: both off.
        self.assertNotIn(self.early.id, drawn)
        self.assertNotIn(self.on_day.id, drawn)
        self.assertIn(self.upcoming.id, drawn)

    def test_it_comes_back_if_the_lead_returns_it(self):
        Activity.objects.filter(id=self.early.id).update(status="returned_by_pl")
        self.assertIn(self.early.id, self._drawn())

    def test_the_leave_calendar_leaves_it_off_too(self):
        from apps.frontend.views.leave_views import _calendar_activities
        from django.test import RequestFactory

        request = RequestFactory().get("/leave/calendar")
        request.user = self.user
        events, by_day = _calendar_activities(request, self.ahead.replace(day=1))
        text = repr(events) + repr(by_day)
        self.assertNotIn(self.early.id, text)
        self.assertNotIn(self.on_day.id, text)
        self.assertIn(self.upcoming.id, text)


class MyPlanMarksItComplete(FinishedEarlyWorld):
    def test_the_row_reads_completed_early_in_green(self):
        from apps.my_plan.services import get_frontend_context

        context = get_frontend_context(
            self.user, {"fy": self.fy, "period": "fy"}, with_readiness=False
        )
        rows = {
            row["id"]: row
            for value in context.values()
            if isinstance(value, list)
            for row in value
            if isinstance(row, dict) and "status_label" in row
        }
        self.assertEqual(rows[self.early.id]["status_label"], FINISHED_EARLY)
        self.assertEqual(rows[self.early.id]["status_tone"], "green")
        self.assertNotEqual(rows[self.on_day.id]["status_label"], FINISHED_EARLY)
        self.assertNotEqual(rows[self.upcoming.id]["status_label"], FINISHED_EARLY)
        # Its plan date is unchanged: only how it reads moved.
        self.assertEqual(rows[self.early.id]["planned_date"], self.ahead)
