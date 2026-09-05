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
    def test_a_frozen_column_is_opaque(self):
        """"The frozen first column on the tables should not be transparent":
        the cells that stay put while the rest scroll under them wear the
        solid surface, not the row's translucent tint."""
        css = _read("static/css/pages.css")
        self.assertIn(
            ".tt-member-row > td:first-child { position: sticky; left: 0; z-index: 1; "
            "background: var(--edify-surface); }",
            css,
        )
        action = css.split(".tt-member-row > td.tt-matrix__action-cell {", 1)[1][:400]
        self.assertIn("background: var(--edify-surface);", action)
        # Hover mixes the accent INTO the surface, so it stays opaque too.
        self.assertIn(
            ".tt-member-row:hover > td:first-child { background: color-mix(in oklab, "
            "var(--edify-accent) 9%, var(--edify-surface)); }",
            css,
        )
        platform = _read("static/css/platform.css")
        label = platform.split(":is(.period-matrix, .tt-area-matrix-shell--matrix > .tt-area-matrix) .period-matrix__label {", 1)[1][:400]
        self.assertIn("position: sticky;", label)
        self.assertIn("background: var(--edify-surface);", label)


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
        self.assertIn("js/micro-ux.js' %}?v=20260905targets1", base)
        self.assertIn("mobile-micro-ux.css' %}?v=20260905targets1", base)


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
