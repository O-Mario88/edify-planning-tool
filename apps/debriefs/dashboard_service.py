"""FieldDebriefDashboardService — the Field Debrief Dashboard's single data
aggregator (mockup: KPI strip, trend chart, activity-type donut, top
challenges, action center, team & partner table, peer solutions, risk
donut, intelligence highlights). Every number here is derived live from
`FieldDebriefService.scoped_queryset()` — nothing is stored or fabricated;
month-over-month deltas are real comparisons against the prior period, or
omitted when there's no prior-period data to compare against honestly.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from django.utils import timezone

from apps.core.fy import fy_options, get_operational_fy

from .field_debrief_service import FieldDebriefService
from .insight_service import INSIGHT_REVIEWER_ROLES
from .models import (
    CompletionStatus,
    DailyDebriefChallenge,
    DebriefActionStatus,
    DebriefStatus,
    RiskLevel,
)

PER_PAGE = 10


def _pct_delta(current: int, previous: int) -> dict | None:
    if previous == 0:
        return None
    change = round((current - previous) / previous * 100)
    return {
        "direction": "up" if change > 0 else "down" if change < 0 else "flat",
        "value": f"{abs(change)}%",
    }


class FieldDebriefDashboardService:
    @staticmethod
    def get_dashboard(principal, params: dict) -> dict:
        params = params or {}
        today = date.today()
        range_days = int(params.get("range_days") or 30)
        start = params.get("start") or (today - timedelta(days=range_days))
        end = params.get("end") or today
        prev_start = start - (end - start) - timedelta(days=1)
        prev_end = start - timedelta(days=1)

        base_qs = FieldDebriefService.scoped_queryset(principal, params)
        current_qs = base_qs.filter(date__date__gte=start, date__date__lte=end)
        previous_qs = FieldDebriefService.scoped_queryset(principal, params).filter(
            date__date__gte=prev_start, date__date__lte=prev_end
        )
        rows = list(
            current_qs.prefetch_related("challenges", "activity_links__activity")
        )
        prev_rows = list(previous_qs)

        kpis = FieldDebriefDashboardService._kpis(rows, prev_rows)
        trend = FieldDebriefDashboardService._trend(current_qs, start, end)
        activity_donut = FieldDebriefDashboardService._activity_type_donut(rows)
        top_challenges = FieldDebriefDashboardService._top_challenges(rows)
        action_center = FieldDebriefDashboardService._action_center(principal, base_qs)
        risk_donut = FieldDebriefDashboardService._risk_donut(rows)
        peer_solutions = FieldDebriefDashboardService._recent_peer_solutions(base_qs)
        highlights = FieldDebriefDashboardService._intelligence_highlights(
            rows, base_qs
        )

        tab = params.get("tab") or "all"
        table_qs = FieldDebriefDashboardService._apply_tab(principal, current_qs, tab)
        page = max(1, int(params.get("page") or 1))
        total = table_qs.count()
        pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        page = min(page, pages)
        table_rows = [
            FieldDebriefDashboardService._table_row(d)
            for d in table_qs.order_by("-date")[(page - 1) * PER_PAGE : page * PER_PAGE]
        ]
        recent_activity = [
            {
                "name": _display_name(d.submitted_by_user_id),
                "verb": "submitted a debrief",
                "title": d.title,
                "at": d.date,
            }
            for d in base_qs.order_by("-date")[:5]
        ]

        return {
            "fy": params.get("fy") or get_operational_fy(),
            "fy_options": fy_options(),
            "district_id": params.get("district_id"),
            "district_options": _district_options(),
            "risk_level": params.get("risk_level"),
            "risk_level_options": [
                (v, label) for v, label in RiskLevel.choices if v != RiskLevel.NONE
            ],
            "q": params.get("q"),
            "start": start,
            "end": end,
            "range_days": range_days,
            "kpis": kpis,
            "trend": trend,
            "activity_donut": activity_donut,
            "top_challenges": top_challenges,
            "action_center": action_center,
            "risk_donut": risk_donut,
            "peer_solutions": peer_solutions,
            "highlights": highlights,
            "can_manage_insights": getattr(principal, "active_role", "")
            in INSIGHT_REVIEWER_ROLES,
            "tab": tab,
            "table_rows": table_rows,
            "table_total": total,
            "table_page": page,
            "table_pages": pages,
            "recent_activity": recent_activity,
            "last_refreshed": timezone.now(),
        }

    @staticmethod
    def _kpis(rows: list, prev_rows: list) -> list[dict]:
        def count(rs, pred):
            return sum(1 for r in rs if pred(r))

        submitted, prev_submitted = len(rows), len(prev_rows)
        completed = count(
            rows, lambda r: r.completion_status == CompletionStatus.COMPLETED_AS_PLANNED
        )
        prev_completed = count(
            prev_rows,
            lambda r: r.completion_status == CompletionStatus.COMPLETED_AS_PLANNED,
        )
        partial = count(
            rows, lambda r: r.completion_status == CompletionStatus.PARTIALLY_COMPLETED
        )
        prev_partial = count(
            prev_rows,
            lambda r: r.completion_status == CompletionStatus.PARTIALLY_COMPLETED,
        )
        unsuccessful = count(
            rows,
            lambda r: r.completion_status
            in (CompletionStatus.UNSUCCESSFUL, CompletionStatus.CANCELLED),
        )
        prev_unsuccessful = count(
            prev_rows,
            lambda r: r.completion_status
            in (CompletionStatus.UNSUCCESSFUL, CompletionStatus.CANCELLED),
        )
        action_required = count(
            rows, lambda r: r.status == DebriefStatus.ACTION_REQUIRED
        )
        prev_action_required = count(
            prev_rows, lambda r: r.status == DebriefStatus.ACTION_REQUIRED
        )
        critical = count(rows, lambda r: r.risk_level == RiskLevel.CRITICAL)
        prev_critical = count(prev_rows, lambda r: r.risk_level == RiskLevel.CRITICAL)
        open_commitments = sum(
            r.commitments.filter(status="open").count() for r in rows
        )
        prev_open_commitments = sum(
            r.commitments.filter(status="open").count() for r in prev_rows
        )
        peer_solutions = sum(r.peer_solutions.count() for r in rows)
        prev_peer_solutions = sum(r.peer_solutions.count() for r in prev_rows)

        return [
            {
                "key": "submitted",
                "icon": "report",
                "variant": "primary",
                "label": "Debriefs Submitted",
                "value": str(submitted),
                "trend": _pct_delta(submitted, prev_submitted),
            },
            {
                "key": "completed",
                "icon": "signoff",
                "variant": "success",
                "label": "Activities Completed",
                "value": str(completed),
                "trend": _pct_delta(completed, prev_completed),
            },
            {
                "key": "partial",
                "icon": "clock",
                "variant": "warning",
                "label": "Partially Completed",
                "value": str(partial),
                "trend": _pct_delta(partial, prev_partial),
            },
            {
                "key": "unsuccessful",
                "icon": "warning",
                "variant": "danger",
                "label": "Unsuccessful / Cancelled",
                "value": str(unsuccessful),
                "trend": _pct_delta(unsuccessful, prev_unsuccessful),
            },
            {
                "key": "action_required",
                "icon": "target",
                "variant": "warning",
                "label": "Action Required",
                "value": str(action_required),
                "trend": _pct_delta(action_required, prev_action_required),
            },
            {
                "key": "critical",
                "icon": "warning",
                "variant": "danger",
                "label": "Critical Escalations",
                "value": str(critical),
                "trend": _pct_delta(critical, prev_critical),
            },
            {
                "key": "open_commitments",
                "icon": "handshake",
                "variant": "default",
                "label": "Open Commitments",
                "value": str(open_commitments),
                "trend": _pct_delta(open_commitments, prev_open_commitments),
            },
            {
                "key": "peer_solutions",
                "icon": "users",
                "variant": "primary",
                "label": "Peer Solutions",
                "value": str(peer_solutions),
                "trend": _pct_delta(peer_solutions, prev_peer_solutions),
            },
        ]

    @staticmethod
    def _trend(qs, start: date, end: date) -> dict:
        days = [(start + timedelta(days=i)) for i in range((end - start).days + 1)]
        rows = list(qs.only("date", "status", "risk_level"))
        by_day = {
            d: {"submitted": 0, "completed": 0, "action_required": 0, "critical": 0}
            for d in days
        }
        for r in rows:
            d = r.date.date()
            if d not in by_day:
                continue
            by_day[d]["submitted"] += 1
            if r.status in (DebriefStatus.RESOLVED, DebriefStatus.CLOSED):
                by_day[d]["completed"] += 1
            if r.status == DebriefStatus.ACTION_REQUIRED:
                by_day[d]["action_required"] += 1
            if r.risk_level == RiskLevel.CRITICAL:
                by_day[d]["critical"] += 1
        return {
            "labels": [d.strftime("%b %d") for d in days],
            "submitted": [by_day[d]["submitted"] for d in days],
            "completed": [by_day[d]["completed"] for d in days],
            "action_required": [by_day[d]["action_required"] for d in days],
            "critical": [by_day[d]["critical"] for d in days],
        }

    @staticmethod
    def _activity_type_donut(rows: list) -> dict:
        counts: Counter = Counter()
        for r in rows:
            for link in r.activity_links.all():
                if link.activity_id:
                    counts[
                        link.activity.get_activity_type_display()
                        if link.activity
                        else "Other"
                    ] += 1
        if not counts:
            return {"labels": [], "counts": [], "total": 0}
        ranked = counts.most_common(6)
        total = sum(counts.values())
        return {
            "labels": [k for k, _ in ranked],
            "counts": [v for _, v in ranked],
            "total": total,
        }

    @staticmethod
    def _top_challenges(rows: list) -> list[dict]:
        counts: Counter = Counter()
        for r in rows:
            for c in r.challenges.all():
                counts[c.challenge_type] += 1
        total = sum(counts.values()) or 1
        ranked = counts.most_common(8)
        return [
            {
                "label": DailyDebriefChallenge(
                    challenge_type=k
                ).get_challenge_type_display(),
                "count": v,
                "pct": round(v / total * 100),
            }
            for k, v in ranked
        ]

    @staticmethod
    def _risk_donut(rows: list) -> dict:
        counts = Counter(r.risk_level for r in rows)
        order = [
            RiskLevel.NONE,
            RiskLevel.MONITOR,
            RiskLevel.PL_ATTENTION,
            RiskLevel.CD_ATTENTION,
            RiskLevel.IA_ATTENTION,
            RiskLevel.HR_ATTENTION,
            RiskLevel.FINANCE_ATTENTION,
            RiskLevel.CRITICAL,
        ]
        labels, values = [], []
        for level in order:
            if counts.get(level):
                labels.append(RiskLevel(level).label)
                values.append(counts[level])
        return {"labels": labels, "counts": values, "total": sum(counts.values())}

    @staticmethod
    def _action_center(principal, base_qs) -> dict:
        from .models import DailyDebriefAction

        mine_action_required = (
            DailyDebriefAction.objects.filter(owner_user_id=principal.user_id)
            .exclude(
                status__in=(DebriefActionStatus.RESOLVED, DebriefActionStatus.CLOSED)
            )
            .count()
        )
        escalations = base_qs.filter(status=DebriefStatus.ESCALATED).count()
        clarifications = base_qs.filter(
            status=DebriefStatus.CLARIFICATION_REQUESTED,
            submitted_by_user_id=principal.user_id,
        ).count()
        overdue_actions = (
            DailyDebriefAction.objects.filter(
                owner_user_id=principal.user_id,
                due_date__lt=date.today(),
            )
            .exclude(
                status__in=(DebriefActionStatus.RESOLVED, DebriefActionStatus.CLOSED)
            )
            .count()
        )
        open_commitments = sum(
            d.commitments.filter(status="open").count()
            for d in base_qs.prefetch_related("commitments")
        )
        return {
            "action_required": mine_action_required,
            "escalations": escalations,
            "clarifications": clarifications,
            "overdue": overdue_actions,
            "open_commitments": open_commitments,
        }

    @staticmethod
    def _recent_peer_solutions(base_qs, limit: int = 5) -> list[dict]:
        from apps.accounts.models import User

        from .models import DailyDebriefPeerSolution

        solutions = list(
            DailyDebriefPeerSolution.objects.filter(debrief__in=base_qs)
            .select_related("debrief")
            .order_by("-created_at")[:limit]
        )
        author_ids = {s.author_user_id for s in solutions}
        names = dict(User.objects.filter(id__in=author_ids).values_list("id", "name"))
        return [
            {
                "id": s.id,
                "author": names.get(s.author_user_id, "—"),
                "suggestion": s.suggestion,
                "endorsements": len(s.endorsed_by_user_ids),
                "created_at": s.created_at,
                "debrief_id": s.debrief_id,
                "debrief_title": s.debrief.title,
            }
            for s in solutions
        ]

    @staticmethod
    def _intelligence_highlights(rows: list, base_qs) -> list[dict]:
        """Returns dicts (not plain strings) so insight-sourced rows can carry
        an `insight_id` — the dashboard template uses it to offer the
        insight's acknowledge/dismiss actions to managers (§15)."""
        from .models import DailyDebriefInsight

        highlights = []
        top = FieldDebriefDashboardService._top_challenges(rows)
        if top:
            highlights.append(
                {
                    "text": f'"{top[0]["label"]}" reported in {top[0]["count"]} debrief(s) this period.',
                    "insight_id": None,
                }
            )
        open_insights = DailyDebriefInsight.objects.filter(status="open").order_by(
            "-occurrence_count"
        )[:3]
        for i in open_insights:
            highlights.append({"text": i.description, "insight_id": i.id})
        repeated_schools = Counter(s for r in rows for s in r.linked_school_ids)
        repeats = [s for s, n in repeated_schools.items() if n >= 2]
        if repeats:
            highlights.append(
                {
                    "text": f"{len(repeats)} school(s) had more than one debrief this period.",
                    "insight_id": None,
                }
            )
        critical = sum(1 for r in rows if r.risk_level == RiskLevel.CRITICAL)
        if critical:
            highlights.append(
                {
                    "text": f"{critical} debrief(s) escalated as Critical.",
                    "insight_id": None,
                }
            )
        return highlights[:6]

    @staticmethod
    def _apply_tab(principal, qs, tab: str):
        if tab == "mine":
            return qs.filter(submitted_by_user_id=principal.user_id)
        if tab == "team":
            return qs.exclude(submitted_by_user_id=principal.user_id).exclude(
                debrief_type="partner"
            )
        if tab == "partner":
            return qs.filter(debrief_type="partner")
        if tab == "escalated":
            return qs.filter(
                status__in=(DebriefStatus.ESCALATED, DebriefStatus.ACTION_REQUIRED)
            ) | qs.filter(
                risk_level__in=(
                    RiskLevel.CD_ATTENTION,
                    RiskLevel.CRITICAL,
                    RiskLevel.HR_ATTENTION,
                    RiskLevel.IA_ATTENTION,
                )
            )
        if tab == "peer_solutions":
            return qs.filter(peer_solutions__isnull=False).distinct()
        return qs

    @staticmethod
    def _table_row(d) -> dict:
        link = d.activity_links.first() if hasattr(d, "activity_links") else None
        return {
            "id": d.id,
            "date": d.date,
            "submitted_by": d.submitted_by_role,
            "submitted_by_name": _display_name(d.submitted_by_user_id),
            "activity_type": link.activity.get_activity_type_display()
            if link and link.activity
            else d.get_kind_display(),
            "target_label": _target_label(d),
            "status": d.get_status_display(),
            "status_key": d.status,
            "title": d.title or "(untitled)",
            "action_required": d.status
            in (DebriefStatus.ACTION_REQUIRED, DebriefStatus.ESCALATED),
            "risk_level": d.risk_level,
            "risk_label": d.get_risk_level_display(),
        }


def _display_name(user_id: str) -> str:
    from apps.accounts.models import User

    u = User.objects.filter(id=user_id).values_list("name", flat=True).first()
    return u or "—"


def _target_label(d) -> str:
    if d.partner_id:
        from apps.partners.models import Partner

        p = (
            Partner.objects.filter(id=d.partner_id)
            .values_list("name", flat=True)
            .first()
        )
        if p:
            return p
    if d.linked_school_ids:
        from apps.schools.models import School

        s = (
            School.objects.filter(id=d.linked_school_ids[0])
            .values_list("name", flat=True)
            .first()
        )
        if s:
            return s
    return "—"


def _district_options() -> list:
    from apps.geography.models import District

    return list(District.objects.order_by("name").values_list("id", "name"))
