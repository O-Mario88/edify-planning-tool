"""Record tables → record cards (§17 class A).

The transform is CSS-only and keyed on `.edify-record-table`. That makes the
markup contract the thing worth pinning: a table that opts in must also carry
the per-cell labels, or the cards render as unlabelled values — and "UGX
200,000" with no label is worse on a phone than a table you have to scroll.

The other half is the opt-in itself. §17 class B — comparison matrices — must
stay tables, because stacking them destroys the column comparison they exist
for. There is a guard here against the class spreading to one.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = ROOT / "templates"
COMPONENT_CSS = ROOT / "static" / "css" / "components" / "mobile-shell.css"

OPT_IN = "edify-record-table"

# §17 class B. Stacking a matrix into cards destroys the comparison it exists
# for, so these must never opt in. Matched as path fragments.
MATRIX_PAGES = (
    "targets/",
    "ssa/intervention",
    "analytics/",
    "budget_intelligence/",
)


def templates_with_class() -> list[Path]:
    return [
        p
        for p in TEMPLATES.rglob("*.html")
        if re.search(rf'class="[^"]*\b{OPT_IN}\b', p.read_text(errors="replace"))
    ]


class RecordTableCssContractTests(SimpleTestCase):
    def setUp(self):
        self.css = COMPONENT_CSS.read_text()

    def test_transform_is_scoped_below_the_desktop_breakpoint(self):
        # Above lg the table must stay a table. A transform that leaked into
        # desktop would turn every data table on the platform into a card list.
        self.assertIn("max-width: 1023.98px", self.css)

    def test_header_row_is_hidden_when_cells_carry_their_own_labels(self):
        self.assertRegex(self.css, r"\.edify-record-table thead\s*\{\s*display:\s*none")

    def test_labels_come_from_the_data_attribute(self):
        self.assertIn("content: attr(data-label)", self.css)

    def test_title_and_action_cells_suppress_the_label(self):
        for attr in ("data-record-title", "data-record-action"):
            with self.subTest(attr=attr):
                self.assertRegex(
                    self.css,
                    rf"\.edify-record-table td\[{attr}\]::before\s*\{{\s*content:\s*none",
                )

    def test_forced_min_widths_are_cancelled(self):
        # Five templates force a min-width so the DESKTOP table stays readable.
        # Left standing on a stacked card it restores the sideways scroll.
        self.assertRegex(self.css, r"\.edify-record-table\s*\{\s*min-width:\s*0")

    def test_action_control_meets_the_touch_floor(self):
        self.assertIn("min-height: 2.75rem", self.css)  # 44px


class RecordTableMarkupContractTests(SimpleTestCase):
    def test_at_least_the_first_wave_has_opted_in(self):
        self.assertGreaterEqual(len(templates_with_class()), 5)

    def test_every_opted_in_table_marks_a_record_title(self):
        # Without a title cell the card has no identity line and reads as a
        # list of labelled values with nothing naming the record.
        for path in templates_with_class():
            src = path.read_text(errors="replace")
            # The row may live in an included partial; only check files that
            # actually contain the row markup.
            if "<td" not in src:
                continue
            with self.subTest(template=str(path.relative_to(ROOT))):
                self.assertIn(
                    "data-record-title",
                    src,
                    "opted in but no cell marked data-record-title",
                )

    def test_no_comparison_matrix_opts_in(self):
        for path in templates_with_class():
            rel = str(path.relative_to(TEMPLATES))
            for matrix in MATRIX_PAGES:
                with self.subTest(template=rel, matrix=matrix):
                    self.assertNotIn(
                        matrix,
                        rel,
                        f"{rel} is a comparison matrix (§17 class B) and must "
                        "stay a table",
                    )

    def test_my_plan_activity_tables_are_converted(self):
        # The CCEO's daily field surface. These are the reason the component
        # exists, so pin them by name rather than by count.
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

    def test_shared_my_plan_action_cell_is_the_card_action(self):
        src = (TEMPLATES / "partials" / "my_plan" / "activity_row.html").read_text()
        self.assertIn("data-record-action", src)

    def test_the_cost_catalogue_rate_is_labelled(self):
        # The rate column was the one that fell off a 390px screen, and a bare
        # "UGX 200,000" in a card with no label is the failure this prevents.
        src = (
            TEMPLATES / "partials" / "cost_settings" / "cost_setting_row.html"
        ).read_text()
        self.assertIn('data-label="Rate"', src)
        self.assertIn("data-record-title", src)
