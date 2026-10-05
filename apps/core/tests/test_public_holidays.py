"""The one public-holiday calendar (apps.core.public_holidays).

Owner, 2026-10-05: "Uganda independence day is on 9th october but it is
showing 10th october. look up the right dates for public holidays for both
Uganda and international Holidays."
"""

from datetime import date

from django.test import TestCase

from apps.accounts.models import CalendarBlock, PublicHoliday, StaffProfile, User
from apps.core.calendar_policy import SchedulingPolicyService
from apps.core.public_holidays import (
    easter_sunday,
    holidays_between,
    national_holidays,
    public_holiday_name,
    public_holidays_between,
    upcoming_public_holidays,
)
from apps.hr.leave_services import PublicHolidayService, WorkingDayCalculator


def _public(year: int) -> dict[date, str]:
    return public_holidays_between(date(year, 1, 1), date(year, 12, 31))


class NationalCalendarTest(TestCase):
    def test_independence_day_is_the_ninth_of_october_every_year(self):
        for year in (2025, 2026, 2027, 2031):
            self.assertEqual(
                public_holiday_name(date(year, 10, 9)), "Independence Day", year
            )
            self.assertIsNone(public_holiday_name(date(year, 10, 10)), year)

    def test_the_fixed_days_are_the_schedule_of_the_public_holidays_act(self):
        self.assertEqual(
            {
                (day.month, day.day): name
                for day, name in _public(2029).items()
                if "Eid" not in name and name not in ("Good Friday", "Easter Monday")
            },
            {
                (1, 1): "New Year's Day",
                (1, 26): "NRM Liberation Day",
                (2, 16): "Archbishop Janani Luwum Day",
                (3, 8): "International Women's Day",
                (5, 1): "Labour Day",
                (6, 3): "Uganda Martyrs' Day",
                (6, 9): "National Heroes' Day",
                (10, 9): "Independence Day",
                (12, 25): "Christmas Day",
                (12, 26): "Boxing Day",
            },
        )

    def test_easter_moves_with_the_year(self):
        self.assertEqual(easter_sunday(2026), date(2026, 4, 5))
        self.assertEqual(easter_sunday(2027), date(2027, 3, 28))
        self.assertEqual(public_holiday_name(date(2026, 4, 3)), "Good Friday")
        self.assertEqual(public_holiday_name(date(2026, 4, 6)), "Easter Monday")
        self.assertEqual(public_holiday_name(date(2027, 3, 26)), "Good Friday")
        self.assertEqual(public_holiday_name(date(2027, 3, 29)), "Easter Monday")
        # Last year's Easter is an ordinary day this year.
        self.assertIsNone(public_holiday_name(date(2027, 4, 6)))

    def test_the_eids_of_2026_are_the_days_that_were_kept(self):
        self.assertEqual(public_holiday_name(date(2026, 3, 20)), "Eid al-Fitr")
        self.assertEqual(public_holiday_name(date(2026, 5, 27)), "Eid al-Adha")

    def test_a_coming_eid_says_it_is_the_expected_day(self):
        self.assertEqual(
            public_holiday_name(date(2027, 3, 9)), "Eid al-Fitr (expected date)"
        )
        self.assertEqual(
            public_holiday_name(date(2027, 5, 16)), "Eid al-Adha (expected date)"
        )

    def test_every_year_has_both_eids_even_past_the_published_tables(self):
        for year in (2031, 2036, 2040):
            names = " ".join(_public(year).values())
            self.assertIn("Eid al-Fitr", names, year)
            self.assertIn("Eid al-Adha", names, year)

    def test_declared_days_belong_to_their_own_year_only(self):
        self.assertEqual(public_holiday_name(date(2026, 1, 15)), "General Election Day")
        self.assertEqual(
            public_holiday_name(date(2026, 5, 12)), "Presidential Inauguration Day"
        )
        self.assertIsNone(public_holiday_name(date(2027, 1, 15)))
        self.assertIsNone(public_holiday_name(date(2027, 5, 12)))

    def test_observances_are_named_but_are_not_days_off(self):
        observances = {
            holiday.name: holiday.date
            for holiday in national_holidays(2026)
            if not holiday.is_public
        }
        self.assertEqual(observances["Easter Sunday"], date(2026, 4, 5))
        self.assertEqual(observances["Mother's Day"], date(2026, 5, 10))
        self.assertEqual(observances["Father's Day"], date(2026, 6, 21))
        self.assertEqual(observances["Ramadan Start"], date(2026, 2, 18))
        self.assertIsNone(public_holiday_name(date(2026, 5, 10)))

    def test_a_holiday_on_a_weekend_moves_nothing_to_monday(self):
        # Boxing Day 2026 is a Saturday, Women's Day 2026 a Sunday.
        self.assertIsNone(public_holiday_name(date(2026, 12, 28)))
        self.assertIsNone(public_holiday_name(date(2026, 3, 9)))


class RecordedHolidayTest(TestCase):
    def test_recorded_days_join_the_national_calendar(self):
        PublicHoliday.objects.create(name="Census Day", date=date(2026, 11, 3))
        CalendarBlock.objects.create(
            title="Boxing Day (observed)",
            block_type="PUBLIC_HOLIDAY",
            start_date=date(2026, 12, 28),
            end_date=date(2026, 12, 28),
        )

        self.assertEqual(public_holiday_name(date(2026, 11, 3)), "Census Day")
        self.assertEqual(
            public_holidays_between(date(2026, 10, 1), date(2026, 11, 30)),
            {date(2026, 10, 9): "Independence Day", date(2026, 11, 3): "Census Day"},
        )
        self.assertEqual(
            public_holiday_name(date(2026, 12, 28)), "Boxing Day (observed)"
        )

    def test_an_announced_eid_replaces_the_expected_day(self):
        self.assertIn(date(2027, 3, 9), _public(2027))
        PublicHoliday.objects.create(name="Idd el-Fitri", date=date(2027, 3, 10))

        year = _public(2027)

        self.assertEqual(year[date(2027, 3, 10)], "Idd el-Fitri")
        self.assertNotIn(date(2027, 3, 9), year)
        # The other Eid is still only expected.
        self.assertEqual(year[date(2027, 5, 16)], "Eid al-Adha (expected date)")

    def test_a_recorded_name_wins_its_own_day(self):
        PublicHoliday.objects.create(name="Uhuru Day", date=date(2026, 10, 9))

        days = [
            holiday
            for holiday in holidays_between(date(2026, 10, 9), date(2026, 10, 9))
            if holiday.is_public
        ]

        self.assertEqual([holiday.name for holiday in days], ["Uhuru Day"])

    def test_upcoming_holidays_are_soonest_first(self):
        upcoming = upcoming_public_holidays(date(2026, 10, 5), limit=3)

        self.assertEqual(
            [(holiday.date, holiday.name) for holiday in upcoming],
            [
                (date(2026, 10, 9), "Independence Day"),
                (date(2026, 12, 25), "Christmas Day"),
                (date(2026, 12, 26), "Boxing Day"),
            ],
        )


class EveryReaderAgreesTest(TestCase):
    """Leave arithmetic and the scheduling policy read the same calendar."""

    def test_working_days_skip_a_national_holiday_nobody_recorded(self):
        self.assertFalse(PublicHoliday.objects.exists())
        # Thu 8 – Mon 12 Oct 2026: the 9th is Independence Day, then a weekend.
        self.assertEqual(
            WorkingDayCalculator.calculate_working_days("2026-10-08", "2026-10-12"), 2
        )
        self.assertEqual(
            PublicHolidayService.get_holidays_in_range("2026-10-01", "2026-10-31"),
            [date(2026, 10, 9)],
        )

    def test_the_scheduling_policy_names_the_holiday(self):
        user = User.objects.create_user(
            email="holiday-policy@example.com",
            name="Holiday Policy",
            roles=["CCEO"],
            active_role="CCEO",
        )
        StaffProfile.objects.create(user=user, title="CCEO")

        verdict = SchedulingPolicyService.check(user, date(2026, 10, 9))
        clear = SchedulingPolicyService.check(user, date(2026, 10, 8))

        self.assertIn(
            "This date is a public holiday: Independence Day.",
            verdict["calendarConflicts"],
        )
        self.assertEqual(clear["calendarConflicts"], [])

    def test_a_recorded_holiday_is_named_once(self):
        CalendarBlock.objects.create(
            title="Independence Day",
            block_type="PUBLIC_HOLIDAY",
            start_date=date(2026, 10, 9),
            end_date=date(2026, 10, 9),
        )

        verdict = SchedulingPolicyService.check(None, date(2026, 10, 9))

        self.assertEqual(
            verdict["calendarConflicts"],
            ["This date is a public holiday: Independence Day."],
        )
