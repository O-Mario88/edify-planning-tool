"""Partner-facilitated group trainings (owner, 2026-09-26).

"Partners sometimes facilitate trainings. For cluster group trainings assigned
to a partner, the facilitation fee part of the group training cost is for the
partner." Asked who completes such a training, the owner chose: staff
complete, the partner facilitates. New assignments follow this rule; work
already assigned to a partner is left as it was.

So a group training assigned to a partner by staff is staff work with a
facilitating partner:

* It is the officer's: `delivery_type` stays "staff", `responsible_staff_id`
  is the officer, and the officer completes it with the attendance and the
  Salesforce ID. The Programme Lead then confirms it or returns it.
* Its facilitation-fee cost lines are the partner's: stamped with the
  partner (`ActivityScheduleCostLine.partner_id`), left out of every staff
  money channel, and paid to the partner through the partner invoice flow
  (50% advance, the balance once the training is verified).
* Every other line (the officer's transport and lunch, meals, venue,
  materials) stays staff money, exactly as for any staff training.

This module is the one place that says which lines are the partner's.

Cluster meetings (owner, 2026-10-02): "Assigning a cluster to the partner ONLY
means they facilitate the cluster activity NOT assigned to them to do school
visit … it should allow them to organize the cluster meeting and facilitate it
so they will be paid facilitation fee. Just like when a partner is selected to
facilitate when the staff schedules a training." So a cluster meeting takes a
facilitating partner exactly as a group training does: it stays the officer's
work, and a meeting a partner facilitates carries the facilitation fee, which
is the partner's. A meeting staff facilitate still has no fee.
"""

from __future__ import annotations

from django.db.models import Q, Sum

from apps.core.activity_types import CLUSTER_MEETING_TYPES
from apps.core.enums import ActivityType

#: The cluster sessions a partner facilitates when staff hand one to it: the
#: group trainings and, since 2026-10-02, the cluster meetings. School-level
#: trainings are not cluster sessions; they name a facilitator directly.
FACILITATED_TRAINING_TYPES = frozenset(
    {
        ActivityType.CLUSTER_TRAINING.value,
        ActivityType.CLUSTER_TRAINING_SSA_COLLECTION.value,
        *(str(value) for value in CLUSTER_MEETING_TYPES),
    }
)

#: The cost-line type of the facilitation fee (costing_service._line_item_type).
FEE_LINE_TYPE = "facilitation"

#: Cost lines that are a facilitating partner's fee, for a query over
#: ActivityScheduleCostLine. Staff money channels exclude these.
PARTNER_FEE_LINES = Q(
    line_item_type=FEE_LINE_TYPE, activity__facilitating_partner_id__isnull=False
)


def facilitates(activity_type) -> bool:
    """Whether a partner assigned to this type of work facilitates it."""
    return (activity_type or "") in FACILITATED_TRAINING_TYPES


def is_facilitated(activity) -> bool:
    return bool(getattr(activity, "facilitating_partner_id", None))


def paid_partner_id(activity):
    """The partner paid for this activity: its delivering partner, or its
    facilitating partner; None for staff work with neither."""
    if getattr(activity, "delivery_type", "") == "partner":
        return activity.assigned_partner_id or None
    return getattr(activity, "facilitating_partner_id", None) or None


def line_partner_id(activity, line_item_type):
    """The partner a new cost line belongs to (costing_service stamps it):
    every line of partner-delivered work, and only the fee of a facilitated
    training."""
    if getattr(activity, "delivery_type", "") == "partner":
        return activity.assigned_partner_id or None
    if is_facilitated(activity) and line_item_type == FEE_LINE_TYPE:
        return activity.facilitating_partner_id
    return None


def partner_lines(activity):
    """The cost lines a partner is paid for: the fee alone of a facilitated
    training; every line of anything else, as partner payment has always
    read them (partner-delivered work, and any older path that pays a
    partner against an activity's whole cost)."""
    lines = activity.schedule_cost_lines.all()
    if getattr(activity, "delivery_type", "") != "partner" and is_facilitated(activity):
        return lines.filter(line_item_type=FEE_LINE_TYPE)
    return lines


def partner_planned_total(activity) -> int:
    return partner_lines(activity).aggregate(s=Sum("amount"))["s"] or 0


def facilitation_fees(activity_ids) -> dict[str, int]:
    """{activity id: its facilitation fee}, one query."""
    from apps.activities.models import ActivityScheduleCostLine

    ids = [i for i in dict.fromkeys(activity_ids or ()) if i]
    if not ids:
        return {}
    return {
        row["activity_id"]: int(row["total"] or 0)
        for row in ActivityScheduleCostLine.objects.filter(
            activity_id__in=ids, line_item_type=FEE_LINE_TYPE
        )
        .values("activity_id")
        .annotate(total=Sum("amount"))
    }


# ── "Facilitated by" (owner, 2026-09-29) ────────────────────────────────────
# "Scheduling training should have a Facilitated by field, listing the
# partners in the database including the staff. If it is going to be done by
# Edify staff then it should just be Staff." Staff may also change it on a
# planned training afterwards. A training facilitated by a partner stays staff
# work exactly as above; "Staff" is simply no facilitating partner.

#: Every staff-run training that may name who facilitates it.
FACILITATOR_TRAINING_TYPES = frozenset(
    {
        ActivityType.CLUSTER_TRAINING.value,
        ActivityType.CLUSTER_TRAINING_SSA_COLLECTION.value,
        ActivityType.IN_SCHOOL_TRAINING.value,
        ActivityType.CORE_TRAINING.value,
        ActivityType.TRAINING.value,
        ActivityType.SCHOOL_IMPROVEMENT_TRAINING.value,
        # A cluster meeting a partner organises and facilitates (owner,
        # 2026-10-02).
        *(str(value) for value in CLUSTER_MEETING_TYPES),
    }
)

#: What a refusal calls the work that takes a facilitator.
FACILITATOR_ONLY_MESSAGE = (
    "Only a training or a cluster meeting takes a Facilitated by partner."
)

#: What "Facilitated by" reads when Edify staff facilitate.
STAFF_FACILITATOR_LABEL = "Staff"

#: A training's facilitator changes only while it is still a plan: once it
#: has started, the day it happened is on record.
FACILITATOR_EDITABLE_STATUSES = frozenset(
    {"not_planned", "planned", "scheduled", "rescheduled", "deferred"}
)


def takes_facilitator(activity_type) -> bool:
    """Whether staff name who facilitates this type of work."""
    return (activity_type or "") in FACILITATOR_TRAINING_TYPES


def is_meeting(activity_type) -> bool:
    """Whether this is a cluster meeting rather than a training."""
    return (activity_type or "") in CLUSTER_MEETING_TYPES


def session_noun(activity_type) -> str:
    """ "meeting" or "training", for a sentence about facilitated work."""
    return "meeting" if is_meeting(activity_type) else "training"


def facilitator_partners():
    """The partners staff may name as a training's facilitator: every active
    partner organisation, by name."""
    from apps.partners.models import Partner

    return list(
        Partner.objects.filter(deleted_at__isnull=True, active_status=True)
        .order_by("name")
        .values("id", "name")
    )


def facilitator_label(activity, partner_name: str = "") -> str:
    """ "Staff", or the facilitating partner's name."""
    partner_id = getattr(activity, "facilitating_partner_id", None)
    if not partner_id:
        return STAFF_FACILITATOR_LABEL
    if partner_name:
        return partner_name
    from apps.partners.models import Partner

    return (
        Partner.objects.filter(id=partner_id).values_list("name", flat=True).first()
        or "Partner"
    )
