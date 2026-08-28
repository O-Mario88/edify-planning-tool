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

    def test_main_dashboard_packs_two_intrinsic_columns_beside_the_rail(self):
        """The admin workspace can never show a hole beside a card.

        Fixed two-panel rows sized every row to its taller panel, so each
        pairing of a long table with a short snapshot left a blank block
        under the short one — and the workspace's desktop two-column rule
        once lived only inside a container query, which rendered the action
        rail as a full-width stack of thin cards on any desktop. The layout
        is now two self-packing columns (tables left, snapshots right)
        beside a genuine rail, each stacking its own cards tightly.
        """
        template = self._source("templates/pages/dashboards/main.html")
        css = self._source("static/css/admin-dashboard.css")

        tables = template[template.index('class="admin-col admin-col--tables"') :]
        tables = tables[: tables.index('class="admin-col admin-col--signals"')]
        for panel in ("admin-priorities", "admin-priority-schools", "admin-clusters"):
            self.assertIn(panel, tables)

        signals = template[template.index('class="admin-col admin-col--signals"') :]
        signals = signals[: signals.index("<aside")]
        for panel in (
            "admin-planning-progress",
            "admin-ssa",
            "admin-partners",
            "admin-budget",
        ):
            self.assertIn(panel, signals)

        # The rail sits BESIDE the workspace at desktop widths — this base
        # rule regressing into a container query is exactly the defect above.
        workspace = css.split(".admin-workspace {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(17.5rem", workspace)
        main = css.split(".admin-workspace__main {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-template-columns: minmax(0, 1.38fr) minmax(0, 1fr)", main)
        self.assertIn(".admin-col { align-content: start; }", css)

    def test_cd_program_lead_surfaces_show_supervised_cceo_area_results(self):
        dashboard = self._source("templates/partials/dashboards/cd/body.html")
        oversight = self._source("templates/partials/analytics/cd/pl_oversight.html")
        drawer = self._source("templates/partials/analytics/cd/drilldown.html")

        self.assertIn("Supervised CCEO Areas", dashboard)
        self.assertIn("_target_area_badges.html", dashboard)
        self.assertIn("CCEO Area Results", oversight)
        self.assertIn("Supervised CCEOs · All Target Areas", drawer)
        self.assertIn("{% for area in c.areas %}", drawer)


class TemplateCommentSyntaxTest(SimpleTestCase):
    """A `{# #}` comment is single-line only; a wrapped one leaks onto the page.

    Django's hash comment ends at the first `#}` on the SAME line. Wrap one
    over several lines and the tag never closes: the opener plus every line
    after it renders as visible text — a paragraph of design rationale
    printed across the top of a dashboard. `{% comment %}` is the multi-line
    form. Caught in review on two role dashboards; this keeps the next one
    from shipping.
    """

    def test_no_template_wraps_a_hash_comment_over_several_lines(self):
        import re
        from pathlib import Path

        from django.conf import settings

        pattern = re.compile(r"\{#(?:(?!#\}).)*?\n", re.S)
        offenders = [
            str(path.relative_to(Path(settings.BASE_DIR)))
            for path in (Path(settings.BASE_DIR) / "templates").rglob("*.html")
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(
            offenders,
            [],
            "Multi-line {# #} comments render as page text; use "
            f"{{% comment %}}: {offenders}",
        )
