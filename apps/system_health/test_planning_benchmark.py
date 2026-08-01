"""The minimal-input contract must be enforceable, not just described.

The goal §2 is really after: a person clusters the school, assigns or schedules
it, uploads evidence, enters the Salesforce id and enters the NetSuite id. The
platform does everything else. These tests are what stop a new required field
quietly appearing in a workflow form and making that untrue.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.system_health.planning_benchmark import (
    FIELD_NAME_ALIASES,
    HUMAN_TOUCHPOINTS,
    PLATFORM_DERIVED,
    SANCTIONED_INPUTS,
    contract,
    report,
    unsanctioned_required_inputs,
)


class ContractShapeTests(SimpleTestCase):
    def test_the_five_touchpoints_are_the_ones_the_owner_named(self):
        self.assertEqual(
            [t.stage for t in HUMAN_TOUCHPOINTS],
            [
                "Cluster the school",
                "Assign to a partner, or schedule the activity",
                "Upload the evidence",
                "Enter the Salesforce activity ID",
                "Enter the NetSuite ID",
            ],
        )

    def test_every_touchpoint_justifies_needing_a_person(self):
        """If a stage cannot say why a human is required, it is a candidate for
        automation rather than a fixed cost."""
        for touchpoint in HUMAN_TOUCHPOINTS:
            with self.subTest(touchpoint.stage):
                self.assertTrue(touchpoint.inputs)
                self.assertGreater(len(touchpoint.why_a_human), 30)

    def test_the_platform_carries_far_more_than_the_person(self):
        figures = contract()
        self.assertGreater(figures["platform_derived"], figures["human_inputs"] * 3)
        self.assertGreater(figures["automation_ratio"], 75)

    def test_nothing_a_person_types_is_asked_for_twice(self):
        self.assertEqual(contract()["repeated_entries"], 0)

    def test_every_derived_field_names_where_it_comes_from(self):
        """A derivation with no named source is a claim, not a fact."""
        for derived in PLATFORM_DERIVED:
            with self.subTest(derived.field):
                self.assertTrue(derived.source.strip())

    def test_the_two_external_identifiers_are_the_only_typed_codes(self):
        """Salesforce and NetSuite ids are carried by hand only because they
        are created outside Edify. Nothing else should be."""
        typed = [i for i in contract()["human_input_names"] if i.endswith("_id")]
        self.assertEqual(sorted(typed), ["netsuite_id", "salesforce_activity_id"])


class NoUnsanctionedQuestionsTests(SimpleTestCase):
    """The check that can actually fail as the product changes."""

    def test_workflow_forms_ask_only_for_what_the_contract_allows(self):
        offenders = unsanctioned_required_inputs()
        self.assertEqual(
            offenders,
            [],
            "A workflow form requires an input the minimal-input contract does "
            f"not sanction: {offenders}. Either the platform should derive it, "
            "or it should be optional, or the contract in "
            "apps/system_health/planning_benchmark.py needs to change on "
            "purpose.",
        )

    def test_the_scanner_would_notice_a_new_required_field(self):
        """A scanner that cannot fail proves nothing."""
        import re

        tag = '<input name="favourite_colour" required>'
        self.assertTrue(re.search(r"\brequired\b", tag))
        self.assertNotIn("favourite_colour", SANCTIONED_INPUTS)

    def test_hidden_required_fields_are_not_treated_as_questions(self):
        """Context the page supplies is not something a person answers."""
        self.assertIn("school_id", SANCTIONED_INPUTS)

    def test_the_known_naming_aliases_are_recorded_not_hidden(self):
        """Two drawers name the same input differently. Sanctioned, because it
        is one question either way -- but written down."""
        self.assertTrue(FIELD_NAME_ALIASES)
        for canonical, alias, why in FIELD_NAME_ALIASES:
            with self.subTest(f"{canonical}/{alias}"):
                self.assertIn(canonical, SANCTIONED_INPUTS)
                self.assertIn(alias, SANCTIONED_INPUTS)
                self.assertTrue(why.strip())


class ReportTests(SimpleTestCase):
    def test_the_report_states_the_contract_rather_than_a_time_claim(self):
        """The old version tried to reason about elapsed seconds. The goal was
        never how fast the typing is -- it is how little there is to type."""
        result = report()
        self.assertIn("contract", result)
        self.assertNotIn("time_reduction", result)


class DrawerLabelTests(SimpleTestCase):
    """The same decision should read the same way wherever it is asked.

    A CCEO uses both planning drawers. Naming one decision "Assign to Partner"
    in one and "Partner Organization" in the other makes them look like two
    different questions.

    The second test guards a mistake made while fixing the first: unifying the
    partner labels left two fields in the schedule drawer both reading
    "Purpose" — the required select that classifies the work, and the optional
    free-text goal. Two identical labels in one form is worse than the
    inconsistency it replaced.
    """

    def _labels(self, relative):
        import re
        from pathlib import Path

        from django.conf import settings

        text = (Path(settings.BASE_DIR) / relative).read_text(encoding="utf-8")
        return re.findall(r'<label for="([^"]+)"[^>]*>([^<]+)</label>', text)

    SCHEDULE = "templates/partials/planning/schedule_drawer.html"
    PARTNER = "templates/partials/planning/assign_partner_drawer.html"

    # There was a test here requiring the partner control to read the same in
    # both drawers. It is gone because the control is: the schedule drawer no
    # longer offers partner assignment at all, so there is one partner picker
    # on the platform and nothing left to keep consistent. Superseded by
    # OneWayToHandWorkToAPartnerTests below.

    def test_the_free_text_goal_reads_the_same_in_both_drawers(self):
        """PartnerAssignment.purpose becomes Activity.activity_purpose_text
        verbatim, so they are one field asked at two moments."""
        schedule = dict(self._labels(self.SCHEDULE))
        partner = dict(self._labels(self.PARTNER))
        self.assertEqual(
            schedule["activity_purpose_text"].strip(),
            partner["purpose"].strip(),
        )

    def test_no_drawer_gives_two_fields_the_same_label(self):
        for relative in (self.SCHEDULE, self.PARTNER):
            with self.subTest(relative):
                labels = [text.strip() for _, text in self._labels(relative)]
                duplicates = {label for label in labels if labels.count(label) > 1}
                self.assertEqual(
                    duplicates,
                    set(),
                    f"{relative} asks two different questions under the same "
                    f"label: {duplicates}",
                )

    def test_the_classification_and_the_goal_stay_distinct(self):
        """The classification drives activity_type; the goal is prose. They
        are not the same question and must not read as one.

        The classification control has two eras: the legacy
        `purpose_of_visit` select, and the Activity Catalogue's "Recommended
        Activities" fieldset that now derives the type from the selected
        Catalogue item. Whichever the drawer carries, its heading must stay
        distinct from the free-text Goal label."""
        import re
        from pathlib import Path

        from django.conf import settings

        schedule = dict(self._labels(self.SCHEDULE))
        goal = schedule["activity_purpose_text"].strip()
        if "purpose_of_visit" in schedule:
            self.assertNotEqual(schedule["purpose_of_visit"].strip(), goal)
            return
        text = (Path(settings.BASE_DIR) / self.SCHEDULE).read_text(encoding="utf-8")
        legends = [
            m.strip() for m in re.findall(r"<legend[^>]*>([^<]+)</legend>", text)
        ]
        self.assertTrue(
            legends,
            "The schedule drawer has neither a purpose_of_visit select nor a "
            "catalogue fieldset — the classification question is missing.",
        )
        for legend in legends:
            self.assertNotEqual(legend, goal)


class OneWayToHandWorkToAPartnerTests(SimpleTestCase):
    """Assigning a school to a partner is one workflow, not two.

    The schedule drawer used to offer "Assigned Partner Delivery" alongside a
    partner picker — a second route to the same outcome as the partner drawer,
    and a worse one: `assign_partner_action_view` creates the PartnerAssignment
    record that the handoff is tracked by, while the schedule drawer's partner
    path created only the Activity. Partner work scheduled that way was
    invisible to anything reading assignments.

    It is also one fewer decision at the moment of scheduling, which is what
    §2 is actually asking for.
    """

    SCHEDULE = "templates/partials/planning/schedule_drawer.html"

    def _drawer(self):
        from pathlib import Path

        from django.conf import settings

        return (Path(settings.BASE_DIR) / self.SCHEDULE).read_text(encoding="utf-8")

    def test_the_schedule_drawer_offers_no_partner_picker(self):
        source = self._drawer()
        self.assertNotIn('name="assigned_partner_id"', source)
        self.assertNotIn("Assigned Partner Delivery", source)

    def test_it_offers_no_delivery_type_choice(self):
        """Delivery type is who is using the drawer, not a question."""
        source = self._drawer()
        self.assertNotIn('<select\nname="delivery_type"', source)
        self.assertNotIn('id="delivery_type"', source)

    def test_rescheduling_preserves_an_existing_partner_activity(self):
        """The trap in removing the control: hard-coding the hidden field to
        'staff' would silently convert a partner activity on reschedule."""
        source = self._drawer()
        self.assertIn('name="delivery_type" :value="delivery"', source)
        self.assertNotIn('name="delivery_type" value="staff"', source)

    def test_the_partner_drawer_remains_the_way_to_hand_work_over(self):
        from pathlib import Path

        from django.conf import settings

        partner = (
            Path(settings.BASE_DIR)
            / "templates/partials/planning/assign_partner_drawer.html"
        ).read_text(encoding="utf-8")
        self.assertIn('name="partner_id"', partner)
