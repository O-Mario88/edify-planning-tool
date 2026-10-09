"""Presentation of the shared work-plan ledger without changing its totals."""

from urllib.parse import urlencode

from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_WORK_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)
from apps.activities.training_names import ONLINE_TRAINING_LABEL
from apps.ssa.plan_alignment import verdict_display

NOT_RECORDED = "—"

# The Detailed Activity Plan is one table for every kind of planned work
# (owner, 2026-10-05), and each of these columns reads one of a short list of
# plain words: Activity is "Visit", "Training" or what else was planned;
# Activity Purpose is why ("In-school Training", "Training Follow Up", "Group
# Training", "Cluster Meeting", a camp or conference by its name); Delivery
# Mode is how ("In-school Training", "School Visit", "Group Training",
# "Cluster Meeting").
IN_SCHOOL_TRAINING = "In-school Training"
GROUP_TRAINING = "Group Training"
CLUSTER_MEETING = "Cluster Meeting"
SCHOOL_VISIT = "School Visit"
#: The School Visit an in-school Training is delivered during.
COMPANION_VISIT_PURPOSE = "in_school_training_delivery_visit"
#: The SSA intervention of work no SSA intervention measures.
GENERAL = "General"


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


def _display(activity, field):
    """A choice field's label, for a model row or a plain test double."""
    reader = getattr(activity, f"get_{field}_display", None)
    if callable(reader):
        return reader() or ""
    return str(getattr(activity, field, "") or "").replace("_", " ").title()


def _kind(activity, summary_group) -> str:
    """meeting | in_school | training | visit | other."""
    if summary_group == "non_school":
        return "other"
    activity_type = activity.activity_type
    if activity_type in CLUSTER_MEETING_TYPES:
        return "meeting"
    if activity_type == "in_school_training":
        return "in_school"
    if activity_type in TRAINING_TYPES:
        return "training"
    if activity_type in VISIT_TYPES:
        return "visit"
    return "other"


def activity_word(activity, summary_group) -> str:
    """Activity: a Visit, a Training, or what else was planned."""
    kind = _kind(activity, summary_group)
    if kind == "visit":
        return "Visit"
    if kind in ("in_school", "training"):
        return "Training"
    if kind == "meeting":
        return "Meeting"
    return (
        _display(activity, "programme_activity_type")
        if getattr(activity, "programme_activity_type", None)
        else _display(activity, "activity_type")
    ) or "Activity"


def activity_purpose(activity, summary_group) -> str:
    """Activity Purpose: why the work is planned, in the planner's words."""
    from apps.partners.purposes import visit_purpose_label

    kind = _kind(activity, summary_group)
    if kind == "in_school":
        return IN_SCHOOL_TRAINING
    if kind == "training":
        return GROUP_TRAINING
    if kind == "meeting":
        return CLUSTER_MEETING
    purpose = getattr(activity, "purpose_type", None)
    if kind == "visit":
        if purpose == COMPANION_VISIT_PURPOSE:
            return IN_SCHOOL_TRAINING
        return visit_purpose_label(purpose, "") or _display(activity, "activity_type")
    # A camp, a conference, a district meeting: the name it was planned under.
    return (
        getattr(activity, "activity_name_snapshot", "")
        or _display(activity, "programme_activity_type")
        or _display(activity, "activity_type")
    )


def delivery_mode(activity, summary_group) -> str:
    """Delivery Mode: how the work reaches the school."""
    kind = _kind(activity, summary_group)
    if kind == "in_school":
        return IN_SCHOOL_TRAINING
    if kind == "training":
        # A Group Training delivered online (owner, 2026-10-09).
        if getattr(activity, "programme_delivery_mode", None) == "online":
            return ONLINE_TRAINING_LABEL
        return GROUP_TRAINING
    if kind == "meeting":
        return CLUSTER_MEETING
    if kind == "visit":
        return SCHOOL_VISIT
    if getattr(activity, "programme_delivery_mode", None):
        return _display(activity, "programme_delivery_mode")
    return (
        str(getattr(activity, "delivery_method_snapshot", "") or "")
        .replace("_", " ")
        .title()
    ) or NOT_RECORDED


def previous_ssa_score(activity) -> str:
    """The school's score in the planned intervention on the SSA the plan was
    made from, as it stood when the work was planned."""
    score = getattr(activity, "source_score", None)
    if score is None:
        return NOT_RECORDED
    return f"{float(score):.1f}"


def delivery_status(activity) -> tuple[str, str]:
    """Status: Scheduled or Complete (owner, 2026-10-05). A plan with no date
    yet is Planned, and work called off is Cancelled."""
    if activity.status == "cancelled":
        return "Cancelled", "neutral"
    if activity.status in COMPLETED_WORK_STATUSES:
        return "Complete", "success"
    dated = getattr(activity, "planned_date", True) or getattr(
        activity, "scheduled_date", None
    )
    return ("Scheduled", "info") if dated else ("Planned", "neutral")


def detail_fields(activity, summary_group, period_label, *, school_cluster_name=""):
    invited = activity.schools_invited
    if invited is None:
        invited = activity.cluster_school_count_snapshot

    def participants(per_school):
        return (
            invited * per_school
            if invited is not None and per_school is not None
            else None
        )

    status, tone = delivery_status(activity)
    school = activity.school if activity.school_id else None
    cluster = activity.cluster if activity.cluster_id else None
    district = (
        getattr(school, "district", None)
        or getattr(cluster, "district", None)
        or getattr(activity, "event_district", None)
    )
    return {
        "detail_group": detail_group(activity, summary_group),
        "school_name": school.name if school else "",
        "school_code": school.school_id if school else "",
        "district_name": getattr(district, "name", "") or "",
        # The cluster the work is for, else the one its school sits in.
        "cluster_name": (cluster.name if cluster else school_cluster_name) or "",
        "activity_word": activity_word(activity, summary_group),
        "activity_purpose": activity_purpose(activity, summary_group),
        "delivery_mode": delivery_mode(activity, summary_group),
        "previous_ssa_score": previous_ssa_score(activity),
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


#: The Detailed Activity Plan's one page of rows.
DETAIL_PAGE_PARAM = "wp_page"

_OPEN_TO_ITS_OWNER = ("draft", "planned", "scheduled", "rescheduled")


def work_plan_action(
    activity,
    *,
    owned,
    enabled,
    recipient=None,
    recipient_name="responsible person",
    recipient_label=None,
):
    """What the reader can do from this row.

    Their own work: Reschedule, and with it Complete and Cancel (``own``;
    ``complete`` once it has a date to be completed on), each the drawer My
    Plan opens. Somebody else's: a message to the person it is theirs to
    chase, a Program Lead to the CCEO, the Country Director to the Program
    Lead (``recipient_label``; owner, 2026-10-05). Closed records stay
    readable; scheduling edits the existing activity.
    """
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
        and activity.status in _OPEN_TO_ITS_OWNER
    ):
        dated = bool(
            getattr(activity, "planned_date", True)
            or getattr(activity, "scheduled_date", None)
        )
        return {
            "text": "Reschedule" if dated else "Schedule",
            "url": f"/my-plan/{activity.id}/reschedule-drawer",
            "drawer": True,
            "description": "Schedule or change the date of this existing activity",
            "own": True,
            "complete": dated and activity.status in ("scheduled", "rescheduled"),
        }
    if not owned and enabled and recipient:
        return {
            "text": f"Send to {recipient_label or recipient_name}",
            "url": "/messages/new?"
            + urlencode(
                {"context_type": "activity", "context_id": activity.id, "to": recipient}
            ),
            "description": (
                f"Review an activity-linked message to {recipient_name} before sending"
                if recipient_label
                else "Review an activity-linked message before sending"
            ),
        }
    return None
