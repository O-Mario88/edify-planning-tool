"""IA dashboard hierarchy and interaction contract."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "pages" / "ia" / "analytics_dashboard.html"
CSS = ROOT / "static" / "css" / "ia-dashboard.css"
QUEUE_TEMPLATE = ROOT / "templates" / "pages" / "ia" / "verification_queue.html"
QUEUE_TABLE = ROOT / "templates" / "pages" / "ia" / "partials" / "queue_table.html"
REVIEW_TEMPLATE = ROOT / "templates" / "pages" / "ia" / "review_workspace.html"


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
            len(
                re.findall(r"<h1[^>]*>Impact Assessment Dashboard</h1>", self.template)
            ),
            1,
        )
        self.assertEqual(self.template.count('id="ia-queue-title"'), 1)
        self.assertEqual(self.template.count("<h3>Queue ownership</h3>"), 1)
        self.assertNotIn("edify-kpi-strip", self.template)
        self.assertNotIn("Quick Actions / Workflows", self.template)

    def test_summary_metrics_use_the_one_approved_kpi_component(self):
        """The 2026-07-30 redesign gave this page a bespoke `ia-metric` tile.

        That made it the only page in the platform with a third KPI treatment,
        and the 2026-07-31 consistency mandate is explicit: one approved
        independent KPI Strip, page-local tiles migrated onto it rather than
        maintained beside it. The strip is the real component, not the
        `edify-kpi-strip` adapter that wraps older bespoke grids.
        """
        self.assertIn('include "components/kpi_strip.html"', self.template)
        self.assertNotIn("ia-metric-grid", self.template)
        self.assertNotIn('class="ia-metric"', self.template)

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
        # The queue states its own ordering. This used to live in a KPI tile's
        # helper text, which put the explanation of the sort somewhere other
        # than the thing being sorted.
        self.assertIn("Prioritized by time waiting", self.template)

    def test_country_oversight_covers_every_required_dimension(self):
        self.assertIn("Activities and verification performance", self.template)
        self.assertIn("Eight-week activity flow", self.template)
        self.assertIn("Regional performance", self.template)
        self.assertIn("District monitoring", self.template)
        self.assertIn("CCEO and Program Lead performance", self.template)
        self.assertIn("activity_trend.planned_points", self.template)
        self.assertIn("district_performance", self.template)
        self.assertIn("leadership_performance", self.template)
        self.assertIn("align-items: start", self.css)

    def test_reporting_period_sits_below_the_reporting_scope(self):
        scope = "results enter finance, targets and leadership analytics."
        period = "{{ date_range }}"
        action = "Review verification queue"

        self.assertEqual(self.template.count(period), 1)
        self.assertEqual(self.template.count("Last upload:"), 1)
        self.assertLess(self.template.index(scope), self.template.index(period))
        self.assertLess(self.template.index(period), self.template.index(action))

    def test_layout_is_component_responsive_and_motion_safe(self):
        self.assertIn('class="ia-dashboard edify-page-canvas"', self.template)
        self.assertNotIn("padding: clamp(1rem, 2vw, 1.5rem)", self.css)
        self.assertNotIn("width: min(100%, 92rem)", self.css)
        self.assertIn("container: ia-queue / inline-size", self.css)
        self.assertIn(".ia-queue-table-scroll", self.css)
        self.assertIn("min-width: 44rem", self.css)
        self.assertIn("repeat(auto-fit", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertIn("overscroll-behavior-x: contain", self.css)

    def test_pending_queue_is_a_native_scrollable_table_at_every_width(self):
        self.assertIn(
            '<table class="ia-queue-table" data-mobile-table="scroll">',
            self.template,
        )
        self.assertIn("<caption", self.template)
        self.assertIn('<th scope="col">Record</th>', self.template)
        self.assertNotIn('role="table"', self.template)
        self.assertNotIn(".ia-queue-table__header {\n    display: none", self.css)

    def test_report_tile_titles_do_not_wrap_at_intermediate_widths(self):
        self.assertIn("container-name: kpi-strip ia-report-kpis", self.css)
        self.assertIn("@container ia-report-kpis (max-width: 64rem)", self.css)
        self.assertIn("@container ia-report-kpis (max-width: 34rem)", self.css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", self.css)
        self.assertIn(".ia-dashboard .kpi-strip__label", self.css)
        self.assertIn(".ia-card-heading h3", self.css)
        self.assertIn("text-wrap: nowrap", self.css)
        self.assertIn("white-space: nowrap", self.css)


class IAVerificationWorkspaceContractTest(SimpleTestCase):
    def setUp(self):
        self.queue = QUEUE_TEMPLATE.read_text(encoding="utf-8")
        self.table = QUEUE_TABLE.read_text(encoding="utf-8")
        self.review = REVIEW_TEMPLATE.read_text(encoding="utf-8")

    def test_queue_has_the_canonical_operational_columns_and_one_primary_action(self):
        for label in (
            "Activity or SSA record",
            "School or cluster",
            "Record type",
            "Submitted by",
            "Evidence status",
            "Salesforce ID status",
            "Submission date",
            "Age",
            "Risk",
            "Next action",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self.table)
        self.assertIn('class="btn btn-primary h-9">Review</a>', self.table)
        self.assertIn("edify-row-overflow__menu", self.table)
        self.assertNotIn("Review Action", self.table)

    def test_queue_uses_three_inline_filters_and_a_real_advanced_filter_dialog(self):
        self.assertEqual(self.queue.count('class="edify-filter-label"'), 6)
        self.assertIn('data-component="filter-drawer"', self.queue)
        self.assertIn('<dialog x-ref="advancedFilters"', self.queue)
        self.assertNotIn('include "components/kpi_strip.html"', self.queue)

    def test_review_is_a_mobile_full_screen_workspace_with_sticky_decisions(self):
        self.assertIn("flex-col lg:flex-row", self.review)
        self.assertIn("fixed inset-0 lg:absolute", self.review)
        self.assertIn("sticky bottom-0", self.review)
        self.assertIn("Clear Activity", self.review)
        self.assertIn("Return for Correction", self.review)
        self.assertIn("@keydown.arrow-right.prevent", self.review)
        self.assertIn("Salesforce Activity ID", self.review)
        self.assertIn("Finance routing", self.review)

    def test_queue_table_is_the_only_surface_not_a_card_inside_a_card(self):
        container = self.queue[self.queue.index('id="queue-table-container"') :]
        opening_tag = container[: container.index(">")]
        self.assertNotIn("edify-surface", opening_tag)
        self.assertNotIn("border", opening_tag)
        self.assertIn('data-component="data-table"', self.table)
