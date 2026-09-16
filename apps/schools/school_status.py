"""What is planned at a school: its visit status and its cluster training.

Owner brief, 2026-09-15: every school with a valid scheduled visit shows
"Scheduled for Visit", and Team Oversight separates the schools with a planned
cluster training or meeting from those with none. Both answers are DERIVED
from canonical Activity records every time they are asked — there is no
editable flag and no stored boolean to go stale. A cancelled, rejected or
returned plan counts as no plan.

One bulk query per question, so a page of 15 schools and a country of 15,000
cost the same number of statements.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Q
from django.utils import timezone

from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES, VISIT_TYPES

#: Statuses that mean the plan is not a plan any more.
DEAD_STATUSES = frozenset(
    {"cancelled", "rejected", "deferred", "not_planned", "returned", "returned_by_ia"}
)
#: Waiting for the school owner's yes — not yet a plan (visit requests).
PENDING_APPROVAL_STATUSES = frozenset({"awaiting_owner_approval"})
#: Returned to planning: real work that currently has no committed date.
RETURNED_TO_PLANNING = frozenset({"returned_by_pl"})

#: Cluster sessions a school can be attached to.
CLUSTER_SESSION_TYPES: tuple[str, ...] = tuple(
    set(CLUSTER_MEETING_TYPES) | {"cluster_training", "cluster_training_ssa_collection"}
)

# ── The visit-planning states ────────────────────────────────────────────────
NO_VISIT_PLANNED = "no_visit_planned"
VISIT_PLANNED = "visit_planned"
SCHEDULED_FOR_VISIT = "scheduled_for_visit"
VISIT_IN_PROGRESS = "visit_in_progress"
VISIT_SUBMITTED = "visit_submitted"
VISIT_VERIFIED = "visit_verified"
VISIT_COMPLETED = "visit_completed"
VISIT_CANCELED = "visit_canceled"

VISIT_LABELS = {
    NO_VISIT_PLANNED: "No Visit Planned",
    VISIT_PLANNED: "Visit Planned",
    SCHEDULED_FOR_VISIT: "Scheduled for Visit",
    VISIT_IN_PROGRESS: "Visit In Progress",
    VISIT_SUBMITTED: "Visit Submitted",
    VISIT_VERIFIED: "Visit Verified",
    VISIT_COMPLETED: "Visit Completed",
    VISIT_CANCELED: "Visit Canceled",
}
VISIT_TONES = {
    NO_VISIT_PLANNED: "neutral",
    VISIT_PLANNED: "info",
    SCHEDULED_FOR_VISIT: "success",
    VISIT_IN_PROGRESS: "info",
    VISIT_SUBMITTED: "info",
    VISIT_VERIFIED: "success",
    VISIT_COMPLETED: "success",
    VISIT_CANCELED: "warning",
}

#: Which activity status means which visit state.
_STATUS_STATE = {
    "planned": VISIT_PLANNED,
    "assigned_to_partner": VISIT_PLANNED,
    "returned_by_pl": VISIT_PLANNED,
    "scheduled": SCHEDULED_FOR_VISIT,
    "partner_scheduled": SCHEDULED_FOR_VISIT,
    "rescheduled": SCHEDULED_FOR_VISIT,
    "in_progress": VISIT_IN_PROGRESS,
    "completion_started": VISIT_IN_PROGRESS,
    "evidence_uploaded": VISIT_SUBMITTED,
    "evidence_accepted": VISIT_SUBMITTED,
    "salesforce_id_required": VISIT_SUBMITTED,
    "submitted_to_pl": VISIT_SUBMITTED,
    "awaiting_ia_verification": VISIT_SUBMITTED,
    "ia_verified": VISIT_VERIFIED,
    "accountant_confirmed": VISIT_COMPLETED,
    "completed": VISIT_COMPLETED,
    "closed": VISIT_COMPLETED,
}

#: Which state wins when a school has several visits in the period. The state
#: a person can still act on outranks one that is finished.
_PRECEDENCE = (
    VISIT_IN_PROGRESS,
    SCHEDULED_FOR_VISIT,
    VISIT_SUBMITTED,
    VISIT_VERIFIED,
    VISIT_COMPLETED,
    VISIT_PLANNED,
    VISIT_CANCELED,
    NO_VISIT_PLANNED,
)


@dataclass
class VisitStatus:
    school_id: str
    key: str = NO_VISIT_PLANNED
    next_date: date | None = None
    activity_id: str | None = None
    delivery_type: str = ""
    partner_name: str = ""

    @property
    def label(self) -> str:
        return VISIT_LABELS[self.key]

    @property
    def tone(self) -> str:
        return VISIT_TONES[self.key]

    @property
    def is_scheduled(self) -> bool:
        return self.key == SCHEDULED_FOR_VISIT

    @property
    def has_plan(self) -> bool:
        return self.key not in (NO_VISIT_PLANNED, VISIT_CANCELED)


def _period_filter(qs, *, fy, date_start, date_end):
    if fy:
        qs = qs.filter(fy=str(fy))
    if date_start and date_end:
        qs = qs.filter(
            Q(planned_date__range=(date_start, date_end))
            | Q(
                planned_date__isnull=True,
                scheduled_date__date__range=(date_start, date_end),
            )
        )
    return qs


def visit_statuses(
    school_ids,
    *,
    fy: str | None = None,
    date_start: date | None = None,
    date_end: date | None = None,
) -> dict[str, VisitStatus]:
    """The visit-planning state of each school, derived from its activities."""
    from apps.activities.models import Activity

    ids = [i for i in school_ids if i]
    statuses = {school_id: VisitStatus(school_id=school_id) for school_id in ids}
    if not ids:
        return statuses

    qs = Activity.objects.filter(
        school_id__in=ids,
        activity_type__in=VISIT_TYPES,
        deleted_at__isnull=True,
    ).exclude(status__in=PENDING_APPROVAL_STATUSES)
    qs = _period_filter(qs, fy=fy, date_start=date_start, date_end=date_end)

    rows = list(
        qs.values(
            "id",
            "school_id",
            "status",
            "planned_date",
            "scheduled_date",
            "delivery_type",
            "assigned_partner_id",
        )
    )
    partner_names = _partner_names({row["assigned_partner_id"] for row in rows})
    best: dict[str, tuple[int, date | None, dict]] = {}
    for row in rows:
        status = row["status"]
        if status in DEAD_STATUSES:
            state = VISIT_CANCELED
        else:
            state = _STATUS_STATE.get(status)
            if state is None:
                continue
        day = row["planned_date"] or (
            row["scheduled_date"].date() if row["scheduled_date"] else None
        )
        rank = _PRECEDENCE.index(state)
        current = best.get(row["school_id"])
        # Same state: the nearest date wins, so "next visit" is the next one.
        if (
            current is None
            or rank < current[0]
            or (
                rank == current[0]
                and day is not None
                and (current[1] is None or day < current[1])
            )
        ):
            best[row["school_id"]] = (rank, day, {**row, "state": state})

    for school_id, (_rank, day, row) in best.items():
        statuses[school_id] = VisitStatus(
            school_id=school_id,
            key=row["state"],
            next_date=day,
            activity_id=row["id"],
            delivery_type=row["delivery_type"] or "",
            partner_name=partner_names.get(row["assigned_partner_id"], ""),
        )
    return statuses


def _partner_names(partner_ids) -> dict[str, str]:
    """Partner names for the ids on these activities, in one query.

    ``Activity.assigned_partner_id`` is a plain column rather than a foreign
    key, so the name cannot be joined in with the rest of the row.
    """
    ids = {i for i in partner_ids if i}
    if not ids:
        return {}
    from apps.partners.models import Partner

    return dict(Partner.all_objects.filter(id__in=ids).values_list("id", "name"))


def visit_status(school, **kwargs) -> VisitStatus:
    school_id = getattr(school, "id", school)
    return visit_statuses([school_id], **kwargs)[school_id]


# ── Cluster training coverage ────────────────────────────────────────────────
TRAINING_PLANNED = "training_planned"
NO_TRAINING_PLANNED = "no_training_planned"

#: Why a school has no cluster training or meeting planned, in the words the
#: table shows. Ordered most specific first.
REASON_NOT_CLUSTERED = "School not attached to a cluster"
REASON_NO_ACTIVE_SCHEDULE = "Cluster has no active schedule"
REASON_CANCELED = "Existing plan canceled"
REASON_RETURNED = "Existing plan returned"
REASON_NO_TRAINING = "No cluster training planned"
REASON_NO_MEETING = "No cluster meeting planned"


@dataclass
class TrainingCoverage:
    school_id: str
    key: str = NO_TRAINING_PLANNED
    reason: str = REASON_NO_TRAINING
    activity_id: str | None = None
    activity_label: str = ""
    activity_type: str = ""
    cluster_id: str | None = None
    cluster_name: str = ""
    planned_date: date | None = None
    delivery_type: str = ""
    partner_name: str = ""
    status: str = ""

    @property
    def planned(self) -> bool:
        return self.key == TRAINING_PLANNED

    @property
    def label(self) -> str:
        if not self.planned:
            return "No Training Planned"
        if self.activity_type in CLUSTER_MEETING_TYPES:
            return "Cluster Meeting Planned"
        return "Training Planned"


def cluster_training_coverage(
    schools,
    *,
    fy: str | None = None,
    date_start: date | None = None,
    date_end: date | None = None,
) -> dict[str, TrainingCoverage]:
    """Whether each school is attached to a live cluster session in the period.

    A school counts as covered only when the planning record links it by name
    (ClusterActivityAttendance, written when the session is scheduled) — never
    because it happens to be in the cluster (owner, 2026-09-15). A cancelled,
    rejected or returned session is not a plan, and the row says so.
    """
    from apps.activities.models import Activity, ClusterActivityAttendance

    rows = list(schools)
    by_id = {getattr(s, "id", s): s for s in rows}
    coverage = {school_id: TrainingCoverage(school_id=school_id) for school_id in by_id}
    if not by_id:
        return coverage

    sessions = _period_filter(
        Activity.objects.filter(
            activity_type__in=CLUSTER_SESSION_TYPES, deleted_at__isnull=True
        ),
        fy=fy,
        date_start=date_start,
        date_end=date_end,
    )
    session_rows = {
        row["id"]: row
        for row in sessions.values(
            "id",
            "status",
            "activity_type",
            "activity_name_snapshot",
            "cluster_id",
            "cluster__name",
            "planned_date",
            "scheduled_date",
            "delivery_type",
            "assigned_partner_id",
        )
    }
    session_partner_names = _partner_names(
        {row["assigned_partner_id"] for row in session_rows.values()}
    )
    attachments: dict[str, list[dict]] = {}
    if session_rows:
        for school_id, activity_id in (
            ClusterActivityAttendance.objects.filter(
                activity_id__in=list(session_rows),
                school_id__in=list(by_id),
            )
            .filter(Q(invited=True) | Q(attended=True))
            .values_list("school_id", "activity_id")
        ):
            attachments.setdefault(school_id, []).append(session_rows[activity_id])

    for school_id, school in by_id.items():
        linked = attachments.get(school_id, [])
        live = [row for row in linked if row["status"] not in DEAD_STATUSES]
        if live:
            live.sort(
                key=lambda row: (
                    row["planned_date"]
                    or (
                        row["scheduled_date"].date()
                        if row["scheduled_date"]
                        else date.max
                    )
                )
            )
            row = live[0]
            coverage[school_id] = TrainingCoverage(
                school_id=school_id,
                key=TRAINING_PLANNED,
                reason="",
                activity_id=row["id"],
                activity_label=row["activity_name_snapshot"] or "",
                activity_type=row["activity_type"],
                cluster_id=row["cluster_id"],
                cluster_name=row["cluster__name"] or "",
                planned_date=row["planned_date"]
                or (row["scheduled_date"].date() if row["scheduled_date"] else None),
                delivery_type=row["delivery_type"] or "",
                partner_name=session_partner_names.get(row["assigned_partner_id"], ""),
                status=row["status"],
            )
            continue

        cluster_id = getattr(school, "cluster_id", None)
        if not cluster_id:
            reason = REASON_NOT_CLUSTERED
        elif linked:
            statuses = {row["status"] for row in linked}
            reason = (
                REASON_RETURNED
                if statuses & {"returned", "returned_by_ia", "returned_by_pl"}
                else REASON_CANCELED
            )
        else:
            reason = REASON_NO_TRAINING
        coverage[school_id] = TrainingCoverage(
            school_id=school_id,
            key=NO_TRAINING_PLANNED,
            reason=reason,
            cluster_id=cluster_id,
            # The cluster's name is resolved by the caller where it lists
            # rows (School.cluster_id is a plain column, not a relation).
            cluster_name="",
        )
    return coverage


def cluster_sessions_without_attachments(cluster_ids, *, fy=None) -> set[str]:
    """Clusters with no live session in the fiscal year — the honest reason a
    member school has nothing planned."""
    from apps.activities.models import Activity

    qs = Activity.objects.filter(
        cluster_id__in=list(cluster_ids),
        activity_type__in=CLUSTER_SESSION_TYPES,
        deleted_at__isnull=True,
    ).exclude(status__in=DEAD_STATUSES)
    if fy:
        qs = qs.filter(fy=str(fy))
    scheduled = set(qs.values_list("cluster_id", flat=True))
    return {cid for cid in cluster_ids if cid and cid not in scheduled}


def today() -> date:
    return timezone.localdate()


__all__ = [
    "CLUSTER_SESSION_TYPES",
    "NO_TRAINING_PLANNED",
    "NO_VISIT_PLANNED",
    "REASON_CANCELED",
    "REASON_NOT_CLUSTERED",
    "REASON_NO_ACTIVE_SCHEDULE",
    "REASON_NO_MEETING",
    "REASON_NO_TRAINING",
    "REASON_RETURNED",
    "SCHEDULED_FOR_VISIT",
    "TRAINING_PLANNED",
    "TRAINING_TYPES",
    "TrainingCoverage",
    "VISIT_LABELS",
    "VisitStatus",
    "cluster_sessions_without_attachments",
    "cluster_training_coverage",
    "visit_status",
    "visit_statuses",
]
