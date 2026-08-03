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


class UrgentRowActionIsUsableTest(SimpleTestCase):
    """Every urgent-schools row must offer an action that says what it does.

    The Program Lead's card rendered a blue button with no label and no href.
    risk_list names the recommended work and urgent_schools_page builds the URL
    that opens it, but nothing joined either to the action_* fields the shared
    table renders, so the cell drew `<a href="">` — a control that looks
    pressable, does nothing, and does not say what it would have done.

    A button with no label is worse than a missing button: it occupies the
    place a user looks for the action and gives them nothing to read.
    """

    def test_the_shared_table_renders_the_action_from_these_fields(self):
        """Pins the contract between the row builder and the template, since
        the two live in different apps and drifted apart once already."""
        from pathlib import Path

        from django.conf import settings

        template = (
            Path(settings.BASE_DIR)
            / "templates/partials/dashboards/urgent_schools_table.html"
        ).read_text()
        for field in ("row.action_label", "row.action_url", "row.action_mode"):
            with self.subTest(field=field):
                self.assertIn(field, template)

    def test_the_program_lead_builder_sets_every_field_the_table_reads(self):
        from pathlib import Path

        from django.conf import settings

        source = (
            Path(settings.BASE_DIR) / "apps/analytics/pl_dashboard_service.py"
        ).read_text()
        for field in ('row["action_label"]', 'row["action_url"]', 'row["action_mode"]'):
            with self.subTest(field=field):
                self.assertIn(
                    field,
                    source,
                    "the table reads this; a row that omits it renders an "
                    "empty control",
                )

    def test_the_label_falls_back_rather_than_rendering_empty(self):
        """recommended_activity_label is derived, so it can be absent. An
        empty string would put the blank button straight back."""
        from pathlib import Path

        from django.conf import settings

        source = (
            Path(settings.BASE_DIR) / "apps/analytics/pl_dashboard_service.py"
        ).read_text()
        assignment = source.split('row["action_label"]', 1)[1][:160]
        self.assertIn(
            "or ",
            assignment,
            "the label needs a fallback — an empty one renders a blank button",
        )
