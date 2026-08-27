from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class DashboardCardRowContractTest(SimpleTestCase):
    """Keep role dashboards aligned without equal-height blank interiors."""

    def _source(self, relative_path):
        return (Path(settings.BASE_DIR) / relative_path).read_text()

    def test_shared_card_rows_use_intrinsic_heights(self):
        css = self._source("static/css/pages.css")
        self.assertIn(".edify-card-row {", css)
        self.assertIn("align-items: start;", css)
        self.assertIn(".pl-intelligence-card {", css)
        self.assertIn("block-size: auto;", css)
        card_row = css.split(".edify-card-row {", 1)[1].split("}", 1)[0]
        self.assertNotIn("stretch", card_row)

    def test_role_dashboards_use_shared_intrinsic_height_rows(self):
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
        team_row = team_row[: team_row.index("CCEO Performance owns the full row")]
        self.assertIn("lg:col-span-7", team_row)
        self.assertIn("lg:col-span-5", team_row)
        self.assertNotIn("lg:col-span-4", team_row)

    def test_pl_cceo_performance_owns_full_row_without_approval_queue(self):
        source = self._source("templates/partials/dashboards/pl/body.html")
        cceo_row = source[source.index("data-pl-cceo-performance-row") :]
        cceo_row = cceo_row[: cceo_row.index("Schools Needing Urgent Attention")]

        self.assertIn("lg:col-span-12", cceo_row)
        self.assertIn('aria-labelledby="pl-cceo-performance-title"', cceo_row)
        self.assertNotIn("Approval Queue", cceo_row)
        self.assertNotIn("dashboards/pl/approval_queue.html", cceo_row)

    def test_main_dashboard_gives_cluster_performance_the_wide_lower_track(self):
        template = self._source("templates/pages/dashboards/main.html")
        css = self._source("static/css/admin-dashboard.css")
        lower_row = template[template.index('class="admin-grid admin-grid--lower"') :]
        lower_row = lower_row[: lower_row.index("</div>\n    </div>")]

        self.assertLess(
            lower_row.index('class="admin-panel admin-clusters"'),
            lower_row.index('class="admin-stack"'),
        )
        self.assertIn(
            "grid-template-columns: minmax(0, 1.45fr) minmax(17rem, 0.72fr)",
            css,
        )
        self.assertIn(
            ".admin-grid--lower :is(.admin-mini-grid, .admin-budget-grid)", css
        )

    def test_cd_program_lead_surfaces_show_supervised_cceo_area_results(self):
        dashboard = self._source("templates/partials/dashboards/cd/body.html")
        oversight = self._source("templates/partials/analytics/cd/pl_oversight.html")
        drawer = self._source("templates/partials/analytics/cd/drilldown.html")

        self.assertIn("Supervised CCEO Areas", dashboard)
        self.assertIn("_target_area_badges.html", dashboard)
        self.assertIn("CCEO Area Results", oversight)
        self.assertIn("Supervised CCEOs · All Target Areas", drawer)
        self.assertIn("{% for area in c.areas %}", drawer)
