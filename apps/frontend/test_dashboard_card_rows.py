from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class DashboardCardRowContractTest(SimpleTestCase):
    """Keep role dashboards aligned without brittle fixed card heights."""

    def _source(self, relative_path):
        return (Path(settings.BASE_DIR) / relative_path).read_text()

    def test_shared_equal_height_row_utility_is_available(self):
        css = self._source("static/css/pages.css")
        self.assertIn(".edify-card-row {", css)
        self.assertIn("align-items: stretch;", css)
        self.assertIn(".pl-intelligence-card {", css)
        self.assertIn("block-size: 100%;", css)

    def test_role_dashboards_use_equal_height_rows(self):
        dashboard_templates = (
            "templates/partials/dashboards/cd/body.html",
            "templates/partials/dashboards/pl/body.html",
            "templates/partials/dashboards/hr/body.html",
            "templates/partials/analytics/cd/body.html",
            "templates/partials/analytics/pl/body.html",
            "templates/partials/debriefs/dashboard_body.html",
        )
        for path in dashboard_templates:
            source = self._source(path)
            self.assertIn("edify-card-row", source, path)
            self.assertNotIn(
                "gap-5 items-start",
                source,
                f"{path} reintroduced an uneven card row",
            )

        rvp = self._source("templates/pages/dashboards/rvp.html")
        self.assertEqual(
            rvp.count("gap-5 items-start"),
            1,
            "Only the RVP page's main content/sidebar shell may remain top-aligned.",
        )
        self.assertGreaterEqual(rvp.count("edify-card-row"), 3)

    def test_cd_dashboard_separates_tall_tables_from_compact_cards(self):
        source = self._source("templates/partials/dashboards/cd/body.html")
        self.assertIn("data-cd-risk-priority-row", source)
        self.assertIn("data-cd-priority-schools-card", source)
        self.assertLess(
            source.index("data-cd-risk-priority-row"),
            source.index("data-cd-priority-schools-card"),
        )
        self.assertIn("lg:flex-row lg:items-center", source)

    def test_cd_analytics_groups_supporting_evidence_by_decision_context(self):
        source = self._source("templates/partials/analytics/cd/body.html")
        self.assertIn("Leadership priorities", source)
        self.assertIn('data-analytics-id="cd-performance-drivers"', source)
        self.assertIn('data-analytics-id="cd-impact-delivery"', source)
        self.assertIn('data-analytics-id="cd-people-oversight"', source)
        self.assertIn('data-analytics-id="cd-finance-reporting"', source)
        self.assertEqual(source.count("data-cd-analytics-row"), 6)
        self.assertEqual(source.count("data-cd-analytics-wide-card"), 1)
        self.assertNotIn("lg:grid-cols-3 gap-5 items-start", source)

    def test_pl_dashboard_rows_fill_the_twelve_column_grid(self):
        source = self._source("templates/partials/dashboards/pl/body.html")
        team_row = source[source.index("Team Performance + Personal Targets") :]
        team_row = team_row[: team_row.index("CCEO Performance + Approval Queue")]
        self.assertIn("lg:col-span-7", team_row)
        self.assertIn("lg:col-span-5", team_row)
        self.assertNotIn("lg:col-span-4", team_row)

    def test_cd_program_lead_surfaces_show_supervised_cceo_area_results(self):
        dashboard = self._source("templates/partials/dashboards/cd/body.html")
        oversight = self._source("templates/partials/analytics/cd/pl_oversight.html")
        drawer = self._source("templates/partials/analytics/cd/drilldown.html")

        self.assertIn("Supervised CCEO Areas", dashboard)
        self.assertIn("_target_area_badges.html", dashboard)
        self.assertIn("CCEO Area Results", oversight)
        self.assertIn("Supervised CCEOs · All Target Areas", drawer)
        self.assertIn("{% for area in c.areas %}", drawer)
