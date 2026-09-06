"""Frozen columns, the period matrix, the tile heuristic, the SSA filter row.

The owner's 2026-09-05 review of the target and report surfaces, pinned at
source so the fixes cannot drift back.
"""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class FrozenColumnContractTest(SimpleTestCase):
    """"The frozen first column on the tables should not be transparent."

    A sticky column is a curtain the rest of the row scrolls behind. It is
    opaque in every theme only when painted over the page background, because
    the blue theme's surface is itself a 58% glass — so every frozen cell on
    the platform paints --edify-frozen-surface, never a bare surface or a
    translucent utility.
    """

    def test_the_frozen_surface_tokens_paint_over_the_page_background(self):
        tokens = _read("static/css/design-system.css")
        self.assertIn(
            "--edify-frozen-surface: linear-gradient(var(--edify-surface), var(--edify-surface)), var(--edify-bg);",
            tokens,
        )
        self.assertIn(
            "--edify-frozen-surface-muted: linear-gradient(var(--edify-surface-muted), var(--edify-surface-muted)), var(--edify-bg);",
            tokens,
        )

    def test_every_stylesheet_frozen_column_paints_the_token(self):
        pages = _read("static/css/pages.css")
        self.assertIn(
            ".tt-member-row > td:first-child { position: sticky; left: 0; z-index: 1; background: var(--edify-frozen-surface); }",
            pages,
        )
        action = pages.split(".tt-member-row > td.tt-matrix__action-cell {", 1)[1][:400]
        self.assertIn("background: var(--edify-frozen-surface);", action)
        area = pages.split(".tt-matrix .tt-area-matrix th:first-child {", 1)[1][:300]
        self.assertIn("background: var(--edify-frozen-surface-muted);", area)
        platform = _read("static/css/platform.css")
        label = platform.split(":is(.period-matrix, .tt-area-matrix-shell--matrix > .tt-area-matrix) .period-matrix__label {", 1)[1][:400]
        self.assertIn("position: sticky;", label)
        self.assertIn("background: var(--edify-frozen-surface);", label)
        self.assertIn("main table .edify-frozen-cell {", platform)
        report = platform.split(".edify-report-matrix__table :is(th, td):first-child {", 1)[1][:300]
        self.assertIn("background: var(--edify-frozen-surface);", report)
        analytics = _read("static/css/pages/analytics-dashboard.css")
        impact = analytics.split('.impact-analysis-table tbody th[scope="row"] {', 1)[1][:300]
        self.assertIn("background: var(--edify-frozen-surface);", impact)

    def test_no_template_freezes_a_cell_with_a_bare_utility(self):
        """A `sticky left-0` cell with a translucent utility (bg-slate-50/60,
        bg-violet-50/30) or a bare surface is the bug; the frozen-cell class
        is the only way a template freezes a column."""
        offenders = []
        for path in ROOT.joinpath("templates").rglob("*.html"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "sticky left-0" in line or "sticky inset-inline-start-0" in line:
                    offenders.append(f"{path.relative_to(ROOT)}: {line.strip()[:80]}")
        self.assertEqual(offenders, [])
        for path in (
            "templates/partials/finance/country_budget/root.html",
            "templates/partials/targets/team/matrix_drawer.html",
        ):
            self.assertIn("edify-frozen-cell", _read(path), path)


class PeriodMatrixContractTest(SimpleTestCase):
    def test_one_matrix_serves_my_target_and_every_team_member_row(self):
        shared = _read("templates/partials/targets/_period_matrix.html")
        self.assertIn("Cumulative progress by time period", shared)
        for measure in (">Target</th>", ">Achieved</th>", ">%</th>"):
            self.assertIn(measure, shared)
        my_body = _read("templates/partials/targets/my_body.html")
        team_body = _read("templates/partials/targets/team/body.html")
        self.assertIn('with rows=matrix_rows heads=matrix_heads', my_body)
        self.assertIn('with variant="team" rows=member.period_matrix_rows', team_body)
        # The team member's dict carries the normalised rows the partial reads.
        service = _read("apps/targets/team_targets.py")
        self.assertIn('"period_matrix_rows": period_matrix_rows,', service)
        self.assertIn('"period_matrix_overall": period_matrix_overall,', service)

    def test_my_target_matrix_is_an_accordion(self):
        my_body = _read("templates/partials/targets/my_body.html")
        # The table leads the page; the six period cards it replaces are gone,
        # and the no-priorities state stands where the table would.
        self.assertNotIn("target-period-progression", my_body)
        self.assertLess(my_body.index("_period_matrix.html"), my_body.index("strategic_priority_overview.html"))
        self.assertEqual(my_body.count("no-performance-priorities-title"), 2)
        section = my_body.split("Operational agreements + approved strategic", 1)[1]
        self.assertIn('<details class="edify-disclosure" open>', section)
        self.assertIn('<h2 id="my-cumulative-progress-title">Cumulative progress by time period</h2>', section)
        self.assertIn('class="edify-disclosure__chevron"', section)
        platform = _read("static/css/platform.css")
        self.assertIn("main .edify-disclosure > summary {", platform)
        self.assertIn("main .edify-disclosure[open] > summary > .edify-disclosure__chevron { transform: rotate(180deg); }", platform)

    def test_the_team_row_scrolls_the_wide_matrix_instead_of_clipping_it(self):
        team_body = _read("templates/partials/targets/team/body.html")
        self.assertIn('class="tt-area-matrix-shell tt-area-matrix-shell--matrix"', team_body)
        platform = _read("static/css/platform.css")
        self.assertIn(".tt-area-matrix-shell--matrix { overflow-x: auto;", platform)
        self.assertIn(":is(.period-matrix, .tt-area-matrix-shell--matrix > .tt-area-matrix) th,", platform)


class ComposedCardTileContractTest(SimpleTestCase):
    def test_the_tile_heuristic_leaves_a_composed_cards_text_block_alone(self):
        """The Reports period card is a text block beside a gauge inside one
        surface. The heuristic painted the text block as a second tile — a
        gradient box 90px wide with "Achieved (no target set)" wrapping word
        by word. A block that shares its surface with other blocks is a part,
        not a tile."""
        js = _read("static/js/micro-ux.js")
        self.assertIn(
            "if (host && host.matches('.edify-surface, [class*=\"rounded-surface\"]') "
            "&& host.children.length > 1) return;",
            js,
        )
        base = _read("templates/base.html")
        # The stylesheet and the script it drives share one cache key.
        self.assertIn("js/micro-ux.js' %}?v=20260906desk5", base)
        self.assertIn("mobile-micro-ux.css' %}?v=20260906desk5", base)


class SsaFilterRowContractTest(SimpleTestCase):
    def test_ssa_performance_filters_share_one_row(self):
        css = _read("static/css/pages.css")
        self.assertIn(
            "#ssa-performance-workspace .sp-filter-grid {\n"
            "  grid-template-columns: repeat(3, minmax(0, 1fr)) auto;\n}",
            css,
        )
        tablet = css.split("@media (max-width: 1024px) {", 1)[1][:700]
        self.assertIn(
            "#ssa-performance-workspace .sp-filter-grid { grid-template-columns: repeat(3, minmax(0, 1fr)) auto; }",
            tablet,
        )
        self.assertIn("#ssa-performance-workspace .sp-filter-actions { grid-column: auto; }", tablet)


class YearComparisonWordingTest(SimpleTestCase):
    def test_a_year_comparison_names_both_years_the_way_the_owner_reads_it(self):
        ssa = _read("templates/partials/ssa/performance_workspace.html")
        self.assertIn(
            'SSA performance FY{{ dashboard.improvement_monitor.baseline_fy|slice:"2:" }} '
            'vs FY{{ dashboard.improvement_monitor.comparison_fy|slice:"2:" }}',
            ssa,
        )
        self.assertNotIn("baseline →", ssa)
        for path in (
            "templates/partials/analytics/panels/visit_effectiveness.html",
            "templates/pages/analytics/visit_effectiveness.html",
        ):
            source = _read(path)
            self.assertIn(
                'SSA performance FY{{ d.methodology.baseline_fy|slice:"-2:" }} '
                'vs FY{{ d.methodology.followup_fy|slice:"-2:" }}',
                source,
                path,
            )
            self.assertNotIn("{{ d.methodology.baseline_fy }} → ", source, path)

    def test_no_template_joins_two_years_with_an_arrow(self):
        import re

        arrow = re.compile(r"FY[^<\n]{0,24}→[^<\n]{0,8}FY")
        offenders = []
        for path in ROOT.joinpath("templates").rglob("*.html"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.lstrip().startswith(("{#", "{% comment")):
                    continue
                if arrow.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}: {line.strip()[:80]}")
        self.assertEqual(offenders, [])
