"""The purpose a planner chooses owns the workflow; the SSA pick owns provenance.

``apps/frontend/test_schedule_drawer_purpose.py`` already states the rule:
"The purpose chooses the workflow; the visible SSA recommendation
disambiguates the governed catalogue row that supplies provenance." The
scheduling drawer did not honour it.

``templates/partials/planning/schedule_drawer.html`` writes ``catalogue_item_id``
exactly once, from the SSA-ranked top recommendation, as a plain hidden input.
Unlike the Core drawers -- which rebind their catalogue choice on ``@change``
-- it never rebinds when Purpose of Visit changes. The server then skips its
purpose-to-catalogue derivation (that branch only runs when no catalogue item
was posted), and ``apps.activities.services.create`` takes the activity type
from ``catalogue_item.workflow_kind``.

So on a school whose top SSA recommendation was an in-school training, a
planner choosing "Donor Visit" created an Activity of type
``in_school_training`` -- costed as a training, reported as a training, and
counted against training targets. The planner's explicit choice lost to a
hidden field they never saw.

The view now reconciles the two: when the pinned catalogue item disagrees with
the purpose, the purpose wins and the costing is re-derived from it.
"""

from __future__ import annotations

from django.test import Client

from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.planning.test_standard_support_scheduling import (
    StandardSupportBase,
    _schedulable_date,
)


class PurposeOwnsTheWorkflowTest(StandardSupportBase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.user)

    def _post(self, **extra):
        payload = {
            "school_id": self.school.school_id,
            "scheduled_date": _schedulable_date().isoformat(),
            "activity_purpose_text": "Show the donor the new classroom block",
            "expected_outcome": "Donor sees the work",
            **extra,
        }
        return self.client.post(
            "/planning/schedule-action", payload, HTTP_HX_REQUEST="true"
        )

    def test_a_stale_ssa_pin_does_not_override_the_chosen_purpose(self):
        """The defect, end to end: pin a training, choose a donor visit."""
        pinned = self.item("STANDARD_IN_SCHOOL_TRAINING")
        self.assertEqual(pinned.workflow_kind, "in_school_training")

        response = self._post(
            purpose_of_visit="donor_visit",
            catalogue_item_id=pinned.id,
            recommendation_reason="SSA recommends in-school training.",
        )

        self.assertIn(response.status_code, (200, 204))
        activity = Activity.objects.order_by("-created_at").first()
        self.assertIsNotNone(activity, "No activity was created.")
        self.assertEqual(
            activity.activity_type,
            "donor_visit",
            "The stale SSA catalogue pin overrode the planner's chosen "
            "purpose, so a donor visit was scheduled and costed as an "
            "in-school training.",
        )
        self.assertNotEqual(activity.catalogue_item_id, pinned.id)
        costing = ActivityCatalogueItem.objects.get(id=activity.catalogue_item_id)
        self.assertEqual(costing.workflow_kind, "donor_visit")
        # The service supplies its own default reason for standard support;
        # what must not survive is the SSA reason for the item we replaced.
        self.assertNotIn(
            "in-school training",
            (activity.recommendation_reason or "").lower(),
            "The activity kept a recommendation reason describing the "
            "catalogue item it no longer uses.",
        )

    def test_a_pin_that_agrees_with_the_purpose_is_left_alone(self):
        """The control: reconciliation must not churn a correct pin, or the
        test above would pass with the pin simply always discarded."""
        pinned = self.item("EDTECH_FOUNDATIONS")

        response = self._post(
            purpose_of_visit="in_school_training",
            catalogue_item_id=pinned.id,
            focus_intervention="learning_environment",
            recommendation_reason="SSA recommends in-school training.",
            override_reason="Authorized priority training selection.",
            teachers_per_school="4",
            expected_participants="4",
        )

        self.assertIn(response.status_code, (200, 204))
        activity = Activity.objects.filter(activity_type="in_school_training").first()
        self.assertIsNotNone(activity)
        self.assertEqual(activity.activity_type, "in_school_training")
        self.assertEqual(activity.training_course_id, pinned.id)
        self.assertEqual(
            activity.catalogue_item.stable_code,
            "STANDARD_IN_SCHOOL_TRAINING",
        )
        self.assertEqual(activity.focus_intervention, "learning_environment")
        self.assertEqual(
            activity.recommendation_reason,
            "SSA recommends in-school training.",
            "A matching priority activity must keep the governed SSA provenance.",
        )
