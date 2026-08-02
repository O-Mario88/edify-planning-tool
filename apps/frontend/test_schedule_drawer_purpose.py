"""The school-visit drawer asks what the visit is FOR.

It had come to lead with a list of Recommended Activities: the engine chose the
activity, and the SSA score appeared only as a badge attached to it. That
inverts the judgement. A field officer knows the school — what they need from
the system is which interventions are struggling, and then to say what they
intend to do about it. Naming the weak interventions and asking for a purpose
is the shape that was asked for, and the shape restored here.

Costing must survive the change, and that is the half worth testing hardest:
purpose -> activity type (PURPOSE_ACTIVITY_TYPES) -> the CD catalogue item that
costs that type. The user never picks a catalogue row, and every scheduled
visit still carries one.
"""

from __future__ import annotations

from django.test import TestCase

from apps.partners.purposes import (
    PARTNER_VISIT_PURPOSES,
    PURPOSE_ACTIVITY_TYPES,
    STAFF_VISIT_PURPOSES,
    purpose_activity_type,
)

TEMPLATE = "templates/partials/planning/schedule_drawer.html"


def _drawer_source() -> str:
    from pathlib import Path

    from django.conf import settings

    return (Path(settings.BASE_DIR) / TEMPLATE).read_text()


class DrawerAsksForPurposeTest(TestCase):
    def test_purpose_of_visit_is_present_and_required(self):
        source = _drawer_source()
        self.assertIn('name="purpose_of_visit"', source)
        self.assertIn("staff_visit_purposes", source)
        # Required: a visit with no stated purpose cannot be costed, reported
        # on, or reviewed later.
        purpose_block = source.split('name="purpose_of_visit"')[1][:400]
        self.assertIn("required", purpose_block)

    def test_the_struggling_ssa_interventions_are_named(self):
        """The diagnostic the officer needs, shown as evidence rather than
        converted into an instruction."""
        source = _drawer_source()
        self.assertIn("SSA interventions performing poorly", source)
        self.assertIn("{% for r in recommendations %}", source)

    def test_the_engine_no_longer_chooses_the_activity(self):
        source = _drawer_source()
        self.assertNotIn(
            '<legend class="edify-text-caption font-bold uppercase tracking-wider '
            'text-slate-400">Recommended Activities</legend>',
            source,
        )
        self.assertNotIn('name="catalogue_choice"', source)

    def test_focus_intervention_remains_selectable(self):
        source = _drawer_source()
        self.assertIn('name="focus_intervention"', source)
        self.assertIn("{% for code, label in interventions %}", source)


class PurposeDrivesCostingTest(TestCase):
    """The costing seam. Removing the catalogue picker must not remove the
    catalogue link — it must derive it."""

    def test_every_offered_purpose_maps_to_an_activity_type(self):
        unmapped = [
            value
            for value, _label in STAFF_VISIT_PURPOSES
            if value not in PURPOSE_ACTIVITY_TYPES
        ]
        self.assertEqual(
            unmapped,
            [],
            "a purpose the drawer offers but cannot map is a visit that "
            "cannot be costed",
        )

    def test_the_purposes_the_user_named_are_offered(self):
        """SSA support, follow-up, donor and story visits — the list this
        drawer exists to present."""
        offered = {value for value, _label in STAFF_VISIT_PURPOSES}
        for expected in (
            "ssa_support",
            "training_follow_up",
            "donor_visit",
            "story_gathering",
        ):
            self.assertIn(expected, offered)

    def test_partner_purposes_are_a_subset_of_staff_purposes(self):
        """The drawer disables non-partner purposes when delivery is Partner,
        which only makes sense if partners are offered nothing extra."""
        staff = {value for value, _label in STAFF_VISIT_PURPOSES}
        partner = {value for value, _label in PARTNER_VISIT_PURPOSES}
        self.assertTrue(partner.issubset(staff))

    def test_an_unknown_purpose_falls_back_rather_than_crashing(self):
        self.assertEqual(
            purpose_activity_type("not_a_purpose", "school_visit"), "school_visit"
        )

    def test_ssa_support_costs_as_an_ssa_collection_visit(self):
        """The mapping that carries the money: choosing "SSA Support" must
        reach the SSA-collection costing, not a plain school visit."""
        self.assertEqual(
            purpose_activity_type("ssa_support"), "school_visit_ssa_collection"
        )


class CatalogueResolverTest(TestCase):
    def test_it_refuses_to_guess_between_two_costings(self):
        """Two catalogue items for one workflow kind is a governance question.
        Picking the first would put money against an activity nobody chose."""
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind

        self.assertIsNone(resolve_item_for_workflow_kind(""))

    def test_it_returns_none_when_nothing_costs_the_purpose(self):
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind

        self.assertIsNone(resolve_item_for_workflow_kind("no_such_workflow_kind"))


class SchoolPlanningStaysVisitsOnlyTest(TestCase):
    """School planning schedules visits. Everything else is planned from the
    Project page or the Work Plan.

    The drawer used to offer the eligible Activity Catalogue directly —
    primary items plus "View Other Eligible Activities" — so whatever the
    catalogue considered eligible for a school could be scheduled from the
    planning page, including programme work that belongs on the Work Plan.
    Asking for a purpose closes that by construction: the drawer offers eight
    visit purposes and nothing else can be expressed through it.
    """

    #: Activity types that are not a visit to a school. Scheduling any of
    #: these from the school planning page is the thing this test prevents.
    NON_VISIT_TYPES = {
        "cluster_meeting",
        "cluster_training",
        "cluster_training_ssa_collection",
        "cluster_meeting_ssa_review",
        "training",
        "project_activity",
        "programme_event",
    }

    def test_no_offered_purpose_schedules_non_visit_work(self):
        offending = {
            value: purpose_activity_type(value)
            for value, _label in STAFF_VISIT_PURPOSES
            if purpose_activity_type(value) in self.NON_VISIT_TYPES
        }
        self.assertEqual(
            offending,
            {},
            "the school planning drawer must not be able to schedule cluster "
            "or programme work — that is planned from the Project page or the "
            "Work Plan",
        )

    def test_the_drawer_no_longer_exposes_the_raw_catalogue(self):
        source = _drawer_source()
        self.assertNotIn("View Other Eligible Activities", source)
        self.assertNotIn("other_catalogue_items", source)

    def test_non_school_work_still_requires_an_approved_catalogue_item(self):
        """The Work Plan path is unchanged and still costed: a programme
        activity with no school and no cluster is only creatable through a
        catalogue item explicitly approved for non-school use."""
        from apps.core.exceptions import BadRequest

        from apps.activities.services import create

        with self.assertRaises(BadRequest) as caught:
            create({"activityType": "training"}, principal=None)
        self.assertIn("school or cluster", str(caught.exception))
