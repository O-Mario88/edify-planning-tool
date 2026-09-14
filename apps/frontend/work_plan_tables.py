"""Presentation of the shared work-plan ledger without changing its totals."""

from urllib.parse import urlencode

from apps.core.activity_types import COMPLETED_WORK_STATUSES, CLUSTER_MEETING_TYPES
from apps.ssa.plan_alignment import verdict_display


def detail_group(activity, summary_group):
    if summary_group == "non_school":
        return "non_school"
    if activity.activity_type in (
        *CLUSTER_MEETING_TYPES,
        "cluster_training",
        "cluster_training_ssa_collection",
    ):
        return "cluster"
    return "cluster" if activity.cluster_id and not activity.school_id else "school"


def detail_fields(activity, summary_group, period_label):
    invited = activity.schools_invited
    if invited is None:
        invited = activity.cluster_school_count_snapshot

    def participants(per_school):
        return (
            invited * per_school
            if invited is not None and per_school is not None
            else None
        )

    if activity.status == "cancelled":
        status, tone = "Cancelled", "neutral"
    elif activity.status in COMPLETED_WORK_STATUSES:
        status, tone = "Complete", "success"
    elif activity.reschedule_count or activity.status == "rescheduled":
        status, tone = "Rescheduled", "warning"
    else:
        status, tone = "Not complete", "warning"
    return {
        "detail_group": detail_group(activity, summary_group),
        "school_name": activity.school.name
        if activity.school_id
        else "School not recorded",
        "school_code": activity.school.school_id if activity.school_id else "",
        "cluster_name": activity.cluster.name
        if activity.cluster_id
        else "Cluster not recorded",
        "schools_invited": invited,
        "teachers_invited": participants(activity.teachers_per_school),
        "leaders_invited": participants(activity.leaders_per_school),
        "others_invited": participants(activity.other_per_school),
        "planned_period": period_label,
        "detail_venue": activity.venue,
        "delivery_status": status,
        "delivery_status_tone": tone,
        "ssa_verdict": verdict_display(activity),
    }


def grouped_tables(rows):
    return [
        {
            "key": key,
            "title": title,
            "page_param": f"wp_{key}_page",
            "rows": [r for r in rows if r["detail_group"] == key],
        }
        for key, title in [
            ("school", "School visits"),
            ("cluster", "Cluster activities"),
            ("non_school", "Non-school activities"),
        ]
    ]


def work_plan_action(
    activity, *, owned, enabled, recipient=None, recipient_name="responsible person"
):
    """Keep closed records readable; scheduling edits the existing activity."""
    if activity.status in COMPLETED_WORK_STATUSES or activity.status in (
        "cancelled",
        "rejected",
        "deferred",
    ):
        return {
            "text": "View",
            "url": f"/my-plan/{activity.id}",
            "description": "View activity record",
        }
    if (
        owned
        and enabled
        and activity.delivery_type != "partner"
        and activity.status in ("draft", "planned", "scheduled", "rescheduled")
    ):
        return {
            "text": "Schedule",
            "url": f"/my-plan/{activity.id}/reschedule-drawer",
            "drawer": True,
            "description": "Schedule or change the date of this existing activity",
        }
    if not owned and enabled and recipient:
        return {
            "text": f"Send to {recipient_name}",
            "url": "/messages/new?"
            + urlencode(
                {"context_type": "activity", "context_id": activity.id, "to": recipient}
            ),
            "description": "Review an activity-linked message before sending",
        }
    return None
