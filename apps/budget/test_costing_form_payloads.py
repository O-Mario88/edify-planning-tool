"""Regression coverage for participant counts posted by browser forms."""

from django.test import SimpleTestCase

from apps.budget.costing import cost_for_activity


TRAINING_RATES = {
    "group_training_participant_meal_cost_per_head": 5_000,
    "group_training_facilitation_fee": 50_000,
    "group_training_venue_cost": 30_000,
}


class CostingFormPayloadTest(SimpleTestCase):
    def test_training_accepts_expected_participants_from_a_number_input(self):
        cost = cost_for_activity(
            {
                "activityType": "cluster_training",
                "expectedParticipants": "12",
            },
            TRAINING_RATES,
        )

        meal = next(line for line in cost.lines if line.label == "Participant meals")
        self.assertEqual(meal.qty, 12)
        self.assertEqual(meal.amount, 60_000)

    def test_training_sums_category_counts_from_number_inputs(self):
        cost = cost_for_activity(
            {
                "activityType": "cluster_training",
                "teachersAttended": "8",
                "leadersAttended": "2",
                "otherParticipants": "",
            },
            TRAINING_RATES,
        )

        meal = next(line for line in cost.lines if line.label == "Participant meals")
        self.assertEqual(meal.qty, 10)

    def test_multi_day_days_accepts_a_string_and_garbage(self):
        """`days` arrives as a string from number inputs; garbage falls back
        to one day instead of raising (the programme-event branch used a bare
        int() until the 2026-08-12 audit's L-2)."""
        rates = {
            "programme_venue_per_day": 100_000,
            "programme_participant_meal_cost_per_head": 5_000,
        }
        cost = cost_for_activity(
            {
                "activityType": "programme_event",
                "expectedParticipants": "10",
                "days": "3",
            },
            rates,
        )
        venue = next(line for line in cost.lines if line.label == "Venue")
        self.assertEqual(venue.qty, 3)

        cost = cost_for_activity(
            {"activityType": "programme_event", "days": "garbage"},
            rates,
        )
        venue = next(line for line in cost.lines if line.label == "Venue")
        self.assertEqual(venue.qty, 1)
