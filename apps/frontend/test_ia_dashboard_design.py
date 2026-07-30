"""IA dashboard hierarchy and interaction contract."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "pages" / "ia" / "analytics_dashboard.html"
CSS = ROOT / "static" / "css" / "ia-dashboard.css"


class IADashboardDesignContractTest(SimpleTestCase):
    def setUp(self):
        self.template = TEMPLATE.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")

    def test_dashboard_has_one_clear_operational_hierarchy(self):
        # One page heading. Matched loosely: the shared page-title class on
        # the h1 is required by the design-system title contract, so a
        # literal bare-tag match would put the two gates in contradiction.
        import re

        self.assertEqual(
            len(re.findall(r"<h1[^>]*>Impact Assessment</h1>", self.template)), 1
        )
        self.assertEqual(self.template.count('id="ia-queue-title"'), 1)
        self.assertEqual(self.template.count("<h3>Queue ownership</h3>"), 1)
        self.assertNotIn("legacy-kpi-strip", self.template)
        self.assertNotIn('include "components/kpi_strip.html"', self.template)
        self.assertNotIn("Quick Actions / Workflows", self.template)

    def test_primary_work_is_actionable_without_scanning_the_page(self):
        for href in (
            "/ia/verification/",
            "/ssa/verification/",
            "/evidence/",
            "/ia/returned/",
            "/ia/duplicates/",
        ):
            with self.subTest(href=href):
                self.assertIn(f'href="{href}"', self.template)
        self.assertIn('href="{{ item.review_url }}"', self.template)
        self.assertIn("Oldest work is shown first", self.template)

    def test_layout_is_component_responsive_and_motion_safe(self):
        self.assertIn("container: ia-queue / inline-size", self.css)
        self.assertIn("@container ia-queue", self.css)
        self.assertIn("repeat(auto-fit", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertIn("overscroll-behavior-x: contain", self.css)
