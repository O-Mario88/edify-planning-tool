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

Owner, 2026-11-09, later: the School Visits file is Activity ID, School ID
and Planned Date, as exported, then School Visit ID and Completed Date, which
the uploader fills in. The headings are those words now; the earlier ones
(``planned_activity_id``, ``visit_sf_id`` …) are still read, so a file made
before keeps uploading.

Headings are compared with case, spacing and underscores ignored, so
"completed_date" is "Completed Date". Every other column is ignored, so an
export is uploaded back as it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.schools.upload_mapping import normalize_header

from .models import BulkKind


@dataclass(frozen=True)
class Column:
    field: str
    heading: str
    #: Earlier headings for the same column, still read.
    also: tuple[str, ...] = ()

    def reads(self) -> tuple[str, ...]:
        return (self.heading, *self.also)


ACTIVITY_ID = Column(
    "activity_id", "Activity ID", ("planned_activity_id", "Planned Activity ID")
)
SCHOOL_ID = Column("school_code", "School ID")
VISIT_ID = Column("visit_sf_id", "School Visit ID", ("visit_sf_id",))
TRAINING_ID = Column("training_sf_id", "Training ID", ("training_sf_id",))
COMPLETED_DATE = Column("completed_on", "Completed Date")
COUNT_COLUMNS: tuple[Column, ...] = (
    Column("teachers", "Teachers Trained"),
    Column("leaders", "School Leaders Trained"),
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
        "One line per planned visit: its Activity ID, School ID and Planned "
        "Date. For each visit that was done, fill in the School Visit ID "
        "(Salesforce) and the Completed Date (YYYY-MM-DD, today or earlier). "
        "Leave a line blank to skip it. Do not change the Activity ID or the "
        "School ID: together they name the visit to complete."
    ),
    BulkKind.TRAINING: (
        "One line per school invited to each planned training, with the "
        "training's Activity ID. For each school that took part fill in the "
        "Training ID (Salesforce), the Completed Date (YYYY-MM-DD) and that "
        "school's Teachers Trained and School Leaders Trained. Lines with the "
        "same Activity ID are one training: its schools are linked to it and "
        "their counts added up. Leave a school's line blank if it did not "
        "attend, or a whole training's lines blank to skip it. Do not change "
        "the Activity ID or the School ID; every other column is ignored."
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
        normalize_header(heading): c.field
        for c in (*COLUMNS[kind], OTHER_ID[kind])
        for heading in c.reads()
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
