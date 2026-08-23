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
        # The recruitment funnel is on EdifyChartSystem.rankedBar now, whose
        # `colors: S.singleSeries.slice()` IS system blue — so the literal
        # array it used to declare is gone by design. Pin the preset.
        self.assertIn(
            "EdifyChartSystem.rankedBar",
            hr,
            "The single-series recruitment bar must use the shared ranked-bar "
            "form, whose palette is system Blue.",
        )

    def test_status_bars_keep_semantic_meaning(self):
        hr = _read("templates/partials/dashboards/hr/body.html")
        # Palette, not assignment syntax: the chart-preset migration builds
        # from EdifyChartSystem and then mutates, so `colors:` became
        # `colors =`. The severity ramp itself is unchanged and is what
        # actually carries the meaning.
        self.assertIn(
            "['var(--edify-chart-green)', "
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

class SharedChartFormTest(SimpleTestCase):
    """Every chart builds from EdifyChartSystem, not just its palette.

    Twelve charts across ten templates borrowed the ordered colours and then
    hand-rolled everything else — bar geometry, stroke weight, markers, grid,
    legend, tooltip. They matched on hue and differed on form, which is why
    one dashboard showed hairline bars and another slab ones, and why the
    owner could still point at a chart that did not look like the reference.
    A palette is not a design system; the form is.
    """

    def test_no_template_hand_rolls_a_chart_config(self):
        import re

        offenders = []
        preset = re.compile(
            r"EdifyChartSystem\.(formBase|areaTrend|rankedBar|comparisonBar|donut|mixedTrend)"
        )
        for path in ROOT.joinpath("templates").rglob("*.html"):
            source = path.read_text(encoding="utf-8")
            if "new ApexCharts" not in source:
                continue
            if not preset.search(source):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(
            sorted(offenders),
            [],
            "These templates create charts without a shared form: "
            + ", ".join(sorted(offenders)),
        )

class ReferenceChartFormTest(SimpleTestCase):
    """The reference form, encoded once: values on marks, no gridlines.

    The reference dashboard labels every bar and slice with its own number,
    which is what makes a ruled background redundant — the reader takes the
    value off the mark instead of tracing it to an axis. Both halves have to
    hold together: dropping the gridlines without the labels would remove the
    only way to read a value.

    The global `window.Apex` block matters as much as the presets. It merges
    into EVERY chart, so while it still declared y-axis gridlines a preset
    asking for `grid.show: false` was overruled and the rules kept rendering.
    """

    def test_gridlines_are_off_in_the_global_default_and_the_presets(self):
        base = _read("templates/base.html")

        globals_block = base.split("window.Apex = {", 1)[1]
        self.assertIn("yaxis: { lines: { show: false } }", globals_block)
        self.assertIn("xaxis: { lines: { show: false } }", globals_block)
        self.assertIn("show: false", globals_block)

    def test_bar_forms_label_their_marks(self):
        base = _read("templates/base.html")

        for preset in ("comparisonBar", "mixedTrend", "rankedBar"):
            block = base.split(preset + ": function", 1)[1].split("},\n\n", 1)[0]
            self.assertIn(
                "dataLabels", block, f"{preset} must put the value on the mark"
            )
            self.assertIn(
                "barLabelFits" if preset != "rankedBar" else "barValueFitsInside",
                block,
                f"{preset} must suppress a label that cannot fit rather than "
                "letting neighbours collide",
            )

    def test_the_rate_line_is_never_labelled_point_by_point(self):
        """A label on every point of a twelve-month line is noise."""
        base = _read("templates/base.html")

        block = base.split("mixedTrend: function", 1)[1]
        self.assertIn("enabledOnSeries: columnIndexes", block)
