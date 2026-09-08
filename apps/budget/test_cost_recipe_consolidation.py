"""One recipe per shape of work, priced from the 2026-09-06 Country Cost
Catalogue — no rate is a second name for another.

Owner, 2026-09-06: "These are the list of activities to put in the cost
catalog. remove the ones you have now." Twenty-two rows: per-activity rates
(Client/Core Staff Visit, SSA Support, OneTest), partner rates (Client/Core
Partner Visit, Partner Meetings), group-session components (Cluster
Meetings/Trainings, TOT trainings and their meals, the conferences, printing,
photocopying, venue, facilitation) and travel per-diems (transport by
district, lunch, breakfast, dinner, accommodation).

Before that (owner, 2026-09-04): "all in-school trainings have the same cost as the school

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
    "client_staff_visit": 10_000,
    "core_staff_visit": 15_000,
    "ssa_support": 7_000,
    "onetest": 9_000,
    "client_partner_visit": 40_000,
    "core_partner_visit": 45_000,
    "partner_meetings": 30_000,
    "cluster_meetings_trainings": 20_000,
    "tot_trainings": 25_000,
    "tot_trainings_meals": 5_000,
    "student_conference": 60_000,
    "proprietor_conference": 70_000,
    "printing_training_materials": 3_000,
    "photocopying_training_materials": 2_000,
    "group_training_venue_cost": 30_000,
    "group_training_facilitation_fee": 50_000,
    "primary_transport_per_day": 50_000,
    "secondary_transport_per_day": 80_000,
    "lunch_per_day": 12_000,
    "secondary_breakfast_per_day": 8_000,
    "secondary_overnight_dinner_per_day": 12_000,
    "secondary_accommodation_per_night": 40_000,
}
# Transport + lunch; the secondary district adds dinner, a night and breakfast.
PRIMARY_STAFF_DAY = 62_000
SECONDARY_STAFF_DAY = 152_000
MATERIALS = (
    RATES["printing_training_materials"] + RATES["photocopying_training_materials"]
)
ROOM = RATES["group_training_facilitation_fee"] + RATES["group_training_venue_cost"]


def _cost(**activity):
    return cost_for_activity({"deliveryType": "staff", **activity}, RATES)


def _keys(cost):
    return [line.key for line in cost.lines]


class SchoolMissionsSharePriceTest(SimpleTestCase):
    """Every staff school mission is one visit day plus the mission's rate."""

    CLIENT = (
        "school_visit",
        "follow_up_visit",
        "coaching_visit",
        "in_school_support",
        "in_school_training",
    )
    CORE = ("core_visit", "core_assessment_visit")
    SSA = ("baseline_ssa_visit", "school_visit_ssa_collection", "ssa_activity")

    def test_a_client_school_mission_is_a_visit_day_plus_the_client_rate(self):
        for activity_type in self.CLIENT:
            with self.subTest(activity_type=activity_type):
                cost = _cost(activityType=activity_type, districtType="primary")
                self.assertEqual(
                    cost.amount, PRIMARY_STAFF_DAY + RATES["client_staff_visit"]
                )
                self.assertIn("client_staff_visit", _keys(cost))
                self.assertFalse(cost.cost_missing)

    def test_a_core_school_mission_carries_the_core_rate(self):
        for activity_type in self.CORE:
            with self.subTest(activity_type=activity_type):
                cost = _cost(activityType=activity_type, districtType="primary")
                self.assertEqual(
                    cost.amount, PRIMARY_STAFF_DAY + RATES["core_staff_visit"]
                )
        by_profile = _cost(
            activityType="school_visit", districtType="primary", costingKind="core"
        )
        self.assertIn("core_staff_visit", _keys(by_profile))
        self.assertNotIn("client_staff_visit", _keys(by_profile))

    def test_ssa_work_carries_the_ssa_support_rate(self):
        for activity_type in self.SSA:
            with self.subTest(activity_type=activity_type):
                cost = _cost(activityType=activity_type, districtType="primary")
                self.assertEqual(cost.amount, PRIMARY_STAFF_DAY + RATES["ssa_support"])

    def test_a_onetest_visit_carries_the_onetest_rate(self):
        cost = _cost(
            activityType="school_visit", districtType="primary", costingKind="onetest"
        )
        self.assertEqual(cost.amount, PRIMARY_STAFF_DAY + RATES["onetest"])

    def test_a_secondary_district_mission_carries_the_full_per_diem(self):
        for activity_type in self.CLIENT:
            with self.subTest(activity_type=activity_type):
                cost = _cost(activityType=activity_type, districtType="secondary")
                self.assertEqual(
                    cost.amount, SECONDARY_STAFF_DAY + RATES["client_staff_visit"]
                )
                self.assertEqual(
                    sorted(k for k in _keys(cost) if k != "client_staff_visit"),
                    sorted(
                        [
                            "secondary_transport_per_day",
                            "lunch_per_day",
                            "secondary_accommodation_per_night",
                            "secondary_overnight_dinner_per_day",
                            "secondary_breakfast_per_day",
                        ]
                    ),
                )

    def test_an_unclassified_activity_still_reads_the_district(self):
        """The fallback used to add PRIMARY transport and lunch whatever the
        district, so secondary work was costed 95,000 short."""
        cost = _cost(activityType="story_gathering_visit", districtType="secondary")
        self.assertEqual(cost.amount, SECONDARY_STAFF_DAY + RATES["client_staff_visit"])

    def test_the_lunch_row_is_one_row(self):
        """The owner's list has one Lunch, not one per district."""
        primary = _cost(activityType="school_visit", districtType="primary")
        secondary = _cost(activityType="school_visit", districtType="secondary")
        self.assertIn("lunch_per_day", _keys(primary))
        self.assertIn("lunch_per_day", _keys(secondary))
        for cost in (primary, secondary):
            self.assertNotIn("secondary_lunch_per_day", _keys(cost))
            self.assertNotIn("secondary_incidentals_per_day", _keys(cost))


class GroupSessionsSharePriceTest(SimpleTestCase):
    GROUP = (
        "training",
        "core_training",
        "school_improvement_training",
    )

    def _session(self, days: int, rate: int = 0, meals: int = 0) -> int:
        return rate + meals + days * (ROOM + MATERIALS) + days * PRIMARY_STAFF_DAY

    def test_every_group_training_costs_the_same_recipe(self):
        """Venue and facilitation per day, printing and photocopying, and the
        staff day. Only a TOT training feeds its participants."""
        for activity_type in self.GROUP:
            with self.subTest(activity_type=activity_type):
                cost = _cost(
                    activityType=activity_type,
                    districtType="primary",
                    expectedParticipants=20,
                )
                self.assertEqual(cost.amount, self._session(1))
                self.assertNotIn("tot_trainings_meals", _keys(cost))
                self.assertFalse(cost.cost_missing)

    def test_a_cluster_training_carries_the_cluster_rate(self):
        for activity_type in ("cluster_training", "cluster_training_ssa_collection"):
            with self.subTest(activity_type=activity_type):
                cost = _cost(
                    activityType=activity_type,
                    districtType="primary",
                    expectedParticipants=20,
                )
                self.assertEqual(
                    cost.amount, self._session(1, RATES["cluster_meetings_trainings"])
                )

    def test_a_tot_training_feeds_its_participants(self):
        cost = _cost(
            activityType="training",
            districtType="primary",
            costingKind="tot",
            expectedParticipants=20,
            days=2,
        )
        self.assertEqual(
            cost.amount,
            self._session(
                2, RATES["tot_trainings"], 20 * 2 * RATES["tot_trainings_meals"]
            ),
        )

    def test_a_tot_training_without_a_headcount_cannot_be_funded(self):
        cost = _cost(activityType="training", districtType="primary", costingKind="tot")
        self.assertTrue(cost.cost_missing)
        self.assertIn("expectedParticipants", cost.missing_items)

    def test_a_conference_is_a_group_session_with_its_own_rate(self):
        plain = _cost(activityType="programme_event", districtType="primary", days=3)
        self.assertEqual(plain.amount, self._session(3))
        student = _cost(
            activityType="programme_event",
            districtType="primary",
            days=3,
            costingKind="student_conference",
        )
        self.assertEqual(student.amount, self._session(3, RATES["student_conference"]))
        proprietor = _cost(
            activityType="programme_event",
            districtType="primary",
            costingKind="proprietor_conference",
        )
        self.assertEqual(
            proprietor.amount, self._session(1, RATES["proprietor_conference"])
        )


class PartnerWorkSharesOneRateTest(SimpleTestCase):
    def test_partner_visits_and_in_school_trainings_share_the_partner_visit_rate(self):
        for activity_type in ("school_visit", "in_school_training"):
            with self.subTest(activity_type=activity_type):
                cost = cost_for_activity(
                    {"activityType": activity_type, "deliveryType": "partner"}, RATES
                )
                self.assertEqual(cost.amount, RATES["client_partner_visit"])
                self.assertEqual(_keys(cost), ["client_partner_visit"])

    def test_partner_work_at_a_core_school_carries_the_core_partner_rate(self):
        cost = cost_for_activity(
            {"activityType": "core_visit", "deliveryType": "partner"}, RATES
        )
        self.assertEqual(_keys(cost), ["core_partner_visit"])

    def test_partner_meetings_and_partner_run_trainings_carry_the_meetings_rate(self):
        for activity in (
            {
                "activityType": "project_activity",
                "deliveryType": "partner",
                "projectId": "p1",
            },
            {"activityType": "partner_activity", "deliveryType": "staff"},
            {
                "activityType": "training",
                "deliveryType": "partner",
                "expectedParticipants": 20,
            },
        ):
            with self.subTest(activity=activity):
                cost = cost_for_activity(activity, RATES)
                self.assertEqual(_keys(cost), ["partner_meetings"])
                self.assertEqual(cost.amount, RATES["partner_meetings"])


class DistrictMeetingsAreCostedSeparatelyTest(SimpleTestCase):
    def test_a_field_event_is_priced_per_day_away(self):
        self.assertEqual(
            _cost(activityType="field_event", districtType="secondary", days=3).amount,
            3 * SECONDARY_STAFF_DAY,
        )

    def test_a_cluster_meeting_is_the_room_the_materials_and_the_staff_day(self):
        cost = _cost(
            activityType="cluster_meeting",
            districtType="primary",
            expectedParticipants=12,
        )
        self.assertEqual(
            cost.amount,
            RATES["cluster_meetings_trainings"]
            + RATES["group_training_venue_cost"]
            + MATERIALS
            + PRIMARY_STAFF_DAY,
        )
        self.assertNotIn("group_training_facilitation_fee", _keys(cost))


class AnOlderCardStillPricesTest(SimpleTestCase):
    """A rate card seeded before the 2026-09-06 list — a saved snapshot's, a
    test's — prices through the renamed keys and adds none of the new rates."""

    OLD = {
        "primary_transport_per_day": 50_000,
        "primary_lunch_per_day": 12_000,
        "secondary_transport_per_day": 80_000,
        "secondary_lunch_per_day": 12_000,
        "secondary_accommodation_per_night": 40_000,
        "secondary_overnight_dinner_per_day": 12_000,
        "secondary_breakfast_per_day": 8_000,
        "group_training_facilitation_fee": 50_000,
        "group_training_venue_cost": 30_000,
        "partner_visit_lump_sum": 40_000,
    }

    def test_a_visit_day_reads_lunch_from_the_old_row(self):
        cost = cost_for_activity(
            {
                "activityType": "school_visit",
                "deliveryType": "staff",
                "districtType": "secondary",
            },
            self.OLD,
        )
        self.assertEqual(cost.amount, SECONDARY_STAFF_DAY)
        self.assertFalse(cost.cost_missing)

    def test_partner_work_reads_the_old_lump_sum(self):
        cost = cost_for_activity(
            {"activityType": "school_visit", "deliveryType": "partner"}, self.OLD
        )
        self.assertEqual(cost.amount, 40_000)
        self.assertEqual(_keys(cost), ["client_partner_visit"])


class RetiredRatesStayRetiredTest(SimpleTestCase):
    def test_no_retired_rate_is_offered_or_read(self):
        self.assertTrue(DUPLICATE_COST_SETTING_KEYS <= RETIRED_COST_SETTING_KEYS)
        self.assertTrue(CANONICAL_RATE_KEYS.isdisjoint(RETIRED_COST_SETTING_KEYS))

    def test_the_engine_never_names_a_retired_rate(self):
        from pathlib import Path

        source = Path("apps/budget/costing.py").read_text(encoding="utf-8")
        for key in RETIRED_COST_SETTING_KEYS:
            with self.subTest(key=key):
                self.assertNotIn(f'"{key}"', source)
