"""What a group training and a cluster meeting cost (owner, 2026-09-26).

"Cluster training should no longer be the cost. Fetch only the group
training participant meals, facilitation fee, venue fee, transport, lunch,
breakfast, dinner and accommodation — divided by the number of trainings
scheduled that day — and look at the district where the cluster is located:
primary or secondary. Fetch printing and photocopying as well."

"The cluster meeting should fetch participant snacks and venue and the
printing and photocopying cost and the per diem based on primary or
secondary districts, divided by the number of activities scheduled that
day. Everything should be fetched from the database."

The per-day division is the Daily Visit Batch's (apps/daily_visit_batches
tests pin the shares); these tests pin which lines a session carries, where
its district comes from, and that the preview names each line as the CD
Cost Catalogue does.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import SimpleTestCase, TestCase

from apps.budget.costing import cost_for_activity
from apps.budget.test_cost_recipe_consolidation import PAGES, RATES

PRIMARY_DAY = ["primary_transport_per_day", "lunch_per_day"]
SECONDARY_DAY = [
    "secondary_transport_per_day",
    "lunch_per_day",
    "secondary_breakfast_per_day",
    "secondary_overnight_dinner_per_day",
    "secondary_accommodation_per_night",
]
MATERIALS = ["printing_training_materials", "photocopying_training_materials"]


def _keys(**activity):
    cost = cost_for_activity(
        {"deliveryType": "staff", "expectedParticipants": 20, **activity}, RATES
    )
    return sorted(line.key for line in cost.lines)


class GroupSessionLinesTest(SimpleTestCase):
    def test_a_group_training_is_meals_fee_venue_materials_and_the_day(self):
        for district, day in (("primary", PRIMARY_DAY), ("secondary", SECONDARY_DAY)):
            with self.subTest(district=district):
                self.assertEqual(
                    _keys(
                        activityType="cluster_training", districtType=district, **PAGES
                    ),
                    sorted(
                        [
                            "group_training_meals",
                            "group_training_facilitation_fee",
                            "group_training_venue_cost",
                            *MATERIALS,
                            *day,
                        ]
                    ),
                )

    def test_a_cluster_meeting_is_snacks_venue_materials_and_the_day(self):
        for district, day in (("primary", PRIMARY_DAY), ("secondary", SECONDARY_DAY)):
            with self.subTest(district=district):
                self.assertEqual(
                    _keys(
                        activityType="cluster_meeting", districtType=district, **PAGES
                    ),
                    sorted(
                        [
                            "cluster_meetings_trainings_meals",
                            "group_training_venue_cost",
                            *MATERIALS,
                            *day,
                        ]
                    ),
                )

    def test_no_per_session_rate_is_charged_on_top(self):
        for activity_type in ("cluster_training", "cluster_meeting"):
            with self.subTest(activity_type=activity_type):
                keys = _keys(activityType=activity_type, districtType="primary")
                self.assertNotIn("cluster_meetings_trainings", keys)
                self.assertNotIn("cluster_meeting", keys)


class ClusterSessionDistrictTest(TestCase):
    """A cluster session priced outside the day batch reads the cluster's
    district for its officer, as the batch does."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model

        from apps.accounts.models import StaffProfile
        from apps.clusters.models import Cluster
        from apps.geography.models import District, Region

        region = Region.objects.create(name="GSL Region")
        cls.home = District.objects.create(name="Home District", region=region)
        cls.away = District.objects.create(name="Away District", region=region)
        user = get_user_model().objects.create(
            email="gsl@edify.test",
            name="GSL Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.officer = StaffProfile.objects.create(
            user=user, title="CCEO", primary_district_id=cls.home.id
        )
        cls.home_cluster = Cluster.objects.create(
            name="Home Cluster", region=region, district=cls.home
        )
        cls.away_cluster = Cluster.objects.create(
            name="Away Cluster", region=region, district=cls.away
        )

    def _district_type(self, cluster):
        from apps.activities.models import Activity
        from apps.activities.services import _costing_input

        activity = Activity(
            activity_type="cluster_training",
            cluster=cluster,
            delivery_type="staff",
            responsible_staff_id=self.officer.id,
            planned_date=date.today() + timedelta(days=7),
        )
        return _costing_input(activity, {})["districtType"]

    def test_the_officers_home_district_is_primary(self):
        self.assertEqual(self._district_type(self.home_cluster), "primary")

    def test_any_other_district_is_secondary(self):
        self.assertEqual(self._district_type(self.away_cluster), "secondary")


class PreviewNamesLinesFromTheCatalogueTest(TestCase):
    def test_a_line_carries_the_catalogues_label(self):
        """The CD renames a rate on the Cost Catalogue; the preview says so."""
        from apps.budget.costing_service import active_catalogue, preview
        from apps.budget.models import CostSetting

        catalogue = active_catalogue()
        self.assertIsNotNone(catalogue)
        CostSetting.objects.filter(catalogue=catalogue, key="lunch_per_day").update(
            label="Officer's lunch"
        )
        CostSetting.objects.filter(
            catalogue=catalogue, key="cluster_meetings_trainings_meals"
        ).update(label="Participant snacks")
        result = preview(
            {
                "activityType": "cluster_meeting",
                "deliveryType": "staff",
                "districtType": "primary",
                "expectedParticipants": 10,
            },
            minimum=True,
        )
        labels = {line["key"]: line["label"] for line in result["lines"]}
        self.assertEqual(labels["lunch_per_day"], "Officer's lunch")
        self.assertEqual(
            labels["cluster_meetings_trainings_meals"], "Participant snacks"
        )


class TheSessionDrawerTest(SimpleTestCase):
    """The group training and cluster meeting drawer (owner, 2026-09-26):
    training names without " · priority need", the recommended trainings and
    interventions listed with a Show all that reaches the rest (scheduling
    is not restricted), and a cost preview that follows every field."""

    def setUp(self):
        from pathlib import Path

        from django.conf import settings

        root = Path(settings.BASE_DIR)
        self.drawer = (
            root / "templates/partials/planning/schedule_cluster_drawer.html"
        ).read_text()
        self.view = (root / "apps/frontend/views/planning_views.py").read_text()

    def test_training_names_carry_no_priority_suffix(self):
        self.assertNotIn("f\"{option['label']} · priority need\"", self.view)
        self.assertNotIn('option["label"] = (', self.view)
        self.assertNotIn("priority need", self.drawer)

    def test_the_lists_show_the_recommended_with_a_show_all(self):
        self.assertIn('id="training_show_all"', self.drawer)
        self.assertIn("activity.addressesPriority", self.drawer)
        self.assertIn('id="meeting_show_all"', self.drawer)
        self.assertIn("meeting_intervention_options_json", self.drawer)
        self.assertIn('"recommended": code in ssa_need.priorities', self.view)
        # No "· avg x/10" on the meeting's options.
        self.assertNotIn("/10{% endif %}</option>", self.drawer)

    def test_the_cost_preview_follows_every_field(self):
        preview = self.drawer.split('id="cluster-cost-preview"', 1)[1].split(">", 1)[0]
        self.assertIn("change from:#cluster-planner-form", preview)
        self.assertIn('hx-include="#cluster-planner-form"', preview)

    def test_the_invited_count_reads_the_list_not_the_clicked_box(self):
        """Called from a checkbox's @change, Alpine's $el is that checkbox, so
        the count read through it was 0 after every tick (owner, 2026-09-26:
        "the numbers of invited schools or participants don't adjust")."""
        self.assertIn("this.$refs.invitedList.querySelectorAll(", self.drawer)
        self.assertIn('x-ref="invitedList"', self.drawer)
        self.assertNotIn(
            "this.$el.querySelectorAll('input[name=invited_school_ids]')", self.drawer
        )
        # Select all / Clear all set the boxes in script: the preview is told.
        self.assertIn("invitedList.dispatchEvent(new Event('change'", self.drawer)

    def test_the_preview_follows_typing_in_the_number_fields(self):
        preview = self.drawer.split('id="cluster-cost-preview"', 1)[1].split(">", 1)[0]
        self.assertIn(
            "input[target.type=='number'] from:#cluster-planner-form", preview
        )

    def test_the_priorities_are_not_listed_twice(self):
        self.assertNotIn("The cluster's SSA priorities:", self.drawer)
