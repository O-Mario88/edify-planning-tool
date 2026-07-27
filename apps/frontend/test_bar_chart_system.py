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

    def test_global_apex_defaults_supply_polished_bar_geometry(self):
        base = _read("templates/base.html")
        self.assertIn("window.EdifyChartSystem", base)
        self.assertIn("colors: window.EdifyChartSystem.comparisonSeries", base)
        self.assertIn("barHeight: '62%'", base)
        # Large enough to read as a pill cap at every bar thickness. ApexCharts
        # clamps the radius to half the bar, so this rounds fully rather than
        # overshooting on a thin one.
        self.assertIn("borderRadius: 14", base)
        self.assertIn("borderRadiusApplication: 'end'", base)
        self.assertIn("backgroundBarColors: ['var(--edify-surface-muted)']", base)

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
