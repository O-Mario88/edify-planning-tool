"""One recipe per shape of work — no rate is a second name for another.

Owner, 2026-09-04: "all in-school trainings have the same cost as the school
visit cost including core school ... all group trainings including core and
special project are the same ... all partner school visits and in-school
trainings have the same partner visit cost ... non-school activities are
treated as group training with participants, venue fee, facilitation fees ...
all other non-school visits are costed like school visit for staff."

Ten rates were retired to make that true: `core_school_visit`,
`ssa_visit_rate`, `core_school_training`, `project_partner_lump_sum` and the
six `programme_*` components.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.budget.costing import cost_for_activity
from apps.budget.reference import (
    CANONICAL_RATE_KEYS,
    DUPLICATE_COST_SETTING_KEYS,
    RETIRED_COST_SETTING_KEYS,
)

RATES = {
    "primary_transport_per_day": 50_000,
    "primary_lunch_per_day": 12_000,
    "secondary_transport_per_day": 80_000,
    "secondary_lunch_per_day": 12_000,
    "secondary_accommodation_per_night": 40_000,
    "secondary_overnight_dinner_per_day": 12_000,
    "secondary_breakfast_per_day": 8_000,
    "secondary_incidentals_per_day": 5_000,
    "group_training_participant_meal_cost_per_head": 5_000,
    "group_training_facilitation_fee": 50_000,
    "group_training_venue_cost": 30_000,
    "cluster_meeting_participant_meal_cost_per_head": 10_000,
    "partner_visit_lump_sum": 40_000,
    "partner_training_lump_sum": 16_000,
}
PRIMARY_STAFF_DAY = 62_000
SECONDARY_STAFF_DAY = 157_000


def _cost(**activity):
    return cost_for_activity({"deliveryType": "staff", **activity}, RATES)


class SchoolMissionsSharePriceTest(SimpleTestCase):
    IN_SCHOOL = (
        "school_visit",
        "follow_up_visit",
        "coaching_visit",
        "in_school_support",
        "core_visit",
        "core_assessment_visit",
        "baseline_ssa_visit",
        "school_visit_ssa_collection",
        "in_school_training",
    )

    def test_every_staff_school_mission_costs_one_visit_day(self):
        for activity_type in self.IN_SCHOOL:
            with self.subTest(activity_type=activity_type):
                cost = _cost(activityType=activity_type, districtType="primary")
                self.assertEqual(cost.amount, PRIMARY_STAFF_DAY)
                self.assertFalse(cost.cost_missing)

    def test_a_secondary_district_mission_carries_the_full_per_diem(self):
        for activity_type in self.IN_SCHOOL:
            with self.subTest(activity_type=activity_type):
                cost = _cost(activityType=activity_type, districtType="secondary")
                self.assertEqual(cost.amount, SECONDARY_STAFF_DAY)

    def test_an_unclassified_activity_still_reads_the_district(self):
        """The fallback used to add PRIMARY transport and lunch whatever the
        district, so secondary work was costed 95,000 short."""
        self.assertEqual(
            _cost(activityType="ssa_activity", districtType="secondary").amount,
            SECONDARY_STAFF_DAY,
        )


class GroupSessionsSharePriceTest(SimpleTestCase):
    GROUP = (
        "training",
        "in_school_training",  # priced as a visit — asserted separately
        "cluster_training",
        "cluster_training_ssa_collection",
        "core_training",
        "school_improvement_training",
        "programme_event",
    )

    def _group_total(self, participants: int, days: int) -> int:
        return (
            participants * days * RATES["group_training_participant_meal_cost_per_head"]
            + days * RATES["group_training_facilitation_fee"]
            + days * RATES["group_training_venue_cost"]
            + days * PRIMARY_STAFF_DAY
        )

    def test_every_group_training_costs_the_same_recipe(self):
        for activity_type in self.GROUP:
            if activity_type == "in_school_training":
                continue
            with self.subTest(activity_type=activity_type):
                cost = _cost(
                    activityType=activity_type,
                    districtType="primary",
                    expectedParticipants=20,
                )
                self.assertEqual(cost.amount, self._group_total(20, 1))
                self.assertFalse(cost.cost_missing)

    def test_a_conference_is_a_group_training(self):
        """Non-school programme work priced from its own six-key family at
        ten times the venue and double the facilitation."""
        self.assertEqual(
            _cost(
                activityType="programme_event",
                districtType="primary",
                expectedParticipants=40,
                days=3,
            ).amount,
            self._group_total(40, 3),
        )

    def test_a_group_session_without_a_headcount_cannot_be_funded(self):
        cost = _cost(activityType="cluster_training", districtType="primary")
        self.assertTrue(cost.cost_missing)
        self.assertIn("expectedParticipants", cost.missing_items)


class PartnerWorkSharesOneRateTest(SimpleTestCase):
    def test_partner_visits_and_in_school_trainings_share_the_visit_rate(self):
        for activity_type in ("school_visit", "in_school_training", "core_visit"):
            with self.subTest(activity_type=activity_type):
                cost = cost_for_activity(
                    {"activityType": activity_type, "deliveryType": "partner"}, RATES
                )
                self.assertEqual(cost.amount, RATES["partner_visit_lump_sum"])
                self.assertEqual(
                    [line.key for line in cost.lines], ["partner_visit_lump_sum"]
                )

    def test_special_project_partner_work_uses_the_same_rate(self):
        """`project_partner_lump_sum` held the same 40,000."""
        cost = cost_for_activity(
            {
                "activityType": "project_activity",
                "deliveryType": "partner",
                "projectId": "p1",
            },
            RATES,
        )
        self.assertEqual([line.key for line in cost.lines], ["partner_visit_lump_sum"])


class DistrictMeetingsAreCostedSeparatelyTest(SimpleTestCase):
    def test_a_field_event_is_priced_per_day_away(self):
        self.assertEqual(
            _cost(activityType="field_event", districtType="secondary", days=3).amount,
            3 * SECONDARY_STAFF_DAY,
        )

    def test_a_cluster_meeting_keeps_its_own_snack_rate(self):
        cost = _cost(
            activityType="cluster_meeting",
            districtType="primary",
            expectedParticipants=12,
        )
        self.assertEqual(
            cost.amount,
            12 * RATES["cluster_meeting_participant_meal_cost_per_head"]
            + RATES["group_training_venue_cost"]
            + PRIMARY_STAFF_DAY,
        )


class RetiredRatesStayRetiredTest(SimpleTestCase):
    def test_no_retired_rate_is_offered_or_read(self):
        self.assertTrue(DUPLICATE_COST_SETTING_KEYS <= RETIRED_COST_SETTING_KEYS)
        self.assertTrue(CANONICAL_RATE_KEYS.isdisjoint(DUPLICATE_COST_SETTING_KEYS))

    def test_the_engine_never_names_a_retired_rate(self):
        from pathlib import Path

        source = Path("apps/budget/costing.py").read_text(encoding="utf-8")
        for key in DUPLICATE_COST_SETTING_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(f'"{key}"', source)
