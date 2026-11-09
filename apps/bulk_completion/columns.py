"""The two upload files' columns, and how a heading row is read.

Owner, 2026-11-03: a file links the Salesforce export to the planned work by
IDs alone —

    planned_activity_id   the activity, as Edify exported it
    school_id             the school
    visit_sf_id           the Salesforce visit ID (School Visits only)
    training_sf_id        the Salesforce training ID (Trainings only)
    completed_date        the day the work was done

— and the training upload two more, ``teachers_trained`` and
``school_leaders_trained`` ("count columns should be required as well").

Owner, 2026-11-09: each file carries only its own ID. The School Visits file
has no training_sf_id column and the Trainings file no visit_sf_id column. The
other upload's ID is still recognised when a file carries it, so a training
line sent to the visit upload is told where it belongs.

Headings are compared with case, spacing and underscores ignored, so
"Planned Activity ID" is ``planned_activity_id``. Every other column is
ignored, so the exported planned activities — with their school, staff and
date columns — are uploaded back as they are.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.schools.upload_mapping import normalize_header

from .models import BulkKind


@dataclass(frozen=True)
class Column:
    field: str
    heading: str


ACTIVITY_ID = Column("activity_id", "planned_activity_id")
SCHOOL_ID = Column("school_code", "school_id")
VISIT_ID = Column("visit_sf_id", "visit_sf_id")
TRAINING_ID = Column("training_sf_id", "training_sf_id")
COMPLETED_DATE = Column("completed_on", "completed_date")
COUNT_COLUMNS: tuple[Column, ...] = (
    Column("teachers", "teachers_trained"),
    Column("leaders", "school_leaders_trained"),
)

COLUMNS = {
    BulkKind.VISIT: (ACTIVITY_ID, SCHOOL_ID, VISIT_ID, COMPLETED_DATE),
    BulkKind.TRAINING: (
        ACTIVITY_ID,
        SCHOOL_ID,
        TRAINING_ID,
        COMPLETED_DATE,
        *COUNT_COLUMNS,
    ),
}

#: Each upload's own Salesforce ID column, and the other upload's, which is
#: read only to tell a misplaced line where it belongs.
OWN_ID = {BulkKind.VISIT: VISIT_ID, BulkKind.TRAINING: TRAINING_ID}
OTHER_ID = {BulkKind.VISIT: TRAINING_ID, BulkKind.TRAINING: VISIT_ID}

#: The cells an uploader fills in. A line with none of them filled is one the
#: uploader left for later: it is skipped, not refused.
FILL_IN_FIELDS = {
    BulkKind.VISIT: ("visit_sf_id", "completed_on"),
    BulkKind.TRAINING: ("training_sf_id", "completed_on", "teachers", "leaders"),
}

#: What a spreadsheet writes for "nothing here": the Planning Oversight
#: export fills an open activity's Completed Date with a dash.
BLANK_CELLS = frozenset({"", "—", "–", "-"})

TEMPLATE_NOTES = {
    BulkKind.VISIT: (
        "One line per planned visit, exported with its planned_activity_id. "
        "Fill in visit_sf_id (Salesforce) and completed_date (YYYY-MM-DD, "
        "today or earlier) for each visit that was done. Leave a line blank "
        "to skip it. Do not change planned_activity_id or School ID; every "
        "other column is there to help you find the visit and is ignored."
    ),
    BulkKind.TRAINING: (
        "One line per school invited to each planned training, exported with "
        "its planned_activity_id. For each school that took part fill in "
        "training_sf_id (Salesforce), completed_date (YYYY-MM-DD) and that "
        "school's teachers_trained and school_leaders_trained. Lines with the "
        "same planned_activity_id are one training: its schools are linked to "
        "it and their counts added up. Leave a school's line blank if it did "
        "not attend, or a whole training's lines blank to skip it. Do not "
        "change planned_activity_id or School ID; every other column is "
        "ignored."
    ),
}


def headings(kind: str) -> list[str]:
    return [column.heading for column in COLUMNS[kind]]


def heading_of(kind: str, field: str) -> str:
    return next(c.heading for c in COLUMNS[kind] if c.field == field)


def field_positions(kind: str, headers: list[str]) -> dict[str, tuple[int, ...]]:
    """{field: every column position carrying its heading}, the other
    upload's ID column included when the file has one."""
    wanted = {
        normalize_header(c.heading): c.field for c in (*COLUMNS[kind], OTHER_ID[kind])
    }
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
