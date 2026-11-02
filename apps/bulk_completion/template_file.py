"""The downloadable template: the uploader's open work, ready to be filled in."""

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
        .select_related("school", "cluster", "training_course")
        .order_by("planned_date", "scheduled_date", "id")
    )


def _day(activity):
    if activity.planned_date:
        return activity.planned_date
    if activity.scheduled_date:
        from apps.core.clock import local_day

        return local_day(activity.scheduled_date)
    return None


def _cells(activity, kind: str, names: dict[str, str]) -> dict[str, object]:
    school = activity.school
    who = activity.responsible_staff_id or activity.monitored_by_staff_id
    responsible = names.get(str(who or ""), "")
    if activity.delivery_type == "partner":
        responsible = names.get(f"partner:{activity.assigned_partner_id}", "Partner")
    cells = {
        "activity_id": activity.id,
        "school_code": school.school_id if school else "",
        "school_name": school.name if school else "",
        "activity_type": activity.get_activity_type_display(),
        "scheduled_on": _day(activity),
        "responsible": responsible,
        # The ID already saved on the activity is offered back, so a line for
        # work whose ID was entered but never handed in completes as it is.
        "salesforce_id": activity.salesforce_activity_id or "",
        "completed_on": "",
    }
    if kind == BulkKind.TRAINING:
        cells.update(
            {
                "title": (
                    activity.training_course.display_name
                    if activity.training_course_id
                    else ""
                ),
                "cluster": activity.cluster.name if activity.cluster_id else "",
                "teachers": activity.teachers_attended or "",
                "leaders": activity.leaders_attended or "",
                "participants": "",
            }
        )
    return cells


def template_sheets(principal, kind: str) -> list[dict]:
    from apps.activities.profile_activities import _partner_names, _staff_names

    activities = [a for a in open_work(principal, kind)[:TEMPLATE_ROW_LIMIT]]
    activities = [a for a in activities if is_open(a)]
    names = _staff_names(
        {a.responsible_staff_id or a.monitored_by_staff_id for a in activities}
    )
    names.update(
        {
            f"partner:{pid}": name
            for pid, name in _partner_names(
                {a.assigned_partner_id for a in activities}
            ).items()
        }
    )
    columns = COLUMNS[kind]
    rows = []
    for activity in activities:
        cells = _cells(activity, kind, names)
        rows.append([cells.get(column.field, "") for column in columns])
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
