from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[2]


class ProjectFilterPlacementTests(TestCase):
    def setUp(self):
        self.template = (ROOT / "templates/pages/projects/index.html").read_text()

    def test_filter_form_is_after_the_header_card(self):
        header_start = self.template.index('<div class="edify-page-header">')
        filter_start = self.template.index('<form id="project-filters"')
        header_end = self.template.index("</div>", header_start)

        self.assertGreater(filter_start, header_end)
        self.assertIn('data-component="filter-toolbar"', self.template[filter_start:])
        self.assertIn('aria-label="Project filters"', self.template[filter_start:])

    def test_header_controls_keep_actions_but_not_filters(self):
        controls = self.template.split('<div class="edify-page-header__controls">', 1)[
            1
        ].split("</div>", 1)[0]

        self.assertNotIn("project-filters", controls)
        self.assertNotIn("project-fy-filter", controls)
        self.assertNotIn("filters-drawer", controls)
        self.assertTrue("New Project" in controls or "Add Eligible Schools" in controls)

    def test_project_filters_have_visible_labels(self):
        form = self.template.split('<form id="project-filters"', 1)[1].split(
            "</form>", 1
        )[0]

        self.assertEqual(form.count('class="edify-filter-label"'), 3)
        for label in ("Financial year", "Project type", "Status"):
            self.assertIn(label, form)
        self.assertIn("More filters", form)
        self.assertIn('hx-push-url="false"', form)

    def test_directory_mobile_rules_cannot_stack_project_filters(self):
        css = (ROOT / "static/css/consistency.css").read_text()
        contract = css.split("Directory pages opt into the canonical toolbar", 1)[
            1
        ].split("The mobile disclosure remains useful", 1)[0]

        self.assertIn("main [data-mobile-family] :is(", contract)
        self.assertIn("#project-filters,", contract)
        self.assertIn("display: flex !important;", contract)
        self.assertIn("grid-template-columns: none !important;", contract)
