"""One abbreviation table for the eight SSA interventions (owner, 2026-09-12)."""

from django.test import SimpleTestCase

from apps.core.enums import SsaIntervention
from apps.core.interventions import (
    INTERVENTION_ABBREVIATIONS,
    abbreviate_interventions,
    intervention_abbr,
    mentions_intervention,
)


class InterventionAbbreviationTest(SimpleTestCase):
    def test_every_intervention_has_a_short_distinct_code(self):
        codes = [
            INTERVENTION_ABBREVIATIONS[code] for code, _ in SsaIntervention.choices
        ]
        self.assertEqual(len(codes), 8)
        self.assertEqual(len(set(codes)), 8)
        self.assertTrue(all(1 < len(c) <= 5 and c.isupper() for c in codes), codes)
        self.assertEqual(intervention_abbr("exposure_to_word_of_god"), "WOG")
        self.assertEqual(
            intervention_abbr("not_an_intervention"), "not_an_intervention"
        )

    def test_names_inside_text_are_abbreviated_and_kept_whole_elsewhere(self):
        self.assertEqual(
            abbreviate_interventions("Weakest: Exposure to the Word of God · Avg 2.1"),
            "Weakest: WOG · Avg 2.1",
        )
        # A label that contains another is matched whole, not in pieces.
        self.assertEqual(
            abbreviate_interventions("Teacher's Environment / Learning Environment"),
            "TE / LE",
        )
        self.assertEqual(
            abbreviate_interventions("Financial health"), "FH"
        )  # case-insensitive
        self.assertEqual(abbreviate_interventions(12), 12)
        self.assertEqual(abbreviate_interventions(""), "")
        self.assertTrue(mentions_intervention("Leadership"))
        self.assertFalse(mentions_intervention("Schools visited"))

    def test_the_three_older_tables_are_this_one(self):
        from apps.analytics.pl_analytics_service import SSA_INTERVENTIONS
        from apps.frontend.views.my_plan_views import SSA_SCORE_ABBREVIATIONS
        from apps.projects.impact_service import INTERVENTION_ABBR

        self.assertIs(SSA_SCORE_ABBREVIATIONS, INTERVENTION_ABBREVIATIONS)
        self.assertIs(INTERVENTION_ABBR, INTERVENTION_ABBREVIATIONS)
        self.assertEqual(
            [code for _, _, code in SSA_INTERVENTIONS],
            list(INTERVENTION_ABBREVIATIONS.values()),
        )
