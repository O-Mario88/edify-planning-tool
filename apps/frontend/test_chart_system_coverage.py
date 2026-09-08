"""Every chart on the platform is drawn through the chart system.

The owner asked for the remaining hand-drawn charts to move onto the chart
system (2026-09-05): the IA eight-week activity flow and the team performance
trend (SVG polylines), the Reports cumulative-progress columns (CSS bars) and
target-health bar, and the budget and funding gauges (conic gradients). Two
forms were added for them — lineTrend and gauge — and this suite is what keeps
a hand-drawn chart from coming back.
"""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    from apps.frontend.template_families import read_template

    return read_template(ROOT, relative_path)


CONVERTED = {
    "templates/partials/ia/dashboard_body.html": "EdifyChartSystem.lineTrend(2)",
    "templates/partials/targets/team/body.html": "EdifyChartSystem.lineTrend(1)",
    "templates/partials/ssa/performance_workspace.html": "EdifyChartSystem.formBase(",
    "templates/partials/analytics/panels/reports.html": "EdifyChartSystem.comparisonBar()",
    "templates/partials/analytics/cd/budget_finance.html": "EdifyChartSystem.gauge(",
    "templates/partials/dashboards/pl/funding_execution.html": "EdifyChartSystem.gauge(",
    "templates/pages/partners/index.html": "EdifyChartSystem.donut(",
}


class ChartSystemCoverageTest(SimpleTestCase):
    def test_the_two_new_forms_exist(self):
        base = _read("templates/base.html")
        self.assertIn("lineTrend: function (seriesCount, opts)", base)
        self.assertIn("gauge: function (tone, label, opts)", base)
        gauge = base.split("gauge: function", 1)[1].split("/* FREEZE-01", 1)[0]
        self.assertIn("type: 'radialBar'", gauge)
        # A gauge's ring wears a semantic tone, never a palette hue by accident.
        for tone in ("success", "warning", "danger"):
            self.assertIn(f"{tone}:", gauge)

    def test_every_converted_chart_names_its_form_and_renders_detached(self):
        for path, form in CONVERTED.items():
            with self.subTest(path=path):
                source = _read(path)
                self.assertIn(form, source)
                self.assertIn("EdifyChartSystem.renderDetached(", source)

    def test_no_template_draws_a_chart_by_hand(self):
        """A polyline series, a conic-gradient ring or a CSS column is a chart
        outside the system: no palette, no legend, no shared axes."""
        offenders = []
        for path in ROOT.joinpath("templates").rglob("*.html"):
            source = path.read_text(encoding="utf-8")
            for marker in (
                "<polyline",
                "conic-gradient(",
                "tt-line-chart__series",
                "ia-line-chart__series",
            ):
                if marker in source:
                    offenders.append(f"{path.relative_to(ROOT)}: {marker}")
        self.assertEqual(offenders, [])
        reports = _read("templates/partials/analytics/panels/reports.html")
        self.assertNotIn('style="height: {% if period.pct', reports)
        self.assertNotIn("Simple stacked bar", reports)

    def test_the_reports_trend_reads_plain_rows_from_the_view(self):
        view = _read("apps/frontend/views/extended_views.py")
        self.assertIn('"reports_trend_payload": [', view)
        reports = _read("templates/partials/analytics/panels/reports.html")
        self.assertIn('json_script:"reports-trend-payload"', reports)
        # The responsive hook the layout contract pins stays on the chart's wrapper.
        self.assertIn('<div class="edify-report-trend-chart w-full"', reports)

    def test_the_ia_view_no_longer_computes_svg_geometry(self):
        view = _read("apps/frontend/views/ia_views.py")
        self.assertNotIn("planned_points", view)
        self.assertIn(
            'activity_trend = {"weeks": weekly_values, "max": trend_max}', view
        )

    def test_pages_that_draw_charts_load_the_library(self):
        for page in (
            "templates/pages/ia/analytics_dashboard.html",
            "templates/pages/oversight/team_planning.html",
            "templates/pages/targets/team.html",
            "templates/pages/reports/index.html",
            "templates/pages/partners/index.html",
        ):
            with self.subTest(page=page):
                self.assertIn('include "partials/vendor/apexcharts.html"', _read(page))


class ChartTeardownTest(SimpleTestCase):
    """A chart dies with the panel that held it.

    ApexCharts watches its own parent with a ResizeObserver, so removing the
    panel reads to it as a resize to nothing: it recomputes geometry from an
    element that no longer measures and writes width="NaN" into the SVG. On a
    dashboard view tab that was a console error on roughly half of all swaps
    (2026-09-06). The observer fires before htmx settles, so the teardown has
    to happen before the swap, not after it.
    """

    def setUp(self):
        self.base = _read("templates/base.html")

    def test_every_chart_is_tracked_when_it_is_created(self):
        self.assertIn("_live: []", self.base)
        self.assertIn(
            "window.EdifyChartSystem._live.push({ el: el, chart: chart });", self.base
        )

    def test_a_replacing_swap_destroys_the_charts_it_discards(self):
        self.assertIn("destroyInside: function (root)", self.base)
        self.assertIn("htmx:beforeSwap", self.base)
        self.assertIn(
            "window.EdifyChartSystem.destroyInside(detail.target);", self.base
        )
        # Only the styles that discard the target's content.
        self.assertIn(
            "if (style === 'innerhtml' || style === 'outerhtml' || style === 'delete') {",
            self.base,
        )

    def test_an_appending_swap_leaves_its_charts_alone(self):
        """beforeend/afterbegin keep what is already there — and its charts."""
        start = self.base.index("_live: []")
        handler = self.base[self.base.index("htmx:beforeSwap", start) :]
        handler = handler[: handler.index("htmx:afterSettle")]
        for style in ("beforeend", "afterbegin", "beforebegin", "afterend"):
            with self.subTest(style=style):
                self.assertNotIn("'" + style + "'", handler)

    def test_a_slot_that_leaves_mid_render_is_not_settled_into(self):
        self.assertIn("if (!el.isConnected) {", self.base)
        self.assertIn("window.EdifyChartSystem._forget(chart);", self.base)

    def test_the_settle_sweep_stays_as_the_backstop(self):
        self.assertIn("sweepDetached: function ()", self.base)
        self.assertIn("window.EdifyChartSystem.sweepDetached();", self.base)
