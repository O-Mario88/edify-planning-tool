"""An appointment is one whole calendar month, on the platform's own calendar.

Month boundaries for every month length, the leap day, what the database
itself refuses, and the hour around midnight where UTC and Africa/Nairobi
disagree about the date.
"""

from __future__ import annotations

import datetime
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase

from apps.acting import services
from apps.acting.models import ACTIVE, EXPIRED, UPCOMING, ActingAssignment, today
from apps.core.exceptions import BadRequest

from .fixtures import (
    NOVEMBER_1,
    OCTOBER_1,
    OCTOBER_31,
    SEPTEMBER_30,
    ActingFixture,
    on_day,
)


class MonthBoundsTests(SimpleTestCase):
    def test_every_month_ends_on_its_own_last_day(self):
        expected = {
            (2026, 1): 31,
            (2026, 2): 28,
            (2028, 2): 29,  # leap year
            (2100, 2): 28,  # a century year that is not one
            (2026, 4): 30,
            (2026, 6): 30,
            (2026, 9): 30,
            (2026, 11): 30,
            (2026, 12): 31,
        }
        for (year, month), last in expected.items():
            start, end = services.month_bounds(year, month)
            self.assertEqual(start, datetime.date(year, month, 1))
            self.assertEqual(end, datetime.date(year, month, last))

    def test_a_month_is_named_and_its_dates_are_worked_out(self):
        self.assertEqual(
            services.parse_month("2026-10"),
            (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)),
        )
        self.assertEqual(
            services.parse_month("2028-02"),
            (datetime.date(2028, 2, 1), datetime.date(2028, 2, 29)),
        )
        for nonsense in ("", "October", "2026-13", "2026", None):
            with self.assertRaises(BadRequest):
                services.parse_month(nonsense)

    def test_the_months_on_offer_run_a_year_from_this_month(self):
        options = services.month_options(datetime.date(2026, 11, 20))
        self.assertEqual(len(options), services.MONTHS_AHEAD)
        self.assertEqual(options[0]["value"], "2026-11")
        self.assertEqual(options[1]["label"], "December 2026")
        self.assertEqual(options[2]["value"], "2027-01")
        self.assertEqual(options[3]["effective"], "February 1 – February 28, 2027")
        self.assertEqual(options[-1]["value"], "2027-10")


class ClockTests(SimpleTestCase):
    """Africa/Nairobi is UTC+3: its day turns at 21:00 UTC the day before."""

    def _at(self, utc: datetime.datetime) -> datetime.date:
        with mock.patch("django.utils.timezone.now", return_value=utc):
            return today()

    def test_the_month_turns_at_midnight_in_nairobi_not_in_utc(self):
        utc = datetime.timezone.utc
        # 30 September 23:59:59 in Nairobi.
        self.assertEqual(
            self._at(datetime.datetime(2026, 9, 30, 20, 59, 59, tzinfo=utc)),
            SEPTEMBER_30,
        )
        # 1 October 00:00:00 in Nairobi, still 30 September in UTC.
        self.assertEqual(
            self._at(datetime.datetime(2026, 9, 30, 21, 0, 0, tzinfo=utc)), OCTOBER_1
        )
        # 31 October 23:59:59 in Nairobi.
        self.assertEqual(
            self._at(datetime.datetime(2026, 10, 31, 20, 59, 59, tzinfo=utc)),
            OCTOBER_31,
        )
        # 1 November 00:00:00 in Nairobi, still 31 October in UTC.
        self.assertEqual(
            self._at(datetime.datetime(2026, 10, 31, 21, 0, 0, tzinfo=utc)), NOVEMBER_1
        )


class StateTests(ActingFixture):
    def test_state_follows_the_dates_with_nobody_touching_it(self):
        appointment = self.appoint_sarah()
        self.assertEqual(appointment.state(SEPTEMBER_30), UPCOMING)
        self.assertEqual(appointment.state(OCTOBER_1), ACTIVE)
        self.assertEqual(appointment.state(OCTOBER_31), ACTIVE)
        self.assertEqual(appointment.state(NOVEMBER_1), EXPIRED)
        # Nothing was written to make that so.
        stored = ActingAssignment.objects.get(id=appointment.id)
        self.assertIsNone(stored.activated_at)
        self.assertIsNone(stored.expired_at)

    def test_the_lists_sort_an_appointment_by_its_dates(self):
        appointment = self.appoint_sarah()
        rows = ActingAssignment.objects.filter(id=appointment.id)
        self.assertTrue(rows.upcoming(SEPTEMBER_30).exists())
        self.assertFalse(rows.active(SEPTEMBER_30).exists())
        self.assertTrue(rows.active(OCTOBER_1).exists())
        self.assertTrue(rows.active(OCTOBER_31).exists())
        self.assertFalse(rows.active(NOVEMBER_1).exists())
        self.assertTrue(rows.history(NOVEMBER_1).exists())

    def test_a_past_month_and_a_month_too_far_ahead_are_refused(self):
        with on_day(OCTOBER_1):
            for month in ("2026-09", "2027-10"):
                with self.assertRaises(BadRequest):
                    services.appoint(
                        self.john, appointee_staff_id=self.sarah_sp.id, month=month
                    )
            # The month already under way can still be covered.
            appointment = services.appoint(
                self.john, appointee_staff_id=self.sarah_sp.id, month="2026-10"
            )
            self.assertEqual(appointment.state(), ACTIVE)


class DatabaseRulesTests(ActingFixture):
    """What the table refuses whoever writes to it."""

    def _row(self, **changes):
        values = {
            "role_key": "acting_pl",
            "acting_role": "Program Lead",
            "appointee": self.sarah,
            "appointee_role": "CCEO",
            "appointed_by": self.john,
            "appointed_by_role": "Program Lead",
            "scope_type": "pl_team",
            "seat": self.john_sp,
            "country": "Uganda",
            "start_date": datetime.date(2027, 3, 1),
            "end_date": datetime.date(2027, 3, 31),
        }
        values.update(changes)
        return ActingAssignment(**values)

    def _refused(self, **changes):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._row(**changes).save()

    def test_a_whole_month_is_accepted(self):
        for start, end in (
            (datetime.date(2027, 2, 1), datetime.date(2027, 2, 28)),
            (datetime.date(2028, 2, 1), datetime.date(2028, 2, 29)),
            (datetime.date(2027, 4, 1), datetime.date(2027, 4, 30)),
            (datetime.date(2027, 12, 1), datetime.date(2027, 12, 31)),
        ):
            self._row(start_date=start, end_date=end).save()

    def test_anything_but_a_whole_month_is_refused(self):
        self._refused(end_date=datetime.date(2027, 2, 28))  # ends before it starts
        self._refused(start_date=datetime.date(2027, 3, 2))  # not the first
        self._refused(end_date=datetime.date(2027, 3, 30))  # a day short
        self._refused(end_date=datetime.date(2027, 4, 30))  # two months
        # A leap February is 29 days: stopping on the 28th is a day short.
        self._refused(
            start_date=datetime.date(2028, 2, 1), end_date=datetime.date(2028, 2, 28)
        )
        # And 1 March is a day too many for an ordinary one.
        self._refused(
            start_date=datetime.date(2027, 2, 1), end_date=datetime.date(2027, 3, 1)
        )

    def test_nobody_is_their_own_appointee(self):
        self._refused(appointee=self.john)

    def test_one_standing_acting_leader_per_seat_and_month(self):
        self._row().save()
        self._refused(appointee=self.david)

    def test_one_standing_appointment_per_person_and_month(self):
        self._row().save()
        self._refused(
            role_key="acting_cd",
            acting_role="CountryDirector",
            appointed_by=self.mary,
            seat=self.mary_sp,
            scope_type="country",
        )

    def test_a_cancelled_appointment_frees_the_seat_and_the_person(self):
        first = self._row()
        first.save()
        ActingAssignment.objects.filter(id=first.id).update(
            cancelled_at=datetime.datetime(2027, 2, 1, tzinfo=datetime.timezone.utc)
        )
        self._row(appointee=self.david).save()
        self._row(seat=self.peter_sp, appointed_by=self.peter).save()

    def test_an_appointment_needs_every_part(self):
        for missing in ("appointee", "appointed_by", "seat", "start_date", "end_date"):
            self._refused(**{missing: None})

    def test_people_named_by_an_appointment_cannot_be_deleted_from_under_it(self):
        from django.db.models import ProtectedError

        self._row().save()
        with self.assertRaises(ProtectedError):
            self.john_sp.delete()
