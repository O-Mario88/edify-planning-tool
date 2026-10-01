"""Every plan fetches its own rows from the Cost Catalogue, and every row is
fetched by some plan.

Owner, 2026-10-01, after the Cost Catalogue audit: "check again and make sure
every plan is fetching the right cost". A scheduled activity is priced by its
catalogue item's costing profile, so the table below is the whole answer: for
each profile, the catalogue rows a staff-run and a partner-run activity fetch.
A profile cannot be added without a line here, and a row cannot sit on Cost
Settings with no plan that reads it. That is how Cluster Training and Cluster
Meeting came to be two editable rows at UGX 0 that priced nothing.
"""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from apps.budget.costing import cost_for_activity
from apps.budget.costing_service import _COSTING_PROFILES, _profiled_input
from apps.budget.reference import CANONICAL_RATE_KEYS

CARD = dict.fromkeys(CANONICAL_RATE_KEYS, 1_000)
STATED = {
    "expectedParticipants": 20,
    "printingPages": 10,
    "photocopyPages": 5,
    "photocopyCopies": 20,
}

PRIMARY_DAY = ["primary_transport_per_day", "lunch_per_day"]
SECONDARY_DAY = [
    "secondary_transport_per_day",
    "lunch_per_day",
    "secondary_breakfast_per_day",
    "secondary_overnight_dinner_per_day",
    "secondary_accommodation_per_night",
]
ROOM = ["group_training_facilitation_fee", "group_training_venue_cost"]
MATERIALS = ["printing_training_materials", "photocopying_training_materials"]
DAY = "<the staff day>"

# profile: (what a staff-run activity fetches, what a partner-run one fetches).
# DAY stands for the day away, primary or secondary by the district.
VISIT_DAY = ([DAY], ["client_partner_visit"])
GROUP_TRAINING = (
    ["group_training_meals", *ROOM, *MATERIALS, DAY],
    # A partner-run group training is the same session, the day included.
    ["group_training_meals", *ROOM, *MATERIALS, DAY],
)
EXPECTED: dict[str, tuple[list[str], list[str]]] = {
    "STAFF_SCHOOL_VISIT": VISIT_DAY,
    "IN_SCHOOL_TRAINING": VISIT_DAY,
    "SSA_DATA_GATHERING": VISIT_DAY,
    "CORE_SCHOOL_VISIT": ([DAY], ["core_partner_visit"]),
    "ONETEST": (["onetest", DAY], ["onetest"]),
    "CLUSTER_MEETING": (
        # Nobody facilitates a meeting, and its snacks are the meeting's own
        # row, never a training's meals.
        [
            "cluster_meetings_trainings_meals",
            "group_training_venue_cost",
            *MATERIALS,
            DAY,
        ],
        ["cluster_meetings_trainings_meals", "group_training_venue_cost", *MATERIALS],
    ),
    "CLUSTER_TRAINING": GROUP_TRAINING,
    "ONLINE_TRAINING": GROUP_TRAINING,
    "GROUP_YOUTH_CAMP": GROUP_TRAINING,
    "TOT_TRAINING": (
        ["tot_trainings", "tot_trainings_meals", *ROOM, *MATERIALS, DAY],
        ["tot_trainings", "tot_trainings_meals", *ROOM, *MATERIALS, DAY],
    ),
    "PROGRAMME_EVENT": ([*ROOM, *MATERIALS, DAY], [*ROOM, *MATERIALS]),
    "STUDENT_CONFERENCE": (
        ["student_conference", *ROOM, *MATERIALS, DAY],
        ["student_conference", *ROOM, *MATERIALS],
    ),
    "PROPRIETOR_CONFERENCE": (
        ["proprietor_conference", *ROOM, *MATERIALS, DAY],
        ["proprietor_conference", *ROOM, *MATERIALS],
    ),
    "ADMIN_PARTNER_MEETING": (["partner_meetings"], ["partner_meetings"]),
    "FIELD_TRAVEL": ([DAY], [DAY]),
}


def _fetched(profile, delivery, district, **extra):
    cost = cost_for_activity(
        _profiled_input(
            {
                **STATED,
                "costingProfile": profile,
                "deliveryType": delivery,
                "districtType": district,
                **extra,
            }
        ),
        CARD,
    )
    assert not cost.cost_missing, (profile, cost.missing_items)
    return [line.key for line in cost.lines]


def _spelled_out(keys, district):
    day = PRIMARY_DAY if district == "primary" else SECONDARY_DAY
    out = []
    for key in keys:
        out.extend(day if key == DAY else [key])
    return out


class EveryProfileFetchesItsRowsTest(SimpleTestCase):
    def test_every_costing_profile_is_in_the_table(self):
        self.assertEqual(set(EXPECTED), set(_COSTING_PROFILES))

    def test_each_profile_fetches_exactly_its_rows(self):
        for profile, (staff, partner) in EXPECTED.items():
            for delivery, keys in (("staff", staff), ("partner", partner)):
                for district in ("primary", "secondary"):
                    with self.subTest(
                        profile=profile, delivery=delivery, district=district
                    ):
                        self.assertEqual(
                            _fetched(profile, delivery, district),
                            _spelled_out(keys, district),
                        )

    def test_every_catalogue_row_is_fetched_by_some_plan(self):
        """A row no plan reads is an editable rate that prices nothing."""
        fetched = {
            key
            for profile in EXPECTED
            for delivery in ("staff", "partner")
            for district in ("primary", "secondary")
            for key in _fetched(profile, delivery, district)
        }
        self.assertEqual(fetched, CANONICAL_RATE_KEYS)

    def test_an_in_school_training_is_costed_as_a_normal_visit(self):
        """Owner, 2026-10-01: "in-school training ... should be costed as a
        normal visit whether scheduled by staff or partner is assigned to do
        in-school training. if it is partner it should carry the same partner
        school visit cost and if it is staff it should carry staff visit."
        """
        for district in ("primary", "secondary"):
            with self.subTest(district=district):
                self.assertEqual(
                    _fetched("IN_SCHOOL_TRAINING", "staff", district),
                    _fetched("STAFF_SCHOOL_VISIT", "staff", district),
                )
                self.assertEqual(
                    _fetched("IN_SCHOOL_TRAINING", "partner", district),
                    _fetched("STAFF_SCHOOL_VISIT", "partner", district),
                )
        self.assertEqual(
            _fetched("IN_SCHOOL_TRAINING", "partner", "primary"),
            ["client_partner_visit"],
        )

    def test_an_in_school_training_costs_the_same_at_every_kind_of_school(self):
        """Owner, 2026-10-01: "in-school training visit for core is the same
        as the in-school training visit for client schools, core trained and
        core graduate". Nothing about the school reaches the recipe, and work
        marked core fetches the same rows."""
        for delivery in ("staff", "partner"):
            plain = cost_for_activity(
                {
                    "activityType": "in_school_training",
                    "deliveryType": delivery,
                    "districtType": "primary",
                },
                CARD,
            )
            at_core = cost_for_activity(
                {
                    "activityType": "in_school_training",
                    "deliveryType": delivery,
                    "districtType": "primary",
                    "costingKind": "core",
                },
                CARD,
            )
            with self.subTest(delivery=delivery):
                self.assertEqual(
                    [line.key for line in at_core.lines],
                    [line.key for line in plain.lines],
                )
                self.assertNotIn(
                    "core_partner_visit", [line.key for line in at_core.lines]
                )

    def test_only_a_core_visit_fetches_the_core_partner_rate(self):
        fetching = sorted(
            profile
            for profile in EXPECTED
            if "core_partner_visit" in _fetched(profile, "partner", "primary")
        )
        self.assertEqual(fetching, ["CORE_SCHOOL_VISIT"])


class EveryCatalogueActivityHasARecipeTest(TestCase):
    def test_every_catalogue_activity_is_priced_by_a_known_profile(self):
        from apps.activity_catalogue.models import ActivityCatalogueItem

        unknown = sorted(
            f"{name} ({profile})"
            for name, profile in ActivityCatalogueItem.objects.values_list(
                "display_name", "costing_profile"
            )
            if profile not in EXPECTED
        )
        self.assertEqual(unknown, [])
