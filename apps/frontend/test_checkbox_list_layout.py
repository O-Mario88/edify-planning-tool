from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class CheckboxListLayoutContractTests(SimpleTestCase):
    def test_shared_selectable_school_rows_use_checkbox_first_layout(self):
        directory = (ROOT / "templates/partials/schools/directory_row.html").read_text()
        planning = (ROOT / "templates/partials/planning/school_row.html").read_text()
        head = (ROOT / "templates/components/school_plan_table_head.html").read_text()
        css = (ROOT / "static/css/platform.css").read_text()

        self.assertIn("school-record-row__summary--selectable", directory)
        # The planning list is a table row since 8bb11a1 (the shared
        # school-plan-table); the same checkbox-first order holds in its cells
        # and in the shared header.
        self.assertIn('class="school-plan-table__select"', planning)
        self.assertIn(
            '{% if selectable %}<th scope="col" class="school-plan-table__select">',
            head,
        )
        self.assertLess(
            head.index("school-plan-table__select"), head.index("School ID")
        )
        self.assertLess(head.index("School ID"), head.index("School Name"))
        for row, school_id, title in (
            (directory, "school-record-row__school-id", "school-record-row__title"),
            (planning, "school-plan-table__id", "school-plan-table__name"),
        ):
            # The decorative building glyph is gone: the row leads with the
            # operational school ID, which is what staff actually quote.
            self.assertNotIn("school-record-row__icon", row)
            self.assertLess(
                row.index("school-record-row__select"), row.index(school_id)
            )
            self.assertLess(row.index(school_id), row.index(title))

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

    def test_directory_actions_are_one_menu_with_every_state_labelled(self):
        directory = (ROOT / "templates/partials/schools/directory_row.html").read_text()

        # One Actions menu per row (owner, 2026-09-26: "School directory
        # actions are add to cluster and Add to project"), so the phone and
        # the desktop read the same full label and nothing wraps on a tablet.
        # The cluster action has three states (add, change, and the refusal),
        # the project action two, and Schedule is the sixth: the Impact
        # Assessment role plans straight from the directory (owner,
        # 2026-09-17, "he can plan direct from the school directory. ONLY and
        # ONLY IA can plan from the school directory"). Reassign Owner is the
        # seventh, for Admin and Impact Assessment (owner, 2026-09-21): moving
        # a portfolio means moving several schools, and the directory is the
        # list a registry administrator is looking at.
        self.assertEqual(directory.count("{% row_actions school.school_name %}"), 1)
        self.assertEqual(directory.count('class="row-menu__item"'), 7)
        self.assertEqual(directory.count('role="menuitem"'), 7)
        self.assertNotIn("school-record-action", directory)
        for label in (
            ">Schedule<",
            ">Add to Cluster<",
            ">Change Cluster<",
            ">Reassign Owner<",
            ">Add to Project<",
        ):
            self.assertIn(label, directory)
        # The two refusals stay on the list, greyed; the cluster one says why.
        self.assertEqual(directory.count('aria-disabled="true"'), 2)
        self.assertIn(
            '<span class="row-menu__reason">{{ school.disabled_reasons.add_to_cluster }}</span>',
            directory,
        )
