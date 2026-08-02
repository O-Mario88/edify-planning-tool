"""Eight interventions, everywhere, or say which are missing.

The Program Lead's "SSA Intelligence — by cluster" matrix showed six. The code
read ``SSA_INTERVENTIONS[:6]`` with a comment explaining that the drawer showed
all eight, so the truncation was intentional at the time and invisible to the
reader: the table had a header row, a score in every cell, and no indication
that Teacher's Environment and Enrolment were simply absent.

That is the failure mode worth guarding. A matrix missing two of eight columns
does not look broken — it looks complete. And the two it dropped were the last
two in the canonical order, which is where a slice always lands, so nobody
would notice by spot-checking the left-hand side.

The second test guards the other half: the analytics module keeps its own
tuple of (code, label, abbreviation) because the matrix needs short column
headers. A private copy of a canonical list is fine until it drifts, so it is
asserted against SsaIntervention rather than trusted.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.analytics.pl_analytics_service import SSA_INTERVENTIONS
from apps.core.enums import SsaIntervention


class InterventionListsAgreeTest(SimpleTestCase):
    def test_the_analytics_list_matches_the_canonical_enum_exactly(self):
        canonical = [code for code, _label in SsaIntervention.choices]
        analytics = [code for code, _label, _abbr in SSA_INTERVENTIONS]
        self.assertEqual(
            analytics,
            canonical,
            "same interventions, same order — a reordered copy silently "
            "relabels every column in the cluster matrix",
        )

    def test_all_eight_are_present(self):
        self.assertEqual(len(SSA_INTERVENTIONS), 8)

    def test_every_intervention_has_a_label_and_a_column_abbreviation(self):
        for code, label, abbreviation in SSA_INTERVENTIONS:
            with self.subTest(code=code):
                self.assertTrue(label.strip(), f"{code} has no label")
                self.assertTrue(abbreviation.strip(), f"{code} has no abbreviation")

    def test_the_abbreviations_are_distinct(self):
        """Two columns headed the same thing is unreadable, and the matrix has
        no room for a legend."""
        abbreviations = [abbr for _c, _l, abbr in SSA_INTERVENTIONS]
        self.assertEqual(len(set(abbreviations)), len(abbreviations))


class ClusterMatrixShowsEveryInterventionTest(SimpleTestCase):
    """The defect itself: the matrix builder must not slice the list."""

    def test_the_builder_does_not_truncate_the_intervention_list(self):
        from pathlib import Path

        from django.conf import settings

        source = (
            Path(settings.BASE_DIR) / "apps/analytics/pl_dashboard_service.py"
        ).read_text()
        self.assertNotIn(
            "SSA_INTERVENTIONS[:",
            source,
            "slicing the canonical list drops columns from the right-hand end "
            "of the matrix, where nobody checks",
        )
