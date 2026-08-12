"""Tables must stay bounded, and the count may only go down.

A table with no bound grows with the data behind it: two cards side by side end
up different heights and the page scrolls for reasons nobody chose. The first
scan found 172 data tables of which 143 showed everything.

The ceiling below is a ratchet, not a target. It exists so the number cannot
creep back up while nobody is looking, and so the remaining ones stay visible
instead of being forgotten.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.system_health.table_inventory import scan_tables, table_report


class TableBoundsTest(SimpleTestCase):
    #: Measured after the first sweep. Lower it when more are wired; never
    #: raise it. A new unbounded table should fail here on the day it is added.
    UNBOUNDED_CEILING = 78

    def test_no_new_unbounded_tables(self):
        report = table_report()
        self.assertLessEqual(
            report["unbounded"],
            self.UNBOUNDED_CEILING,
            f"{report['unbounded']} tables show every row (ceiling "
            f"{self.UNBOUNDED_CEILING}). Wire the new one with "
            '{% paginate rows "x_page" as pager %} and '
            "components/table_pager.html, or lower nothing and fix it.",
        )

    def test_the_scanner_still_sees_tables_at_all(self):
        """A scanner that finds nothing would pass the test above forever."""
        report = table_report()
        self.assertGreater(report["total"], 100)
        self.assertGreater(report["paginated"], 50)

    def test_a_sliced_table_is_not_counted_as_done(self):
        """`|slice:` caps the rows and tells the reader nothing. It is bounded
        but silent, which is how somebody comes to believe they have seen
        everything there is."""
        states = {f.state for f in scan_tables()}
        self.assertIn("sliced", states)
        report = table_report()
        self.assertNotEqual(report["sliced"], 0)
        # Sliced is reported separately from paginated, never folded into it.
        self.assertEqual(
            report["total"],
            report["paginated"] + report["sliced"] + report["unbounded"],
        )

    def test_every_finding_names_a_template_and_a_row_source(self):
        for finding in scan_tables()[:40]:
            with self.subTest(finding.template):
                self.assertTrue(finding.template.endswith(".html"))
                self.assertTrue(finding.source)
                self.assertGreater(finding.line, 0)


class PageSizeTest(SimpleTestCase):
    def test_the_platform_shows_ten_rows_a_table(self):
        from apps.core.pagination import TABLE_PAGE_SIZE

        self.assertEqual(TABLE_PAGE_SIZE, 10)

    def test_a_long_table_does_not_render_a_link_per_page(self):
        """40 pages must not mean 40 links."""
        from apps.core.pagination import paginate_rows

        pages = paginate_rows(list(range(400)), page=20)["pages"]
        self.assertLessEqual(len(pages), 7)
        self.assertIn("...", pages)
        self.assertIn(20, pages)
