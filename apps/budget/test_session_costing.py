"""Group-session cost calculators (apps.budget.session_costing): a cluster
meeting or a group training, in a primary or a secondary district.

The arithmetic under test: a session's direct cost plus an equal share of the
staff member's day away, such that ``per session x sessions + day`` is the
whole day's money: nothing charged twice, nothing lost to the divisor.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import SimpleTestCase

from apps.budget.session_costing import (
    CostingValidationError,
    cost_primary_cluster_meeting,
    cost_primary_group_training,
    cost_secondary_cluster_meeting,
    cost_secondary_group_training,
)
from apps.core.exceptions import BadRequest


class PrimaryClusterMeetingTests(SimpleTestCase):
    def test_twenty_participants_over_four_meetings_at_the_default_rates(self):
        cost = cost_primary_cluster_meeting(participant_count=20, meetings_per_day=4)

        self.assertEqual(cost.direct_costs.snack_total, 240_000)
        self.assertEqual(cost.direct_costs.venue_fee, 50_000)
        self.assertEqual(cost.direct_costs.direct_total, 290_000)

        self.assertEqual(cost.daily_rates.total_daily_rate, 330_000)
        self.assertEqual(cost.allocated_daily_rates.transport_share, 75_000)
        self.assertEqual(cost.allocated_daily_rates.meals_share, 7_500)
        self.assertEqual(cost.allocated_daily_rates.allocated_daily_total, 82_500)

        self.assertEqual(cost.totals.total_cost_per_meeting, 372_500)
        self.assertEqual(cost.totals.total_day_cost, 1_490_000)

    def test_zero_participants_is_the_venue_plus_the_day_share(self):
        cost = cost_primary_cluster_meeting(participant_count=0, meetings_per_day=4)
        self.assertEqual(cost.direct_costs.snack_total, 0)
        self.assertEqual(cost.direct_costs.direct_total, 50_000)
        self.assertEqual(cost.totals.total_cost_per_meeting, 132_500)
        self.assertEqual(cost.totals.total_day_cost, 530_000)

    def test_one_meeting_carries_the_whole_day(self):
        cost = cost_primary_cluster_meeting(participant_count=20, meetings_per_day=1)
        self.assertEqual(cost.allocated_daily_rates.allocated_daily_total, 330_000)
        self.assertEqual(cost.totals.total_cost_per_meeting, 620_000)
        self.assertEqual(cost.totals.total_day_cost, 620_000)

    def test_rate_overrides_replace_the_defaults(self):
        cost = cost_primary_cluster_meeting(
            10,
            2,
            snack_rate=10_000,
            venue_fee=40_000,
            daily_transport=200_000,
            daily_meals=20_000,
        )
        self.assertEqual(cost.direct_costs.snack_total, 100_000)
        self.assertEqual(cost.direct_costs.direct_total, 140_000)
        self.assertEqual(cost.allocated_daily_rates.transport_share, 100_000)
        self.assertEqual(cost.allocated_daily_rates.meals_share, 10_000)
        self.assertEqual(cost.totals.total_cost_per_meeting, 250_000)
        self.assertEqual(cost.totals.total_day_cost, 500_000)

    def test_zero_meetings_per_day_is_refused_not_divided_by(self):
        with self.assertRaises(CostingValidationError) as ctx:
            cost_primary_cluster_meeting(participant_count=20, meetings_per_day=0)
        self.assertIn("meetings_per_day", str(ctx.exception))

    def test_negative_meetings_participants_and_rates_are_refused(self):
        with self.assertRaises(CostingValidationError):
            cost_primary_cluster_meeting(20, -1)
        with self.assertRaises(CostingValidationError):
            cost_primary_cluster_meeting(-1, 4)
        for rate in ("snack_rate", "venue_fee", "daily_transport", "daily_meals"):
            with self.subTest(rate=rate), self.assertRaises(CostingValidationError):
                cost_primary_cluster_meeting(20, 4, **{rate: -1})

    def test_to_dict_carries_every_group(self):
        payload = cost_primary_cluster_meeting(20, 4).to_dict()
        self.assertEqual(
            set(payload),
            {
                "participant_count",
                "meetings_per_day",
                "direct_costs",
                "daily_rates",
                "allocated_daily_rates",
                "totals",
            },
        )
        self.assertEqual(
            payload["direct_costs"],
            {"snack_total": 240_000, "venue_fee": 50_000, "direct_total": 290_000},
        )
        self.assertEqual(
            payload["allocated_daily_rates"],
            {
                "transport_share": 75_000,
                "meals_share": 7_500,
                "allocated_daily_total": 82_500,
            },
        )
        self.assertEqual(
            payload["totals"],
            {"total_cost_per_meeting": 372_500, "total_day_cost": 1_490_000},
        )


class SecondaryClusterMeetingTests(SimpleTestCase):
    # Transport 80,000 + per diem 32,000 (8,000 + 12,000 + 12,000)
    # + accommodation 40,000 = 152,000 for the day.
    RATES = dict(
        meal_snack_rate_per_person=12_000,
        venue_fee=50_000,
        transport_daily=80_000,
        breakfast_rate=8_000,
        lunch_rate=12_000,
        dinner_rate=12_000,
        accommodation_rate=40_000,
    )

    def test_the_day_splits_equally_across_one_two_and_four_meetings(self):
        for meetings in (1, 2, 4):
            with self.subTest(meetings=meetings):
                cost = cost_secondary_cluster_meeting(20, meetings, **self.RATES)
                day = cost.daily_operational_breakdown
                self.assertEqual(day.total_daily_operational, 152_000)

                share = cost.allocated_per_meeting
                self.assertEqual(share.total_allocated, Decimal(152_000) / meetings)
                self.assertEqual(share.allocated_transport, Decimal(80_000) / meetings)
                self.assertEqual(share.allocated_meals, Decimal(32_000) / meetings)
                self.assertEqual(
                    share.allocated_accommodation, Decimal(40_000) / meetings
                )
                self.assertEqual(
                    share.allocated_transport
                    + share.allocated_meals
                    + share.allocated_accommodation,
                    share.total_allocated,
                )
                # Every meeting's share, added back up, is exactly the day.
                self.assertEqual(share.total_allocated * meetings, 152_000)

                self.assertEqual(cost.direct_costs.total_direct, 290_000)
                self.assertEqual(
                    cost.totals.cost_per_meeting, 290_000 + share.total_allocated
                )
                self.assertEqual(
                    cost.totals.total_day_budget, 290_000 * meetings + 152_000
                )

    def test_the_daily_breakdown_is_itemised(self):
        day = cost_secondary_cluster_meeting(
            20, 4, **self.RATES
        ).daily_operational_breakdown
        self.assertEqual(day.transport, 80_000)
        self.assertEqual(day.meals.breakfast, 8_000)
        self.assertEqual(day.meals.lunch, 12_000)
        self.assertEqual(day.meals.dinner, 12_000)
        self.assertEqual(day.meals.total_meals, 32_000)
        self.assertEqual(day.accommodation, 40_000)

    def test_four_meetings_a_day_is_the_default(self):
        cost = cost_secondary_cluster_meeting(20, **self.RATES)
        self.assertEqual(cost.cluster_meetings_count, 4)
        self.assertEqual(cost.allocated_per_meeting.total_allocated, 38_000)
        self.assertEqual(cost.totals.cost_per_meeting, 328_000)
        self.assertEqual(cost.totals.total_day_budget, 1_312_000)

    def test_zero_participants_leaves_the_venue_and_the_day_share(self):
        cost = cost_secondary_cluster_meeting(0, 4, **self.RATES)
        self.assertEqual(cost.direct_costs.participant_meals_total, 0)
        self.assertEqual(cost.direct_costs.total_direct, 50_000)
        self.assertEqual(cost.totals.cost_per_meeting, 88_000)
        self.assertEqual(cost.totals.total_day_budget, 352_000)

    def test_an_aggregated_per_diem_prices_the_same_as_its_meals(self):
        rates = {
            k: v
            for k, v in self.RATES.items()
            if k not in ("breakfast_rate", "lunch_rate", "dinner_rate")
        }
        itemised = cost_secondary_cluster_meeting(20, 4, **self.RATES)
        aggregated = cost_secondary_cluster_meeting(
            20, 4, daily_per_diem=32_000, **rates
        )

        self.assertEqual(aggregated.totals, itemised.totals)
        self.assertEqual(
            aggregated.allocated_per_meeting, itemised.allocated_per_meeting
        )
        meals = aggregated.daily_operational_breakdown.meals
        self.assertEqual(meals.total_meals, 32_000)
        # An aggregate says nothing about how it divides; no split is invented.
        self.assertIsNone(meals.breakfast)
        self.assertIsNone(meals.lunch)
        self.assertIsNone(meals.dinner)

    def test_the_per_diem_must_be_given_one_way_not_both_not_neither(self):
        without_meals = {
            k: v
            for k, v in self.RATES.items()
            if k not in ("breakfast_rate", "lunch_rate", "dinner_rate")
        }
        with self.assertRaises(CostingValidationError):
            cost_secondary_cluster_meeting(20, 4, daily_per_diem=32_000, **self.RATES)
        with self.assertRaises(CostingValidationError):
            cost_secondary_cluster_meeting(20, 4, **without_meals)
        # Itemising means all three meals: a forgotten dinner is not a free one.
        with self.assertRaises(CostingValidationError):
            cost_secondary_cluster_meeting(
                20, 4, breakfast_rate=8_000, lunch_rate=12_000, **without_meals
            )

    def test_zero_or_negative_meeting_count_is_refused(self):
        for meetings in (0, -1, -4):
            with self.subTest(meetings=meetings):
                with self.assertRaises(CostingValidationError) as ctx:
                    cost_secondary_cluster_meeting(20, meetings, **self.RATES)
                self.assertIn("cluster_meetings_count", str(ctx.exception))

    def test_negative_counts_and_rates_are_refused(self):
        with self.assertRaises(CostingValidationError):
            cost_secondary_cluster_meeting(-5, 4, **self.RATES)
        for rate in self.RATES:
            with self.subTest(rate=rate), self.assertRaises(CostingValidationError):
                cost_secondary_cluster_meeting(20, 4, **{**self.RATES, rate: -1})


class PrimaryGroupTrainingTests(SimpleTestCase):
    def test_two_trainings_a_day_with_facilitation_and_materials(self):
        cost = cost_primary_group_training(
            participant_count=25,
            trainings_per_day=2,
            meal_rate_per_participant=12_000,
            venue_fee=30_000,
            facilitation_fee=50_000,
            materials_cost=20_000,
            daily_transport=50_000,
            daily_staff_lunch=12_000,
        )
        direct = cost.direct_costs
        self.assertEqual(direct.participant_meals_total, 300_000)
        self.assertEqual(direct.venue_fee, 30_000)
        self.assertEqual(direct.facilitation_fee, 50_000)
        self.assertEqual(direct.materials_cost, 20_000)
        self.assertEqual(direct.total_direct, 400_000)

        day = cost.daily_operational_costs
        self.assertEqual(day.transport, 50_000)
        self.assertEqual(day.staff_lunch, 12_000)
        self.assertEqual(day.total_daily, 62_000)

        share = cost.allocated_per_training
        self.assertEqual(share.allocated_transport, 25_000)
        self.assertEqual(share.allocated_staff_lunch, 6_000)
        self.assertEqual(share.total_allocated, 31_000)

        self.assertEqual(cost.totals.cost_per_training, 431_000)
        self.assertEqual(cost.totals.total_day_cost, 862_000)

    def test_a_single_training_carries_the_whole_day(self):
        cost = cost_primary_group_training(
            25,
            1,
            meal_rate_per_participant=12_000,
            venue_fee=30_000,
            facilitation_fee=50_000,
            daily_transport=50_000,
            daily_staff_lunch=12_000,
        )
        self.assertEqual(cost.allocated_per_training.total_allocated, 62_000)
        self.assertEqual(cost.totals.cost_per_training, 442_000)
        self.assertEqual(cost.totals.total_day_cost, 442_000)

    def test_zero_cost_line_items_default_to_nothing(self):
        # A session at the office: no venue, no facilitator, no handouts.
        cost = cost_primary_group_training(
            10,
            2,
            meal_rate_per_participant=12_000,
            daily_transport=50_000,
            daily_staff_lunch=12_000,
        )
        self.assertEqual(cost.direct_costs.venue_fee, 0)
        self.assertEqual(cost.direct_costs.facilitation_fee, 0)
        self.assertEqual(cost.direct_costs.materials_cost, 0)
        self.assertEqual(cost.direct_costs.total_direct, 120_000)
        self.assertEqual(cost.totals.cost_per_training, 151_000)
        self.assertEqual(cost.totals.total_day_cost, 302_000)

    def test_zero_participants_leaves_the_fixed_items(self):
        cost = cost_primary_group_training(
            0,
            2,
            meal_rate_per_participant=12_000,
            venue_fee=30_000,
            daily_transport=50_000,
            daily_staff_lunch=12_000,
        )
        self.assertEqual(cost.direct_costs.participant_meals_total, 0)
        self.assertEqual(cost.direct_costs.total_direct, 30_000)
        self.assertEqual(cost.totals.cost_per_training, 61_000)

    def test_invalid_trainings_per_day_is_refused(self):
        for trainings in (0, -1):
            with self.subTest(trainings=trainings):
                with self.assertRaises(CostingValidationError) as ctx:
                    cost_primary_group_training(
                        25,
                        trainings,
                        meal_rate_per_participant=12_000,
                        daily_transport=50_000,
                        daily_staff_lunch=12_000,
                    )
                self.assertIn("trainings_per_day", str(ctx.exception))

    def test_negative_counts_and_rates_are_refused(self):
        base = dict(
            meal_rate_per_participant=12_000,
            venue_fee=30_000,
            facilitation_fee=50_000,
            materials_cost=20_000,
            daily_transport=50_000,
            daily_staff_lunch=12_000,
        )
        with self.assertRaises(CostingValidationError):
            cost_primary_group_training(-1, 2, **base)
        for rate in base:
            with self.subTest(rate=rate), self.assertRaises(CostingValidationError):
                cost_primary_group_training(25, 2, **{**base, rate: -1})


class SecondaryGroupTrainingTests(SimpleTestCase):
    # The benchmark day: four trainings of thirty, every line item non-zero.
    # Transport 80,000 + per diem 32,000 + accommodation 40,000 = 152,000.
    BENCHMARK = dict(
        meal_rate_per_participant=12_000,
        venue_fee=30_000,
        facilitation_fee=50_000,
        materials_cost=20_000,
        transport_rate=80_000,
        breakfast_rate=8_000,
        lunch_rate=12_000,
        dinner_rate=12_000,
        accommodation_rate=40_000,
    )

    def test_benchmark_four_trainings_of_thirty(self):
        cost = cost_secondary_group_training(
            participant_count=30, trainings_per_day=4, **self.BENCHMARK
        )
        direct = cost.direct_costs
        self.assertEqual(direct.participant_meals_total, 360_000)
        self.assertEqual(direct.total_direct, 460_000)

        day = cost.daily_operational_breakdown
        self.assertEqual(day.transport, 80_000)
        self.assertEqual(day.meals.breakfast, 8_000)
        self.assertEqual(day.meals.lunch, 12_000)
        self.assertEqual(day.meals.dinner, 12_000)
        self.assertEqual(day.meals.total_per_diem, 32_000)
        self.assertEqual(day.accommodation, 40_000)
        self.assertEqual(day.total_daily_allowances, 152_000)

        share = cost.allocated_per_training
        self.assertEqual(share.allocated_transport, 20_000)
        self.assertEqual(share.allocated_meals, 8_000)
        self.assertEqual(share.allocated_accommodation, 10_000)
        self.assertEqual(share.total_allocated, 38_000)

        self.assertEqual(cost.totals.cost_per_training, 498_000)
        self.assertEqual(cost.totals.total_day_cost, 1_992_000)

    def test_the_four_shares_add_back_up_to_the_day_exactly(self):
        cost = cost_secondary_group_training(30, 4, **self.BENCHMARK)
        share = cost.allocated_per_training
        sessions = [share.total_allocated for _ in range(cost.trainings_per_day)]
        self.assertEqual(
            sum(sessions), cost.daily_operational_breakdown.total_daily_allowances
        )
        self.assertEqual(
            sum(share.allocated_transport for _ in range(4)),
            cost.daily_operational_breakdown.transport,
        )
        self.assertEqual(
            sum(share.allocated_meals for _ in range(4)),
            cost.daily_operational_breakdown.meals.total_per_diem,
        )
        self.assertEqual(
            sum(share.allocated_accommodation for _ in range(4)),
            cost.daily_operational_breakdown.accommodation,
        )
        # And the day's total is the four sessions plus the day, no more.
        self.assertEqual(
            cost.totals.total_day_cost,
            cost.totals.cost_per_training * 4,
        )

    def test_thirty_participants_and_four_trainings_are_the_defaults(self):
        cost = cost_secondary_group_training(**self.BENCHMARK)
        self.assertEqual(cost.participant_count, 30)
        self.assertEqual(cost.trainings_per_day, 4)
        self.assertEqual(cost.totals.cost_per_training, 498_000)

    def test_zero_cost_items(self):
        rates = {**self.BENCHMARK, "venue_fee": 0, "materials_cost": 0}
        cost = cost_secondary_group_training(30, 4, **rates)
        self.assertEqual(cost.direct_costs.venue_fee, 0)
        self.assertEqual(cost.direct_costs.materials_cost, 0)
        self.assertEqual(cost.direct_costs.total_direct, 410_000)
        self.assertEqual(cost.totals.cost_per_training, 448_000)
        self.assertEqual(cost.totals.total_day_cost, 1_792_000)

        # Left out entirely, the optional items are also nothing.
        without = {
            k: v
            for k, v in self.BENCHMARK.items()
            if k not in ("venue_fee", "facilitation_fee", "materials_cost")
        }
        cost = cost_secondary_group_training(30, 4, **without)
        self.assertEqual(cost.direct_costs.total_direct, 360_000)

    def test_an_aggregated_per_diem_prices_the_same_as_its_meals(self):
        without_meals = {
            k: v
            for k, v in self.BENCHMARK.items()
            if k not in ("breakfast_rate", "lunch_rate", "dinner_rate")
        }
        itemised = cost_secondary_group_training(30, 4, **self.BENCHMARK)
        aggregated = cost_secondary_group_training(
            30, 4, per_diem_total=32_000, **without_meals
        )
        self.assertEqual(aggregated.totals, itemised.totals)
        self.assertEqual(
            aggregated.allocated_per_training, itemised.allocated_per_training
        )
        self.assertEqual(
            aggregated.daily_operational_breakdown.meals.total_per_diem, 32_000
        )
        self.assertIsNone(aggregated.daily_operational_breakdown.meals.breakfast)

        with self.assertRaises(CostingValidationError):
            cost_secondary_group_training(
                30, 4, per_diem_total=32_000, **self.BENCHMARK
            )
        with self.assertRaises(CostingValidationError):
            cost_secondary_group_training(30, 4, **without_meals)

    def test_trainings_per_day_of_zero_or_less_is_refused(self):
        for trainings in (0, -1, -4):
            with self.subTest(trainings=trainings):
                with self.assertRaises(CostingValidationError) as ctx:
                    cost_secondary_group_training(30, trainings, **self.BENCHMARK)
                self.assertIn("trainings_per_day", str(ctx.exception))

    def test_negative_counts_and_rates_are_refused(self):
        with self.assertRaises(CostingValidationError):
            cost_secondary_group_training(-1, 4, **self.BENCHMARK)
        for rate in self.BENCHMARK:
            with self.subTest(rate=rate), self.assertRaises(CostingValidationError):
                cost_secondary_group_training(30, 4, **{**self.BENCHMARK, rate: -1})


class InputHandlingTests(SimpleTestCase):
    """The calculators are called from JSON clients, HTML forms and Python
    alike, so they take numbers however those arrive, and refuse what is not
    a number rather than pricing it as zero."""

    def test_form_strings_price_like_numbers(self):
        as_strings = cost_primary_cluster_meeting("20", "4", snack_rate="12000")
        as_numbers = cost_primary_cluster_meeting(20, 4, snack_rate=12_000)
        self.assertEqual(as_strings, as_numbers)

    def test_floats_do_not_bring_binary_rounding_with_them(self):
        cost = cost_primary_cluster_meeting(3, 1, snack_rate=0.1)
        self.assertEqual(cost.direct_costs.snack_total, Decimal("0.3"))
        self.assertEqual(
            cost_primary_group_training(
                1,
                1,
                meal_rate_per_participant=12_000.5,
                daily_transport=0,
                daily_staff_lunch=0,
            ).direct_costs.participant_meals_total,
            Decimal("12000.5"),
        )

    def test_decimals_pass_straight_through(self):
        cost = cost_primary_cluster_meeting(20, 4, snack_rate=Decimal("12000"))
        self.assertEqual(cost.totals.total_cost_per_meeting, Decimal("372500"))

    def test_fractional_counts_and_non_numbers_are_refused(self):
        with self.assertRaises(CostingValidationError):
            cost_primary_cluster_meeting(20.5, 4)
        with self.assertRaises(CostingValidationError):
            cost_primary_cluster_meeting(20, "four")
        with self.assertRaises(CostingValidationError):
            cost_primary_cluster_meeting(20, 4, snack_rate="twelve thousand")
        with self.assertRaises(CostingValidationError):
            cost_primary_cluster_meeting(20, 4, snack_rate=float("nan"))
        with self.assertRaises(CostingValidationError):
            cost_primary_cluster_meeting(20, 4, snack_rate=float("inf"))
        with self.assertRaises(CostingValidationError):
            cost_primary_cluster_meeting(20, 4, snack_rate=True)
        with self.assertRaises(CostingValidationError):
            cost_primary_cluster_meeting(20, 4, snack_rate=[12_000])

    def test_a_required_rate_left_out_is_an_error_not_a_free_item(self):
        with self.assertRaises(CostingValidationError) as ctx:
            cost_primary_group_training(
                25,
                2,
                meal_rate_per_participant=None,
                daily_transport=50_000,
                daily_staff_lunch=12_000,
            )
        self.assertIn("meal_rate_per_participant", str(ctx.exception))

    def test_the_error_is_both_a_value_error_and_a_bad_request(self):
        with self.assertRaises(ValueError):
            cost_primary_cluster_meeting(20, 0)
        with self.assertRaises(BadRequest) as ctx:
            cost_primary_cluster_meeting(20, 0)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("meetings_per_day", str(ctx.exception.detail))
