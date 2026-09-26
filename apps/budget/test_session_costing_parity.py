"""The costing engine and the session costing calculators agree.

apps.budget.session_costing is the executable form of the session costing
spec (2026-09-26). apps.budget.costing prices a scheduled session from the
Cost Catalogue, and apps.daily_visit_batches shares the day across the
sessions run on it. These tests put the same figures through both and
require the same shilling back, so the calculators stay the oracle for what
a cluster meeting or a group training costs. The database-backed half, where
the sessions go through the real scheduling path, lives beside the batch
tests: apps.daily_visit_batches.tests.DailyVisitBatchAgreesWithTheSessionCalculatorsTest.

Catalogue key                        calculator input
cluster_meetings_trainings_meals     snack_rate / meal_snack_rate_per_person
group_training_meals                 meal_rate_per_participant
group_training_venue_cost            venue_fee
group_training_facilitation_fee      facilitation_fee
printing_/photocopying_..._materials materials_cost (by the page)
primary_transport_per_day            daily_transport
secondary_transport_per_day          transport_daily / transport_rate
lunch_per_day                        daily_meals / daily_staff_lunch / lunch_rate
secondary_breakfast_per_day          breakfast_rate
secondary_overnight_dinner_per_day   dinner_rate
secondary_accommodation_per_night    accommodation_rate

The engine adds what the spec leaves to the catalogue: a session's own rate
(Cluster Meeting, Cluster Training), 0 on this card so the two sides compare
line for line.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import SimpleTestCase

from apps.budget.costing import cost_for_activity
from apps.budget.session_costing import (
    cost_primary_cluster_meeting,
    cost_primary_group_training,
    cost_secondary_cluster_meeting,
    cost_secondary_group_training,
)
from apps.daily_visit_batches.pricing import (
    KEY_LABELS,
    allocate_pool,
    compute_daily_pool,
)

CARD = {
    "cluster_meeting": 0,
    "cluster_meetings_trainings": 0,
    "cluster_meetings_trainings_meals": 12_000,
    "group_training_meals": 12_000,
    "group_training_venue_cost": 50_000,
    "group_training_facilitation_fee": 50_000,
    "printing_training_materials": 500,
    "photocopying_training_materials": 100,
    "primary_transport_per_day": 300_000,
    "secondary_transport_per_day": 80_000,
    "lunch_per_day": 30_000,
    "secondary_breakfast_per_day": 8_000,
    "secondary_overnight_dinner_per_day": 12_000,
    "secondary_accommodation_per_night": 40_000,
}
# Ten pages printed and five pages copied for twenty people: 5,000 + 10,000.
PAGES = {"printingPages": 10, "photocopyPages": 5, "photocopyCopies": 20}
MATERIALS = 10 * 500 + 5 * 20 * 100
# The secondary day: transport, breakfast, lunch, dinner, accommodation.
SECONDARY_DAY = 80_000 + 8_000 + 30_000 + 12_000 + 40_000


def engine_day(activity: dict, sessions: int) -> tuple[int, int, list[int]]:
    """What the engine and the Daily Visit Batch charge `sessions` identical
    sessions on one day: (a session's own lines, the day, each session's
    share of the day). The recipe's own lines ride on top of an equal
    whole-shilling split of the day pool, exactly as
    _recalculate_and_write_lines does it; a remainder shilling goes to the
    first sessions."""
    own = cost_for_activity(activity, CARD)
    assert not own.cost_missing, own.missing_items
    direct = sum(line.amount for line in own.lines if line.key not in KEY_LABELS)
    recipe_day = sum(line.amount for line in own.lines if line.key in KEY_LABELS)
    pool = compute_daily_pool(CARD, activity["districtType"])
    # The recipe's own copy of the day is exactly the pool that replaces it.
    assert recipe_day == sum(pool.values()), (recipe_day, pool)
    shares = [sum(share.values()) for share in allocate_pool(pool, sessions)]
    return direct, sum(pool.values()), shares


class ParityAssertions(SimpleTestCase):
    def assert_day_agrees(self, spec_per_session, spec_day, direct, day, shares):
        """The whole day agrees exactly, and every session agrees to within
        the whole-shilling rounding of the split (at most one shilling per
        pool item), while the shares still add back up to the day."""
        self.assertEqual(direct * len(shares) + day, spec_day)
        self.assertEqual(sum(shares), day)
        for share in shares:
            self.assertLessEqual(abs(Decimal(direct + share) - spec_per_session), 5)


class PrimaryClusterMeetingParityTest(ParityAssertions):
    ACTIVITY = {
        "activityType": "cluster_meeting",
        "deliveryType": "staff",
        "districtType": "primary",
        "expectedParticipants": 20,
    }

    def _spec(self, meetings: int):
        return cost_primary_cluster_meeting(
            20,
            meetings,
            snack_rate=12_000,
            venue_fee=50_000,
            daily_transport=300_000,
            daily_meals=30_000,
        )

    def test_the_worked_example_twenty_participants_four_meetings(self):
        spec = self._spec(4)
        direct, day, shares = engine_day(self.ACTIVITY, 4)
        self.assertEqual(direct, 290_000)
        self.assertEqual(direct, spec.direct_costs.direct_total)
        self.assertEqual(day, 330_000)
        self.assertEqual(day, spec.daily_rates.total_daily_rate)
        self.assertEqual(shares, [82_500] * 4)
        self.assertEqual([direct + share for share in shares], [372_500] * 4)
        self.assertEqual(spec.totals.total_cost_per_meeting, 372_500)
        self.assertEqual(direct * 4 + day, 1_490_000)
        self.assertEqual(spec.totals.total_day_cost, 1_490_000)

    def test_every_meeting_count_agrees(self):
        for meetings in (1, 2, 3, 4, 5, 7):
            with self.subTest(meetings=meetings):
                spec = self._spec(meetings)
                direct, day, shares = engine_day(self.ACTIVITY, meetings)
                self.assert_day_agrees(
                    spec.totals.total_cost_per_meeting,
                    spec.totals.total_day_cost,
                    direct,
                    day,
                    shares,
                )

    def test_zero_participants(self):
        spec = cost_primary_cluster_meeting(
            0,
            4,
            snack_rate=12_000,
            venue_fee=50_000,
            daily_transport=300_000,
            daily_meals=30_000,
        )
        # The engine refuses to fund a catered session for nobody (owner,
        # 2026-09-15: never priced for nobody); the arithmetic still agrees.
        own = cost_for_activity({**self.ACTIVITY, "expectedParticipants": 0}, CARD)
        self.assertTrue(own.cost_missing)
        self.assertIn("expectedParticipants", own.missing_items)
        direct = sum(line.amount for line in own.lines if line.key not in KEY_LABELS)
        self.assertEqual(direct, spec.direct_costs.direct_total)
        self.assertEqual(direct, 50_000)


class SecondaryClusterMeetingParityTest(ParityAssertions):
    ACTIVITY = {
        "activityType": "cluster_meeting",
        "deliveryType": "staff",
        "districtType": "secondary",
        "expectedParticipants": 20,
    }

    def _spec(self, meetings: int):
        return cost_secondary_cluster_meeting(
            20,
            meetings,
            meal_snack_rate_per_person=12_000,
            venue_fee=50_000,
            transport_daily=80_000,
            breakfast_rate=8_000,
            lunch_rate=30_000,
            dinner_rate=12_000,
            accommodation_rate=40_000,
        )

    def test_the_day_carries_the_per_diem_and_a_night(self):
        spec = self._spec(4)
        direct, day, shares = engine_day(self.ACTIVITY, 4)
        self.assertEqual(direct, 290_000)
        self.assertEqual(day, SECONDARY_DAY)
        self.assertEqual(day, spec.daily_operational_breakdown.total_daily_operational)
        self.assertEqual(shares, [42_500] * 4)
        self.assertEqual(spec.allocated_per_meeting.total_allocated, 42_500)
        self.assertEqual(direct + shares[0], spec.totals.cost_per_meeting)
        self.assertEqual(direct * 4 + day, spec.totals.total_day_budget)

    def test_every_meeting_count_agrees(self):
        for meetings in (1, 2, 3, 4, 6):
            with self.subTest(meetings=meetings):
                spec = self._spec(meetings)
                direct, day, shares = engine_day(self.ACTIVITY, meetings)
                self.assert_day_agrees(
                    spec.totals.cost_per_meeting,
                    spec.totals.total_day_budget,
                    direct,
                    day,
                    shares,
                )


class PrimaryGroupTrainingParityTest(ParityAssertions):
    TYPES = ("cluster_training", "training", "core_training")

    def _activity(self, activity_type: str, participants: int = 25) -> dict:
        return {
            "activityType": activity_type,
            "deliveryType": "staff",
            "districtType": "primary",
            "expectedParticipants": participants,
            **PAGES,
        }

    def _spec(self, trainings: int, participants: int = 25):
        return cost_primary_group_training(
            participants,
            trainings,
            meal_rate_per_participant=12_000,
            venue_fee=50_000,
            facilitation_fee=50_000,
            materials_cost=MATERIALS,
            daily_transport=300_000,
            daily_staff_lunch=30_000,
        )

    def test_two_trainings_a_day_with_materials(self):
        spec = self._spec(2)
        for activity_type in self.TYPES:
            with self.subTest(activity_type=activity_type):
                direct, day, shares = engine_day(self._activity(activity_type), 2)
                # 300,000 meals + 50,000 venue + 50,000 facilitation + 15,000
                # materials, and half of the 330,000 day.
                self.assertEqual(direct, 415_000)
                self.assertEqual(direct, spec.direct_costs.total_direct)
                self.assertEqual(shares, [165_000, 165_000])
                self.assertEqual(direct + shares[0], spec.totals.cost_per_training)
                self.assertEqual(direct * 2 + day, spec.totals.total_day_cost)

    def test_every_training_count_agrees(self):
        for trainings in (1, 2, 3, 4):
            with self.subTest(trainings=trainings):
                spec = self._spec(trainings)
                direct, day, shares = engine_day(
                    self._activity("cluster_training"), trainings
                )
                self.assert_day_agrees(
                    spec.totals.cost_per_training,
                    spec.totals.total_day_cost,
                    direct,
                    day,
                    shares,
                )


class SecondaryGroupTrainingParityTest(ParityAssertions):
    ACTIVITY = {
        "activityType": "training",
        "deliveryType": "staff",
        "districtType": "secondary",
        "expectedParticipants": 30,
        **PAGES,
    }

    def _spec(self, trainings: int):
        return cost_secondary_group_training(
            30,
            trainings,
            meal_rate_per_participant=12_000,
            venue_fee=50_000,
            facilitation_fee=50_000,
            materials_cost=MATERIALS,
            transport_rate=80_000,
            breakfast_rate=8_000,
            lunch_rate=30_000,
            dinner_rate=12_000,
            accommodation_rate=40_000,
        )

    def test_the_benchmark_four_trainings_of_thirty(self):
        spec = self._spec(4)
        direct, day, shares = engine_day(self.ACTIVITY, 4)
        # 360,000 meals + 50,000 + 50,000 + 15,000, and a quarter of the day.
        self.assertEqual(direct, 475_000)
        self.assertEqual(direct, spec.direct_costs.total_direct)
        self.assertEqual(day, SECONDARY_DAY)
        self.assertEqual(day, spec.daily_operational_breakdown.total_daily_allowances)
        self.assertEqual(shares, [42_500] * 4)
        self.assertEqual(sum(shares), spec.allocated_per_training.total_allocated * 4)
        self.assertEqual(direct + shares[0], spec.totals.cost_per_training)
        self.assertEqual(direct * 4 + day, spec.totals.total_day_cost)

    def test_every_training_count_agrees(self):
        for trainings in (1, 2, 3, 4):
            with self.subTest(trainings=trainings):
                spec = self._spec(trainings)
                direct, day, shares = engine_day(self.ACTIVITY, trainings)
                self.assert_day_agrees(
                    spec.totals.cost_per_training,
                    spec.totals.total_day_cost,
                    direct,
                    day,
                    shares,
                )


class PartnerRunGroupTrainingParityTest(SimpleTestCase):
    def test_a_partner_run_training_is_the_session_on_a_day_of_its_own(self):
        """A group training assigned to a partner is priced as the session
        (session costing spec, 2026-09-26), not as the Partner Meetings lump
        sum. Partner work is not pooled into a Daily Visit Batch, so the
        training carries its whole day: the spec with one training a day."""
        own = cost_for_activity(
            {
                "activityType": "training",
                "deliveryType": "partner",
                "districtType": "primary",
                "expectedParticipants": 25,
                **PAGES,
            },
            CARD,
        )
        spec = cost_primary_group_training(
            25,
            1,
            meal_rate_per_participant=12_000,
            venue_fee=50_000,
            facilitation_fee=50_000,
            materials_cost=MATERIALS,
            daily_transport=300_000,
            daily_staff_lunch=30_000,
        )
        self.assertFalse(own.cost_missing)
        self.assertEqual(own.amount, spec.totals.cost_per_training)
        self.assertEqual(own.amount, spec.totals.total_day_cost)
        self.assertNotIn("partner_meetings", [line.key for line in own.lines])
        self.assertIn("group_training_meals", [line.key for line in own.lines])
