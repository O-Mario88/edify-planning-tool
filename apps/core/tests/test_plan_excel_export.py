"""Every plan a role holds can leave the platform as a workbook.

Owner, 2026-09-22: "IA and PL and CD and Regional Programme Leads, and CCEO
should be able to export all of their plans into Excel."

Four of those five already had an export and got a CSV, which opens in Excel
and then argues with it about dates and money. The rows are unchanged — the
same `export_rows` the CSV has always used — so these tests hold the two things
that could go wrong: that the workbook carries exactly those rows, and that the
CSV every existing link points at still answers.
"""

from __future__ import annotations

import io

from django.test import SimpleTestCase

from apps.core.excel import XLSX_CONTENT_TYPE, workbook_response


def _sheets(response):
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(response.content))
    return {
        name: [list(row) for row in book[name].iter_rows(values_only=True)]
        for name in book.sheetnames
    }


class WorkbookResponseTest(SimpleTestCase):
    def test_it_is_a_download_a_spreadsheet_will_open(self):
        response = workbook_response(
            "plan.xlsx", [{"title": "Plan", "headers": ["A"], "rows": [[1]]}]
        )
        self.assertEqual(response["Content-Type"], XLSX_CONTENT_TYPE)
        self.assertIn('filename="plan.xlsx"', response["Content-Disposition"])

    def test_the_rows_arrive_exactly_as_they_were_handed_over(self):
        response = workbook_response(
            "plan.xlsx",
            [
                {
                    "title": "Plan",
                    "headers": ["School", "Cost"],
                    "rows": [["Hope Primary", 120000], ["Faith Junior", 90000]],
                }
            ],
        )
        self.assertEqual(
            _sheets(response)["Plan"],
            [
                ["School", "Cost"],
                ["Hope Primary", 120000],
                ["Faith Junior", 90000],
            ],
        )

    def test_a_plan_with_no_rows_is_still_a_readable_workbook(self):
        # An officer who has planned nothing yet must get a file with the
        # column headings, not a broken download.
        response = workbook_response(
            "plan.xlsx", [{"title": "Plan", "headers": ["School"], "rows": []}]
        )
        self.assertEqual(_sheets(response)["Plan"], [["School"]])

    def test_a_sheet_name_excel_would_refuse_is_made_acceptable(self):
        response = workbook_response(
            "plan.xlsx",
            [{"title": "Team/Plan: 2026 " + "x" * 40, "headers": ["A"], "rows": []}],
        )
        name = next(iter(_sheets(response)))
        self.assertLessEqual(len(name), 31)
        for bad in "[]:*?/\\":
            self.assertNotIn(bad, name)

    def test_several_sheets_keep_their_own_rows(self):
        response = workbook_response(
            "plan.xlsx",
            [
                {"title": "Plan", "headers": ["A"], "rows": [["one"]]},
                {"title": "Summary", "headers": ["B"], "rows": [["two"]]},
            ],
        )
        sheets = _sheets(response)
        self.assertEqual(sheets["Plan"], [["A"], ["one"]])
        self.assertEqual(sheets["Summary"], [["B"], ["two"]])


class TheExportsOfferBothFilesTest(SimpleTestCase):
    """The format is asked for in the URL, and CSV stays the default."""

    def test_the_oversight_exports_read_the_format_parameter(self):
        from django.test import RequestFactory

        from apps.frontend.views.oversight_views import _wants_excel

        rf = RequestFactory()
        for query, expected in (
            ("?format=xlsx", True),
            ("?format=excel", True),
            ("?format=XLSX", True),
            ("?format=csv", False),
            ("", False),
        ):
            with self.subTest(query=query):
                self.assertEqual(_wants_excel(rf.get(f"/export{query}")), expected)

    def test_my_plan_offers_both_files(self):
        from pathlib import Path

        page = (
            Path(__file__).resolve().parents[3] / "templates/pages/my_plan/index.html"
        ).read_text()
        self.assertIn("{% querystring export='csv' %}", page)
        self.assertIn("{% querystring export='xlsx' %}", page)

    def test_every_oversight_workspace_offers_both_files(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        for name in (
            "pl_workspace",  # Programme Lead, Impact Assessment, Regional Lead
            "team_country_workspace",
            "cd_workspace",  # Country Director
        ):
            source = (root / f"templates/partials/oversight/{name}.html").read_text()
            with self.subTest(workspace=name):
                self.assertIn("Export CSV", source)
                self.assertIn("Export Excel", source)
                self.assertIn("format=xlsx", source)
