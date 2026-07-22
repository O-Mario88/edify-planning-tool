"""Schools Needing Urgent Attention — the one resolver.

The card answers: among the schools PLANNED FOR THIS MONTH, which need the
most urgent attention, and why? Portfolio-wide risk analysis lives elsewhere.

Strict precedence, SSA first:

  1. No SSA        (critical) — and NO intervention conclusion may render:
                    without a current verified SSA there is no basis for one.
  2. No Visit or Training (critical)
  3. No Training   (high)
  4. No Visit      (high)
  5. The canonical engine's top unresolved recommendation.

One school appears once, under its highest issue. Everything is delegated:
SSA validity = confirmed current-FY record; completion = IA_VERIFIED_STATUSES;
entitlement = client one visit + one training per FY, core = package slots;
ranking = ssa.recommendation_engine. Nothing is recomputed here.
"""

from __future__ import annotations

from datetime import date

from apps.targets.my_targets import IA_VERIFIED_STATUSES

_PRECEDENCE = {
    "no_ssa": 0,
    "no_visit_or_training": 1,
    "no_training": 2,
    "no_visit": 3,
    "intervention_critical": 4,
    "intervention_warning": 5,
    "intervention_follow_up": 6,
}

_VISIT_TYPES = ("school_visit", "core_visit")
_TRAINING_TYPES = (
    "training",
    "in_school_training",
    "school_improvement_training",
    "core_training",
)
_LIVE = ("cancelled", "rejected", "deferred")


def _month_bounds(fy: str, month: int) -> tuple[date, date]:
    year = int(fy) - 1 if month >= 10 else int(fy)
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def _schedule_context(month_activities, kinds) -> str | None:
    """Secondary text: a scheduled-but-incomplete activity is not absent."""
    for a in month_activities:
        if a.activity_type not in kinds:
            continue
        if a.status in ("assigned_to_partner", "partner_pending_schedule"):
            return "Partner yet to schedule"
        if a.planned_date:
            return f"scheduled for {a.planned_date.strftime('%-d %b')}"
    return None


def resolve_urgent_issue(school, fy: str, month_activities: list) -> dict:
    """The mandate's decision logic, verbatim in precedence."""
    from apps.ssa.models import SsaRecord

    has_current_ssa = SsaRecord.objects.filter(
        school=school,
        fy=fy,
        verification_status="confirmed",
        deleted_at__isnull=True,
    ).exists()

    if not has_current_ssa:
        ssa_planned = any("ssa" in (a.activity_type or "") for a in month_activities)
        return {
            "key": "no_ssa",
            "label": "No SSA",
            "severity": "critical",
            "detail": (
                "Current verified SSA is required before intervention "
                "performance can be determined."
            ),
            "context": _schedule_context(month_activities, _VISIT_TYPES),
            "action_label": "Complete SSA" if ssa_planned else "Schedule SSA",
            "action_url": f"/planning?school_id={school.school_id}",
        }

    from apps.activities.models import Activity

    def _done(kinds) -> bool:
        return Activity.objects.filter(
            school=school,
            activity_type__in=kinds,
            fy=fy,
            status__in=IA_VERIFIED_STATUSES,
            deleted_at__isnull=True,
        ).exists()

    visit_done = _done(_VISIT_TYPES)
    training_done = _done(_TRAINING_TYPES)

    if not visit_done and not training_done:
        return {
            "key": "no_visit_or_training",
            "label": "No Visit or Training",
            "severity": "critical",
            "detail": "Verified SSA exists, but no required support is completed.",
            "context": _schedule_context(
                month_activities, _VISIT_TYPES + _TRAINING_TYPES
            ),
            "action_label": "Open Planning",
            "action_url": f"/planning?school_id={school.school_id}",
        }
    if not training_done:
        return {
            "key": "no_training",
            "label": "No Training",
            "severity": "high",
            "detail": None,
            "context": _schedule_context(month_activities, _TRAINING_TYPES),
            "action_label": "Plan Training",
            "action_url": f"/planning?school_id={school.school_id}",
        }
    if not visit_done:
        return {
            "key": "no_visit",
            "label": "No Visit",
            "severity": "high",
            "detail": None,
            "context": _schedule_context(month_activities, _VISIT_TYPES),
            "action_label": "Plan Visit",
            "action_url": f"/planning?school_id={school.school_id}",
        }

    from apps.core.enums import SsaIntervention, ssa_score_band
    from apps.ssa.recommendation_engine import prioritized_interventions

    ranked = prioritized_interventions(school, n=1)
    if not ranked:
        return {
            "key": "intervention_follow_up",
            "label": "Support complete",
            "severity": "normal",
            "detail": None,
            "context": None,
            "action_label": "View School",
            "action_url": f"/schools/{school.id}",
        }
    top = ranked[0]
    score = top.get("score")
    band = ssa_score_band(score)[0] if score is not None else ""
    key = (
        "intervention_critical"
        if band == "Critical"
        else "intervention_warning"
        if band == "Warning"
        else "intervention_follow_up"
    )
    label = dict(SsaIntervention.choices).get(top["intervention"], top["intervention"])
    return {
        "key": key,
        "label": f"{label} · {score} {band}".strip(),
        "severity": "critical" if key == "intervention_critical" else "warning",
        "detail": None,
        "context": None,
        "action_label": "View Recommendation",
        "action_url": f"/schools/{school.id}",
    }


def monthly_urgent_schools(
    user, fy: str | None = None, month: int | None = None, limit: int = 7
) -> dict:
    """Card rows: unique schools planned this month, highest issue first."""
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy
    from apps.core.scoping import resolve_user_scope, school_queryset

    fy = fy or get_operational_fy()
    today = date.today()
    month = int(month or today.month)
    start, end = _month_bounds(fy, month)

    scope = resolve_user_scope(user)
    schools = school_queryset(scope)
    planned = (
        Activity.objects.filter(
            school__in=schools,
            fy=fy,
            planned_date__gte=start,
            planned_date__lt=end,
            deleted_at__isnull=True,
        )
        .exclude(status__in=_LIVE)
        .select_related("school")
        .order_by("planned_date")
    )
    by_school: dict[str, list] = {}
    for a in planned:
        by_school.setdefault(a.school_id, []).append(a)

    rows = []
    for school_id, acts in by_school.items():
        school = acts[0].school
        issue = resolve_urgent_issue(school, fy, acts)
        first = acts[0]
        rows.append(
            {
                "school_id": school.id,
                "name": school.name,
                "where": getattr(getattr(school, "district", None), "name", "") or "",
                "planned": (
                    f"{first.activity_type.replace('_', ' ').title()}: "
                    f"{first.planned_date.strftime('%-d %b')}"
                    if first.planned_date
                    else ""
                ),
                "planned_date": first.planned_date,
                **issue,
            }
        )
    rows.sort(
        key=lambda r: (
            _PRECEDENCE.get(r["key"], 9),
            r["planned_date"] or date.max,
            r["name"],
        )
    )
    # "Support complete" rows are not urgent — the card shows problems only.
    rows = [
        r
        for r in rows
        if r["key"] != "intervention_follow_up" or r["severity"] != "normal"
    ]
    return {
        "rows": rows[:limit],
        "total_schools": len(rows),
        "month": month,
        "fy": fy,
    }
