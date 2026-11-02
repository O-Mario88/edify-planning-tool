"""The two upload files: their columns, the headings accepted for each, and
the downloadable templates.

A template is filled in advance with the uploader's open work — one line per
scheduled visit or training, carrying its Edify Activity ID — so a line is
matched to its activity exactly and the uploader only types the Salesforce ID
and the date it was done. A line typed by hand without the Activity ID is
still matched, from the School ID, the type and the scheduled date, and is
sent for review when that does not pick out one activity.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.schools.upload_mapping import normalize_header

from .models import BulkKind


@dataclass(frozen=True)
class Column:
    field: str
    heading: str
    aliases: tuple[str, ...] = ()
    #: Written into the template from the activity; read only to match.
    prefilled: bool = False


VISIT_COLUMNS: tuple[Column, ...] = (
    Column("activity_id", "Edify Activity ID", ("activity id", "edify id"), True),
    Column("school_code", "School ID", ("school code",), True),
    Column("school_name", "School Name", ("school",), True),
    Column("activity_type", "Visit Type", ("activity type", "type"), True),
    Column("scheduled_on", "Scheduled Date", ("planned date", "visit date"), True),
    Column("responsible", "Responsible", ("staff", "owner"), True),
    Column(
        "salesforce_id",
        "School Visit ID",
        ("visit id", "salesforce visit id", "sf visit id", "salesforce id"),
    ),
    Column(
        "completed_on",
        "Completion Date",
        ("completed date", "date completed", "completed on"),
    ),
)

TRAINING_COLUMNS: tuple[Column, ...] = (
    Column("activity_id", "Edify Activity ID", ("activity id", "edify id"), True),
    Column("activity_type", "Training Type", ("activity type", "type"), True),
    Column("title", "Training", ("training name", "course"), True),
    Column("cluster", "Cluster", (), True),
    Column("school_code", "School ID", ("school code",), True),
    Column("scheduled_on", "Scheduled Date", ("planned date", "training date"), True),
    Column("responsible", "Responsible", ("staff", "owner"), True),
    Column(
        "salesforce_id",
        "Training ID",
        ("salesforce training id", "sf training id", "salesforce id"),
    ),
    Column(
        "completed_on",
        "Completion Date",
        ("completed date", "date completed", "completed on"),
    ),
    Column("teachers", "Teachers Attended", ("teachers",)),
    Column("leaders", "School Leaders Attended", ("leaders", "leaders attended")),
    Column(
        "participants",
        "Participating School IDs",
        ("participating schools", "schools attended", "attending school ids"),
    ),
)

COLUMNS = {BulkKind.VISIT: VISIT_COLUMNS, BulkKind.TRAINING: TRAINING_COLUMNS}

#: A file must carry these columns (a cell may still be empty, and is then
#: reported on its own line).
REQUIRED_FIELDS = ("salesforce_id", "completed_on")
#: ...and one of these, to say which activity a line completes.
IDENTIFYING_FIELDS = ("activity_id", "school_code")

TEMPLATE_NOTES = {
    BulkKind.VISIT: (
        "Type each visit's Salesforce School Visit ID and the date it was done "
        "(YYYY-MM-DD, today or earlier). Leave the other columns as they are. "
        "Lines you leave without a Visit ID are reported, not completed."
    ),
    BulkKind.TRAINING: (
        "Type each training's Salesforce Training ID, the date it was done "
        "(YYYY-MM-DD), and how many teachers and school leaders attended. For a "
        "cluster or group training list the School IDs that attended, "
        "separated by commas, or give one line per school with the same "
        "Activity ID."
    ),
}


def field_index(kind: str, headers: list[str]) -> dict[str, int]:
    """{field: column position} for the headings this file carries."""
    wanted: dict[str, str] = {}
    for column in COLUMNS[kind]:
        wanted[normalize_header(column.heading)] = column.field
        for alias in column.aliases:
            wanted.setdefault(normalize_header(alias), column.field)
    index: dict[str, int] = {}
    for position, heading in enumerate(headers):
        field = wanted.get(normalize_header(heading))
        if field and field not in index:
            index[field] = position
    return index


def missing_columns(kind: str, index: dict[str, int]) -> list[str]:
    headings = {column.field: column.heading for column in COLUMNS[kind]}
    missing = [headings[field] for field in REQUIRED_FIELDS if field not in index]
    if not any(field in index for field in IDENTIFYING_FIELDS):
        missing.append(f"{headings['activity_id']} or {headings['school_code']}")
    return missing


def expected_headings(kind: str) -> list[str]:
    return [column.heading for column in COLUMNS[kind]]
