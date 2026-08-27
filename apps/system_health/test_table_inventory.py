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
    #: Measured after the first sweep. Lower it when more are wired; raise it
    #: only for a table bounded by something other than the dataset, and say
    #: what bounds it. A new unbounded table should fail here on the day it is
    #: added -- it did, which is why the two entries below are written down.
    #:
    #: 79 rather than 78 for one deliberate exception: the Uganda master table
    #: on /priorities reproduces the approved master in full, and a page of a
    #: master plan is not the master plan. It is bounded by the plan itself
    #: (75 milestone rows), not by the size of any dataset.
    #:
    #: 81 rather than 79 for two more on the impact workspace, both bounded in
    #: Python where this scanner -- which reads templates -- cannot see it:
    #:
    #: * `dashboard.drivers` is exactly len(DRIVER_DEFINITIONS) rows: five
    #:   pre-declared association tests whose p-values are corrected as a
    #:   family. The count is fixed by the analysis, not by the data. Adding a
    #:   sixth would change the correction, so it cannot drift unnoticed.
    #: * `dashboard.geography.lagging` is capped at LAGGING_SHOWN (10) in
    #:   impact_engine.py. That cap used to be silent, which is the failure
    #:   this module's docstring describes -- a reader takes ten rows headed
    #:   "Lagging district-intervention combinations" to be all of them. The
    #:   page now states the count it is showing and the total it came from,
    #:   so the bound is disclosed rather than hidden.
    UNBOUNDED_CEILING = 81

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
