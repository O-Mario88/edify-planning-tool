"""FieldDebriefWeeklyRollupService — weekly summaries (§17), computed live
from `FieldDebriefService.scoped_queryset()` rather than a stored
`FieldDebriefWeeklySummary` table. Matches this codebase's "derive, don't
cache" convention (see my_targets.py, the PD reminders panel) — a stored
weekly-summary row would need its own population job just to stay correct,
for data that's already a single aggregation query away.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Q

from .field_debrief_service import FieldDebriefService
from .models import CompletionStatus, DebriefStatus


def _week_bounds(anchor: date | None = None) -> tuple[date, date]:
    anchor = anchor or date.today()
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


class FieldDebriefWeeklyRollupService:
    @staticmethod
    def for_user(principal, week_start: date | None = None) -> dict:
        start, end = _week_bounds(week_start)
        qs = FieldDebriefService.scoped_queryset(principal, {"mine": True}).filter(date__date__gte=start, date__date__lte=end)
        rows = list(qs.prefetch_related("challenges", "support_requests", "peer_solutions"))
        return {
            "week_start": start, "week_end": end,
            "activities_attempted": len(rows),
            "activities_completed": sum(1 for r in rows if r.completion_status == CompletionStatus.COMPLETED_AS_PLANNED),
            "activities_unsuccessful": sum(1 for r in rows if r.completion_status == CompletionStatus.UNSUCCESSFUL),
            "schools_visited": len({s for r in rows for s in r.linked_school_ids}),
            "interventions_addressed": sorted({i for r in rows for i in r.intervention_tags}),
            "top_challenges": _top_challenges(rows),
            "open_commitments": sum(1 for r in rows for c in r.commitments.all() if c.status == "open"),
            "support_requested": sum(r.support_requests.count() for r in rows),
            "peer_solutions_contributed": sum(r.peer_solutions.count() for r in rows),
        }

    @staticmethod
    def for_pl(principal, week_start: date | None = None) -> dict:
        start, end = _week_bounds(week_start)
        qs = FieldDebriefService.scoped_queryset(principal, {}).filter(date__date__gte=start, date__date__lte=end)
        rows = list(qs)
        own = FieldDebriefWeeklyRollupService.for_user(principal, week_start)
        return {
            "week_start": start, "week_end": end,
            "own": own,
            "team_debriefs": len(rows),
            "partner_debriefs": sum(1 for r in rows if r.debrief_type == "partner"),
            "recurring_issues": _recurring_issue_count(rows),
            "actions_open": sum(r.actions.exclude(status__in=("resolved", "closed")).count() for r in rows),
        }

    @staticmethod
    def for_country(principal, week_start: date | None = None) -> dict:
        start, end = _week_bounds(week_start)
        qs = FieldDebriefService.scoped_queryset(principal, {}).filter(date__date__gte=start, date__date__lte=end)
        rows = list(qs)
        return {
            "week_start": start, "week_end": end,
            "total_debriefs": len(rows),
            "critical_escalations": sum(1 for r in rows if r.risk_level == "critical"),
            "restricted_incidents": sum(1 for r in rows if r.is_restricted_incident),
            "actions_open": sum(r.actions.exclude(status__in=("resolved", "closed")).count() for r in rows),
        }


def _top_challenges(rows, limit: int = 5) -> list[dict]:
    counts: dict[str, int] = {}
    for r in rows:
        for c in r.challenges.all():
            counts[c.challenge_type] = counts.get(c.challenge_type, 0) + 1
    from .models import DailyDebriefChallenge

    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return [{"challenge_type": k, "label": DailyDebriefChallenge(challenge_type=k).get_challenge_type_display(), "count": v} for k, v in ranked]


def _recurring_issue_count(rows) -> int:
    from .models import DailyDebriefInsight

    school_ids = {s for r in rows for s in r.linked_school_ids}
    staff_ids = {r.staff_id for r in rows if r.staff_id}
    return DailyDebriefInsight.objects.filter(status="open").filter(
        Q(scope_id__in=school_ids) | Q(scope_id__in=staff_ids)
    ).count()


def field_debrief_intelligence_summary(principal, days: int = 30) -> dict:
    """Compact "Field Debrief Intelligence" card for embedding into the PL
    Team Targets, CD, HR, IA, and RVP dashboards (§11) — a few real numbers
    plus the top challenge, all through the same role-scoped queryset every
    other Field Debrief view uses, so it can never show a role data outside
    its own scope."""
    since = date.today() - timedelta(days=days)
    qs = FieldDebriefService.scoped_queryset(principal, {}).filter(date__date__gte=since)
    rows = list(qs.prefetch_related("challenges"))
    top = _top_challenges(rows, limit=1)
    return {
        "total": len(rows),
        "critical": sum(1 for r in rows if r.risk_level == "critical"),
        "action_required": sum(1 for r in rows if r.status == DebriefStatus.ACTION_REQUIRED),
        "escalated": sum(1 for r in rows if r.status == DebriefStatus.ESCALATED),
        "top_challenge": top[0]["label"] if top else None,
        "top_challenge_count": top[0]["count"] if top else 0,
        "days": days,
    }
