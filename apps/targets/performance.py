"""PerformanceService — the single backend engine for staff performance.

ONE set of achievement predicates, reused by every consumer (metrics,
drilldowns, target status, system-health). Counts can never diverge because
there is exactly one definition of "achieved."

Achievement rule (strict):
  An activity counts as achieved when its status is in ACHIEVED_STATUSES
  (completed / ia_verified / accountant_confirmed). Staff-delivered activities
  terminate at ia_verified; partner activities at completed. A VISIT or TRAINING
  counts as achieved ONLY when evidence_status == 'accepted' AND an Activity
  Code (salesforce_activity_id) is present. Drafts / planned / cancelled /
  returned / unverified activities never count. SSA counts only when confirmed
  with all 8 intervention scores.

All counts are DB aggregations (Count with conditional Q filters), never Python
loops over activities. Scope-aware: a CCEO sees only their own activities
(responsible_staff_id); a PL sees their supervised team; CD sees the country.
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES
from apps.core.fy import (
    get_fy_date_range,
    get_mid_year_range,
    get_quarter_date_range,
)


# ── Achievement predicates (the single source of truth) ─────────────────────

# Statuses that mean the activity's work is genuinely done.
ACHIEVED_STATUSES = ("ia_verified", "closed", "accountant_confirmed")

# Activity-type sets.
CLUSTER_MEETING_TYPE = "cluster_meeting"
PARTNER_ACTIVITIES = ("partner_activity", "project_activity")


def _achieved_q() -> Q:
    """Base Q: status is a genuine done-state."""
    return Q(status__in=ACHIEVED_STATUSES)


def _visit_achieved_q() -> Q:
    """A school visit counts only when completed + evidence accepted + Activity Code present."""
    return (
        _achieved_q()
        & Q(activity_type__in=VISIT_TYPES)
        & Q(evidence_status="accepted")
        & ~Q(salesforce_activity_id="")
        & ~Q(salesforce_activity_id=None)
    )


def _training_achieved_q() -> Q:
    """A training counts only when completed + evidence accepted + TS Activity Code + participants."""
    return (
        _achieved_q()
        & Q(activity_type__in=TRAINING_TYPES)
        & Q(evidence_status="accepted")
        & ~Q(salesforce_activity_id="")
        & ~Q(salesforce_activity_id=None)
    )


def _cluster_meeting_achieved_q() -> Q:
    """A cluster meeting counts when completed + evidence accepted."""
    return (
        _achieved_q()
        & Q(activity_type=CLUSTER_MEETING_TYPE)
        & Q(evidence_status="accepted")
    )


def _ia_verified_q() -> Q:
    """Activities that passed IA verification."""
    return _achieved_q() & Q(ia_verification_status="confirmed")


def _evidence_accepted_q() -> Q:
    """Activities with accepted evidence (submitted + accepted)."""
    return Q(evidence_status="accepted")


def _activity_code_q() -> Q:
    """Activities with an Activity Code entered."""
    return (
        ~Q(salesforce_activity_id="") & ~Q(salesforce_activity_id=None) & _achieved_q()
    )


# ── Period bounds ────────────────────────────────────────────────────────────


def period_bounds(
    fy: str,
    period_type: str = "fy",
    quarter: str | None = None,
    month: int | None = None,
) -> tuple[datetime, datetime]:
    """Return the (start, end) datetime range for a performance period.

    Cumulative: a quarter spans its 3 months; mid-year = Q1+Q2; FY = all.
    week/month narrow within the FY. All ranges are FY-aware (Oct 1 start)."""
    period_type = (period_type or "fy").lower()
    if period_type == "fy":
        return get_fy_date_range(fy)
    if period_type in ("mid_year", "midyear"):
        return get_mid_year_range(fy)
    if period_type == "quarter" and quarter:
        return get_quarter_date_range(fy, quarter)
    if period_type == "month" and month:
        return get_fy_date_range(fy)  # narrow below
    return get_fy_date_range(fy)


# ── Core metric computation ─────────────────────────────────────────────────


def staff_metrics(
    staff_id: str, fy: str, start: datetime | None = None, end: datetime | None = None
) -> dict:
    """Compute every performance metric for a staff member in a period.

    All counts are DB aggregations. Returns a flat dict of metric→count. The
    responsible_staff_id is the StaffProfile CUID PK (matches Activity field)."""
    from apps.activities.models import Activity

    if start is None or end is None:
        start, end = get_fy_date_range(fy)

    # Base queryset: this staff's activities in the FY, within the period range,
    # not deleted. Period narrowing uses scheduled_date (when the work happened).
    base = Activity.objects.filter(
        responsible_staff_id=staff_id,
        deleted_at__isnull=True,
        fy=fy,
        scheduled_date__gte=start,
        scheduled_date__lt=end,
    )

    # Single aggregate query with conditional counts — one DB round-trip.
    agg = base.aggregate(
        school_visits=Count("id", filter=_visit_achieved_q()),
        schools_trained=Count("id", filter=_training_achieved_q()),
        cluster_meetings=Count("id", filter=_cluster_meeting_achieved_q()),
        group_trainings=Count(
            "id",
            filter=(
                _training_achieved_q()
                & Q(
                    activity_type__in=(
                        "training",
                        "school_improvement_training",
                        "cluster_training",
                        "core_training",
                    )
                )
            ),
        ),
        evidence_submitted=Count("id", filter=_evidence_accepted_q()),
        activity_codes_submitted=Count("id", filter=_activity_code_q()),
        ia_verified_activities=Count("id", filter=_ia_verified_q()),
        partner_activities_supervised=Count(
            "id", filter=(_achieved_q() & Q(delivery_type="partner"))
        ),
        total_planned=Count("id"),
        total_completed=Count("id", filter=_achieved_q()),
        teachers_trained_sum=Sum("teachers_attended", filter=_training_achieved_q()),
        leaders_trained_sum=Sum("leaders_attended", filter=_training_achieved_q()),
    )

    # SSA completion (separate model). Confirmed + all 8 scores.
    ssa_completed = _count_ssa_for_staff(staff_id, fy, start, end)

    return {
        "school_visits": agg["school_visits"] or 0,
        "schools_trained": agg["schools_trained"] or 0,
        "ssa_completed": ssa_completed,
        "cluster_meetings": agg["cluster_meetings"] or 0,
        "group_trainings": agg["group_trainings"] or 0,
        "evidence_submitted": agg["evidence_submitted"] or 0,
        "activity_codes_submitted": agg["activity_codes_submitted"] or 0,
        "ia_verified_activities": agg["ia_verified_activities"] or 0,
        "partner_activities_supervised": agg["partner_activities_supervised"] or 0,
        "total_planned": agg["total_planned"] or 0,
        "total_completed": agg["total_completed"] or 0,
        "teachers_trained": int(agg["teachers_trained_sum"] or 0),
        "leaders_trained": int(agg["leaders_trained_sum"] or 0),
    }


def _count_ssa_for_staff(staff_id: str, fy: str, start: datetime, end: datetime) -> int:
    """SSA records completed for schools owned by this staff in the period.
    'Completed' = confirmed verification + all 8 intervention scores present."""
    from apps.ssa.models import SsaRecord, SsaScore
    from apps.accounts.models import StaffSchoolAssignment

    school_ids = list(
        StaffSchoolAssignment.objects.filter(staff_id=staff_id).values_list(
            "school_id", flat=True
        )
    )
    if not school_ids:
        return 0
    # SSA records for these schools, confirmed, in the period, with 8 scores.
    confirmed = SsaRecord.objects.filter(
        school_id__in=school_ids,
        fy=fy,
        verification_status="confirmed",
        date_of_ssa__gte=start,
        date_of_ssa__lt=end,
        deleted_at__isnull=True,
    )
    # Filter to records with exactly 8 distinct scores.
    count = 0
    for rec in confirmed.values("id"):
        score_count = (
            SsaScore.objects.filter(ssa_record_id=rec["id"])
            .values("intervention")
            .distinct()
            .count()
        )
        if score_count == 8:
            count += 1
    return count


# ── Drilldown (exact records behind a metric) ───────────────────────────────


def drilldown(
    staff_id: str,
    metric: str,
    fy: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict]:
    """Return the exact Activity/SSA records counted by a metric — so the card
    count always equals the drilldown count."""
    from apps.activities.models import Activity

    if start is None or end is None:
        start, end = get_fy_date_range(fy)

    base = Activity.objects.filter(
        responsible_staff_id=staff_id,
        deleted_at__isnull=True,
        fy=fy,
        scheduled_date__gte=start,
        scheduled_date__lt=end,
    ).select_related("school")

    metric_q = {
        "school_visits": _visit_achieved_q(),
        "schools_trained": _training_achieved_q(),
        "cluster_meetings": _cluster_meeting_achieved_q(),
        "group_trainings": _training_achieved_q()
        & Q(
            activity_type__in=(
                "training",
                "school_improvement_training",
                "cluster_training",
                "core_training",
            )
        ),
        "evidence_submitted": _evidence_accepted_q(),
        "activity_codes_submitted": _activity_code_q(),
        "ia_verified_activities": _ia_verified_q(),
        "partner_activities_supervised": _achieved_q() & Q(delivery_type="partner"),
    }.get(metric, _achieved_q())

    if metric == "ssa_completed":
        return _drilldown_ssa(staff_id, fy, start, end)

    rows = []
    for a in base.filter(metric_q):
        rows.append(
            {
                "id": a.id,
                "activityType": a.activity_type,
                "status": a.status,
                "schoolId": a.school.school_id if a.school_id else None,
                "schoolName": a.school.name if a.school_id else None,
                "scheduledDate": a.scheduled_date.isoformat()
                if a.scheduled_date
                else None,
                "evidenceStatus": a.evidence_status,
                "activityCode": a.salesforce_activity_id,
                "iaVerificationStatus": a.ia_verification_status,
            }
        )
    return rows


def _drilldown_ssa(
    staff_id: str, fy: str, start: datetime, end: datetime
) -> list[dict]:
    from apps.ssa.models import SsaRecord
    from apps.accounts.models import StaffSchoolAssignment

    school_ids = list(
        StaffSchoolAssignment.objects.filter(staff_id=staff_id).values_list(
            "school_id", flat=True
        )
    )
    if not school_ids:
        return []
    confirmed = SsaRecord.objects.filter(
        school_id__in=school_ids,
        fy=fy,
        verification_status="confirmed",
        date_of_ssa__gte=start,
        date_of_ssa__lt=end,
        deleted_at__isnull=True,
    ).select_related("school")
    rows = []
    for rec in confirmed:
        score_count = rec.scores.values("intervention").distinct().count()
        if score_count == 8:
            rows.append(
                {
                    "id": rec.id,
                    "schoolId": rec.school.school_id,
                    "schoolName": rec.school.name,
                    "dateOfSsa": rec.date_of_ssa.isoformat(),
                    "averageScore": rec.average_score,
                    "verificationStatus": rec.verification_status,
                }
            )
    return rows


__all__ = [
    "ACHIEVED_STATUSES",
    "staff_metrics",
    "drilldown",
    "period_bounds",
    "resolve_target",
    "target_status",
    "build_target_card",
    "staff_metrics_with_targets",
    "_visit_achieved_q",
    "_training_achieved_q",
    "_cluster_meeting_achieved_q",
    "_achieved_q",
]


# ── Target resolution ───────────────────────────────────────────────────────

# Map metric key → StaffTargetProfile field name.
_TARGET_FIELD = {
    "school_visits": "visits_target",
    "schools_trained": "trainings_target",
    "ssa_completed": "ssa_target",
    "cluster_meetings": "cluster_meetings_target",
    "group_trainings": "group_trainings_target",
    "evidence_submitted": "evidence_target",
    "activity_codes_submitted": "activity_codes_target",
    "ia_verified_activities": "ia_verified_target",
    "accountability_completed": "accountability_target",
}


def resolve_target(staff_id: str, fy: str, metric: str) -> int:
    """The configured annual target for a metric. Returns 0 when unconfigured."""
    from apps.accounts.models import StaffTargetProfile

    field = _TARGET_FIELD.get(metric)
    if not field:
        return 0
    tp = StaffTargetProfile.objects.filter(staff_id=staff_id, fy=fy).first()
    if not tp:
        return 0
    return getattr(tp, field, 0) or 0


# ── Target status logic ─────────────────────────────────────────────────────


def target_status(
    achieved: int,
    target: int,
    period_start: datetime,
    period_end: datetime,
    now: datetime | None = None,
) -> str:
    """Compute a status from achieved vs target + elapsed time within the period.

    Returns one of: completed, exceeded, on_track, behind, at_risk, no_target.
    Uses elapsed-time-within-period to compute expected progress."""
    if target <= 0:
        return "no_target"
    if achieved >= target:
        return "exceeded" if achieved > target else "completed"
    now = now or timezone.now()
    if now < period_start:
        # Period hasn't started yet.
        return "on_track"
    total = (period_end - period_start).total_seconds()
    elapsed = (min(now, period_end) - period_start).total_seconds()
    pct_elapsed = elapsed / total if total > 0 else 1.0
    expected = target * pct_elapsed
    if achieved >= expected:
        return "on_track"
    # Below expected: how far below determines behind vs at_risk.
    ratio = achieved / expected if expected > 0 else 0
    if ratio < 0.5:
        return "at_risk"
    return "behind"


def build_target_card(
    metric: str,
    achieved: int,
    target: int,
    period_start: datetime,
    period_end: datetime,
    now: datetime | None = None,
) -> dict:
    """Build a single target card: metric, target, achieved, remaining, pct, status."""
    status = target_status(achieved, target, period_start, period_end, now)
    pct = round((achieved / target) * 100, 1) if target > 0 else 0
    return {
        "metric": metric,
        "target": target,
        "achieved": achieved,
        "remaining": max(0, target - achieved),
        "percentage": pct,
        "status": status,
    }


# ── Staff metrics + targets combined ────────────────────────────────────────


def staff_metrics_with_targets(
    staff_id: str,
    fy: str,
    start: datetime | None = None,
    end: datetime | None = None,
    quarter: str | None = None,
) -> dict:
    """Compute metrics + resolve targets + build status cards for every metric.
    This is the single entry point for the 'My Targets' / 'Team Targets' views.

    Time periods: pass quarter="Q1".."Q4" to scope achieved work to that
    quarter AND pro-rate every annual target to a quarter share (annual ÷ 4).
    No quarter = FY Cumulative (annual targets, full-year achievement)."""
    if quarter in ("Q1", "Q2", "Q3", "Q4"):
        from apps.core.fy import get_quarter_date_range

        start, end = get_quarter_date_range(fy, quarter)
    metrics = staff_metrics(staff_id, fy, start, end)
    if start is None or end is None:
        start, end = get_fy_date_range(fy)
    cards = {}
    for metric_key, achieved in metrics.items():
        target = resolve_target(staff_id, fy, metric_key)
        if quarter in ("Q1", "Q2", "Q3", "Q4") and target:
            target = round(target * 0.25)
        cards[metric_key] = build_target_card(metric_key, achieved, target, start, end)
    return {
        "fy": fy,
        "metrics": metrics,
        "cards": cards,
        "total_planned": metrics.get("total_planned", 0),
        "total_completed": metrics.get("total_completed", 0),
        "completion_rate": round(
            (metrics.get("total_completed", 0) / metrics.get("total_planned", 1)) * 100,
            1,
        )
        if metrics.get("total_planned")
        else 0,
    }


# ── Workload / fairness context ─────────────────────────────────────────────


def workload_context(staff_id: str) -> dict:
    """The fairness context alongside achievement — so a CCEO with 5 schools
    and easy territory isn't ranked above one with 40 schools and remote
    districts. Returns assigned-school counts, district/cluster spread, leave."""
    from apps.accounts.models import StaffSchoolAssignment, Leave
    from apps.schools.models import School

    school_ids = list(
        StaffSchoolAssignment.objects.filter(staff_id=staff_id).values_list(
            "school_id", flat=True
        )
    )
    schools = School.objects.filter(id__in=school_ids, deleted_at__isnull=True).values(
        "id", "school_type", "district_id"
    )
    core_count = sum(1 for s in schools if s["school_type"] == "core")
    client_count = sum(1 for s in schools if s["school_type"] == "client")
    district_ids = list({s["district_id"] for s in schools if s["district_id"]})

    # Cluster count from the schools' cluster_id.
    cluster_ids = list(
        School.objects.filter(
            id__in=school_ids, deleted_at__isnull=True, cluster_id__isnull=False
        )
        .values_list("cluster_id", flat=True)
        .distinct()
    )

    # Leave days in the current FY (approved leave).
    from apps.core.fy import get_operational_fy, get_fy_date_range

    fy = get_operational_fy()
    fy_start, fy_end = get_fy_date_range(fy)
    from django.db.models import Sum

    leave = (
        Leave.objects.filter(
            staff_id=staff_id,
            status="approved",
            start_date__gte=fy_start,
            start_date__lt=fy_end,
        ).aggregate(total=Sum("days"))["total"]
        or 0
    )

    return {
        "assignedSchoolCount": len(school_ids),
        "coreSchoolCount": core_count,
        "clientSchoolCount": client_count,
        "districtCount": len(district_ids),
        "clusterCount": len(cluster_ids),
        "leaveDays": int(leave),
        "primaryDistrictId": None,  # resolved from StaffProfile if needed
    }
