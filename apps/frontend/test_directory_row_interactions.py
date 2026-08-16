from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
INTERACTIVE_GUARD = "a, button, input, label, select, textarea, [role=button]"


class DirectoryRowInteractionContractTests(SimpleTestCase):
    def test_school_row_empty_space_toggles_without_hijacking_controls(self):
        row = (ROOT / "templates/partials/schools/directory_row.html").read_text()

        self.assertIn("data-row-disclosure-summary", row)
        self.assertIn(f"closest('{INTERACTIVE_GUARD}')", row)
        self.assertIn("openSchoolId = openSchoolId === '{{ school.id }}' ? null", row)
        self.assertIn("frontend:school_detail", row)
        self.assertEqual(row.count("frontend:school_detail"), 1)

    def test_cluster_row_empty_space_toggles_without_hijacking_profile_link(self):
        card = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()

        self.assertIn("data-row-disclosure-summary", card)
        self.assertIn(f"closest('{INTERACTIVE_GUARD}')", card)
        self.assertIn("cardExpanded = !cardExpanded", card)
        self.assertIn('href="/clusters/{{ cluster.id }}"', card)
        self.assertIn('href="/clusters/{{ cluster.id }}" @click.stop', card)
        self.assertEqual(card.count('href="/clusters/{{ cluster.id }}"'), 1)

    def test_cluster_summary_keeps_details_visible_before_expansion(self):
        card = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()

        summary = card.split('class="cluster-card__summary"', 1)[1].split(
            "<!-- Expanded details block -->", 1
        )[0]
        self.assertIn("school-record-row__metadata cluster-card__metadata", summary)
        self.assertIn("Cluster Leader:", summary)
        self.assertIn("SSA Coverage:", summary)

    def test_cluster_expansion_uses_the_shared_ssa_detail_format(self):
        card = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()

        expanded = card.split("<!-- Expanded details block -->", 1)[1]
        self.assertIn('x-transition.opacity.duration.150ms', expanded)
        self.assertIn('partials/schools/ssa_score_groups.html', expanded)
        self.assertIn("selected_fy=selected_fy", expanded)
        self.assertLess(
            expanded.index("partials/schools/ssa_score_groups.html"),
            expanded.index("expanded-schools-"),
        )

    def test_cluster_disclosure_has_keyboard_accessible_native_button(self):
        card = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()

        self.assertIn(':aria-expanded="cardExpanded.toString()"', card)
        self.assertIn('aria-controls="cluster-details-{{ cluster.id }}"', card)
        self.assertIn('id="cluster-details-{{ cluster.id }}"', card)
