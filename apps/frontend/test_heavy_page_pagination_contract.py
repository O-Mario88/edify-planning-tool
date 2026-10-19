from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class HeavyPagePaginationContractTest(SimpleTestCase):
    def test_strategic_priorities_bounds_the_expensive_nested_forms(self):
        # The page became the Priority Setting TAB of the Priorities page on
        # 2026-09-07; the markup this bounds moved into the view the rail
        # swaps, and the page around it is now the rail and nothing else.
        source = (ROOT / "templates/partials/priorities/setting_view.html").read_text()

        self.assertIn('{% paginate milestone_rows "milestones_page" as', source)
        self.assertIn("{% for item in milestones_pager.rows %}", source)
        self.assertIn(
            '{% include "components/table_pager.html" with pager=milestones_pager',
            source,
        )

    def test_finance_blockers_and_access_matrix_are_bounded(self):
        blocked = (ROOT / "templates/pages/accounts/blocked.html").read_text()
        matrix = (ROOT / "templates/pages/admin/page_access_matrix.html").read_text()

        self.assertIn('{% paginate blocked "blocked_page"', blocked)
        self.assertIn("{% for item in blocked_pager.rows %}", blocked)
        self.assertIn('{% paginate pages "pages_page" as', matrix)
        self.assertIn("{% for page in pages_pager.rows %}", matrix)
        self.assertIn("{% for role in roles_pager.rows %}", matrix)
