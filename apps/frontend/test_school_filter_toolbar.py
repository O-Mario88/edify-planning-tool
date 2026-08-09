from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class SchoolFilterToolbarContractTests(SimpleTestCase):
    def test_clear_action_is_the_final_item_in_the_filter_grid(self):
        template = (ROOT / "templates/pages/schools/index.html").read_text()
        grid = template.split('<div class="school-filter-grid grid gap-3">', 1)[1]
        grid = grid.split("</form>", 1)[0]

        self.assertEqual(grid.count("<select"), 5)
        self.assertIn(
            'include "partials/schools/directory_sub_county_filter.html"',
            grid,
        )
        self.assertIn('class="school-filter-clear ', grid)
        self.assertLess(grid.rindex("<select"), grid.index("school-filter-clear"))
        self.assertNotIn('class="flex items-center justify-between pt-1"', grid)

    def test_desktop_filter_grid_uses_one_full_width_row_with_consistent_padding(self):
        css = (ROOT / "static/css/platform.css").read_text()

        self.assertIn(
            "#filters-form.school-filters-form {\n  display: block !important;",
            css,
        )
        self.assertIn(
            "grid-template-columns: repeat(6, minmax(0, 1fr)) max-content !important;",
            css,
        )
        self.assertIn(
            'main [data-mobile-family="directory"] #filters-form.school-filters-form',
            css,
        )
        self.assertIn("padding: 0.875rem 1rem 1rem !important;", css)
        self.assertIn("align-items: end;", css)

    def test_tablet_filter_grid_wins_after_the_consistency_bridge(self):
        css = (ROOT / "static/css/components/mobile-micro-ux.css").read_text()

        self.assertIn("main #filters-form .school-filter-grid", css)
        self.assertIn("display: grid !important", css)
        self.assertIn(
            "grid-template-columns: repeat(6, minmax(0, 1fr)) max-content !important;",
            css,
        )
