"""Regression tests for deployment-blocking workflow-health predicates."""

from django.test import TestCase

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.system_health.services import missing_cost_lines_count


class MissingCostLinesContractTest(TestCase):
    def _activity(self, *, cost: int) -> Activity:
        return Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            fy="FY26",
            quarter="Q1",
            est_cost_cents=cost,
        )

    def test_zero_cost_scheduled_work_does_not_require_a_budget_line(self):
        self._activity(cost=0)

        self.assertEqual(missing_cost_lines_count(), 0)

    def test_cost_bearing_scheduled_work_without_lines_blocks(self):
        activity = self._activity(cost=25_000)

        self.assertEqual(missing_cost_lines_count(), 1)

        ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=25_000,
            amount=25_000,
        )
        self.assertEqual(missing_cost_lines_count(), 0)


class WorkPricedLaterIsNotReportedTest(TestCase):
    """Health checks count what someone can correct, not work that the
    workflow prices, pools or clears at a later step by design (2026-09-13
    ecosystem audit)."""

    def test_a_visit_request_is_priced_when_its_owner_approves_it(self):
        Activity.objects.create(
            activity_type="school_visit",
            status="awaiting_owner_approval",
            fy="FY26",
            quarter="Q1",
            est_cost_cents=25_000,
        )
        self.assertEqual(missing_cost_lines_count(), 0)

    def test_an_unpriced_visit_request_is_neither_executed_nor_cleared(self):
        from apps.activities.closure_services import ClosureEligibilityService
        from apps.system_health.services import _workflow_issues

        request = Activity.objects.create(
            activity_type="school_visit", status="awaiting_owner_approval"
        )
        checklist, blockers = ClosureEligibilityService.evaluate(request)
        self.assertFalse(checklist.activity_executed)
        self.assertIn("Activity not executed", [b.blocking_reason for b in blockers])
        self.assertEqual(_workflow_issues()["accountsClearanceBeforeIa"], 0)

    def test_only_a_dated_live_plan_can_be_missing_its_day_batch(self):
        from apps.system_health.services import _workflow_issues

        school = _school()
        for status, planned_date in (
            ("planned", None),
            ("awaiting_owner_approval", "2026-08-20"),
            ("completed", "2026-03-02"),
        ):
            Activity.objects.create(
                activity_type="school_visit",
                delivery_type="staff",
                school=school,
                status=status,
                planned_date=planned_date,
            )
        self.assertEqual(_workflow_issues()["scheduledVisitsMissingBatch"], 0)
        Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            school=school,
            status="scheduled",
            planned_date="2026-08-21",
        )
        self.assertEqual(_workflow_issues()["scheduledVisitsMissingBatch"], 1)


class ClusterMeetingCostLinesFollowTheRecipeTest(TestCase):
    """System Health reads what belongs on a cluster meeting from the costing
    recipe. It kept a list of its own, which still said a meeting is snacks
    alone after the recipe gave every meeting its room, and reported each
    meeting scheduled as a blocker."""

    def setUp(self):
        self.meeting = Activity.objects.create(
            activity_type="cluster_meeting", status="scheduled"
        )

    def _line(self, key, activity=None, **fields):
        return ActivityScheduleCostLine.objects.create(
            activity=activity or self.meeting,
            cost_setting_key=key,
            label=key,
            unit_cost=5_000,
            amount=5_000,
            **fields,
        )

    def _reported(self):
        from apps.system_health.services import cluster_meeting_lines_off_recipe

        return sorted(
            cluster_meeting_lines_off_recipe().values_list(
                "cost_setting_key", flat=True
            )
        )

    def _blockers(self):
        from apps.system_health.services import _workflow_issues

        return [
            blocker
            for blocker in _workflow_issues()["blockers"]
            if "cluster meeting cost line" in blocker
        ]

    def test_the_recipe_is_snacks_the_room_the_handouts_and_the_day(self):
        """The keys are read off the recipe. A meeting's snacks are its own
        rate, not a group training's meals (owner, 2026-10-01), nobody
        facilitates a meeting, and no per-meeting rate rides on top."""
        from apps.budget.costing import cluster_meeting_rate_keys

        self.assertEqual(
            cluster_meeting_rate_keys(),
            {
                "cluster_meetings_trainings_meals",
                "group_training_venue_cost",
                "printing_training_materials",
                "photocopying_training_materials",
                "primary_transport_per_day",
                "secondary_transport_per_day",
                "lunch_per_day",
                "secondary_breakfast_per_day",
                "secondary_overnight_dinner_per_day",
                "secondary_accommodation_per_night",
            },
        )

    def test_what_the_recipe_charges_a_meeting_is_not_a_wrong_cost(self):
        from apps.budget.costing import cluster_meeting_rate_keys

        review = Activity.objects.create(
            activity_type="cluster_meeting_ssa_review", status="scheduled"
        )
        for key in cluster_meeting_rate_keys():
            self._line(key)
            self._line(key, activity=review)

        self.assertEqual(self._reported(), [])
        self.assertEqual(self._blockers(), [])

    def test_a_line_saved_under_an_earlier_recipe_is_not_a_wrong_cost(self):
        """The snacks under their first name, and the per-meeting rate the
        recipe charged from 2026-09-06 to 2026-09-26."""
        for key in (
            "cluster_meeting_participant_meal_cost_per_head",
            "cluster_meetings_trainings",
            "cluster_meeting",
        ):
            self._line(key)

        self.assertEqual(self._reported(), [])

    def test_a_cost_the_cd_linked_to_the_meetings_item_is_not_a_wrong_cost(self):
        from apps.budget.models import CostSetting

        item, other = (_catalogue_item(code) for code in ("LINKED", "OTHER"))
        CostSetting.objects.create(
            key="meeting_banner",
            label="Banner",
            unit_cost=5_000,
            catalogue_item=item,
        )
        self._line("meeting_banner", activity_catalogue_item_id=item.id)
        self.assertEqual(self._reported(), [])

        # The same rate on a meeting of an item it is not linked to.
        elsewhere = Activity.objects.create(
            activity_type="cluster_meeting", status="scheduled"
        )
        self._line(
            "meeting_banner", activity=elsewhere, activity_catalogue_item_id=other.id
        )
        self.assertEqual(self._reported(), ["meeting_banner"])

    def test_a_rate_no_meeting_recipe_charged_is_reported(self):
        wrong = [
            # Nobody facilitates a meeting.
            "group_training_facilitation_fee",
            # A training's meals are not a meeting's snacks.
            "group_training_meals",
            # Retired cluster keys the repair commands look for.
            "cluster_meeting_cost",
            "meals_per_participant",
            "mobilisation_per_participant",
            "venue",
        ]
        for key in wrong:
            self._line(key)
        # The same keys on a training are the training's business.
        training = Activity.objects.create(
            activity_type="cluster_training", status="scheduled"
        )
        self._line("group_training_facilitation_fee", activity=training)

        self.assertEqual(self._reported(), sorted(wrong))
        self.assertEqual(
            self._blockers(),
            [
                "6 cluster meeting cost line(s) carry a rate the meeting "
                "recipe does not charge."
            ],
        )


def _catalogue_item(code):
    from apps.activity_catalogue.models import ActivityCatalogueItem

    return ActivityCatalogueItem.objects.create(
        stable_code=f"HEALTH_CONTRACT_{code}",
        source_name=f"Health contract {code}",
        display_name=f"Health contract {code}",
        activity_type="cluster_meeting",
        delivery_method="cluster_meeting",
        workflow_kind="cluster_meeting",
        status="active",
        salesforce_record_type="MEETING",
        evidence_profile="CLUSTER_MEETING_FORM",
        costing_profile="CLUSTER_MEETING",
    )


def _school():
    from apps.geography.models import District, Region
    from apps.schools.models import School

    region = Region.objects.create(name="Health Contract Region")
    district = District.objects.create(name="Health Contract District", region=region)
    return School.objects.create(
        school_id="SCH-HEALTH-CONTRACT",
        name="Contract Primary",
        region=region,
        district=district,
    )
