"""A partner does more than one thing, and the form can say so.

Owner, 2026-09-22:

  "Some partners are doing more than one activity. Can you make sure the list
  of interventions and their activities are in checkbox so that many activities
  can be assigned to partners."

The tick-list is built from the live catalogue rather than a second list, so
these tests put real catalogue items and mappings behind it and assert the
three things that matter: what is offered, what a post is allowed to store, and
that the single `ssa_intervention` column every existing reader depends on
still says something true.
"""

from __future__ import annotations

from django.test import TestCase

from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ActivityInterventionMapping,
    CatalogueStatus,
    MappingMode,
)
from apps.core.enums import SsaIntervention
from apps.partners import capabilities
from apps.partners.models import Partner


def _item(code, name, *, partner_delivery=True, status=CatalogueStatus.ACTIVE):
    """One catalogue item. An ACTIVE row must name its three profiles
    (`active_catalogue_profiles_required`), so they are filled here rather than
    left to a default the database refuses."""
    return ActivityCatalogueItem.objects.create(
        stable_code=code,
        source_name=name,
        display_name=name,
        activity_type="school_visit",
        delivery_method="in_person",
        workflow_kind="school_visit",
        status=status,
        partner_delivery_allowed=partner_delivery,
        evidence_profile="school_visit",
        costing_profile="school_visit",
        salesforce_record_type="School_Visit",
    )


def _maps(item, intervention, *, mode=None):
    """One mapping row, in the shape the database will accept.

    `catalogue_mapping_intervention_shape`: a row either names an intervention
    with a fixed or multiple-allowed mode, or names none with one of the modes
    that carry no intervention.
    """
    return ActivityInterventionMapping.objects.create(
        catalogue_item=item,
        intervention=intervention,
        mapping_mode=mode or MappingMode.FIXED,
        active=True,
    )


class WhatTheFormOffersTest(TestCase):
    def setUp(self):
        self.first = list(SsaIntervention)[0].value
        self.second = list(SsaIntervention)[1].value
        self.literacy = _item("CAP-1", "Literacy coaching")
        self.finance = _item("CAP-2", "Financial health review")
        _maps(self.literacy, self.first)
        _maps(self.finance, self.second)

    def _group(self, groups, key):
        return next(group for group in groups if group["key"] == key)

    def _codes(self, groups, key):
        return [a["code"] for a in self._group(groups, key)["activities"]]

    def test_every_intervention_is_offered_as_its_own_group(self):
        # Including the ones the catalogue has nothing under yet: a partner may
        # cover an intervention before a named activity for it exists.
        keys = {group["key"] for group in capabilities.intervention_activity_options()}
        for value, _label in SsaIntervention.choices:
            with self.subTest(intervention=value):
                self.assertIn(value, keys)

    def test_an_activity_is_offered_under_its_own_intervention_and_no_other(self):
        groups = capabilities.intervention_activity_options()
        self.assertIn("CAP-1", self._codes(groups, self.first))
        self.assertIn("CAP-2", self._codes(groups, self.second))
        self.assertNotIn("CAP-2", self._codes(groups, self.first))
        self.assertNotIn("CAP-1", self._codes(groups, self.second))

    def test_work_a_partner_cannot_deliver_is_not_offered(self):
        _item("CAP-3", "Staff-only audit", partner_delivery=False)
        offered = {
            activity["code"]
            for group in capabilities.intervention_activity_options()
            for activity in group["activities"]
        }
        self.assertNotIn("CAP-3", offered)

    def test_a_retired_catalogue_item_is_not_offered(self):
        _item("CAP-4", "Retired course", status=CatalogueStatus.RETIRED)
        offered = {
            activity["code"]
            for group in capabilities.intervention_activity_options()
            for activity in group["activities"]
        }
        self.assertNotIn("CAP-4", offered)

    def test_work_that_moves_any_intervention_gets_its_own_group(self):
        _maps(
            _item("CAP-5", "Cluster convening"),
            None,
            mode=MappingMode.ANY_SSA_INTERVENTION,
        )
        groups = capabilities.intervention_activity_options()
        self.assertIn("CAP-5", self._codes(groups, capabilities.ANY_INTERVENTION_KEY))

    def test_partner_work_with_no_mapping_is_still_reachable(self):
        # An activity nobody can tick is an activity no partner can be
        # recorded as doing, so it gets a group of its own rather than
        # disappearing.
        _item("CAP-6", "Unmapped support")
        groups = capabilities.intervention_activity_options()
        self.assertIn(
            "CAP-6",
            [
                a["code"]
                for a in self._group(groups, capabilities.UNMAPPED_KEY)["activities"]
            ],
        )


class WhatASubmitMayStoreTest(TestCase):
    def setUp(self):
        self.first = list(SsaIntervention)[0].value
        self.second = list(SsaIntervention)[1].value
        _maps(_item("CAP-1", "Literacy coaching"), self.first)

    def test_many_interventions_and_many_activities_are_kept(self):
        chosen = capabilities.selected_capabilities(
            [self.first, self.second], ["CAP-1"]
        )
        self.assertEqual(chosen["ssa_interventions"], [self.first, self.second])
        self.assertEqual(chosen["activity_codes"], ["CAP-1"])

    def test_the_single_column_holds_the_first_intervention(self):
        # Everything that reads `ssa_intervention` — the register, the
        # oversight grouping, the profile header — keeps working.
        chosen = capabilities.selected_capabilities([self.second, self.first], [])
        self.assertEqual(chosen["ssa_intervention"], self.second)

    def test_a_group_that_is_not_an_intervention_never_becomes_one(self):
        chosen = capabilities.selected_capabilities(
            [capabilities.UNMAPPED_KEY, self.first], []
        )
        self.assertEqual(chosen["ssa_intervention"], self.first)

    def test_a_code_the_form_never_offered_is_dropped(self):
        chosen = capabilities.selected_capabilities(
            ["not-an-intervention", self.first], ["CAP-1", "CAP-NOPE"]
        )
        self.assertEqual(chosen["ssa_interventions"], [self.first])
        self.assertEqual(chosen["activity_codes"], ["CAP-1"])

    def test_nothing_ticked_stores_nothing_and_refuses_nothing(self):
        chosen = capabilities.selected_capabilities([], [])
        self.assertEqual(chosen["ssa_interventions"], [])
        self.assertEqual(chosen["activity_codes"], [])
        self.assertIsNone(chosen["ssa_intervention"])

    def test_the_same_tick_twice_is_one_tick(self):
        chosen = capabilities.selected_capabilities(
            [self.first, self.first], ["CAP-1", "CAP-1"]
        )
        self.assertEqual(chosen["ssa_interventions"], [self.first])
        self.assertEqual(chosen["activity_codes"], ["CAP-1"])


class WhatASavedPartnerReadsTest(TestCase):
    def setUp(self):
        self.first = list(SsaIntervention)[0].value
        self.second = list(SsaIntervention)[1].value
        _item("CAP-1", "Literacy coaching")

    def test_a_partner_reads_back_everything_it_was_given(self):
        partner = Partner.objects.create(
            name="Many Things Ltd",
            ssa_intervention=self.first,
            ssa_interventions=[self.first, self.second],
            activity_codes=["CAP-1"],
        )
        described = partner.capabilities
        self.assertEqual(
            [item["key"] for item in described["interventions"]],
            [self.first, self.second],
        )
        self.assertEqual(
            described["activities"], [{"code": "CAP-1", "name": "Literacy coaching"}]
        )

    def test_a_partner_added_before_the_tick_list_still_reads_correctly(self):
        # The migration backfills, but a row written by anything else must not
        # come back blank: the single column is the fallback.
        partner = Partner.objects.create(
            name="One Thing Ltd", ssa_intervention=self.second
        )
        self.assertEqual(
            [item["key"] for item in partner.capabilities["interventions"]],
            [self.second],
        )

    def test_a_partner_with_nothing_recorded_says_so_rather_than_erroring(self):
        partner = Partner.objects.create(name="Nothing Recorded Ltd")
        self.assertEqual(partner.capabilities["interventions"], [])
        self.assertEqual(partner.capabilities["activities"], [])
        self.assertEqual(partner.ssa_intervention_label, "General Support")
