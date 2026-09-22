"""One .xlsx writer, so every plan export looks like the same document.

Owner, 2026-09-22: "IA and PL and CD and Regional Programme Leads, and CCEO
should be able to export all of their plans into Excel."

Every one of those roles already had an export; four of the five got a CSV.
A CSV opens in Excel and then argues with it — dates read as text in one
locale and as numbers in another, a UGX figure loses its grouping, and the
column widths are whatever the reader drags them to. The Work Plan export had
already solved this with openpyxl, and the styling here is that export's,
lifted so the plan a Lead sends to a Country Director looks like the plan a
CCEO sends to a Lead.

The rows are not built here. Each export hands over exactly what its own page
rendered — the same list, in the same order — because an export that re-queries
is an export that can disagree with the screen it was taken from.
"""

from __future__ import annotations

from django.http import HttpResponse

#: The Work Plan export's palette, kept identical on purpose.
HEADER_FILL = "102A43"
HEADER_RULE = "1677FF"
ROW_RULE = "D9E2EC"
BAND = "F7FAFC"

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def workbook_response(filename: str, sheets: list[dict]) -> HttpResponse:
    """A styled workbook as a download.

    Each sheet is ``{title, headers, rows, widths?, number_formats?}``.
    ``number_formats`` maps a 1-based column index to an Excel format, for the
    money and count columns that otherwise arrive as bare integers.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    workbook.remove(workbook.active)
    rule = Side(style="thin", color=ROW_RULE)

    for spec in sheets or [{"title": "Export", "headers": [], "rows": []}]:
        # Excel refuses a sheet title over 31 characters or carrying []:*?/\\.
        sheet = workbook.create_sheet(_sheet_title(spec.get("title") or "Export"))
        headers = list(spec.get("headers") or [])
        if headers:
            sheet.append(headers)
        for row in spec.get("rows") or []:
            sheet.append(list(row))

        if headers:
            for cell in sheet[1]:
                cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
                cell.font = Font(color="FFFFFF", bold=True, size=10)
                cell.alignment = Alignment(vertical="center")
                cell.border = Border(bottom=Side(style="medium", color=HEADER_RULE))
            sheet.row_dimensions[1].height = 28
            sheet.freeze_panes = "A2"
            if sheet.max_row > 1:
                sheet.auto_filter.ref = sheet.dimensions

        formats = spec.get("number_formats") or {}
        for row_index in range(2, sheet.max_row + 1):
            fill = PatternFill(
                "solid", fgColor=BAND if row_index % 2 == 0 else "FFFFFF"
            )
            for cell in sheet[row_index]:
                cell.fill = fill
                cell.border = Border(bottom=rule)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
            for column, number_format in formats.items():
                sheet.cell(row_index, column).number_format = number_format

        widths = spec.get("widths") or _widths_for(headers)
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        sheet.sheet_view.showGridLines = False

    response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    workbook.save(response)
    return response


def _sheet_title(title: str) -> str:
    for bad in "[]:*?/\\":
        title = title.replace(bad, " ")
    return (title.strip() or "Export")[:31]


def _widths_for(headers) -> list[int]:
    """A readable width from the header alone — wide enough to read, capped so
    one long heading does not push every other column off the screen."""
    return [min(42, max(14, len(str(header)) + 6)) for header in headers]
