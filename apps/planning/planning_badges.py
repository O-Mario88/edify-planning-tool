"""Count-aware planning indicators for the Planning page and Cluster School List.

Two indicators per school — Visit, and Training or Cluster Engagement — read
from the canonical activity records on each request. Nothing is stored: there
is no ``school.visit_planned`` to go stale, and the browser renders only what
this returns.

The rules that make the indicators honest:

* **Counts, not a boolean.** A school may legitimately hold several activities
  of one kind; "2 Planned · 1 Complete" is the truth, "Planned" is not.
* **Planned, actual, submitted and verified stay distinct.** Only IA-verified
  work is Complete (green). Submitted work is Awaiting Verification (blue).
* **Informational only.** Nothing here gates planning. The Plan action stays
  open whatever an indicator says.
* **Explicit cluster invitation.** A Cluster Meeting or Group Training counts
  for a school only when that school was invited by name (or recorded as
  attending). Belonging to the cluster is not being planned for.
* **Partner work counts where the school is.** A Partner's scheduled visit is
  a planned visit at that school, and a handover still waiting for the
  Partner's date shows as Partner Planned, so staff can see support is
  already arranged.

Used ONLY by the Planning page and the Cluster School List (owner, 2026-09-23).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from django.db.models import Exists, OuterRef, Q

from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES, VISIT_TYPES

VISIT = "visit"
TRAINING = "training"

ENGAGEMENT_TYPES = (*TRAINING_TYPES, *CLUSTER_MEETING_TYPES)

# ── Status buckets ───────────────────────────────────────────────────────────
PLANNED_STATUSES = ("planned", "scheduled", "partner_scheduled", "assigned_to_partner")
IN_PROGRESS_STATUSES = (
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "evidence_accepted",
    "returned",
    "returned_by_pl",
    "returned_by_ia",
)
AWAITING_STATUSES = (
    "salesforce_id_required",
    "submitted_to_pl",
    "awaiting_ia_verification",
    # Written without IA sign-off on legacy rows; never green on its own.
    "completed",
    "closed",
)
IA_SIGNED_OFF_STATUSES = ("ia_verified", "accountant_confirmed")
#: Not a plan at all: cancelled, superseded, or a request nobody approved yet.
UNCOUNTED_STATUSES = (
    "cancelled",
    "rejected",
    "deferred",
    "not_planned",
    "rescheduled",
    "awaiting_owner_approval",
)

STATE_NOT_PLANNED = "not_planned"
STATE_PLANNED = "planned"
STATE_ACTIVE = "in_progress"
STATE_VERIFIED = "verified"
STATE_REPLAN = "needs_replanning"


def _is_verified(status: str, ia_status: str | None) -> bool:
    return status in IA_SIGNED_OFF_STATUSES or (
        ia_status == "confirmed" and status not in UNCOUNTED_STATUSES
    )


def _bucket(status: str, ia_status: str | None, planned_date, today) -> str | None:
    if status in UNCOUNTED_STATUSES:
        return None
    if _is_verified(status, ia_status):
        return "verified"
    if status in PLANNED_STATUSES:
        if planned_date and planned_date < today:
            return "needs_replanning"
        return "planned"
    if status in IN_PROGRESS_STATUSES:
        return "in_progress"
    if status in AWAITING_STATUSES:
        return "awaiting_verification"
    return None


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


def next_activity(indicators: dict) -> dict | None:
    """The earliest dated plan across both indicators, for Next Activity."""
    dated = [ind for ind in indicators.values() if ind.next_date]
    if not dated:
        return None
    first = min(dated, key=lambda ind: ind.next_date)
    return {"label": first.next_label, "date": first.next_date}


def _category(activity_type: str) -> str | None:
    if activity_type in VISIT_TYPES:
        return VISIT
    if activity_type in ENGAGEMENT_TYPES:
        return TRAINING
    return None


@dataclass
class PlanningIndicator:
    category: str
    planned: int = 0
    partner_planned: int = 0
    in_progress: int = 0
    awaiting_verification: int = 0
    verified: int = 0
    needs_replanning: int = 0
    next_date: date | None = None
    # What the next dated plan is ("Partner Visit", "Cluster Meeting"), so the
    # Next Activity cell is written here rather than guessed in a template.
    next_label: str = ""
    activity_ids: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            self.planned
            + self.partner_planned
            + self.in_progress
            + self.awaiting_verification
            + self.verified
            + self.needs_replanning
        )

    @property
    def state(self) -> str:
        if self.needs_replanning:
            return STATE_REPLAN
        if self.planned or self.partner_planned:
            return STATE_PLANNED
        if self.in_progress or self.awaiting_verification:
            return STATE_ACTIVE
        if self.verified:
            return STATE_VERIFIED
        return STATE_NOT_PLANNED

    @property
    def label(self) -> str:
        parts = []
        if self.needs_replanning:
            parts.append(f"{self.needs_replanning} Needs Replanning")
        if self.partner_planned:
            parts.append(f"{self.partner_planned} Partner Planned")
        if self.planned:
            parts.append(f"{self.planned} Planned")
        if self.in_progress:
            parts.append(f"{self.in_progress} In Progress")
        if self.awaiting_verification:
            parts.append(f"{self.awaiting_verification} Awaiting Verification")
        if self.verified:
            parts.append(f"{self.verified} Complete")
        if not parts:
            return "Not Planned"
        if self.next_date and (self.planned or self.partner_planned):
            parts.append(self.next_date.strftime("%-d %b"))
        return " · ".join(parts)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["state"] = self.state
        data["label"] = self.label
        data["total"] = self.total
        return data


class SchoolPlanningBadgeService:
    """Read-only. Four queries for a page of schools, whatever its size."""

    @staticmethod
    def badges(
        school_ids, *, fy: str, today: date | None = None
    ) -> dict[str, dict[str, PlanningIndicator]]:
        from apps.activities.models import Activity, ClusterActivityAttendance
        from apps.partners.models import PartnerAssignment

        today = today or date.today()
        ids = [str(i) for i in school_ids]
        out = {
            sid: {
                VISIT: PlanningIndicator(VISIT),
                TRAINING: PlanningIndicator(TRAINING),
            }
            for sid in ids
        }
        if not ids:
            return out

        seen: set[tuple[str, str]] = set()

        def add(sid, activity_id, activity_type, status, ia, planned_date, partner):
            category = _category(activity_type)
            if category is None or (sid, activity_id) in seen:
                return
            bucket = _bucket(status, ia, planned_date, today)
            if bucket is None:
                return
            seen.add((sid, activity_id))
            ind = out[sid][category]
            if bucket == "planned" and partner:
                ind.partner_planned += 1
            else:
                setattr(ind, bucket, getattr(ind, bucket) + 1)
            ind.activity_ids.append(activity_id)
            if (
                bucket == "planned"
                and planned_date
                and (ind.next_date is None or planned_date < ind.next_date)
            ):
                ind.next_date = planned_date
                noun = _NEXT_NOUN.get(activity_type) or (
                    "Visit" if category == VISIT else "Training"
                )
                ind.next_label = f"Partner {noun}" if partner else noun

        fields = (
            "id",
            "activity_type",
            "status",
            "ia_verification_status",
            "planned_date",
            "delivery_type",
        )
        # 1. School-level work: staff, Partner, Special Project and Core alike.
        for row in (
            Activity.objects.filter(school_id__in=ids, fy=fy, deleted_at__isnull=True)
            .exclude(status__in=UNCOUNTED_STATUSES)
            .values("school_id", *fields)
        ):
            add(
                row["school_id"],
                row["id"],
                row["activity_type"],
                row["status"],
                row["ia_verification_status"],
                row["planned_date"],
                row["delivery_type"] == "partner",
            )

        # 2. Cluster sessions the school was explicitly invited to or attended.
        for row in (
            ClusterActivityAttendance.objects.filter(
                school_id__in=ids,
                activity__fy=fy,
                activity__deleted_at__isnull=True,
            )
            .filter(Q(invited=True) | Q(attended=True))
            .exclude(activity__status__in=UNCOUNTED_STATUSES)
            .values(
                "school_id",
                *(f"activity__{f}" for f in fields),
            )
        ):
            add(
                row["school_id"],
                row["activity__id"],
                row["activity__activity_type"],
                row["activity__status"],
                row["activity__ia_verification_status"],
                row["activity__planned_date"],
                row["activity__delivery_type"] == "partner",
            )

        # 3. Legacy cluster rows that recorded attendance only in the array.
        for row in (
            Activity.objects.filter(
                fy=fy,
                deleted_at__isnull=True,
                school__isnull=True,
                attended_school_ids__overlap=ids,
            )
            .exclude(status__in=UNCOUNTED_STATUSES)
            .values("attended_school_ids", *fields)
        ):
            for sid in set(row["attended_school_ids"] or []) & set(ids):
                add(
                    sid,
                    row["id"],
                    row["activity_type"],
                    row["status"],
                    row["ia_verification_status"],
                    row["planned_date"],
                    row["delivery_type"] == "partner",
                )

        # 4. Partner handovers still waiting for the Partner's date. Once the
        #    Partner schedules, the activity in (1) carries the count instead,
        #    so nothing is counted twice.
        from apps.partners.support_responsibility import active_assignment_q

        for row in (
            PartnerAssignment.objects.filter(
                school_id__in=ids,
                scheduled_activity__isnull=True,
                status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
            )
            .filter(active_assignment_q(fy))
            .values(
                "id",
                "school_id",
                "expected_activity_type",
                "catalogue_item__workflow_kind",
            )
        ):
            kind = row["expected_activity_type"] or row["catalogue_item__workflow_kind"]
            category = TRAINING if kind in ENGAGEMENT_TYPES else VISIT
            ind = out[row["school_id"]][category]
            ind.partner_planned += 1
        return out

    # ── List filters: the same buckets, expressed as queryset conditions ────
    @staticmethod
    def filter_queryset(qs, key: str, *, fy: str, principal=None, today=None):
        """Narrow a School queryset to one Planning filter, in the database.

        Built from the same status buckets as ``badges`` so a filter and the
        indicators on the rows it returns cannot disagree, and applied before
        pagination so page counts are honest.
        """
        from apps.activities.models import Activity, ClusterActivityAttendance
        from apps.partners.models import PartnerAssignment
        from apps.partners.support_responsibility import active_assignment_q

        today = today or date.today()
        if key in ("", "all", None):
            return qs

        def school_work(types, statuses=None, extra=Q()):
            q = Activity.objects.filter(
                school=OuterRef("pk"),
                fy=fy,
                deleted_at__isnull=True,
                activity_type__in=types,
            ).exclude(status__in=UNCOUNTED_STATUSES)
            if statuses is not None:
                q = q.filter(status__in=statuses)
            return Exists(q.filter(extra))

        def invited_work(types, statuses=None, extra=Q()):
            q = ClusterActivityAttendance.objects.filter(
                school=OuterRef("pk"),
                activity__fy=fy,
                activity__deleted_at__isnull=True,
                activity__activity_type__in=types,
            ).filter(Q(invited=True) | Q(attended=True))
            q = q.exclude(activity__status__in=UNCOUNTED_STATUSES)
            if statuses is not None:
                q = q.filter(activity__status__in=statuses)
            return Exists(q.filter(extra))

        def waiting_handover(types):
            kinds = Q(expected_activity_type__in=types) | Q(
                expected_activity_type__isnull=True,
                catalogue_item__workflow_kind__in=types,
            )
            return Exists(
                PartnerAssignment.objects.filter(
                    school=OuterRef("pk"),
                    scheduled_activity__isnull=True,
                    status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
                )
                .filter(active_assignment_q(fy))
                .filter(kinds)
            )

        def any_visit():
            return school_work(VISIT_TYPES) | waiting_handover(VISIT_TYPES)

        def any_training():
            return (
                school_work(ENGAGEMENT_TYPES)
                | invited_work(ENGAGEMENT_TYPES)
                | waiting_handover(ENGAGEMENT_TYPES)
            )

        all_types = (*VISIT_TYPES, *ENGAGEMENT_TYPES)
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
                school_work(
                    VISIT_TYPES,
                    PLANNED_STATUSES,
                    Q(responsible_staff_id__in=mine, delivery_type="staff"),
                )
            )
        if key == "visit_not_planned":
            return qs.exclude(any_visit())
        if key == "training_not_planned":
            return qs.exclude(any_training())
        if key == "both_planned":
            return qs.filter(any_visit()).filter(any_training())
        if key == "awaiting_verification":
            not_verified = ~Q(ia_verification_status="confirmed")
            return qs.filter(
                school_work(all_types, AWAITING_STATUSES, not_verified)
                | invited_work(
                    all_types,
                    AWAITING_STATUSES,
                    ~Q(activity__ia_verification_status="confirmed"),
                )
            )
        if key == "completed":
            verified = Q(status__in=IA_SIGNED_OFF_STATUSES) | Q(
                ia_verification_status="confirmed"
            )
            return qs.filter(
                school_work(all_types, extra=verified)
                | invited_work(
                    all_types,
                    extra=Q(activity__status__in=IA_SIGNED_OFF_STATUSES)
                    | Q(activity__ia_verification_status="confirmed"),
                )
            )
        if key == "needs_replanning":
            overdue = Q(planned_date__lt=today) & ~Q(ia_verification_status="confirmed")
            return qs.filter(
                school_work(all_types, PLANNED_STATUSES, overdue)
                | invited_work(
                    all_types,
                    PLANNED_STATUSES,
                    Q(activity__planned_date__lt=today)
                    & ~Q(activity__ia_verification_status="confirmed"),
                )
            )
        return qs


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


__all__ = [
    "PLANNING_SUPPORT_FILTERS",
    "PlanningIndicator",
    "SchoolPlanningBadgeService",
    "TRAINING",
    "VISIT",
    "next_activity",
]
