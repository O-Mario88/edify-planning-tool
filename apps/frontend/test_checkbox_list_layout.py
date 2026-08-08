from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class CheckboxListLayoutContractTests(SimpleTestCase):
    def test_shared_selectable_school_rows_use_checkbox_first_layout(self):
        directory = (ROOT / "templates/partials/schools/directory_row.html").read_text()
        planning = (ROOT / "templates/partials/planning/school_row.html").read_text()
        css = (ROOT / "static/css/platform.css").read_text()

        for row in (directory, planning):
            self.assertIn("school-record-row__summary--selectable", row)
            self.assertLess(
                row.index("school-record-row__select"),
                row.index("school-record-row__icon"),
            )
            self.assertLess(
                row.index("school-record-row__icon"),
                row.index("school-record-row__title"),
            )

        self.assertIn("grid-template-columns: 2rem minmax(0, 1fr) auto", css)
        self.assertIn("grid-column: 1;", css)
        self.assertIn("background: transparent;", css)
        self.assertNotIn("inset-inline-start: 1.7rem", css)

    def test_directory_actions_have_compact_mobile_labels_and_consistent_icons(self):
        directory = (ROOT / "templates/partials/schools/directory_row.html").read_text()
        cluster_icon = (
            ROOT / "templates/partials/schools/_cluster_action_icon.html"
        ).read_text()
        project_icon = (
            ROOT / "templates/partials/schools/_project_action_icon.html"
        ).read_text()
        css = (ROOT / "static/css/platform.css").read_text()

        self.assertEqual(directory.count("school-record-action__label--full"), 4)
        self.assertEqual(directory.count("school-record-action__label--compact"), 4)
        self.assertEqual(directory.count("_cluster_action_icon.html"), 2)
        self.assertEqual(directory.count("_project_action_icon.html"), 2)
        self.assertIn('<circle cx="12" cy="5"', cluster_icon)
        self.assertIn("M3.5 7.5h6", project_icon)
        self.assertIn(".school-record-action__label--full { display: none; }", css)
        self.assertIn(".school-record-action__label--compact { display: inline; }", css)
