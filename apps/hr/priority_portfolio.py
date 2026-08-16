"""Read-only grouped priority portfolio assembled from each owning system."""

from __future__ import annotations

from collections import defaultdict

from apps.core.enums import SsaIntervention, VerificationStatus, ssa_score_band


def priority_portfolio(*, user, fy: str, strategic_milestones: list[dict]) -> list[dict]:
    """Return planning, SSA, manual, and PD priorities without copying sources."""
    from apps.accounts.models import StaffSchoolAssignment
    from apps.hr.models import PerformancePriority, PerformanceReview
    from apps.professional_development.models import ProfessionalDevelopmentRequest
    from apps.schools.models import School
    from apps.ssa.models import SsaRecord

    staff_id = getattr(user, "staff_profile_id", None)
    if not staff_id:
        return []

    planning_rows = []
    for row in strategic_milestones:
        if row.get("remaining") is None:
            continue
        annual_target = row.get("fyPlan") or row.get("allocatedTarget") or 0
        actual = row.get("fyActual") or 0
        remaining = max(0, annual_target - actual)
        planning_rows.append(
            {
                "title": row["milestone"],
                "detail": row["priority"],
                "meta": f"{remaining} remaining of {annual_target}",
                "tone": "success" if not remaining else "warning",
                "action": "Plan work",
                "url": f'/planning?fy={fy}&priority_allocation={row["allocationId"]}',
            }
        )

    assigned_school_ids = list(
        StaffSchoolAssignment.objects.filter(staff_id=staff_id).values_list(
            "school_id", flat=True
        )
    )
    school_ids = list(
        School.objects.filter(id__in=assigned_school_ids).values_list("id", flat=True)
    )
    latest_by_school = {}
    if school_ids:
        records = (
            SsaRecord.objects.filter(
                school_id__in=school_ids,
                fy=fy,
                verification_status=VerificationStatus.CONFIRMED,
            )
            .prefetch_related("scores")
            .order_by("school_id", "-date_of_ssa", "-created_at")
        )
        for record in records:
            latest_by_school.setdefault(str(record.school_id), record)

    ssa_rows = []
    missing_count = len(set(map(str, school_ids)) - set(latest_by_school))
    if missing_count:
        ssa_rows.append(
            {
                "title": "Complete current-FY SSA coverage",
                "detail": f"{missing_count} assigned school(s) have no confirmed FY{fy} SSA.",
                "meta": "Confirmed SSA only",
                "tone": "danger",
                "action": "Open SSA",
                "url": f"/ssa?fy={fy}",
            }
        )
    weak: dict[str, list[float]] = defaultdict(list)
    for record in latest_by_school.values():
        for score in record.scores.all():
            if score.score < 8:
                weak[score.intervention].append(score.score)
    labels = dict(SsaIntervention.choices)
    for intervention, scores in sorted(weak.items(), key=lambda item: min(item[1])):
        weakest = min(scores)
        band, _color, tone = ssa_score_band(weakest)
        ssa_rows.append(
            {
                "title": labels.get(intervention, intervention.replace("_", " ").title()),
                "detail": f"{len(scores)} school(s) below Strong; lowest score {weakest:g}.",
                "meta": f"{band} · confirmed FY{fy} SSA",
                "tone": tone,
                "action": "Plan response",
                "url": f"/planning?fy={fy}&priority_source=ssa&intervention={intervention}",
            }
        )

    review = (
        PerformanceReview.objects.filter(staff_id=staff_id, fy=fy)
        .order_by("-created_at")
        .first()
    )
    manual_rows = []
    if review:
        for row in PerformancePriority.objects.filter(
            review=review, source_rule__isnull=True
        ).order_by("sequence"):
            manual_rows.append(
                {
                    "title": row.outcome_statement,
                    "detail": row.measures_of_success or row.target or "Manually agreed priority",
                    "meta": f"Weight {row.weight}% · {row.get_status_display()}",
                    "tone": "neutral",
                    "action": "View agreement",
                    "url": "/performance-conversation",
                }
            )

    pd_rows = [
        {
            "title": row.course_name,
            "detail": row.relevance_to_role or row.skills_to_develop or row.institution,
            "meta": row.get_status_display(),
            "tone": "info",
            "action": "View development",
            "url": f"/my-professional-development/?fy={fy}",
        }
        for row in ProfessionalDevelopmentRequest.objects.filter(
            staff_id=staff_id, fy=fy
        ).order_by("start_date", "created_at")
    ]

    return [
        {"key": "planning", "label": "Planning feed", "rows": planning_rows},
        {"key": "ssa", "label": "SSA focus", "rows": ssa_rows},
        {"key": "manual", "label": "Manual priorities", "rows": manual_rows},
        {"key": "pd", "label": "Professional development", "rows": pd_rows},
    ]
