"""Country Director Executive Command Center — the CD's /dashboard.

National oversight, approvals, targets, finance, risk, compliance and
leadership action. Never a field-planning page: every action is review /
approve-return / request-recovery / assign-follow-up / inspect / export.

All figures derive from the real workflow chain (School → Cluster → Planning
→ Activity → Costing → Fund Request → Execution → Evidence + Activity SF ID
→ IA Verification → Accountability + NetSuite → Closed). Reuses
CDAnalyticsService section math so the dashboard and the analytics cockpit
can never disagree. Activity SF ID = program proof; NetSuite Code =
accountability proof. The CD approves — the accountant disburses.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Avg, Q, Sum

from apps.accounts.models import User
from apps.core.fy import get_operational_fy
from apps.core.models import _normalize_datetime_value
from apps.schools.models import School

from apps.analytics.cd_analytics_service import (
    CDAnalyticsService,
    _country_activities,
    _cycle_fys,
    _refresh_target_ledger,
    resolve_cd_scope,
)
from apps.analytics.pl_analytics_service import (
    COMPLETED_STATUSES,
    SSA_INTERVENTIONS,
    TRAINING_TYPES,
    VERIFIED_STATUSES,
    VISIT_TYPES,
    _norm,
    _pct,
    ssa_band,
)
from apps.analytics.pl_dashboard_service import SF_ID_OVERDUE_DAYS, _requires_sf_id

REGION_BEHIND_THRESHOLD = 60  # attention trigger: region achievement below this
HIGH_RISK_PL_BANDS = ("High Risk", "Critical")


def _ugx_compact(amount: int) -> str:
    if amount >= 1_000_000_000:
        return f"UGX {amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"UGX {amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"UGX {amount / 1_000:.0f}K"
    return f"UGX {amount:,}"


class CDDashboardService:
    """Facade for the CD Executive Command Center. All figures are
    country-wide, real, and month/FY filterable."""

    @staticmethod
    def get_dashboard(user, fy: str | None = None, month: int | None = None) -> dict:
        fy = fy or get_operational_fy()
        cd = resolve_cd_scope(fy, month=month)
        acts = _country_activities(cd)
        # The KPI strip's "Country Target Progress" and the PL performance
        # table's per-row target_pct both read the validated ledger — refresh
        # it for the CCEOs in scope first so the two can never disagree
        # because one side was staler than the other (mandate: never
        # invoked proactively for CD/RVP rollups otherwise, unlike My/Team
        # Targets which rebuild on every page load).
        _refresh_target_ledger(cd)

        pl_rows = CDDashboardService.pl_performance(cd, acts)
        regional = CDDashboardService.regional_performance(cd, acts)

        from apps.debriefs.rollup_service import field_debrief_intelligence_summary

        return {
            "fy": fy,
            "month": month,
            "kpi_strip_items": CDDashboardService.kpis(cd, acts, fy, pl_rows),
            "leadership_attention": CDDashboardService.leadership_attention(
                cd, acts, fy, regional
            ),
            "country_performance": CDDashboardService.country_performance(cd),
            "regional_performance": regional,
            "pl_performance": pl_rows,
            "finance_snapshot": CDDashboardService.finance_snapshot(cd, acts, fy),
            "operational_risk": CDDashboardService.operational_risk_backlog(
                cd, acts, fy
            ),
            "ssa_matrix": CDDashboardService.ssa_matrix(cd, acts),
            "priority_schools": CDDashboardService.priority_schools(cd, acts),
            "quick_actions": CDDashboardService.quick_actions(),
            "budget_stage": CDDashboardService.budget_stage(fy),
            "field_debrief_intel": field_debrief_intelligence_summary(user),
            "scope_meta": {
                "pl_count": len(CDAnalyticsService._pls()),
                "cceo_count": len(cd.cceo_user_ids),
                "school_count": len(cd.school_ids),
            },
        }

    # ── KPI strip (8, per mandate §6) ────────────────────────────────────────
    @staticmethod
    def kpis(cd, acts, fy, pl_rows) -> list[dict]:
        completed = acts.filter(status__in=COMPLETED_STATUSES)

        analytics = {k["label"]: k for k in CDAnalyticsService.kpis(cd, acts)}
        target_progress = analytics["Overall Target Achievement"]["value"]

        active_schools = (
            completed.exclude(school_id__isnull=True)
            .values("school_id")
            .distinct()
            .count()
        )

        core = CDDashboardService._core_on_track(fy)

        planned_n = acts.count()
        productivity = _pct(completed.count(), planned_n)

        sf_required = _requires_sf_id(acts)
        sf_total = sf_required.count()
        sf_with = sf_required.exclude(
            Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")
        ).count()
        sf_compliance = _pct(sf_with, sf_total)

        pending = CDDashboardService._pending_cd_items(fy)
        high_risk_teams = sum(
            1 for r in pl_rows["rows"] if r["risk"] in HIGH_RISK_PL_BANDS
        )

        def card(icon, label, value, variant, helper, link=""):
            return {
                "icon": icon,
                "label": label,
                "value": value,
                "variant": variant,
                "helper": helper,
                "link": link,
            }

        return [
            card(
                "target",
                "Country Target Progress",
                target_progress,
                "primary",
                "valid completed vs assigned targets",
                "/analytics/country-director",
            ),
            card(
                "school",
                "Active Schools Served",
                f"{active_schools:,}",
                "success",
                "completed activity this period",
            ),
            card(
                "shield",
                "Core Schools On Track",
                f"{core['pct']}%",
                "info",
                f"{core['on_track']} of {core['total']} core plans",
                "/core-school-health",
            ),
            card(
                "users",
                "Staff Productivity",
                f"{productivity}%",
                "info",
                f"{completed.count():,} of {planned_n:,} activities completed",
            ),
            card(
                "cloud",
                "Activity SF ID Compliance",
                f"{sf_compliance}%",
                "violet",
                f"{sf_with:,} of {sf_total:,} requiring SF IDs",
                "/completed-activities",
            ),
            card(
                "clock",
                "Pending Fund Requests",
                str(pending["count"]),
                "warning",
                pending["amount_label"],
                "/fund-requests/weekly",
            ),
            card(
                "currency",
                "Budget Utilization",
                analytics["Budget Utilization"]["value"],
                "finance",
                "disbursed vs requested pipeline",
            ),
            card(
                "warning",
                "High-Risk Teams",
                str(high_risk_teams),
                "danger",
                "PL teams at High Risk / Critical",
            ),
        ]

    @staticmethod
    def _core_on_track(fy) -> dict:
        """Core plan is on track when its baseline exists and the 4+4 package
        is progressing (any completed visit/training)."""
        from apps.core_schools.models import CorePlan

        plans = CorePlan.objects.filter(status__iexact="active")
        total = plans.count()
        on_track = (
            plans.filter(baseline_average__isnull=False)
            .filter(Q(visits_completed__gt=0) | Q(trainings_completed__gt=0))
            .count()
        )
        return {
            "total": total,
            "on_track": on_track,
            "pct": _pct(on_track, total),
            "behind": max(0, total - on_track),
        }

    @staticmethod
    def _pending_cd_items(fy) -> dict:
        """Everything waiting on the CD: escalated weekly fund requests plus
        the monthly country budget when it sits at a CD stage."""
        from apps.fund_requests.models import WeeklyFundRequest
        from apps.monthly_work_plan.models import MonthlyWorkPlanBudget

        weekly = WeeklyFundRequest.objects.filter(fy=fy, status="submitted_to_cd")
        weekly_n = weekly.count()
        amount = int(weekly.aggregate(s=Sum("total_amount"))["s"] or 0)
        budget_n = MonthlyWorkPlanBudget.objects.filter(
            fy=fy,
            status__in=[
                "draft_generated",
                "cd_review",
                "admin_plan_added",
                "returned_by_rvp",
            ],
        ).count()
        return {
            "count": weekly_n + budget_n,
            "weekly": weekly_n,
            "budgets": budget_n,
            "amount": amount,
            "amount_label": (
                f"{_ugx_compact(amount)} pending"
                if amount
                else ("monthly budget needs review" if budget_n else "nothing waiting")
            ),
        }

    # ── Leadership attention (mandate §7 triggers) ───────────────────────────
    @staticmethod
    def leadership_attention(cd, acts, fy, regional) -> list[dict]:
        cards = []

        behind = [
            r for r in regional["rows"] if r["achievement"] < REGION_BEHIND_THRESHOLD
        ]
        if behind:
            worst = behind[-1]
            cards.append(
                {
                    "tone": "danger",
                    "title": f"{len(behind)} Region{'s' if len(behind) > 1 else ''} Behind Target",
                    "line1": f"{worst['name']} is at {worst['achievement']}% vs the {REGION_BEHIND_THRESHOLD}% threshold.",
                    "action": "View Regional Performance",
                    "link": "/analytics/country-director",
                }
            )

        overdue_sf = CDDashboardService._sf_overdue(acts)
        if overdue_sf:
            cards.append(
                {
                    "tone": "warning",
                    "title": "High Activity SF ID Backlog",
                    "line1": f"{overdue_sf:,} completed activities missing Activity SF IDs beyond {SF_ID_OVERDUE_DAYS} days.",
                    "action": "Inspect Backlog",
                    "link": "/completed-activities",
                }
            )

        pending = CDDashboardService._pending_cd_items(fy)
        if pending["count"]:
            cards.append(
                {
                    "tone": "info",
                    "title": f"{pending['count']} Fund Item{'s' if pending['count'] > 1 else ''} Pending",
                    "line1": (
                        f"{pending['amount_label']} awaiting Country Director action."
                        if pending["weekly"]
                        else "Country monthly budget awaiting your review."
                    ),
                    "action": "Review Approvals",
                    "link": "/fund-requests/weekly"
                    if pending["weekly"]
                    else "/country-budget/",
                }
            )
        return cards[:3]

    @staticmethod
    def _sf_overdue(acts) -> int:
        from django.utils import timezone

        cutoff = timezone.now() - timedelta(days=SF_ID_OVERDUE_DAYS)
        return (
            _requires_sf_id(acts)
            .filter(
                Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id=""),
                updated_at__lt=cutoff,
            )
            .count()
        )

    # ── Country performance (4 series, mandate §8) ───────────────────────────
    @staticmethod
    def country_performance(cd) -> dict:
        """Planned = everything scheduled for the month (the plan), Completed =
        marked complete, Verified = IA-verified, plus the cumulative
        target-achievement line from the analytics engine."""
        from apps.core.fy import get_month_date_range

        base = CDAnalyticsService.performance_vs_target(cd)  # labels + pct line
        full = _country_activities(resolve_cd_scope(cd.fy))
        planned, completed, verified = [], [], []
        for m in range(1, 13):
            start, end = get_month_date_range(cd.fy, m)
            mq = full.filter(
                planned_date__gte=start.date(), planned_date__lt=end.date()
            )
            planned.append(mq.count())
            completed.append(mq.filter(status__in=COMPLETED_STATUSES).count())
            verified.append(mq.filter(status__in=VERIFIED_STATUSES).count())
        return {
            "labels": base["labels"],
            "pct": base["pct"],
            "has_target": base["has_target"],
            "planned": planned,
            "completed": completed,
            "verified": verified,
        }

    # ── Regional performance ranking (mandate §9) ────────────────────────────
    @staticmethod
    def regional_performance(cd, acts) -> dict:
        from apps.geography.models import Region

        schools = School.objects.filter(id__in=cd.school_ids)
        region_ids = list(
            schools.exclude(region__isnull=True)
            .order_by("region_id")
            .values_list("region_id", flat=True)
            .distinct()
        )
        names = dict(Region.objects.filter(id__in=region_ids).values_list("id", "name"))
        rows = []
        for rid in region_ids:
            r_school_ids = set(
                schools.filter(region_id=rid).values_list("id", flat=True)
            )
            r_acts = acts.filter(school_id__in=r_school_ids)
            planned = r_acts.count()
            done = r_acts.filter(status__in=COMPLETED_STATUSES).count()
            achievement = _pct(done, planned)
            no_ssa = (
                schools.filter(region_id=rid)
                .exclude(current_fy_ssa_status="done")
                .count()
            )
            risk = (
                "danger"
                if achievement < 50
                else "warning"
                if achievement < REGION_BEHIND_THRESHOLD
                else "success"
            )
            rows.append(
                {
                    "id": rid,
                    "name": names.get(rid, "Region"),
                    "achievement": achievement,
                    "planned": planned,
                    "completed": done,
                    "schools": len(r_school_ids),
                    "no_ssa": no_ssa,
                    "tone": risk,
                }
            )
        rows.sort(key=lambda r: -r["achievement"])
        for i, r in enumerate(rows, start=1):
            r["rank"] = i
        national = _pct(
            acts.filter(status__in=COMPLETED_STATUSES).count(), acts.count()
        )
        return {"rows": rows, "national": national}

    # ── PL performance table (mandate §10) ───────────────────────────────────
    @staticmethod
    def pl_performance(cd, acts) -> dict:
        acts.filter(status__in=COMPLETED_STATUSES)
        base = {r["id"]: r for r in CDAnalyticsService.pl_oversight(cd, acts)["rows"]}
        band = {
            "Low Risk": ("On Track", "success"),
            "Medium Risk": ("Watch", "amber"),
            "High Risk": ("High Risk", "warning"),
            "Critical Risk": ("Critical", "danger"),
        }
        rows = []
        for pl in CDAnalyticsService._pls():
            b = base.get(pl.id)
            if not b:
                continue
            cceos = CDAnalyticsService._pl_cceos(pl, cd)
            ids = set()
            school_ids = set()
            for c in cceos:
                ids.add(c["staff_id"])
                if c["user_id"]:
                    ids.add(c["user_id"])
                school_ids |= c["school_ids"]
            team_acts = acts.filter(
                Q(responsible_staff_id__in=ids) | Q(school_id__in=school_ids)
            )
            planned = team_acts.count()
            verified = team_acts.filter(status__in=VERIFIED_STATUSES).count()
            sf_req = _requires_sf_id(team_acts)
            sf_pending = sf_req.filter(
                Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")
            ).count()
            label, tone = band.get(b["risk"], (b["risk"], "neutral"))
            rows.append(
                {
                    "id": pl.id,
                    "name": pl.name,
                    "region": CDDashboardService._pl_region(school_ids),
                    "target_pct": b["target_pct"],
                    "staff": len(cceos),
                    "planned": planned,
                    "verified": verified,
                    "sf_pending": sf_pending,
                    "backlog": b["backlog"],
                    "risk": label,
                    "risk_tone": tone,
                }
            )
        rows.sort(key=lambda r: r["target_pct"])
        return {"rows": rows}

    @staticmethod
    def _pl_region(school_ids) -> str:
        if not school_ids:
            return "—"
        r = (
            School.objects.filter(id__in=school_ids)
            .exclude(region__isnull=True)
            .values_list("region__name", flat=True)
            .first()
        )
        return r or "—"

    # ── Fund approval & finance snapshot (mandate §11) ───────────────────────
    @staticmethod
    def finance_snapshot(cd, acts, fy) -> dict:
        from apps.fund_requests.models import AdvanceRequest, WeeklyFundRequest

        pending_rows = []
        qs = WeeklyFundRequest.objects.filter(fy=fy, status="submitted_to_cd").order_by(
            "week_start_date"
        )[:6]
        names = dict(
            User.objects.filter(id__in=[r.responsible_user for r in qs]).values_list(
                "id", "name"
            )
        )
        for r in qs:
            # AdvanceRequest.planned_date is an instant while the weekly fund
            # request owns date-only boundaries. Use an aware half-open window
            # so the final day's advances are counted and strict timezone mode
            # cannot turn a dashboard read into a 500 response.
            week_start = _normalize_datetime_value(r.week_start_date)
            week_end_exclusive = _normalize_datetime_value(
                r.week_end_date + timedelta(days=1)
            )
            covered = AdvanceRequest.objects.filter(
                responsible_user_id=r.responsible_user,
                planned_date__gte=week_start,
                planned_date__lt=week_end_exclusive,
            ).count()
            pending_rows.append(
                {
                    "id": r.id,
                    "team": names.get(r.responsible_user, "Team"),
                    "amount": _ugx_compact(int(r.total_amount or 0)),
                    "covered": covered,
                    "stage": "CD Review",
                }
            )

        # Funded but not completed — money out, work not done.
        funded = (
            AdvanceRequest.objects.filter(
                activity__fy=fy,
                activity__deleted_at__isnull=True,
                status__in=["disbursed", "accountability_pending", "accounted"],
            )
            .exclude(activity__status__in=COMPLETED_STATUSES)
            .select_related("activity")
        )
        today = date.today()
        funded_amount = int(funded.aggregate(s=Sum("disbursed_amount"))["s"] or 0)
        overdue = sum(
            1
            for a in funded
            if a.activity
            and a.activity.planned_date
            and a.activity.planned_date < today
        )
        not_started = sum(
            1
            for a in funded
            if a.activity and a.activity.status in ("scheduled", "planned")
        )
        return {
            "pending_rows": pending_rows,
            "pending_count": len(pending_rows),
            "funded_not_completed": {
                "amount": _ugx_compact(funded_amount),
                "activities": funded.count(),
                "overdue": overdue,
                "not_started": not_started,
                "in_progress": max(0, funded.count() - overdue - not_started),
            },
        }

    # ── Operational risk & backlog (mandate §12 — 6 cards) ───────────────────
    @staticmethod
    def operational_risk_backlog(cd, acts, fy) -> list[dict]:
        completed = acts.filter(status__in=COMPLETED_STATUSES)
        schools = School.objects.filter(id__in=cd.school_ids)
        all_ids = set(schools.values_list("id", flat=True))

        overdue_sf = CDDashboardService._sf_overdue(acts)
        returned = acts.filter(status__in=["returned_by_pl", "returned_by_ia"]).count()
        try:
            from apps.core_schools.models import CoreActivitySlot

            returned += CoreActivitySlot.objects.exclude(
                Q(returned_reason__isnull=True) | Q(returned_reason="")
            ).count()
        except Exception:  # noqa: BLE001
            pass

        visited = set(
            completed.filter(activity_type__in=VISIT_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )
        trained = set(
            completed.filter(activity_type__in=TRAINING_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )
        core = CDDashboardService._core_on_track(fy)
        leave_alerts = CDDashboardService._leave_conflicts(cd, acts)

        def c(icon, label, count, tone, helper, link):
            return {
                "icon": icon,
                "label": label,
                "count": count,
                "tone": tone,
                "helper": helper,
                "link": link,
            }

        return [
            c(
                "cloud",
                "Overdue Activity SF IDs",
                overdue_sf,
                "danger",
                f"{SF_ID_OVERDUE_DAYS}+ days",
                "/completed-activities",
            ),
            c(
                "warning",
                "Returned Verifications",
                returned,
                "warning",
                "sent back by PL / IA",
                "/analytics/country-director",
            ),
            c(
                "school",
                "Schools No Recent Visit",
                len(all_ids - visited),
                "warning",
                "this period",
                "/analytics/country-director/drilldown?drill=risk&issue=no_visit",
            ),
            c(
                "book",
                "Schools No Training",
                len(all_ids - trained),
                "info",
                "this period",
                "/analytics/country-director/drilldown?drill=risk&issue=no_training",
            ),
            c(
                "shield",
                "Core Schools Behind",
                core["behind"],
                "violet",
                "assessment + 4 visits + 4 trainings",
                "/core-school-health",
            ),
            c(
                "calendar",
                "Leave / Conflict Alerts",
                leave_alerts,
                "info",
                "coverage clashes next 7 days",
                "/leave/coverage",
            ),
        ]

    @staticmethod
    def _leave_conflicts(cd, acts) -> int:
        from apps.accounts.models import Leave

        today = date.today()
        wk_end = (today + timedelta(days=7)).isoformat()
        leaves = Leave.objects.filter(
            status__in=["approved", "pending"],
            start_date__lte=wk_end,
            end_date__gte=today.isoformat(),
        ).select_related("staff")
        conflicts = 0
        for lv in leaves:
            ids = {lv.staff_id}
            if lv.staff and lv.staff.user_id:
                ids.add(lv.staff.user_id)
            if (
                acts.filter(
                    responsible_staff_id__in=ids,
                    scheduled_date__date__gte=lv.start_date,
                    scheduled_date__date__lte=lv.end_date,
                )
                .exclude(status="cancelled")
                .exists()
            ):
                conflicts += 1
        return conflicts

    # ── School & SSA intelligence (mandate §13 — all 8 interventions) ────────
    @staticmethod
    def ssa_matrix(cd, acts) -> dict:
        """Region rows (plus clusters with genuine school membership) ×
        the eight backend SSA interventions, latest verified annual cycle."""
        from apps.geography.models import Region
        from apps.ssa.models import SsaRecord, SsaScore

        latest, _prev = _cycle_fys(cd.school_ids, cd.fy)
        codes = [c for _, _, c in SSA_INTERVENTIONS]
        if not latest:
            return {"rows": [], "codes": codes, "latest_fy": None}

        def matrix_row(label, school_ids, kind, rid=""):
            rids = list(
                SsaRecord.objects.filter(
                    school_id__in=school_ids, verification_status="confirmed", fy=latest
                ).values_list("id", flat=True)
            )
            if not rids:
                return None
            by = {
                r["intervention"]: r["a"]
                for r in SsaScore.objects.filter(ssa_record_id__in=rids)
                .values("intervention")
                .annotate(a=Avg("score"))
            }
            cells = []
            for v, _label, _code in SSA_INTERVENTIONS:
                pct = _norm(by.get(v))
                cells.append({"pct": pct, "tone": ssa_band(pct)[2]})
            overall = _norm(
                SsaRecord.objects.filter(id__in=rids).aggregate(a=Avg("average_score"))[
                    "a"
                ]
            )
            return {
                "label": label,
                "kind": kind,
                "id": rid,
                "cells": cells,
                "overall": overall,
                "overall_tone": ssa_band(overall)[2],
            }

        schools = School.objects.filter(id__in=cd.school_ids)
        rows = []
        for rid in (
            schools.exclude(region__isnull=True)
            .order_by("region_id")
            .values_list("region_id", flat=True)
            .distinct()
        ):
            name = (
                Region.objects.filter(id=rid).values_list("name", flat=True).first()
                or "Region"
            )
            row = matrix_row(
                name,
                set(schools.filter(region_id=rid).values_list("id", flat=True)),
                "region",
                rid,
            )
            if row:
                rows.append(row)
        # Clusters with genuine membership only — never fabricated groupings.
        names, membership = CDAnalyticsService._cluster_membership(cd, acts)
        for cid, sids in sorted(membership.items()):
            if len(sids) >= 2:
                row = matrix_row(names.get(cid, "Cluster"), sids, "cluster", cid)
                if row:
                    rows.append(row)
        return {"rows": rows, "codes": codes, "latest_fy": latest}

    @staticmethod
    def priority_schools(cd, acts, limit=6) -> list[dict]:
        """Schools with the most compounded workflow gaps — inspect /
        assign-follow-up only, never direct scheduling."""
        from apps.ssa.models import SsaRecord

        completed = acts.filter(status__in=COMPLETED_STATUSES)
        schools = School.objects.filter(id__in=cd.school_ids).select_related(
            "district", "region"
        )
        visited = set(
            completed.filter(activity_type__in=VISIT_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )
        trained = set(
            completed.filter(activity_type__in=TRAINING_TYPES)
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )
        latest, _prev = _cycle_fys(cd.school_ids, cd.fy)
        weak = set()
        if latest:
            weak = set(
                SsaRecord.objects.filter(
                    school_id__in=cd.school_ids,
                    verification_status="confirmed",
                    fy=latest,
                    average_score__lt=5.0,
                ).values_list("school_id", flat=True)
            )
        sf_missing = set(
            _requires_sf_id(acts)
            .filter(
                Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")
            )
            .exclude(school_id__isnull=True)
            .values_list("school_id", flat=True)
        )

        rows = []
        for s in schools:
            issues = []
            if s.id not in visited:
                issues.append("No Visit")
            if s.id not in trained:
                issues.append("No Training")
            if s.current_fy_ssa_status != "done":
                issues.append("No SSA")
            if s.id in weak:
                issues.append("SSA Weakness")
            if s.id in sf_missing:
                issues.append("SF ID Missing")
            if len(issues) >= 2:
                risk = "High" if len(issues) >= 3 else "Medium"
                rows.append(
                    {
                        "id": s.id,
                        "school": s.name,
                        "region": (
                            s.district.name
                            if s.district_id
                            else (s.region.name if s.region_id else "—")
                        ),
                        "issues": issues[:3],
                        "risk": risk,
                        "risk_tone": "danger" if risk == "High" else "warning",
                    }
                )
        rows.sort(key=lambda r: (-len(r["issues"]), r["school"]))
        return rows[:limit]

    # ── Quick leadership actions (mandate §14 — all real routes) ─────────────
    @staticmethod
    def quick_actions() -> list[dict]:
        return [
            {
                "label": "Review Fund Requests",
                "icon": "currency",
                "url": "/fund-requests/weekly",
                "helper": "CD approval queue",
            },
            {
                "label": "View High-Risk Regions",
                "icon": "warning",
                "url": "/analytics/country-director",
                "helper": "regional risk intelligence",
            },
            {
                "label": "Inspect Activity SF ID Backlog",
                "icon": "cloud",
                "url": "/completed-activities",
                "helper": "completed work missing SF IDs",
            },
            {
                "label": "See Core School Delays",
                "icon": "shield",
                "url": "/core-school-health",
                "helper": "assessment + 4 visits + 4 trainings",
            },
            {
                "label": "Review Team Targets",
                "icon": "target",
                "url": "/team-targets/",
                "helper": "PL and CCEO target health",
            },
            {
                "label": "Open Country Report",
                "icon": "report",
                "url": "/reports",
                "helper": "export center",
            },
        ]

    # ── Country monthly budget stage (kept for the finance snapshot chip) ────
    @staticmethod
    def budget_stage(fy) -> dict:
        labels = {
            "draft_generated": ("Draft", "Needs CD review"),
            "cd_review": ("In CD Review", "Complete review, add admin plan"),
            "admin_plan_added": ("Ready to Submit", "Send to RVP for approval"),
            "submitted_to_rvp": ("With RVP", "Awaiting RVP approval"),
            "approved_by_rvp": ("Approved", "Ready for accountant"),
            "returned_by_rvp": ("Returned by RVP", "Fix and resubmit"),
            "sent_to_accountant": ("With Accountant", "Disbursement in progress"),
            "disbursed": ("Disbursed", "Funds released"),
            "closed": ("Closed", "Month complete"),
        }
        from apps.monthly_work_plan.models import MonthlyWorkPlanBudget

        b = MonthlyWorkPlanBudget.objects.filter(fy=fy).order_by("-month_key").first()
        if not b:
            return {
                "label": "Not Started",
                "helper": "no monthly budget yet",
                "status": None,
                "month": None,
                "amount": None,
            }
        label, helper = labels.get(b.status, (b.status, ""))
        return {
            "label": label,
            "helper": helper,
            "status": b.status,
            "month": b.month_key,
            "amount": _ugx_compact(int(b.total_amount or 0)),
        }
