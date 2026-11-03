"""The downloadable template: the upload's columns and nothing else, with
the uploader's open work already filled in by ID.

Each open activity gives a line with its planned_activity_id and school_id;
a cluster or group training gives one line per school invited to it, since
the upload takes one line per participating school. The uploader types the
Salesforce ID, the completed date and, for a training, the counts.
"""

from __future__ import annotations

from django.db.models import Q

from apps.core.fy import get_operational_fy

from .columns import COLUMNS, TEMPLATE_NOTES
from .models import BulkKind
from .rules import KIND_TYPES, activities_in_reach, is_open

#: A template lists at most this many open activities; a country's year of
#: visits is well under it, and the file stays quick to open.
TEMPLATE_ROW_LIMIT = 20000

FILE_STEMS = {
    BulkKind.VISIT: "bulk-school-visit-completion",
    BulkKind.TRAINING: "bulk-training-completion",
}

#: Where an activity's saved Salesforce ID is offered back, by upload.
SALESFORCE_FIELD = {BulkKind.VISIT: "visit_sf_id", BulkKind.TRAINING: "training_sf_id"}


def open_work(principal, kind: str):
    """Open activities of this kind in the uploader's reach, this FY or
    earlier (next year's work cannot be completed before its year starts)."""
    from apps.activities.services import STARTABLE_STATUSES, SUBMITTABLE_STATUSES

    staff_open = Q(status__in=(*STARTABLE_STATUSES, *SUBMITTABLE_STATUSES)) & ~Q(
        delivery_type="partner"
    )
    partner_waiting = Q(delivery_type="partner", status="awaiting_ia_verification")
    return (
        activities_in_reach(principal)
        .filter(activity_type__in=KIND_TYPES[kind], fy__lte=get_operational_fy())
        .filter(staff_open | partner_waiting)
        .select_related("school")
        .order_by("planned_date", "scheduled_date", "id")
    )


def _invited_schools(activities) -> dict[str, list[str]]:
    """{activity id: School IDs invited} for the trainings with no school."""
    from apps.activities.models import ClusterActivityAttendance

    ids = [a.pk for a in activities if not a.school_id]
    invited: dict[str, list[str]] = {}
    if not ids:
        return invited
    for activity_id, code in (
        ClusterActivityAttendance.objects.filter(activity_id__in=ids)
        .order_by("school__name")
        .values_list("activity_id", "school__school_id")
    ):
        if code:
            invited.setdefault(activity_id, []).append(code)
    return invited


def _lines(activity, kind: str, invited: dict) -> list[dict]:
    cells = {
        "activity_id": activity.id,
        # The ID already saved on the activity is offered back, so a line for
        # work whose ID was entered but never handed in completes as it is.
        SALESFORCE_FIELD[kind]: activity.salesforce_activity_id or "",
    }
    if kind == BulkKind.TRAINING:
        cells.update(
            {
                "teachers": activity.teachers_attended or "",
                "leaders": activity.leaders_attended or "",
            }
        )
    if activity.school_id:
        return [{**cells, "school_code": activity.school.school_id}]
    schools = invited.get(activity.id) or [""]
    return [{**cells, "school_code": code} for code in schools]


def template_sheets(principal, kind: str) -> list[dict]:
    activities = [a for a in open_work(principal, kind)[:TEMPLATE_ROW_LIMIT]]
    activities = [a for a in activities if is_open(a)]
    invited = _invited_schools(activities) if kind == BulkKind.TRAINING else {}
    columns = COLUMNS[kind]
    rows = [
        [line.get(column.field, "") for column in columns]
        for activity in activities
        for line in _lines(activity, kind, invited)
    ]
    return [
        {
            "title": "Completions",
            "headers": [column.heading for column in columns],
            "rows": rows,
        },
        {
            "title": "How to fill it in",
            "headers": ["Instructions"],
            "rows": [[TEMPLATE_NOTES[kind]]],
            "widths": [120],
            "filter": False,
        },
    ]
