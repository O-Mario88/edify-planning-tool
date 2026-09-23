"""Tables must stay bounded, and the count may only go down.

A table with no bound grows with the data behind it: two cards side by side end
up different heights and the page scrolls for reasons nobody chose. A table
capped with `|slice:` is worse — it is bounded and silent, which is how somebody
comes to believe they have seen everything there is.

The first scan found 172 data tables of which 143 showed everything. The sweep
of 2026-09-22 ("fix the tables that are capped and unbounded") wired the rest:
of 293 tables, 285 page and 0 are sliced. The eight that remain unbounded are
each bounded by something other than a dataset, and the ceiling below names
every one — it is a ratchet, not a target.
"""

from __future__ import annotations

import pathlib
import tempfile

from django.test import SimpleTestCase

from apps.system_health import table_inventory
from apps.system_health.table_inventory import scan_tables, table_report


class TableBoundsTest(SimpleTestCase):
    #: Every table that still shows all its rows, and what bounds it instead of
    #: the dataset. Lower this when one is wired; raise it only for a table
    #: bounded by something other than the data, and say what bounds it here.
    #: A new unbounded table fails this test on the day it is added.
    #:
    #: * `pages/planning/fiscal_years.html` — one row per fiscal year the
    #:   platform has ever governed: three today, one more each October. The
    #:   page exists to see the years side by side.
    #: * The four My Plan cards — School Visits, Trainings, Cluster Meetings and
    #:   Programme Activities (owner, 2026-09-16). The page shows a person's
    #:   whole fiscal year arranged by month, and a pager over it puts the thing
    #:   the page exists for behind "Next". Bounded by what one officer can
    #:   physically do in twelve months; a plan growing past that is a workload
    #:   finding that should show rather than be hidden a page at a time.
    #: * `partials/priorities/master_view.html` — the Uganda master table
    #:   reproduces the approved master in full, and a page of a master plan is
    #:   not the master plan. Bounded by the plan (75 milestone rows).
    #: * `partials/targets/team/body.html` — the scanner reads the matrix's
    #:   column loop. Its rows are the team (bounded by supervisees) and its
    #:   companion trend is exactly twelve financial-year months; both exist to
    #:   be compared side by side, which is what a pager would break.
    #: * `partials/today/workbench.html` — `waiting` is capped at WAITING_LIMIT
    #:   (8) in today_views and the card's header discloses the whole queue
    #:   ("View all N"): bounded in Python, and the reader is told there is more.
    #: * `partials/clusters/cluster_schools_table.html` — the schools of one
    #:   cluster, drawn inside that cluster's card (a card list until the table
    #:   redesign, 8bb11a1, so the scanner never saw it). Bounded by cluster
    #:   size: clusters group a few neighbouring schools (the largest in the
    #:   16,000-school scaled estate has six).
    #: * `partials/dashboards/pl/programmes_view.html` — the monthly
    #:   completion table behind the Program Lead's chart (8bb11a1): one row
    #:   per supervised officer, twelve month columns. Bounded by the team,
    #:   like the team targets matrix, and read side by side with the chart.
    #: * `partials/oversight/cluster_activity_table.html` — one officer's group
    #:   trainings and cluster meetings for the year on the cluster oversight
    #:   page (7586e32). Bounded by what one officer can deliver in twelve
    #:   months, the same reasoning as the My Plan cards above.
    UNBOUNDED_CEILING = 11

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

    def test_no_table_hides_rows_behind_a_silent_cap(self):
        """`|slice:` caps the rows and tells the reader nothing.

        Fifty-one tables did this, which is fifty-one places a reader could
        believe they had seen everything. None do now, and one appearing again
        fails here rather than in somebody's report.
        """
        report = table_report()
        self.assertEqual(
            report["sliced"],
            0,
            "a table caps its rows with |slice: and says nothing. Give it "
            '{% paginate rows "x_page" as pager %} and '
            "components/table_pager.html so the rest can be reached.",
        )

    def test_a_sliced_table_is_still_recognised_as_one(self):
        """The check above is only worth anything while the scanner can tell.

        Asserted against a table written here rather than against the live
        count, which is now zero — a scanner that had stopped recognising a cap
        would otherwise pass that test forever.
        """
        # Inside the project, because the scanner reports every finding as a
        # path relative to it.
        from django.conf import settings

        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as directory:
            root = pathlib.Path(directory)
            (root / "capped.html").write_text(
                "<table><tbody>"
                "{% for row in rows|slice:':40' %}<tr><td>{{ row }}</td></tr>"
                "{% endfor %}</tbody></table>"
            )
            (root / "whole.html").write_text(
                "<table><tbody>"
                "{% for row in rows %}<tr><td>{{ row }}</td></tr>"
                "{% endfor %}</tbody></table>"
            )
            original = table_inventory.TEMPLATES
            table_inventory.TEMPLATES = root
            try:
                states = {f.template.split("/")[-1]: f.state for f in scan_tables()}
            finally:
                table_inventory.TEMPLATES = original
        self.assertEqual(states.get("capped.html"), "sliced")
        self.assertEqual(states.get("whole.html"), "unbounded")

    def test_a_server_pagination_strip_after_a_table_pages_it(self):
        """Planning pages its school tables in the view and draws the
        "Showing 1-25 of N" strip under them, beyond the pager neighbourhood:
        that is paginated, but a strip that only precedes a table is not."""
        from django.conf import settings

        rows = "<table><tbody>{% for row in rows %}<tr><td>{{ row }}</td></tr>{% endfor %}</tbody></table>"
        strip = '<div class="edify-pagination-scope">Showing 1-25 of 300</div>'
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as directory:
            root = pathlib.Path(directory)
            (root / "paged.html").write_text(rows + "x" * 2000 + strip)
            (root / "before.html").write_text(strip + rows)
            original = table_inventory.TEMPLATES
            table_inventory.TEMPLATES = root
            try:
                states = {f.template.split("/")[-1]: f.state for f in scan_tables()}
            finally:
                table_inventory.TEMPLATES = original
        self.assertEqual(states.get("paged.html"), "paginated")
        self.assertEqual(states.get("before.html"), "unbounded")

    def test_the_three_states_stay_separate(self):
        # Sliced is reported beside paginated, never folded into it.
        report = table_report()
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
