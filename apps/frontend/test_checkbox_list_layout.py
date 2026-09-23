from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class CheckboxListLayoutContractTests(SimpleTestCase):
    def test_shared_selectable_school_rows_use_checkbox_first_layout(self):
        directory = (ROOT / "templates/partials/schools/directory_row.html").read_text()
        planning = (ROOT / "templates/partials/planning/school_row.html").read_text()
        css = (ROOT / "static/css/platform.css").read_text()

        self.assertIn("school-record-row__summary--selectable", directory)
        # The decorative building glyph is gone: the row leads with the
        # operational school ID, which is what staff actually quote.
        self.assertNotIn("school-record-row__icon", directory)
        self.assertLess(
            directory.index("school-record-row__select"),
            directory.index("school-record-row__school-id"),
        )
        self.assertLess(
            directory.index("school-record-row__school-id"),
            directory.index("school-record-row__title"),
        )

        # Planning is a table since 8bb11a1, in the same order: the checkbox
        # cell, the School ID cell, then the name.
        self.assertNotIn("school-record-row__icon", planning)
        self.assertLess(
            planning.index("school-record-row__select"),
            planning.index("school-plan-table__id"),
        )
        self.assertLess(
            planning.index("school-plan-table__id"),
            planning.index("school-plan-table__name"),
        )

        self.assertIn("grid-template-columns: 2rem minmax(0, 1fr) auto", css)
        self.assertIn("grid-column: 1;", css)
        self.assertIn("background: transparent;", css)
        self.assertNotIn("inset-inline-start: 1.7rem", css)

    def test_school_id_has_a_bounded_responsive_identity_track(self):
        css = (ROOT / "static/css/platform.css").read_text()
        mobile_css = (ROOT / "static/css/components/mobile-micro-ux.css").read_text()

        self.assertIn(".school-record-row__school-id", css)
        self.assertIn("fit-content(7.5rem) minmax(0, 1fr)", css)
        self.assertIn("fit-content(6rem) minmax(0, 1fr)", mobile_css)
        self.assertIn("fit-content(5rem) minmax(0, 1fr)", mobile_css)

    def test_directory_actions_have_compact_mobile_labels_and_consistent_icons(self):
        directory = (ROOT / "templates/partials/schools/directory_row.html").read_text()
        cluster_icon = (
            ROOT / "templates/partials/schools/_cluster_action_icon.html"
        ).read_text()
        project_icon = (
            ROOT / "templates/partials/schools/_project_action_icon.html"
        ).read_text()
        css = (ROOT / "static/css/platform.css").read_text()

        # Every action carries both labels — the phone shows one, the desktop
        # the other — so the two counts move together whatever actions the row
        # grows. The cluster action has three states now (add, change, and the
        # refusal), the project action two, and Schedule is the sixth: the
        # Impact Assessment role plans straight from the directory (owner,
        # 2026-09-17, "he can plan direct from the school directory. ONLY and
        # ONLY IA can plan from the school directory"). Reassign Owner is the
        # seventh, for Admin and Impact Assessment (owner, 2026-09-21): moving
        # a portfolio means moving several schools, and the directory is the
        # list a registry administrator is looking at.
        full = directory.count("school-record-action__label--full")
        self.assertEqual(full, directory.count("school-record-action__label--compact"))
        self.assertEqual(full, 7)
        self.assertEqual(directory.count("_cluster_action_icon.html"), 3)
        self.assertEqual(directory.count("_project_action_icon.html"), 2)
        self.assertIn('<circle cx="12" cy="5"', cluster_icon)
        self.assertIn("M3.5 7.5h6", project_icon)
        self.assertIn(".school-record-action__label--full { display: none; }", css)
        self.assertIn(".school-record-action__label--compact { display: inline; }", css)
