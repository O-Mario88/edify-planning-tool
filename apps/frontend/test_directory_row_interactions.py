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
        self.assertEqual(card.count('href="/clusters/{{ cluster.id }}"'), 1)

    def test_cluster_disclosure_has_keyboard_accessible_native_button(self):
        card = (ROOT / "templates/partials/clusters/cluster_card.html").read_text()

        self.assertIn(':aria-expanded="cardExpanded.toString()"', card)
        self.assertIn('aria-controls="cluster-details-{{ cluster.id }}"', card)
        self.assertIn('id="cluster-details-{{ cluster.id }}"', card)
