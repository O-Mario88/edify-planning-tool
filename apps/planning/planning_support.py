"""The Planning page's support filters and Next Activity.

The Visit and Training counts themselves are ``school_planning_badges``' —
one calculation for the Planning page and the Cluster School List (owner,
2026-09-22). This module adds only what Partner-supported planning needs on
top (owner, 2026-09-23), and builds it from the same status buckets and the
same visit / training / cluster-meeting classification, so a filter and the
badges on the rows it returns cannot disagree:

* ``filter_queryset`` — the ten Planning filters, as database conditions
  applied before pagination so page counts stay honest;
* ``next_activities`` — the earliest upcoming planned activity per school,
  read from the badge service's ``details`` pass rather than a second count.

Informational only. Nothing here gates planning.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Exists, OuterRef, Q

from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES, VISIT_TYPES
from apps.planning.school_planning_badges import (
    _POST_DELIVERY,
    AWAITING_VERIFICATION_STATUSES,
    CLUSTER_MEETINGS,
    CLUSTER_SESSION_TYPES,
    NEEDS_REPLANNING_STATUSES,
    PLANNED_STATUSES,
    TRAININGS,
    VERIFIED_STATUSES,
    VISITS,
)

#: Every status a badge counts; anything else counts for nothing.
COUNTED_STATUSES = (
    PLANNED_STATUSES
    | AWAITING_VERIFICATION_STATUSES
    | VERIFIED_STATUSES
    | NEEDS_REPLANNING_STATUSES
)

#: The Planning filter menu, in the owner's order.
PLANNING_SUPPORT_FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "All Schools"),
    ("staff_managed", "Staff Managed"),
    ("partner_support", "Partner Support"),
    ("my_scheduled_visits", "My Scheduled Visits"),
    ("visit_not_planned", "Visit Not Planned"),
    ("training_not_planned", "Training Not Planned"),
    ("both_planned", "Both Planned"),
    ("awaiting_verification", "Awaiting Verification"),
    ("completed", "Completed"),
    ("needs_replanning", "Needs Replanning"),
)


# ── Classification as queryset conditions (school_planning_badges._classify) ─
def _kind_q(kind: str | None, prefix: str = "") -> Q:
    """Activities the badge service would count under ``kind`` (None = any)."""
    types = f"{prefix}activity_type__in"
    flag = Q(**{f"{prefix}catalogue_item__counts_toward_client_training": True}) | Q(
        **{f"{prefix}catalogue_item__is_training_course": True}
    )
    if kind == VISITS:
        return Q(**{types: VISIT_TYPES})
    if kind == TRAININGS:
        return Q(**{types: TRAINING_TYPES}) | (flag & ~Q(**{types: VISIT_TYPES}))
    if kind == CLUSTER_MEETINGS:
        return Q(**{types: CLUSTER_MEETING_TYPES}) & ~flag
    return Q(**{types: (*VISIT_TYPES, *TRAINING_TYPES, *CLUSTER_MEETING_TYPES)}) | flag


def _counted(kind: str | None, statuses, *, fy: str) -> Q:
    """Schools with at least one activity the badges count as ``kind``.

    The same three routes the badge service reads: activities that name the
    school, cluster sessions it is attached to by name, and delivered cluster
    sessions that recorded it in ``attended_school_ids``.
    """
    from apps.activities.models import Activity, ClusterActivityAttendance

    statuses = tuple(statuses)
    direct = Exists(
        Activity.objects.filter(
            school=OuterRef("pk"),
            fy=fy,
            deleted_at__isnull=True,
            status__in=statuses,
        ).filter(_kind_q(kind))
    )
    if kind == VISITS:
        return direct  # no cluster session is a visit

    register = Exists(
        ClusterActivityAttendance.objects.filter(
            school=OuterRef("pk"),
            activity__fy=fy,
            activity__deleted_at__isnull=True,
            activity__activity_type__in=CLUSTER_SESSION_TYPES,
            activity__status__in=statuses,
        )
        .filter(Q(invited=True) | Q(attended=True))
        # Once delivered, the register is the record: invited but absent is
        # not credited.
        .exclude(activity__status__in=_POST_DELIVERY, attended=False)
        .filter(_kind_q(kind, "activity__"))
    )

    delivered = [s for s in statuses if s in _POST_DELIVERY]
    attended_ids: set[str] = set()
    if delivered:
        for school_ids in (
            Activity.objects.filter(
                fy=fy,
                deleted_at__isnull=True,
                activity_type__in=CLUSTER_SESSION_TYPES,
                status__in=delivered,
                attended_school_ids__len__gt=0,
            )
            .filter(_kind_q(kind))
            .values_list("attended_school_ids", flat=True)
        ):
            attended_ids.update(school_ids or [])
    counted = Q(direct) | Q(register)
    return counted | Q(pk__in=attended_ids) if attended_ids else counted


def filter_queryset(qs, key: str | None, *, fy: str, principal=None):
    """Narrow a School queryset to one Planning filter, in the database."""
    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment
    from apps.partners.support_responsibility import active_assignment_q

    if key in ("", "all", None):
        return qs
    partner_support = Exists(
        PartnerAssignment.objects.filter(school=OuterRef("pk")).filter(
            active_assignment_q(fy)
        )
    )
    if key == "partner_support":
        return qs.filter(partner_support)
    if key == "staff_managed":
        return qs.exclude(partner_support)
    if key == "my_scheduled_visits":
        from apps.core.scoping import owner_ids

        mine = [i for i in owner_ids(principal) if i] if principal else []
        return qs.filter(
            Exists(
                Activity.objects.filter(
                    school=OuterRef("pk"),
                    fy=fy,
                    deleted_at__isnull=True,
                    activity_type__in=VISIT_TYPES,
                    status__in=PLANNED_STATUSES,
                    responsible_staff_id__in=mine,
                    delivery_type="staff",
                )
            )
        )
    if key == "visit_not_planned":
        return qs.exclude(_counted(VISITS, COUNTED_STATUSES, fy=fy))
    if key == "training_not_planned":
        return qs.exclude(_counted(TRAININGS, COUNTED_STATUSES, fy=fy))
    if key == "both_planned":
        return qs.filter(_counted(VISITS, COUNTED_STATUSES, fy=fy)).filter(
            _counted(TRAININGS, COUNTED_STATUSES, fy=fy)
        )
    if key == "awaiting_verification":
        return qs.filter(_counted(None, AWAITING_VERIFICATION_STATUSES, fy=fy))
    if key == "completed":
        return qs.filter(_counted(None, VERIFIED_STATUSES, fy=fy))
    if key == "needs_replanning":
        return qs.filter(_counted(None, NEEDS_REPLANNING_STATUSES, fy=fy))
    return qs


# ── Next Activity ────────────────────────────────────────────────────────────
_NEXT_NOUN = {
    "cluster_meeting": "Cluster Meeting",
    "cluster_meeting_ssa_review": "Cluster Meeting",
    "cluster_training": "Group Training",
    "cluster_training_ssa_collection": "Group Training",
    "donor_visit": "Donor Visit",
    "story_gathering_visit": "Content Gathering",
    "school_visit_ssa_collection": "Data Gathering",
    "baseline_ssa_visit": "Data Gathering",
    "in_school_training": "In-school Training",
    "school_visit": "School Visit",
}
_KIND_NOUN = {
    VISITS: "Visit",
    TRAININGS: "Training",
    CLUSTER_MEETINGS: "Cluster Meeting",
}


def next_activities(details, *, today: date | None = None) -> dict[str, dict]:
    """The earliest upcoming planned activity per school, for Next Activity.

    ``details`` is the list the badge service's ``get_for_schools``
    filled in the same pass as the badges. One query names Partner-delivered
    ones ("Partner Visit") so staff can see who is coming.
    """
    from apps.activities.models import Activity

    today = today or date.today()
    first: dict[str, dict] = {}
    for row in details:
        day = row["date"]
        if row["bucket"] != "planned" or day is None or day < today:
            continue
        current = first.get(row["school_id"])
        # Ties go to the lower id, so both lists name the same activity.
        if current is None or (day, row["activity_id"]) < (
            current["date"],
            current["activity_id"],
        ):
            first[row["school_id"]] = row
    if not first:
        return {}
    partner = set(
        Activity.objects.filter(
            id__in=[row["activity_id"] for row in first.values()],
            delivery_type="partner",
        ).values_list("id", flat=True)
    )
    out = {}
    for school_id, row in first.items():
        noun = _NEXT_NOUN.get(row["activity_type"]) or _KIND_NOUN[row["kind"]]
        if row["activity_id"] in partner:
            noun = f"Partner {noun}"
        out[school_id] = {"label": noun, "date": row["date"]}
    return out


__all__ = [
    "COUNTED_STATUSES",
    "PLANNING_SUPPORT_FILTERS",
    "filter_queryset",
    "next_activities",
]
