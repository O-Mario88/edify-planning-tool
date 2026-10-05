"""Planned work on a public holiday or on its owner's leave day.

Owner, 2026-10-05: "mark all activities planned on public holidays and days
staff set for leave red and alert the staff to reschedule the activities for
that day."

What is pinned here: which activities are marked and in what words, the one
notice per person per day off and when it is said again or closed, and that
approving leave, rescheduling and recording a holiday each keep the notices
true.
"""

from __future__ import annotations

from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import (
    Leave,
    PublicHoliday,
    StaffProfile,
    StaffSchoolAssignment,
    User,
)
from apps.activities.day_off import (
    DAY_OFF_EVENT,
    HOLIDAY,
    LEAVE,
    day_off_marks,
    send_day_off_alerts,
)
from apps.activities.models import Activity
from apps.activities.services import reschedule
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.tests.test_reg02_calendar_policy import _CalendarFixture
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.notifications.services import NotificationLinkResolver
from apps.schools.models import School

INDEPENDENCE_DAY = date(2026, 10, 9)  # a Friday
ORDINARY_DAY = date(2026, 10, 8)
TODAY = "2026-10-05"


def _person(email: str, name: str) -> StaffProfile:
    user = User.objects.create_user(
        email=email, name=name, roles=["CCEO"], active_role="CCEO"
    )
    return StaffProfile.objects.create(user=user, title="CCEO")


class DayOffFixture(TestCase):
    def setUp(self):
        self.officer = _person("day-off-officer@example.com", "Dora Officer")
        self.colleague = _person("day-off-colleague@example.com", "Colin League")
        region = Region.objects.create(name="Day Off Region")
        district = District.objects.create(name="Day Off District", region=region)
        self.school = School.objects.create(
            school_id="DAYOFF-1",
            name="Day Off Primary",
            region=region,
            district=district,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.officer, school_id=self.school.id
        )

    def _visit(self, day: date, *, staff=None, status="scheduled", **extra) -> Activity:
        staff = staff or self.officer
        return Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=get_operational_fy(day),
            quarter=get_quarter_for_date(day),
            planned_date=day,
            responsible_staff_id=staff.id,
            status=status,
            **extra,
        )

    def _leave(self, staff, start: str, end: str, *, status="approved", cover=None):
        return Leave.objects.create(
            staff=staff,
            type="personal_time_off",
            start_date=start,
            end_date=end,
            days=1,
            status=status,
            covering_staff=cover,
        )

    def _notices(self, staff=None):
        return Notification.objects.filter(
            source_event_type=DAY_OFF_EVENT,
            recipient_id=(staff or self.officer).user_id,
        ).order_by("context_id", "created_at")


class DayOffMarksTest(DayOffFixture):
    def test_work_on_a_public_holiday_is_marked(self):
        on_holiday = self._visit(INDEPENDENCE_DAY)
        ordinary = self._visit(ORDINARY_DAY)

        marks = day_off_marks([on_holiday, ordinary])

        self.assertEqual(list(marks), [on_holiday.id])
        mark = marks[on_holiday.id]
        self.assertEqual(mark.label, "Public holiday")
        self.assertEqual(mark.summary, "Fri 9 Oct · Public holiday")
        self.assertEqual(mark.days[0].kind, HOLIDAY)
        self.assertEqual(
            mark.advice,
            "Fri 9 Oct is a public holiday (Independence Day). "
            "Reschedule this activity.",
        )

    def test_work_on_the_owners_approved_leave_day_is_marked(self):
        self._leave(self.officer, "2026-10-06", "2026-10-07", cover=self.colleague)
        mine = self._visit(date(2026, 10, 6))
        theirs = self._visit(date(2026, 10, 6), staff=self.colleague)

        marks = day_off_marks([mine, theirs])

        # A colleague's work on the same day is not on anybody's leave.
        self.assertEqual(list(marks), [mine.id])
        self.assertEqual(marks[mine.id].label, "On leave")
        self.assertEqual(marks[mine.id].days[0].kind, LEAVE)
        self.assertEqual(
            marks[mine.id].why,
            "Dora Officer is on leave on Tue 6 Oct. Colin League is covering.",
        )

    def test_a_leave_request_still_waiting_marks_nothing(self):
        self._leave(self.officer, "2026-10-06", "2026-10-07", status="pending")
        self._leave(self.officer, "2026-10-13", "2026-10-13", status="rejected")

        marks = day_off_marks(
            [self._visit(date(2026, 10, 6)), self._visit(date(2026, 10, 13))]
        )

        self.assertEqual(marks, {})

    def test_work_filed_under_the_user_id_is_found_too(self):
        self._leave(self.officer, "2026-10-06", "2026-10-06")
        legacy = self._visit(date(2026, 10, 6))
        Activity.objects.filter(id=legacy.id).update(
            responsible_staff_id=self.officer.user_id
        )
        legacy.refresh_from_db()

        self.assertIn(legacy.id, day_off_marks([legacy]))

    def test_work_already_started_or_delivered_is_left_alone(self):
        rows = [
            self._visit(INDEPENDENCE_DAY, status=status)
            for status in ("completion_started", "completed", "cancelled")
        ]

        self.assertEqual(day_off_marks(rows), {})

    def test_a_holiday_inside_a_multi_day_activity_marks_it(self):
        training = self._visit(date(2026, 10, 7), end_date=date(2026, 10, 10))

        mark = day_off_marks([training])[training.id]

        self.assertEqual([day.day for day in mark.days], [INDEPENDENCE_DAY])

    def test_a_holiday_and_a_leave_day_are_both_named(self):
        self._leave(self.officer, "2026-10-09", "2026-10-09")
        visit = self._visit(INDEPENDENCE_DAY)

        mark = day_off_marks([visit])[visit.id]

        self.assertEqual(mark.label, "Holiday and leave")
        self.assertEqual({day.kind for day in mark.days}, {HOLIDAY, LEAVE})
        # One line for a table cell, however many days there are.
        self.assertEqual(mark.summary, "Fri 9 Oct · Public holiday +1 more")

    def test_a_scheduled_instant_is_read_on_its_local_day(self):
        """A day chosen in a drawer is saved at local midnight, which is the
        evening before in UTC."""
        visit = self._visit(INDEPENDENCE_DAY)
        Activity.objects.filter(id=visit.id).update(
            planned_date=None,
            scheduled_date=timezone.make_aware(
                datetime(2026, 10, 9), timezone.get_current_timezone()
            ),
        )
        visit.refresh_from_db()

        self.assertIn(visit.id, day_off_marks([visit]))

    def test_marking_a_page_of_rows_is_a_fixed_number_of_queries(self):
        self._leave(self.officer, "2026-10-06", "2026-10-07")
        few = [self._visit(INDEPENDENCE_DAY) for _ in range(2)]
        many = few + [self._visit(date(2026, 10, 6)) for _ in range(12)]

        with self.assertNumQueries(4):
            day_off_marks(few)
        with self.assertNumQueries(4):
            day_off_marks(many)


@freeze_time(TODAY)
class DayOffAlertsTest(DayOffFixture):
    def test_one_notice_per_person_per_day_off(self):
        self._visit(INDEPENDENCE_DAY)
        self._visit(INDEPENDENCE_DAY)
        self._visit(ORDINARY_DAY)
        self._leave(self.officer, "2026-10-06", "2026-10-06")
        self._visit(date(2026, 10, 6))
        self._visit(INDEPENDENCE_DAY, staff=self.colleague)

        self.assertEqual(send_day_off_alerts(), 3)

        leave_day, holiday = self._notices()
        self.assertEqual(holiday.title, "Reschedule 2 activities planned for Fri 9 Oct")
        self.assertEqual(
            holiday.body,
            "Friday 9 October is a public holiday (Independence Day). Move: "
            "School Visit at Day Off Primary; School Visit at Day Off Primary.",
        )
        self.assertEqual(holiday.target_route, "/my-plan?fy=2027&month=10")
        self.assertEqual(holiday.action_label, "Reschedule in My Plan")
        self.assertEqual(leave_day.title, "Reschedule 1 activity planned for Tue 6 Oct")
        self.assertIn("is a day you are on leave", leave_day.body)
        self.assertEqual(self._notices(self.colleague).count(), 1)

    def test_a_second_run_says_nothing_twice(self):
        self._visit(INDEPENDENCE_DAY)
        send_day_off_alerts()

        self.assertEqual(send_day_off_alerts(), 0)
        self.assertEqual(self._notices().count(), 1)

    def test_a_notice_put_away_is_not_sent_again(self):
        self._visit(INDEPENDENCE_DAY)
        send_day_off_alerts()
        self._notices().update(status="archived")

        self.assertEqual(send_day_off_alerts(), 0)
        self.assertEqual(self._notices().count(), 1)

    def test_a_day_whose_list_grows_is_said_again(self):
        self._visit(INDEPENDENCE_DAY)
        send_day_off_alerts()
        self._notices().update(status="read")
        self._visit(INDEPENDENCE_DAY)

        self.assertEqual(send_day_off_alerts(), 1)

        (notice,) = self._notices()
        self.assertEqual(notice.title, "Reschedule 2 activities planned for Fri 9 Oct")
        self.assertEqual(notice.status, "unread")

    def test_the_notice_closes_when_the_day_is_clear(self):
        visit = self._visit(INDEPENDENCE_DAY)
        send_day_off_alerts()
        Activity.objects.filter(id=visit.id).update(planned_date=ORDINARY_DAY)

        self.assertEqual(send_day_off_alerts(), 0)

        (notice,) = self._notices()
        self.assertIsNotNone(notice.resolved_at)
        self.assertEqual(notice.status, "archived")

    def test_days_already_past_are_not_announced(self):
        self._visit(date(2026, 5, 27))  # Eid al-Adha, months ago

        self.assertEqual(send_day_off_alerts(), 0)

    def test_one_persons_sweep_leaves_the_others_alone(self):
        self._visit(INDEPENDENCE_DAY)
        self._visit(INDEPENDENCE_DAY, staff=self.colleague)

        self.assertEqual(send_day_off_alerts(user_id=self.officer.user_id), 1)

        self.assertEqual(self._notices().count(), 1)
        self.assertEqual(self._notices(self.colleague).count(), 0)

    def test_the_notice_opens_my_plan_on_the_month(self):
        self.assertEqual(
            NotificationLinkResolver.resolve(
                DAY_OFF_EVENT, "day_off", "dayoff-2026-12-25", "CCEO"
            ),
            ("/my-plan?fy=2027&month=12", "Reschedule in My Plan"),
        )


@freeze_time(TODAY)
class RecordedHolidayAlertTest(DayOffFixture):
    def test_a_day_recorded_as_a_holiday_is_announced(self):
        self._visit(ORDINARY_DAY)
        self.assertEqual(send_day_off_alerts(), 0)
        PublicHoliday.objects.create(name="Census Day", date=ORDINARY_DAY)

        self.assertEqual(send_day_off_alerts(), 1)

        self.assertIn("a public holiday (Census Day)", self._notices().get().body)


@freeze_time("2026-08-08")
class RescheduleSettlesTheNoticeTest(_CalendarFixture, TestCase):
    """Moving the activity off the day closes its notice there and then."""

    HOLIDAY = "2026-08-17"  # a Monday, recorded as a holiday below
    CLEAR_DAY = "2026-08-18"

    def test_rescheduling_off_the_holiday_closes_the_notice(self):
        activity = self._create(self.HOLIDAY)
        PublicHoliday.objects.create(name="Census Day", date=self.HOLIDAY)
        self.assertEqual(send_day_off_alerts(), 1)
        notices = Notification.objects.filter(
            source_event_type=DAY_OFF_EVENT, recipient_id=self.cceo.id
        )
        self.assertIsNone(notices.get().resolved_at)

        with self.captureOnCommitCallbacks(execute=True):
            reschedule(
                activity["id"],
                {"scheduledDate": self.CLEAR_DAY, "reason": "Census Day"},
                self.cceo,
            )

        self.assertIsNotNone(notices.get().resolved_at)


@freeze_time(TODAY)
class DayOffPagesTest(DayOffFixture):
    """The mark on the pages that list planned work."""

    def setUp(self):
        super().setUp()
        self.on_holiday = self._visit(INDEPENDENCE_DAY, delivery_type="staff")
        self.ordinary = self._visit(ORDINARY_DAY, delivery_type="staff")
        self.client.force_login(self.officer.user)

    def test_my_plan_lists_the_work_to_move_first_and_marks_its_row(self):
        response = self.client.get("/my-plan?fy=2027&month=10")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.context["day_off_work"]],
            [self.on_holiday.id],
        )
        body = response.content.decode()
        self.assertIn('data-card="day-off-work"', body)
        # The cell is short so the card never wraps; the reason is its title.
        self.assertIn(
            'title="Fri 9 Oct is a public holiday (Independence Day).">'
            "Fri 9 Oct · Public holiday</span>",
            body,
        )
        self.assertIn(f'hx-get="/my-plan/{self.on_holiday.id}/reschedule-drawer"', body)
        # The card's row and the row in the School Visits table.
        self.assertEqual(body.count('class="mp-dayoff-row"'), 2)
        self.assertEqual(body.count("Public holiday: reschedule"), 1)

    def test_my_plan_has_no_card_when_nothing_sits_on_a_day_off(self):
        Activity.objects.filter(id=self.on_holiday.id).update(
            planned_date=date(2026, 10, 12)
        )

        response = self.client.get("/my-plan?fy=2027&month=10")

        self.assertEqual(response.context["day_off_work"], [])
        self.assertNotContains(response, 'data-card="day-off-work"')
        self.assertNotContains(response, "mp-dayoff-row")

    def test_the_work_plan_marks_the_row(self):
        response = self.client.get("/work-plan?view=month&period=10&fy=2027")

        self.assertEqual(response.status_code, 200)
        marked = [row["id"] for row in response.context["rows"] if row["day_off"]]
        self.assertEqual(marked, [self.on_holiday.id])
        self.assertContains(response, "Public holiday: reschedule", count=1)
        self.assertContains(response, "mp-dayoff-row", count=1)

    def test_the_leave_page_lists_the_readers_work_on_a_day_off(self):
        response = self.client.get("/personal-time-off")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [conflict["id"] for conflict in response.context["my_conflicts"]],
            [self.on_holiday.id],
        )
        self.assertContains(
            response, "Fri 9 Oct is a public holiday (Independence Day)."
        )
