"""The day a traveller comes home has no night and no dinner.

Owner, 2026-10-05: "a week accommodation is 4 days because the fifth day they
travel back and sleep and eat dinner from home. But transport, breakfast and
lunch remains for 5 days. If the schedule is up to Saturday, then
accommodation and dinner is for 5 days."
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import SimpleTestCase
from freezegun import freeze_time

from apps.accounts.models import StaffSchoolAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.costing import cost_for_activity
from apps.budget.costing_service import preview
from apps.schools.models import School

from .models import DailyVisitBatch
from .pricing import (
    ACCOMMODATION_KEY,
    DINNER_KEY,
    MANAGEMENT_ACCOMMODATION_KEY,
    RETURN_DAY_DROPPED_KEYS,
    compute_daily_pool,
    day_keys,
)
from .return_day import is_return_day, priced_as_return_day
from .services import batch_needs_repricing, remove_school
from .tests import SECONDARY_RATES, DailyVisitBatchTestCase

RATES = dict(SECONDARY_RATES)
NIGHT = RATES[ACCOMMODATION_KEY]
DINNER = RATES[DINNER_KEY]
FULL_DAY = sum(RATES.values())
DAY_HOME = FULL_DAY - NIGHT - DINNER

# The week of Monday 3 August 2026 ("today" in the fixture is 27 July).
MON, TUE, WED, THU, FRI, SAT = (date(2026, 8, 3) + timedelta(days=n) for n in range(6))
NEXT_MON = date(2026, 8, 10)


class ReturnDayRecipeTest(SimpleTestCase):
    def test_the_day_home_fetches_transport_breakfast_and_lunch_only(self):
        self.assertEqual(
            day_keys("secondary", return_day=True),
            [
                "secondary_transport_per_day",
                "lunch_per_day",
                "secondary_breakfast_per_day",
            ],
        )
        self.assertEqual(
            set(day_keys("secondary")) - set(day_keys("secondary", return_day=True)),
            {ACCOMMODATION_KEY, DINNER_KEY},
        )

    def test_it_drops_whichever_accommodation_rate_the_traveller_has(self):
        self.assertEqual(
            day_keys("secondary", MANAGEMENT_ACCOMMODATION_KEY, return_day=True),
            day_keys("secondary", return_day=True),
        )
        self.assertEqual(
            RETURN_DAY_DROPPED_KEYS,
            {ACCOMMODATION_KEY, MANAGEMENT_ACCOMMODATION_KEY, DINNER_KEY},
        )

    def test_a_primary_day_is_untouched(self):
        self.assertEqual(day_keys("primary", return_day=True), day_keys("primary"))

    def test_the_pool_of_the_day_home(self):
        pool = compute_daily_pool(RATES, "secondary", return_day=True)
        self.assertEqual(sum(pool.values()), DAY_HOME)
        self.assertEqual(sum(compute_daily_pool(RATES, "secondary").values()), FULL_DAY)

    def test_the_pure_recipe_reads_the_day_home(self):
        visit = {
            "activityType": "school_visit",
            "deliveryType": "staff",
            "districtType": "secondary",
        }
        self.assertEqual(cost_for_activity(visit, RATES).amount, FULL_DAY)
        home = cost_for_activity({**visit, "returnDay": True}, RATES)
        self.assertEqual(home.amount, DAY_HOME)
        self.assertFalse(home.cost_missing)
        # A trip of several days is priced by its own recipe, as it was.
        trip = {
            "activityType": "field_event",
            "deliveryType": "staff",
            "districtType": "secondary",
            "days": 3,
        }
        self.assertEqual(
            cost_for_activity({**trip, "returnDay": True}, RATES).amount,
            cost_for_activity(trip, RATES).amount,
        )


@freeze_time("2026-07-27")
class WeekAwayTest(DailyVisitBatchTestCase):
    def setUp(self):
        super().setUp()
        # A school has one staff support visit a year: one school a day.
        self.away_schools = [self._secondary_school(n) for n in range(7)]
        self._next_school = iter(self.away_schools)
        self.visits: dict[date, Activity] = {}

    def _secondary_school(self, n):
        school = School.objects.create(
            school_id=f"AWAY-{n}",
            name=f"Away School {n}",
            region=self.region,
            district=self.secondary_district_a,
            sub_county=self.sub_county,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.staff_profile, school_id=school.id
        )
        return school

    def _away(self, *days):
        for day in days:
            school = next(self._next_school)
            result = self._schedule([school.school_id], day, reason="one a day")
            self.visits[day] = Activity.objects.get(id=result["activities"][0]["id"])

    def _at_home(self, day):
        result = self._schedule(["BATCH-P-1"], day, reason="home district")
        self.visits[day] = Activity.objects.get(id=result["activities"][0]["id"])

    def _keys(self, day):
        return set(
            ActivityScheduleCostLine.objects.filter(
                activity=self.visits[day]
            ).values_list("cost_setting_key", flat=True)
        )

    def _total(self, day):
        return Activity.objects.get(id=self.visits[day].id).est_cost_cents

    def _nights(self, *days):
        return [day for day in days if ACCOMMODATION_KEY in self._keys(day)]

    def _dinners(self, *days):
        return [day for day in days if DINNER_KEY in self._keys(day)]

    def _assert_full(self, *days):
        for day in days:
            with self.subTest(full=day):
                self.assertEqual(self._total(day), FULL_DAY)
                self.assertLessEqual({ACCOMMODATION_KEY, DINNER_KEY}, self._keys(day))

    def _assert_day_home(self, day):
        self.assertEqual(self._total(day), DAY_HOME)
        self.assertEqual(
            self._keys(day),
            {
                "secondary_transport_per_day",
                "lunch_per_day",
                "secondary_breakfast_per_day",
            },
        )
        batch = Activity.objects.get(id=self.visits[day].id).daily_visit_batch
        self.assertTrue(priced_as_return_day(batch))
        self.assertEqual(batch.daily_pool_amount, DAY_HOME)
        self.assertFalse(batch_needs_repricing(batch))

    def test_a_week_away_is_four_nights_and_four_dinners(self):
        """Monday to Friday: the fifth day they travel back."""
        week = (MON, TUE, WED, THU, FRI)
        self._away(*week)

        self.assertEqual(self._nights(*week), [MON, TUE, WED, THU])
        self.assertEqual(self._dinners(*week), [MON, TUE, WED, THU])
        self._assert_full(MON, TUE, WED, THU)
        self._assert_day_home(FRI)
        # Transport, breakfast and lunch remain for all five days.
        for key in (
            "secondary_transport_per_day",
            "secondary_breakfast_per_day",
            "lunch_per_day",
        ):
            with self.subTest(key=key):
                self.assertTrue(all(key in self._keys(day) for day in week))
        self.assertEqual(
            sum(self._total(day) for day in week), 5 * DAY_HOME + 4 * (NIGHT + DINNER)
        )

    def test_a_week_up_to_saturday_is_five_nights_and_five_dinners(self):
        week = (MON, TUE, WED, THU, FRI)
        self._away(*week)
        self._assert_day_home(FRI)

        # Saturday is planned afterwards: Friday gets its night back.
        self._away(SAT)

        self.assertEqual(self._nights(*week, SAT), list(week))
        self.assertEqual(self._dinners(*week, SAT), list(week))
        self._assert_full(*week)
        self._assert_day_home(SAT)

    def test_the_order_the_days_are_planned_in_does_not_matter(self):
        self._away(FRI, WED, MON, THU, TUE)
        self.assertEqual(self._nights(MON, TUE, WED, THU, FRI), [MON, TUE, WED, THU])
        self._assert_day_home(FRI)

    def test_one_day_away_on_its_own_keeps_its_night_and_dinner(self):
        self._away(WED)
        self._assert_full(WED)
        self.assertFalse(is_return_day(self.staff_user.id, WED))

    def test_two_days_away_are_one_night(self):
        self._away(TUE, WED)
        self._assert_full(TUE)
        self._assert_day_home(WED)

    def test_taking_the_last_day_off_makes_the_day_before_the_day_home(self):
        self._away(MON, TUE, WED)
        self._assert_day_home(WED)

        remove_school(activity_id=self.visits[WED].id)

        self._assert_full(MON)
        self._assert_day_home(TUE)

    def test_taking_a_middle_day_off_ends_the_run_there(self):
        self._away(MON, TUE, WED, THU)
        remove_school(activity_id=self.visits[TUE].id)
        # Monday is now a day away on its own; Wednesday starts a new run.
        self._assert_full(MON, WED)
        self._assert_day_home(THU)

    def test_a_day_in_the_home_district_ends_the_run(self):
        self._away(MON, TUE)
        self._at_home(WED)
        self._away(THU, FRI)

        self._assert_full(MON, THU)
        self._assert_day_home(TUE)
        self._assert_day_home(FRI)
        self.assertEqual(
            self._keys(WED), {"primary_transport_per_day", "lunch_per_day"}
        )

    def test_sunday_ends_the_week(self):
        self._away(FRI, SAT, NEXT_MON)
        self._assert_full(FRI)
        self._assert_day_home(SAT)
        # Monday follows a day nobody was away on.
        self._assert_full(NEXT_MON)

    def test_two_schools_on_the_day_home_share_what_is_left(self):
        self._away(THU)
        first, second = next(self._next_school), next(self._next_school)
        result = self._schedule(
            [first.school_id, second.school_id], FRI, reason="two schools"
        )
        totals = sorted(
            Activity.objects.filter(
                id__in=[item["id"] for item in result["activities"]]
            ).values_list("est_cost_cents", flat=True)
        )
        self.assertEqual(sum(totals), DAY_HOME)
        self.assertEqual(totals, [DAY_HOME // 2, DAY_HOME - DAY_HOME // 2])

    def test_the_drawer_estimate_is_the_day_home(self):
        self._away(MON, TUE)
        school = next(self._next_school)

        def estimate(day):
            return preview(
                {
                    "activityType": "school_visit",
                    "deliveryType": "staff",
                    "schoolId": school.school_id,
                    "plannedDate": day.isoformat(),
                },
                responsible_user_id=self.staff_user.id,
            )

        wednesday = estimate(WED)
        self.assertEqual(wednesday["amount"], DAY_HOME)
        self.assertEqual(
            {line["key"] for line in wednesday["lines"]} & RETURN_DAY_DROPPED_KEYS,
            set(),
        )
        # A day with nobody away before it is priced in full.
        self.assertEqual(estimate(FRI)["amount"], FULL_DAY)

    def test_a_day_already_worked_is_not_repriced(self):
        """Thursday was the day home and has been delivered: planning Friday
        afterwards does not hand Thursday a night it was never slept."""
        self._away(WED, THU)
        self._assert_day_home(THU)
        Activity.objects.filter(id=self.visits[THU].id).update(status="completed")

        self._away(FRI)

        self.assertEqual(self._total(THU), DAY_HOME)
        self.assertNotIn(ACCOMMODATION_KEY, self._keys(THU))
        self._assert_day_home(FRI)

    def test_a_week_priced_before_the_rule_is_found_and_repriced(self):
        from unittest.mock import patch

        from .services import _recalculate_and_write_lines

        with patch(
            "apps.daily_visit_batches.services.is_return_day", lambda *a, **k: False
        ):
            self._away(MON, TUE, WED)
        self._assert_full(MON, TUE, WED)
        batch = DailyVisitBatch.objects.get(
            responsible_user=self.staff_user.id, visit_date=WED
        )
        self.assertTrue(batch_needs_repricing(batch))
        for day in (MON, TUE):
            self.assertFalse(
                batch_needs_repricing(
                    DailyVisitBatch.objects.get(
                        responsible_user=self.staff_user.id, visit_date=day
                    )
                )
            )

        _recalculate_and_write_lines(batch, None, batch.responsible_user)

        self._assert_full(MON, TUE)
        self._assert_day_home(WED)


@freeze_time("2026-07-27")
class PlansMadeBeforeTheRulesTest(WeekAwayTest):
    """Daily visit batches migration 0003 and what it calls."""

    def _priced_the_old_way(self, *days):
        from unittest.mock import patch

        with patch(
            "apps.daily_visit_batches.services.is_return_day", lambda *a, **k: False
        ):
            self._away(*days)

    def _batch(self, day, user=None):
        return DailyVisitBatch.objects.get(
            responsible_user=(user or self.staff_user).id, visit_date=day
        )

    def test_the_day_home_of_a_week_planned_earlier_is_found_and_repriced(self):
        from .repricing import find_days_to_reprice, night_is_stale, reprice_days

        self._priced_the_old_way(MON, TUE, WED, THU, FRI)
        self._assert_full(MON, TUE, WED, THU, FRI)
        friday = self._batch(FRI)
        self.assertTrue(night_is_stale(friday))
        self.assertFalse(night_is_stale(self._batch(THU)))

        self.assertEqual(find_days_to_reprice(), [friday.id])
        lines = []
        result = reprice_days(write=lines.append)

        self.assertEqual(result, {"repriced": [friday.id], "skipped": [], "left": []})
        self.assertIn(f"UGX {FULL_DAY:,} -> UGX {DAY_HOME:,}", lines[0])
        self._assert_full(MON, TUE, WED, THU)
        self._assert_day_home(FRI)
        self.assertEqual(find_days_to_reprice(), [])

    def test_the_migration_reprices_them_through_its_historical_models(self):
        from importlib import import_module

        from django.apps import apps as django_apps

        from .repricing import find_days_to_reprice

        self._priced_the_old_way(MON, TUE)
        self.assertEqual(find_days_to_reprice(django_apps), [self._batch(TUE).id])

        import_module(
            "apps.daily_visit_batches.migrations.0003_reprice_planned_nights_away"
        ).reprice(django_apps, None)

        self._assert_full(MON)
        self._assert_day_home(TUE)

    def test_a_day_already_past_is_history(self):
        from .repricing import find_days_to_reprice

        self._priced_the_old_way(MON, TUE)
        self.assertEqual(find_days_to_reprice(today=TUE), [self._batch(TUE).id])
        self.assertEqual(find_days_to_reprice(today=WED), [])

    def test_a_week_that_has_left_draft_is_kept_as_it_was_priced(self):
        from apps.fund_requests.models import WeeklyFundRequest

        from .repricing import reprice_days

        self._priced_the_old_way(MON, TUE)
        updated = WeeklyFundRequest.objects.filter(
            responsible_user=self.staff_user.id,
            week_start_date__lte=TUE,
            week_end_date__gte=TUE,
        ).update(status="submitted_to_pl")
        self.assertEqual(updated, 1)
        tuesday = self._batch(TUE)

        lines = []
        result = reprice_days(write=lines.append)

        self.assertEqual(result, {"repriced": [], "skipped": [tuesday.id], "left": []})
        self.assertIn("its week has left draft", lines[0])
        self._assert_full(TUE)

    def test_nothing_is_started_after_the_deadline(self):
        import time

        from .repricing import reprice_days

        self._priced_the_old_way(MON, TUE)
        tuesday = self._batch(TUE)
        result = reprice_days(write=lambda _line: None, deadline=time.monotonic() - 1)
        self.assertEqual(result, {"repriced": [], "skipped": [], "left": [tuesday.id]})
        self._assert_full(TUE)

    def test_a_night_at_the_wrong_travellers_rate_is_found_and_repriced(self):
        from unittest.mock import patch

        from apps.accounts.models import StaffProfile, User
        from apps.budget.models import CostSetting
        from apps.core.rbac import EdifyRole

        from .repricing import find_days_to_reprice, reprice_days

        CostSetting.objects.update_or_create(
            key=MANAGEMENT_ACCOMMODATION_KEY,
            catalogue=self.catalogue,
            defaults={
                "label": "Accommodation - PL, CD, IA and Accountant",
                "unit_cost": 210000,
                "fy": self.catalogue.fy,
                "version": 1,
            },
        )
        lead = User.objects.create_user(
            email="lead-away@test.com",
            name="Lead Away",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            password="x",
            is_active=True,
        )
        profile = StaffProfile.objects.create(user=lead, title="Program Lead")
        school = self.away_schools[-1]
        StaffSchoolAssignment.objects.create(staff=profile, school_id=school.id)
        self.principal = lead
        # Planned while every night fetched the one accommodation row.
        with (
            patch(
                "apps.daily_visit_batches.services.accommodation_key_for_staff",
                lambda _user: ACCOMMODATION_KEY,
            ),
            patch(
                "apps.activities.services._accommodation_key_for",
                lambda _user: ACCOMMODATION_KEY,
            ),
        ):
            result = self._schedule([school.school_id], WED, reason="solo")
        visit = Activity.objects.get(id=result["activities"][0]["id"])
        self.assertEqual(visit.est_cost_cents, FULL_DAY)
        batch = self._batch(WED, lead)

        self.assertEqual(find_days_to_reprice(), [batch.id])
        reprice_days(write=lambda _line: None)

        visit.refresh_from_db()
        self.assertEqual(visit.est_cost_cents, FULL_DAY - NIGHT + 210000)
        self.assertEqual(find_days_to_reprice(), [])
