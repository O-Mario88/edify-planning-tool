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
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    workbook.remove(workbook.active)

    for spec in sheets or [{"title": "Export", "headers": [], "rows": []}]:
        # Excel refuses a sheet title over 31 characters or carrying []:*?/\\.
        sheet = workbook.create_sheet(_sheet_title(spec.get("title") or "Export"))
        headers = list(spec.get("headers") or [])
        if headers:
            sheet.append(headers)
        for row in spec.get("rows") or []:
            sheet.append(list(row))

        if headers:
            style_header(sheet)
            sheet.freeze_panes = "A2"
            if sheet.max_row > 1:
                sheet.auto_filter.ref = sheet.dimensions
        style_body(sheet, spec.get("number_formats") or {})

        widths = spec.get("widths") or _widths_for(headers)
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        sheet.sheet_view.showGridLines = False

    response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    workbook.save(response)
    return response


def style_header(sheet) -> None:
    """The navy heading row every plan export opens with."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    fill = PatternFill("solid", fgColor=HEADER_FILL)
    font = Font(color="FFFFFF", bold=True, size=10)
    alignment = Alignment(vertical="center")
    border = Border(bottom=Side(style="medium", color=HEADER_RULE))
    for row in sheet.iter_rows(min_row=1, max_row=1):
        for cell in row:
            cell.fill = fill
            cell.font = font
            cell.alignment = alignment
            cell.border = border
    sheet.row_dimensions[1].height = 28


def style_body(sheet, number_formats: dict[int, str] | None = None) -> None:
    """Banded, ruled, top-aligned body rows, and each column's number format.

    One pass with `iter_rows`, and one style object per kind shared by every
    cell. `sheet[row_index]` recomputes the sheet's width on every call, so
    styling row by row that way was quadratic: 231 million iterations and
    11-15 s for a 4,000-row Work Plan at 50,000 schools (2026-09-24 audit).
    """
    from openpyxl.styles import Alignment, Border, PatternFill, Side
    from openpyxl.styles.cell_style import StyleArray

    fills = (
        PatternFill("solid", fgColor="FFFFFF"),
        PatternFill("solid", fgColor=BAND),
    )
    border = Border(bottom=Side(style="thin", color=ROW_RULE))
    alignment = Alignment(vertical="top", wrap_text=True)
    formats = number_formats or {}
    # Assigning a style through the cell looks it up in the workbook's style
    # list by hashing it, three times per cell: ~250,000 lookups and most of a
    # 4,000-row export's time (2026-09-24 A+ audit). The first cell of each
    # band still goes through the assignment, which registers the style in
    # the order it always did; every later cell takes the same list indices
    # directly, which is exactly what the assignment stores.
    fill_ids: dict[bool, int] = {}
    border_id = alignment_id = None
    for row_index, row in enumerate(sheet.iter_rows(min_row=2), start=2):
        banded = row_index % 2 == 0
        fill_id = fill_ids.get(banded)
        for cell in row:
            if fill_id is None:
                cell.fill = fills[banded]
                cell.border = border
                cell.alignment = alignment
                fill_id = fill_ids[banded] = cell._style.fillId
                border_id = cell._style.borderId
                alignment_id = cell._style.alignmentId
                continue
            style = cell._style
            if not style:
                # What openpyxl's style descriptor does for an unstyled cell.
                style = cell._style = StyleArray()
            style.fillId = fill_id
            style.borderId = border_id
            style.alignmentId = alignment_id
        for column, number_format in formats.items():
            sheet.cell(row_index, column).number_format = number_format


def _sheet_title(title: str) -> str:
    for bad in "[]:*?/\\":
        title = title.replace(bad, " ")
    return (title.strip() or "Export")[:31]


def _widths_for(headers) -> list[int]:
    """A readable width from the header alone — wide enough to read, capped so
    one long heading does not push every other column off the screen."""
    return [min(42, max(14, len(str(header)) + 6)) for header in headers]
