"""Record tables preserve their real table anatomy on narrow screens."""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = ROOT / "templates"
COMPONENT_CSS = ROOT / "static" / "css" / "components" / "mobile-shell.css"

OPT_IN = "edify-record-table"


def templates_with_class() -> list[Path]:
    return [
        p
        for p in TEMPLATES.rglob("*.html")
        if re.search(rf'class="[^"]*\b{OPT_IN}\b', p.read_text(errors="replace"))
    ]


class RecordTableCssContractTests(SimpleTestCase):
    def setUp(self):
        self.css = COMPONENT_CSS.read_text()

    def test_mobile_table_contract_is_scoped_below_the_desktop_breakpoint(self):
        self.assertIn("max-width: 1023.98px", self.css)

    def test_table_header_rows_and_cells_keep_native_display_roles(self):
        for marker in (
            ".edify-record-table { display: table !important; }",
            ".edify-record-table > thead { display: table-header-group !important; }",
            ".edify-record-table > tbody { display: table-row-group !important; }",
            "display: table-row !important",
            "display: table-cell !important",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.css)

    def test_record_table_wrapper_scrolls_horizontally(self):
        block = self.css.split(".edify-record-table-wrap {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-x: auto", block)
        self.assertIn("overscroll-behavior-inline: contain", block)

    def test_data_labels_do_not_render_as_card_rows(self):
        self.assertNotIn("content: attr(data-label)", self.css)
        self.assertNotRegex(
            self.css, r"\.edify-record-table\s+thead\s*\{\s*display:\s*none"
        )


class RecordTableMarkupContractTests(SimpleTestCase):
    def test_at_least_the_first_wave_has_opted_in(self):
        self.assertGreaterEqual(len(templates_with_class()), 5)

    def test_my_plan_activity_tables_use_the_shared_table_contract(self):
        for name in (
            "school_visits",
            "cluster_trainings",
            "cluster_meetings",
            "programme_activities",
        ):
            path = TEMPLATES / "partials" / "my_plan" / f"{name}.html"
            with self.subTest(partial=name):
                src = path.read_text()
                self.assertIn(OPT_IN, src)
                self.assertIn("data-record-title", src)
                self.assertIn("data-label=", src)

    def test_shared_my_plan_action_cell_keeps_its_source_marker(self):
        src = (TEMPLATES / "partials" / "my_plan" / "activity_row.html").read_text()
        self.assertIn("data-record-action", src)

    def test_the_cost_catalogue_rates_keep_their_governed_source_labels(self):
        src = (
            TEMPLATES / "partials" / "cost_settings" / "cost_setting_row.html"
        ).read_text()
        for label in ("Country operational cost", "Minimum viable cost"):
            with self.subTest(label=label):
                self.assertIn(f'data-label="{label}"', src)
        self.assertIn("data-record-title", src)

    def test_budget_horizons_share_one_tabbed_page_and_table_format(self):
        page = (TEMPLATES / "pages" / "budgets" / "monthly.html").read_text()
        table = (
            TEMPLATES / "partials" / "budgets" / "budget_group_tables.html"
        ).read_text()
        for label in ("Monthly Budget", "Quarterly Budget", "Annual Budget"):
            with self.subTest(label=label):
                self.assertIn(label, page)
        for column in ("Staff cost (UGX)", "Activity (UGX)", "Grand total"):
            with self.subTest(column=column):
                self.assertIn(column, table)

    def test_weekly_advance_actions_use_the_role_specific_contract(self):
        workflow = (
            TEMPLATES / "partials" / "fund_requests" / "weekly_request_workflow.html"
        ).read_text()
        for label in (
            "Send for Approval",
            "Self Fund",
            "Approve",
            "Return",
            "Disburse",
            "Fund Received",
        ):
            with self.subTest(label=label):
                self.assertIn(label, workflow)
        self.assertIn("Correct the underlying activities in My Plan", workflow)
        self.assertIn("hide_row_owners=True", workflow)

        root = (TEMPLATES / "partials" / "fund_requests" / "root.html").read_text()
        self.assertIn('aria-label="Staff weekly advance requests"', root)
