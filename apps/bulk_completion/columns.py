"""The two upload files' columns, and how a heading row is read.

Owner, 2026-11-03: a file links the Salesforce export to the planned work by
IDs alone. Both uploads read the same five columns —

    planned_activity_id   the activity, from the Planning Oversight export
    school_id             the school, from the Salesforce export
    visit_sf_id           the Salesforce visit ID (empty on a training line)
    training_sf_id        the Salesforce training ID (empty on a visit line)
    completed_date        the day the work was done

— and the training upload two more, ``teachers_trained`` and
``school_leaders_trained`` ("count columns should be required as well").

Headings are compared with case, spacing and underscores ignored, so
"Planned Activity ID" is ``planned_activity_id``. Every other column is
ignored, so a raw Salesforce or Planning Oversight export is uploaded as it
is, without deleting columns first.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.schools.upload_mapping import normalize_header

from .models import BulkKind


@dataclass(frozen=True)
class Column:
    field: str
    heading: str


SHARED_COLUMNS: tuple[Column, ...] = (
    Column("activity_id", "planned_activity_id"),
    Column("school_code", "school_id"),
    Column("visit_sf_id", "visit_sf_id"),
    Column("training_sf_id", "training_sf_id"),
    Column("completed_on", "completed_date"),
)
COUNT_COLUMNS: tuple[Column, ...] = (
    Column("teachers", "teachers_trained"),
    Column("leaders", "school_leaders_trained"),
)

COLUMNS = {
    BulkKind.VISIT: SHARED_COLUMNS,
    BulkKind.TRAINING: (*SHARED_COLUMNS, *COUNT_COLUMNS),
}

#: What a spreadsheet writes for "nothing here": the Planning Oversight
#: export fills an open activity's Completed Date with a dash.
BLANK_CELLS = frozenset({"", "—", "–", "-"})

TEMPLATE_NOTES = {
    BulkKind.VISIT: (
        "One line per visit. Give visit_sf_id (Salesforce) and completed_date "
        "(YYYY-MM-DD, today or earlier); leave training_sf_id empty. Any other "
        "column is ignored, so you can paste these columns beside a Salesforce "
        "or Planning Oversight export."
    ),
    BulkKind.TRAINING: (
        "One line per school that took part. Give training_sf_id (Salesforce), "
        "completed_date (YYYY-MM-DD), and that school's teachers_trained and "
        "school_leaders_trained; leave visit_sf_id empty. Lines with the same "
        "planned_activity_id are one training: its schools are linked to it "
        "and their counts added up. Any other column is ignored."
    ),
}


def headings(kind: str) -> list[str]:
    return [column.heading for column in COLUMNS[kind]]


def heading_of(kind: str, field: str) -> str:
    return next(c.heading for c in COLUMNS[kind] if c.field == field)


def field_positions(kind: str, headers: list[str]) -> dict[str, tuple[int, ...]]:
    """{field: every column position carrying its heading}."""
    wanted = {normalize_header(c.heading): c.field for c in COLUMNS[kind]}
    found: dict[str, list[int]] = {}
    for position, heading in enumerate(headers):
        field = wanted.get(normalize_header(heading))
        if field:
            found.setdefault(field, []).append(position)
    return {field: tuple(positions) for field, positions in found.items()}


def missing_columns(kind: str, positions: dict) -> list[str]:
    return [c.heading for c in COLUMNS[kind] if c.field not in positions]


def cell_values(row: list, positions: dict[str, tuple[int, ...]]) -> dict[str, str]:
    """{field: value} for one line. A heading given twice (an export's own
    "Completed Date" beside the Salesforce one) reads the first cell that
    holds something."""
    values: dict[str, str] = {}
    for field, places in positions.items():
        values[field] = ""
        for position in places:
            text = str((row[position] if position < len(row) else "") or "").strip()
            if text not in BLANK_CELLS:
                values[field] = text
                break
    return values
