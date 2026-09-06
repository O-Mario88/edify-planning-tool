"""The Country Director adds an activity as school work or non-school work
(owner, 2026-09-06), and it behaves like a governed catalogue item."""

from __future__ import annotations

from django.test import TestCase

from apps.activity_catalogue.authoring import create_catalogue_item
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.core.exceptions import BadRequest


class CreateCatalogueItemTest(TestCase):
    def _create(self, **overrides):
        data = {
            "name": "OneTest Diagnostic Visit",
            "kind": "school",
            "activityType": "school_visit",
            "deliveryMethod": "school_visit",
            "costingProfile": "ONETEST",
            "reason": "OneTest visits are costed on their own rate.",
        }
        data.update(overrides)
        return create_catalogue_item(data, actor_id="cd_1")

    def test_a_school_activity_is_a_governed_item_with_a_version_and_a_rule(self):
        item = self._create()
        self.assertEqual(item.stable_code, "ONETEST_DIAGNOSTIC_VISIT")
        self.assertEqual(item.status, "active")
        self.assertEqual(item.workflow_kind, "school_visit")
        self.assertEqual(item.costing_profile, "ONETEST")
        self.assertTrue(item.individual_school_allowed)
        self.assertTrue(item.requires_school)
        self.assertFalse(item.non_school_allowed)
        self.assertEqual(item.evidence_profile, "SCHOOL_VISIT_FORM")
        self.assertEqual(item.versions.count(), 1)
        self.assertIsNotNone(item.eligibility_rule)
        self.assertTrue(item.aliases.exists())

    def test_a_non_school_activity_is_a_programme_line_not_a_school_visit(self):
        item = self._create(
            name="Proprietor Conference 2027",
            kind="non_school",
            activityType="programme_event",
            deliveryMethod="group",
            costingProfile="PROPRIETOR_CONFERENCE",
            participantCounts=True,
            multiDay=True,
        )
        self.assertEqual(item.workflow_kind, "programme_event")
        self.assertTrue(item.non_school_allowed)
        self.assertFalse(item.individual_school_allowed)
        self.assertFalse(item.requires_school)
        self.assertTrue(item.multi_day_allowed)
        self.assertTrue(item.requires_participant_counts)
        self.assertEqual(item.evidence_profile, "TRAINING_ATTENDANCE")

    def test_the_same_name_twice_gets_a_distinct_code_or_is_refused(self):
        self._create()
        with self.assertRaises(BadRequest):
            self._create()

    def test_kind_type_delivery_recipe_and_reason_are_required(self):
        for bad in (
            {"kind": "somewhere"},
            {"activityType": "nope"},
            {"deliveryMethod": "cluster_training", "activityType": "school_visit"},
            {"costingProfile": "NOPE"},
            {"reason": ""},
            {"name": ""},
        ):
            with self.subTest(bad=bad), self.assertRaises(BadRequest):
                self._create(**bad)
        self.assertFalse(ActivityCatalogueItem.objects.filter(display_name="OneTest Diagnostic Visit").exists())

    def test_an_intervention_gives_the_item_a_primary_mapping(self):
        item = self._create(name="Numeracy Support Visit", intervention="christlike_behaviour")
        mapping = item.intervention_mappings.get(is_primary=True)
        self.assertEqual(mapping.intervention, "christlike_behaviour")
