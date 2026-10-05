"""A table's columns never run into each other.

Owner, 2026-10-05, of the Planning list: "make sure the columns are not
overlapping into each other ... and any other table in the platform with that
issue". A cluster's name ("Greater Abako Cluster") ran out of the Cluster
column and across the Visit Plan Status chip beside it.

How it happens. Every table is held to one line and may not clip a cell
(consistency.css, EVERY TABLE STAYS ON ONE LINE, with ``!important``): a
column grows to what it holds and the table scrolls sideways. A table that
FIXES its layout cannot grow a column, so there a long value has nowhere to go
but over its neighbour — unless the cell is given the weight to end in an
ellipsis instead. A rule without ``!important`` does not have that weight,
which is how Planning's own ellipsis rule had been losing since it was
written.

The geometry is asserted in the browser (e2e/table-columns-do-not-overlap
.spec.js). These tests hold the three facts in the stylesheets that the
geometry rests on, so the Django suite says so first.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
CSS = ROOT / "static" / "css"

#: The generated bundles: Tailwind's utilities, and the indexed copies.
_GENERATED = ("main.css",)


def _read(relative: str) -> str:
    return (CSS / relative).read_text(encoding="utf-8")


def _rules(styles: str) -> str:
    """A stylesheet without its comments."""
    return re.sub(r"/\*.*?\*/", "", styles, flags=re.S)


class FixedTablesDoNotSpillTest(SimpleTestCase):
    def test_planning_s_cluster_cell_ends_in_an_ellipsis_with_the_weight_to_win(self):
        styles = _rules(_read("components/planning-cluster-column.css"))
        rule = re.search(
            r"td\.school-plan-table__cluster\s*\{([^}]*)\}", styles, flags=re.S
        )
        self.assertIsNotNone(rule, "the Cluster cell has lost its rule")
        body = rule.group(1)
        # Without !important each of these loses to the one-line rule, and
        # the name paints over the Visit Plan Status beside it.
        self.assertRegex(body, r"overflow:\s*hidden\s*!important")
        self.assertRegex(body, r"text-overflow:\s*ellipsis\s*!important")

    def test_the_one_line_rule_is_what_a_fixed_table_has_to_outweigh(self):
        """The rule the test above answers. If it stops forbidding a cell to
        clip, that weight is no longer needed and this file can say less."""
        styles = _rules(_read("consistency.css"))
        rule = re.search(
            r"table:not\(\.sr-only, \.edify-visually-hidden\) :is\(td, th\)\s*\{([^}]*)\}",
            styles,
            flags=re.S,
        )
        self.assertIsNotNone(rule)
        self.assertRegex(rule.group(1), r"overflow:\s*visible\s*!important")
        self.assertRegex(rule.group(1), r"white-space:\s*nowrap\s*!important")

    def test_the_lifecycle_tables_size_to_what_they_hold(self):
        """Core Trained, Core Graduate and Champion schools on Core Schools
        fixed seven columns by percentage and expected to wrap; held to one
        line, a long school name ran across the columns beside it. They are
        ordinary tables: no fixed layout, no column width of their own."""
        for sheet in sorted(CSS.rglob("*.css")):
            if sheet.name in _GENERATED:
                continue
            styles = _rules(sheet.read_text(encoding="utf-8"))
            for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", styles):
                if "core-lifecycle-table" not in selector:
                    continue
                with self.subTest(sheet=sheet.name, selector=selector.strip()[:80]):
                    self.assertNotRegex(body, r"table-layout:\s*fixed")
                    self.assertNotRegex(body, r"(^|[;\s])width:\s*\d+%")

    def test_a_table_that_fixes_its_layout_is_a_known_one(self):
        """Fixing a table's layout is the one way to make a column overlap,
        so each place a stylesheet does it is listed here with how its cells
        end. A new one belongs on this list only once its text cells clip
        with ``!important`` (or cannot be longer than their column) and the
        browser spec has been pointed at it."""
        known = {
            # The column planner (micro-ux.js): text cells carry
            # .edify-cell-truncate and clip with !important.
            # Planning and the Cluster School List: the school name is a
            # toggle that clips itself; Planning's Cluster cell clips above.
            "consistency.css": 2,
            # The PL dashboard's SSA matrix and urgent-schools table, and the
            # Target Performance matrices: figures and fixed labels.
            "pages.css": 3,
            # Country Execution's small tables: every cell clips, !important.
            "pages/country-oversight.css": 1,
            # The analytics geography card's distribution table: figures.
            "pages/analytics-dashboard.css": 1,
        }
        found = {}
        for sheet in sorted(CSS.rglob("*.css")):
            if sheet.name in _GENERATED:
                continue
            count = len(
                re.findall(
                    r"table-layout:\s*fixed", _rules(sheet.read_text(encoding="utf-8"))
                )
            )
            if count:
                found[sheet.relative_to(CSS).as_posix()] = count
        self.assertEqual(found, known)
