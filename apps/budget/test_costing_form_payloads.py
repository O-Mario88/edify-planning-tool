"""Regression coverage for participant counts posted by browser forms."""

from django.test import SimpleTestCase

from apps.budget.costing import cost_for_activity, resolve_activity_cost


TRAINING_RATES = {
    "group_training_participant_meal_cost_per_head": 5_000,
    "group_training_facilitation_fee": 50_000,
    "group_training_venue_cost": 30_000,
}


class CostingFormPayloadTest(SimpleTestCase):
    def test_training_accepts_expected_participants_from_a_number_input(self):
        cost = cost_for_activity(
            {
                "activityType": "in_school_training",
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
                "activityType": "in_school_training",
                "teachersAttended": "8",
                "leadersAttended": "2",
                "otherParticipants": "",
            },
            TRAINING_RATES,
        )

        meal = next(line for line in cost.lines if line.label == "Participant meals")
        self.assertEqual(meal.qty, 10)

    def test_recosting_accepts_category_counts_serialized_as_strings(self):
        cost = resolve_activity_cost(
            {
                "activityType": "in_school_training",
                "teachersAttended": "6",
                "leadersAttended": "3",
                "otherParticipants": "1",
            },
            TRAINING_RATES,
            snapshot_lines=[
                {
                    "label": "Old snapshot",
                    "costSettingKey": "old",
                    "unitCost": 1,
                    "quantity": 1,
                    "amount": 1,
                }
            ],
        )

        meal = next(line for line in cost.lines if line.label == "Participant meals")
        self.assertEqual(meal.qty, 10)

