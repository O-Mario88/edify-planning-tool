from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class HeavyPagePaginationContractTest(SimpleTestCase):
    def test_core_school_health_bounds_each_independent_table(self):
        source = (ROOT / "templates/pages/core_schools/leadership.html").read_text()

        self.assertIn('{% paginate d.stalledSlots "stalled_page"', source)
        self.assertIn("{% for s in stalled_pager.rows %}", source)
        self.assertIn('{% paginate d.plans "plans_page"', source)
        self.assertIn("{% for p in plans_pager.rows %}", source)
        self.assertIn('{% paginate d.districts "districts_page"', source)
        self.assertIn("{% for r in districts_pager.rows %}", source)

    def test_strategic_priorities_bounds_the_expensive_nested_forms(self):
        source = (ROOT / "templates/pages/hr/priority_configuration.html").read_text()

        self.assertIn('{% paginate milestone_rows "milestones_page" 10', source)
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
        self.assertIn('{% paginate pages "pages_page" 25', matrix)
        self.assertIn("{% for page in pages_pager.rows %}", matrix)
        self.assertIn("{% for role in roles_pager.rows %}", matrix)
