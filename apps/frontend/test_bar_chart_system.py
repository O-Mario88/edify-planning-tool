from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class BarChartSystemContractTest(SimpleTestCase):
    """Keep comparison bars visually ordered across every dashboard."""

    COMPARISON_CHARTS = (
        "static/js/alpine-components.js",
        "templates/partials/analytics/cd/performance_vs_target.html",
        "templates/partials/analytics/cd/target_by_pl.html",
        "templates/partials/analytics/performance_overview.html",
        "templates/partials/analytics/pl/staff_partner.html",
        "templates/partials/analytics/pl/team_performance.html",
        "templates/partials/dashboards/cd/body.html",
        "templates/partials/dashboards/pl/body.html",
        "templates/partials/dashboards/pl/team_performance.html",
        "templates/pages/dashboards/rvp.html",
    )

    def test_ordered_series_tokens_are_blue_orange_green(self):
        tokens = _read("static/css/design-system.css")
        primary = tokens.index("--edify-chart-series-primary: var(--edify-chart-blue);")
        secondary = tokens.index(
            "--edify-chart-series-secondary: var(--edify-chart-orange);"
        )
        tertiary = tokens.index(
            "--edify-chart-series-tertiary: var(--edify-chart-green);"
        )
        self.assertLess(primary, secondary)
        self.assertLess(secondary, tertiary)
        self.assertIn("--edify-chart-bar-track:", tokens)

    def test_global_apex_defaults_match_reference_chart_geometry(self):
        base = _read("templates/base.html")
        self.assertIn("window.EdifyChartSystem", base)
        self.assertIn("colors: window.EdifyChartSystem.comparisonSeries", base)
        self.assertIn("columnWidth: '54%'", base)
        self.assertIn("barHeight: '58%'", base)
        self.assertIn("borderRadius: 4", base)
        self.assertIn("borderRadiusApplication: 'end'", base)
        self.assertIn("backgroundBarOpacity: 0", base)
        self.assertIn("stroke: { curve: 'straight', width: 2", base)
        self.assertIn("size: 4", base)
        self.assertIn("strokeWidth: 2", base)

        tokens = _read("static/css/design-system.css")
        self.assertIn("--edify-chart-blue: var(--brand-primary);", tokens)
        self.assertIn("--edify-chart-tooltip: #111827;", tokens)

    def test_line_charts_use_direct_segments_instead_of_smoothed_curves(self):
        line_charts = (
            "templates/partials/analytics/cd/performance_vs_target.html",
            "templates/partials/analytics/performance_overview.html",
            "templates/partials/analytics/pl/core_champion.html",
            "templates/partials/analytics/pl/team_performance.html",
            "templates/partials/dashboards/cd/body.html",
            "templates/partials/dashboards/hr/body.html",
            "templates/partials/dashboards/pl/body.html",
            "templates/partials/dashboards/pl/team_performance.html",
            "templates/partials/debriefs/dashboard_body.html",
            "templates/partials/targets/my_body.html",
            "templates/pages/dashboards/rvp.html",
        )
        for relative_path in line_charts:
            source = _read(relative_path)
            self.assertNotIn(
                "curve: 'smooth'",
                source,
                f"{relative_path} should use the reference's direct line segments",
            )

    def test_comparison_charts_use_the_shared_ordered_palette(self):
        for relative_path in self.COMPARISON_CHARTS:
            source = _read(relative_path)
            self.assertIn(
                "EdifyChartSystem",
                source,
                f"{relative_path} must use the shared Blue / Orange / Green order",
            )

        hr = _read("templates/partials/dashboards/hr/body.html")
        self.assertIn(
            "'var(--edify-chart-green)', "
            "'var(--edify-chart-blue)', "
            "'var(--edify-chart-orange)'",
            hr,
            "The HR line is green so its two bar series remain Blue then Orange.",
        )
        self.assertIn(
            "colors: ['var(--edify-chart-blue)']",
            hr,
            "The single-series recruitment bar must use system Blue.",
        )

    def test_status_bars_keep_semantic_meaning(self):
        hr = _read("templates/partials/dashboards/hr/body.html")
        self.assertIn(
            "colors: ['var(--edify-chart-green)', "
            "'var(--edify-chart-amber)', 'var(--edify-chart-red)']",
            hr,
        )
        self.assertIn("backgroundBarOpacity: 0", hr)

        custom = _read("static/css/pages/special-project-analytics.css")
        self.assertIn(
            ".spa-score-bars i { display:block; height:100%; "
            "border-radius:inherit; background:var(--edify-chart-series-primary);",
            custom,
        )
        self.assertIn(
            ".spa-score-bars span:last-child i { "
            "background:var(--edify-chart-series-secondary);",
            custom,
        )

        projects = _read("templates/pages/projects/index.html")
        self.assertIn(
            "Partner-led</span>",
            projects,
        )
        self.assertIn(
            "background:var(--edify-chart-series-secondary)",
            projects,
        )
