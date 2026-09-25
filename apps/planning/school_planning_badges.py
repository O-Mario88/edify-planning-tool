"""Visit and training planning badges for the two lists where people plan.

Owner brief, 2026-09-22: the Planning page school list and the Cluster School
List show, per school, how many visits and trainings are planned, waiting for
verification and IA-verified in the selected financial year. Nowhere else —
My Plan stays the detailed execution list, and every other surface is left as
it was.

On the operational year the lists read forward into the years ahead
(``fy_policy.planning_horizon``, owner 2026-09-23): a school planned in
September for October is planned, not "Not Planned" because its date falls in
the next fiscal year.

One read-only calculation serves both lists, so for the same school, financial
year and period the two cannot disagree. Nothing is stored: every count is
derived from the canonical Activity records and their workflow status each
time it is asked, so there is no ``school.visit_planned`` flag to go stale.

The badges are information, never a gate. A school with three planned visits
and two verified trainings stays selectable, keeps its Schedule button and can
be planned again — a follow-up, another intervention, another package slot or
a project activity is legitimate further work. ``existing_plan_warning`` is the
soft note the schedule drawer shows; it blocks nothing.

Three queries per call, whatever the number of schools:

1. activities that name the school directly;
2. cluster sessions the school is attached to by name
   (``ClusterActivityAttendance``) — never mere cluster membership;
3. completed cluster sessions that recorded the school in
   ``attended_school_ids`` (the older attendance record).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Q

from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    TRAINING_TYPES,
    VISIT_TYPES,
)

# ── Workflow status → badge bucket ───────────────────────────────────────────
#: Orange: a live plan that has not been delivered yet.
PLANNED_STATUSES = frozenset(
    {
        "planned",
        "scheduled",
        "rescheduled",
        "assigned_to_partner",
        "partner_scheduled",
        "in_progress",
        "completion_started",
    }
)
#: Blue: delivered and submitted, not yet verified by IA. ``completed`` is the
#: legacy value no production transition writes; it was never IA-verified, so
#: it is not shown as green.
AWAITING_VERIFICATION_STATUSES = frozenset(
    {
        "evidence_uploaded",
        "evidence_accepted",
        "salesforce_id_required",
        "submitted_to_pl",
        "awaiting_ia_verification",
        "completed",
    }
)
#: Green: IA-verified work (targets.my_targets.IA_VERIFIED_STATUSES).
VERIFIED_STATUSES = frozenset({"ia_verified", "accountant_confirmed", "closed"})
#: Amber: returned work that is no longer an active plan and needs replanning.
NEEDS_REPLANNING_STATUSES = frozenset({"returned", "returned_by_pl", "returned_by_ia"})
# Everything else — cancelled, rejected, deferred, not_planned and a visit
# request still awaiting its owner's approval — counts for nothing.

#: Statuses after delivery, when a cluster session's register is final: a
#: school counts only when it is marked as having attended.
_POST_DELIVERY = AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES

#: Cluster sessions a school can be attached to by name.
CLUSTER_SESSION_TYPES: tuple[str, ...] = tuple(
    sorted(
        set(CLUSTER_MEETING_TYPES)
        | {"cluster_training", "cluster_training_ssa_collection"}
    )
)

VISITS = "visits"
TRAININGS = "trainings"
CLUSTER_MEETINGS = "cluster_meetings"

#: Badge tones. Orange / blue / green / amber / gray, as the brief names them.
TONE_PLANNED = "planned"
TONE_AWAITING = "awaiting"
TONE_VERIFIED = "verified"
TONE_REPLAN = "replan"
TONE_NONE = "none"


def _bucket(status: str) -> str | None:
    if status in PLANNED_STATUSES:
        return "planned"
    if status in AWAITING_VERIFICATION_STATUSES:
        return "awaiting_verification"
    if status in VERIFIED_STATUSES:
        return "verified"
    if status in NEEDS_REPLANNING_STATUSES:
        return "needs_replanning"
    return None


@dataclass
class BadgeCounts:
    planned_count: int = 0
    awaiting_verification_count: int = 0
    verified_count: int = 0
    needs_replanning_count: int = 0
    next_date: date | None = None

    @property
    def total(self) -> int:
        return (
            self.planned_count
            + self.awaiting_verification_count
            + self.verified_count
            + self.needs_replanning_count
        )

    def add(self, bucket: str, day: date | None) -> None:
        setattr(self, f"{bucket}_count", getattr(self, f"{bucket}_count") + 1)
        if bucket == "planned" and day is not None:
            if self.next_date is None or day < self.next_date:
                self.next_date = day

    def chips(self, *, noun: str = "") -> list[dict]:
        """The small labelled counts the row shows, in reading order.

        ``noun`` prefixes every label ("Cluster Meeting") where the kind of
        session must be named; visits and trainings are named by the column.
        """
        prefix = f"{noun} " if noun else ""
        chips = []
        if self.planned_count:
            chips.append(
                {"label": f"{self.planned_count} {prefix}Planned", "tone": TONE_PLANNED}
            )
        if self.awaiting_verification_count:
            chips.append(
                {
                    "label": f"{self.awaiting_verification_count} {prefix}Awaiting Verification",
                    "tone": TONE_AWAITING,
                }
            )
        if self.verified_count:
            chips.append(
                {
                    "label": f"{self.verified_count} {prefix}Complete",
                    "tone": TONE_VERIFIED,
                }
            )
        if self.needs_replanning_count:
            chips.append(
                {
                    "label": f"{self.needs_replanning_count} {prefix}Needs Replanning",
                    "tone": TONE_REPLAN,
                }
            )
        return chips

    def as_dict(self) -> dict:
        return {
            "planned_count": self.planned_count,
            "awaiting_verification_count": self.awaiting_verification_count,
            "verified_count": self.verified_count,
            "needs_replanning_count": self.needs_replanning_count,
            "next_date": self.next_date.isoformat() if self.next_date else None,
        }


@dataclass
class SchoolPlanningBadges:
    school_id: str
    visits: BadgeCounts = field(default_factory=BadgeCounts)
    trainings: BadgeCounts = field(default_factory=BadgeCounts)
    cluster_meetings: BadgeCounts = field(default_factory=BadgeCounts)

    @property
    def visit_chips(self) -> list[dict]:
        return self.visits.chips() or [{"label": "Not Planned", "tone": TONE_NONE}]

    @property
    def training_chips(self) -> list[dict]:
        # A cluster meeting a school is invited to is training planned for
        # it (owner, 2026-09-25): the badge reads "Not Planned" only when
        # neither a group training nor a cluster meeting is planned.
        if self.trainings.chips() or self.cluster_meetings.chips():
            return self.trainings.chips()
        return [{"label": "Not Planned", "tone": TONE_NONE}]

    @property
    def cluster_meeting_chips(self) -> list[dict]:
        # Named as a meeting, beside the training chips, so the reader sees
        # which kind of session the training plan is.
        return self.cluster_meetings.chips(noun="Cluster Meeting")

    def as_dict(self) -> dict:
        return {
            "school_id": self.school_id,
            "visits": self.visits.as_dict(),
            "trainings": self.trainings.as_dict(),
            "cluster_meetings": self.cluster_meetings.as_dict(),
        }


def _classify(activity_type: str, counts_as_training: bool) -> str | None:
    """Which badge an activity belongs to.

    The activity's own type decides first. Only a type that is neither a visit
    nor a training — a cluster meeting, a project or partner activity — may be
    counted as training, and only when its governed catalogue item says it
    counts toward the training requirement.
    """
    if activity_type in TRAINING_TYPES:
        return TRAININGS
    if activity_type in VISIT_TYPES:
        return VISITS
    if counts_as_training:
        return TRAININGS
    if activity_type in CLUSTER_MEETING_TYPES:
        return CLUSTER_MEETINGS
    return None


def _day(planned_date, scheduled_date) -> date | None:
    if planned_date:
        return planned_date
    return scheduled_date.date() if scheduled_date else None


def _period_q(prefix: str, period) -> Q:
    date_start, date_end = period
    return Q(**{f"{prefix}planned_date__range": (date_start, date_end)}) | Q(
        **{
            f"{prefix}planned_date__isnull": True,
            f"{prefix}scheduled_date__date__range": (date_start, date_end),
        }
    )


def _fy_values(financial_year) -> list[str] | None:
    """One fiscal year, or the several a planning horizon covers
    (``apps.planning.fy_policy.planning_horizon``)."""
    if not financial_year:
        return None
    if isinstance(financial_year, (list, tuple, set, frozenset)):
        return sorted({str(fy) for fy in financial_year if fy}) or None
    return [str(financial_year)]


_TRAINING_FLAG = Q(catalogue_item__counts_toward_client_training=True) | Q(
    catalogue_item__is_training_course=True
)


class SchoolPlanningBadgeService:
    """The one server-side calculation behind both lists' badges."""

    @staticmethod
    def get_for_schools(
        school_ids,
        *,
        financial_year: str | None,
        period: tuple[date, date] | None = None,
        details: list | None = None,
    ) -> dict[str, SchoolPlanningBadges]:
        """Badges for each school. ``details``, when given, receives one
        entry per counted activity — what the drawer's View Existing Plans
        lists — so the list and the counts come from the same pass."""
        from apps.activities.models import Activity, ClusterActivityAttendance

        ids = list(dict.fromkeys(i for i in school_ids if i))
        badges = {
            school_id: SchoolPlanningBadges(school_id=school_id) for school_id in ids
        }
        if not ids:
            return badges

        fys = _fy_values(financial_year)
        # (school_id, activity_id) already counted — a session reached by two
        # routes (named on the row and in the register) is one session.
        seen: set[tuple[str, str]] = set()

        def count(school_id, activity_id, activity_type, flag, status, day):
            key = (school_id, activity_id)
            if key in seen:
                return
            kind = _classify(activity_type, flag)
            bucket = _bucket(status)
            if kind is None or bucket is None:
                return
            seen.add(key)
            getattr(badges[school_id], kind).add(bucket, day)
            if details is not None:
                details.append(
                    {
                        "school_id": school_id,
                        "activity_id": activity_id,
                        "activity_type": activity_type,
                        "kind": kind,
                        "bucket": bucket,
                        "status": status,
                        "date": day,
                    }
                )

        # 1. Activities that name the school.
        direct = Activity.objects.filter(
            school_id__in=ids, deleted_at__isnull=True
        ).filter(
            Q(activity_type__in=(*VISIT_TYPES, *TRAINING_TYPES, *CLUSTER_MEETING_TYPES))
            | _TRAINING_FLAG
        )
        if fys:
            direct = direct.filter(fy__in=fys)
        if period:
            direct = direct.filter(_period_q("", period))
        for row in direct.values(
            "id",
            "school_id",
            "activity_type",
            "status",
            "planned_date",
            "scheduled_date",
            "catalogue_item__counts_toward_client_training",
            "catalogue_item__is_training_course",
        ):
            count(
                row["school_id"],
                row["id"],
                row["activity_type"],
                bool(
                    row["catalogue_item__counts_toward_client_training"]
                    or row["catalogue_item__is_training_course"]
                ),
                row["status"],
                _day(row["planned_date"], row["scheduled_date"]),
            )

        # 2. Cluster sessions the school is attached to by name. Membership of
        # the cluster alone never counts (owner, 2026-09-15).
        register = ClusterActivityAttendance.objects.filter(
            school_id__in=ids,
            activity__deleted_at__isnull=True,
            activity__activity_type__in=CLUSTER_SESSION_TYPES,
        ).filter(Q(invited=True) | Q(attended=True))
        if fys:
            register = register.filter(activity__fy__in=fys)
        if period:
            register = register.filter(_period_q("activity__", period))
        for row in register.values(
            "school_id",
            "invited",
            "attended",
            "activity_id",
            "activity__activity_type",
            "activity__status",
            "activity__planned_date",
            "activity__scheduled_date",
            "activity__catalogue_item__counts_toward_client_training",
            "activity__catalogue_item__is_training_course",
        ):
            status = row["activity__status"]
            # Once delivered, the register is the record: a school invited but
            # absent did not receive the session and is not credited with it.
            if status in _POST_DELIVERY and not row["attended"]:
                continue
            count(
                row["school_id"],
                row["activity_id"],
                row["activity__activity_type"],
                bool(
                    row["activity__catalogue_item__counts_toward_client_training"]
                    or row["activity__catalogue_item__is_training_course"]
                ),
                status,
                _day(row["activity__planned_date"], row["activity__scheduled_date"]),
            )

        # 3. Delivered cluster sessions that recorded attendance on the
        # activity itself rather than in the register.
        attended = Activity.objects.filter(
            deleted_at__isnull=True,
            activity_type__in=CLUSTER_SESSION_TYPES,
            status__in=_POST_DELIVERY,
            attended_school_ids__overlap=ids,
        )
        if fys:
            attended = attended.filter(fy__in=fys)
        if period:
            attended = attended.filter(_period_q("", period))
        wanted = set(ids)
        for row in attended.values(
            "id",
            "activity_type",
            "status",
            "planned_date",
            "scheduled_date",
            "attended_school_ids",
            "catalogue_item__counts_toward_client_training",
            "catalogue_item__is_training_course",
        ):
            flag = bool(
                row["catalogue_item__counts_toward_client_training"]
                or row["catalogue_item__is_training_course"]
            )
            for school_id in row["attended_school_ids"] or []:
                if school_id in wanted:
                    count(
                        school_id,
                        row["id"],
                        row["activity_type"],
                        flag,
                        row["status"],
                        _day(row["planned_date"], row["scheduled_date"]),
                    )
        return badges

    @staticmethod
    def attach(rows, *, financial_year, period=None, key: str = "id") -> None:
        """Set ``planningBadges`` on each row dict, in one batched call."""
        rows = list(rows)
        badges = SchoolPlanningBadgeService.get_for_schools(
            [row[key] for row in rows],
            financial_year=financial_year,
            period=period,
        )
        for row in rows:
            row["planningBadges"] = badges.get(row[key]) or SchoolPlanningBadges(
                school_id=row[key]
            )


# ── The soft warning the schedule drawer shows ───────────────────────────────
def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


_BUCKET_LABELS = {
    "planned": "Planned",
    "awaiting_verification": "Awaiting Verification",
    "verified": "Complete",
    "needs_replanning": "Needs Replanning",
}
_BUCKET_TONES = {
    "planned": TONE_PLANNED,
    "awaiting_verification": TONE_AWAITING,
    "verified": TONE_VERIFIED,
    "needs_replanning": TONE_REPLAN,
}


def existing_plan_warning(school_id, *, financial_year) -> dict | None:
    """What the school already has, said once, before another is planned.

    Informational only: the drawer offers View Existing Plans, Continue
    Planning, Plan as Follow-Up and Cancel, and nothing is refused — another
    visit, a follow-up, a different intervention, a Core slot or a project
    activity is legitimate further work. ``None`` when the school has no
    planned, submitted or verified visit or training this year.
    """
    from apps.core.enums import ActivityType

    details: list[dict] = []
    badges = SchoolPlanningBadgeService.get_for_schools(
        [school_id], financial_year=financial_year, details=details
    ).get(school_id)
    if badges is None:
        return None
    parts = []
    for counts, noun in ((badges.visits, "visit"), (badges.trainings, "training")):
        if counts.planned_count:
            parts.append(_plural(counts.planned_count, f"planned {noun}"))
        if counts.awaiting_verification_count:
            parts.append(
                _plural(counts.awaiting_verification_count, noun)
                + " awaiting verification"
            )
        if counts.verified_count:
            parts.append(_plural(counts.verified_count, f"completed {noun}"))
    if not parts:
        return None
    summary = (
        parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    )
    type_labels = dict(ActivityType.choices)
    plans = sorted(
        (
            {
                "activity_id": row["activity_id"],
                "label": type_labels.get(row["activity_type"], row["activity_type"]),
                "status_label": _BUCKET_LABELS[row["bucket"]],
                "tone": _BUCKET_TONES[row["bucket"]],
                "date": row["date"],
            }
            for row in details
            if row["kind"] in (VISITS, TRAININGS)
        ),
        key=lambda plan: (plan["date"] is None, plan["date"] or date.min),
    )
    return {
        "message": (
            f"This school already has {summary}. You may continue if this is "
            "another required visit, follow-up, intervention, or project activity."
        ),
        "badges": badges,
        "plans": plans,
    }


__all__ = [
    "AWAITING_VERIFICATION_STATUSES",
    "BadgeCounts",
    "NEEDS_REPLANNING_STATUSES",
    "PLANNED_STATUSES",
    "SchoolPlanningBadgeService",
    "SchoolPlanningBadges",
    "VERIFIED_STATUSES",
    "existing_plan_warning",
]
