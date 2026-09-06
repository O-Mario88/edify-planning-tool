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


class LifecycleDoorTest(TestCase):
    """The lifecycle form on the catalogue page posts a status change.

    The 2026-09-06 UI pass found every such post raising: the transition
    service took a row lock outside a transaction."""

    def test_the_country_director_can_retire_an_activity_through_the_page(self):
        from django.test import Client

        from apps.accounts.models import User

        cd = User.objects.create(
            id="cd_life",
            email="cd.life@edify.org",
            name="CD Life",
            roles=["CountryDirector"],
            active_role="CountryDirector",
        )
        item = create_catalogue_item(
            {
                "name": "Lifecycle Door Visit",
                "kind": "school",
                "activityType": "school_visit",
                "deliveryMethod": "school_visit",
                "costingProfile": "STAFF_SCHOOL_VISIT",
                "reason": "door test",
            },
            actor_id=cd.id,
        )
        client = Client()
        client.force_login(cd)
        response = client.post(
            f"/settings/activity-catalogue/{item.id}/lifecycle",
            {"status": "inactive", "reason": "no longer offered"},
        )
        self.assertEqual(response.status_code, 302, response.content[:200])
        item.refresh_from_db()
        self.assertEqual(item.status, "inactive")
        self.assertEqual(item.versions.count(), 2)
