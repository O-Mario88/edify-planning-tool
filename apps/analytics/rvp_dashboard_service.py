"""RVP Dashboard — the regional executive operating system.

Strategic oversight only: the RVP approves Country Monthly and Annual
Budgets, monitors Country Directors, evaluates region/project/partner impact
and directs strategy — never field execution, never disbursement. Everything
here reuses the country-wide engines (CDAnalyticsService scope, the validated
target ledger, the annual-SSA comparison) so the RVP sees the same numbers the
country teams see, rolled up.

Deployment note: this platform runs one country per deployment, so the RVP's
"regional portfolio" resolves to the deployment country (settings.COUNTRY_ID)
and performance ranking runs over its Regions — honest to the data model, no
invented country rows.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.core.fy import get_operational_fy
from apps.schools.models import School

from apps.analytics.cd_analytics_service import (
    CDAnalyticsService,
    _country_activities,
    _cycle_fys,
    _prime_target_series,
    resolve_cd_scope,
)
from apps.analytics.cd_dashboard_service import _ugx_compact
from apps.analytics.pl_analytics_service import (
    COMPLETED_STATUSES,
    TRAINING_TYPES,
    _norm,
    _pct,
)

VERIFIED_STATUSES = ("ia_verified", "verified", "closed")


def _region_of_school_map(cd):
    return {
        s["id"]: s["district__region__name"]
        for s in School.objects.filter(id__in=cd.school_ids)
        .exclude(district__isnull=True)
        .values("id", "district__region__name")
    }


class RVPDashboardService:
    # ── page payload ─────────────────────────────────────────────────────────
    @staticmethod
    def get_dashboard(user, fy: str | None = None, month: str | None = None) -> dict:
        from apps.monthly_work_plan.models import (
            CountryAnnualBudget,
            MonthlyWorkPlanBudget,
            RVPApprovalDecision,
            StrategyNote,
        )

        fy = fy or get_operational_fy()
        cd = resolve_cd_scope(fy)
        acts = _country_activities(cd)
        # Same validated-ledger read as CD Analytics/CD Dashboard — refresh
        # first so the RVP never inherits a staler number than the country
        # teams see. This rollup calls _weighted_overall(cd) 3x below; priming
        # cd.per_user_series here means every one of those pools from the SAME
        # pre-fetched series instead of each re-rebuilding + re-fetching
        # per-user monthly_targets/achievements from scratch.
        _prime_target_series(cd)
        completed_qs = acts.filter(status__in=COMPLETED_STATUSES)
        acts.filter(status__in=VERIFIED_STATUSES)

        from apps.monthly_work_plan.services import _rvp_country_scope

        scope_country = _rvp_country_scope()
        budgets = MonthlyWorkPlanBudget.objects.filter(fy=fy).filter(
            Q(country_id=scope_country) | Q(country_id__isnull=True) | Q(country_id="")
        )
        awaiting = budgets.filter(status="submitted_to_rvp").order_by("month_key")
        approved = budgets.filter(
            status__in=["approved_by_rvp", "sent_to_accountant", "disbursed", "closed"]
        )
        returned = budgets.filter(status="returned_by_rvp")
        annuals = CountryAnnualBudget.objects.filter(fy=fy, country_id=scope_country)
        annual_pending = annuals.filter(status="submitted_to_rvp")
        annual_approved = annuals.filter(status="approved_by_rvp")

        # Regional target achievement — the SAME weighted five-area validated
        # ledger the CD analytics KPI uses.
        overall_pct, overall_a, overall_t = CDAnalyticsService._weighted_overall(cd)

        regions = RVPDashboardService.region_ranking(cd, acts, fy)
        high_risk_regions = [
            r for r in regions if r["status"] in ("High Risk", "Critical")
        ]
        cds = RVPDashboardService.cd_performance(cd, acts, fy)
        on_track_cds = sum(1 for c in cds if c["risk"] in ("Strong", "On Track"))

        projects = RVPDashboardService.special_projects(cd, acts, fy)
        projects_on_track = sum(
            1
            for p in projects
            if p["impact"] in ("Great Impact", "Positive Impact")
            and p["target_pct"] >= 60
        )
        under_review = [
            p
            for p in projects
            if p["recommendation"]
            in ("Request Redesign", "Put Under Review", "Close Project")
        ]

        awaiting_amt = int(awaiting.aggregate(s=Sum("total_amount"))["s"] or 0)
        approved_amt = int(approved.aggregate(s=Sum("total_amount"))["s"] or 0)
        annual_total = int(annual_approved.aggregate(s=Sum("total_amount"))["s"] or 0)
        budget_util = CDAnalyticsService._budget_utilization(cd)

        reached = set(
            completed_qs.exclude(school_id__isnull=True).values_list(
                "school_id", flat=True
            )
        )
        teachers = int(
            completed_qs.filter(activity_type__in=TRAINING_TYPES).aggregate(
                s=Sum("teachers_attended")
            )["s"]
            or 0
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

        kpis = [
            card(
                "target",
                "Regional Target Achievement",
                f"{overall_pct}%",
                "primary",
                "weighted five-area validated ledger",
            ),
            card(
                "map",
                "Regions Overseen",
                str(len(regions)),
                "info",
                "with active schools",
            ),
            card(
                "users",
                "Country Directors On Track",
                f"{on_track_cds} / {len(cds)}",
                "success" if on_track_cds == len(cds) and cds else "warning",
                "performance + finance thresholds",
            ),
            card(
                "clock",
                "Monthly Budget Pending Approval",
                _ugx_compact(awaiting_amt) if awaiting_amt else "0",
                "warning" if awaiting.count() else "success",
                f"{awaiting.count()} budget(s) awaiting you",
            ),
            card(
                "report",
                "Annual Budget Status",
                f"{annual_approved.count()} / {annuals.count() or 0}",
                "info",
                f"{annual_pending.count()} submitted · "
                f"{annuals.filter(status='returned_by_rvp').count()} returned",
            ),
            card(
                "shield",
                "Special Projects On Track",
                f"{projects_on_track} / {len(projects)}",
                "violet",
                "execution + verified annual impact",
            ),
            card(
                "currency",
                "Budget Utilization",
                f"{budget_util}%",
                "finance",
                # _budget_utilization divides disbursed by *requested*, not by
                # an approved total. The old "disbursed vs approved" caption
                # described a different number than the one being shown.
                "disbursed vs requested",
            ),
            card(
                "school",
                "Schools Impacted",
                f"{len(reached):,}",
                "info",
                "verified activity",
            ),
            card(
                "users",
                "Teachers Trained",
                f"{teachers:,}",
                "success",
                "verified attendance",
            ),
            card(
                "warning",
                "High-Risk Regions",
                str(len(high_risk_regions)),
                "danger" if high_risk_regions else "success",
                "high risk or critical",
            ),
        ]

        # ── Leadership attention (top 3, never decorative) ───────────────────
        attention = []
        if awaiting.count():
            oldest = awaiting.order_by("submitted_at").first()
            age = (
                (timezone.now() - oldest.submitted_at).days
                if oldest and oldest.submitted_at
                else 0
            )
            attention.append(
                {
                    "key": "budgets",
                    "tone": "warning",
                    "title": "Country Budget Pending Approval",
                    "body": (
                        f"{_ugx_compact(awaiting_amt)} across {awaiting.count()} "
                        f"monthly budget(s) awaiting your approval"
                        + (f" · oldest {age}d" if age else "")
                    ),
                    "action": "Review Monthly Budgets",
                    "drill": "approvals",
                }
            )
        if high_risk_regions:
            attention.append(
                {
                    "key": "risk",
                    "tone": "danger",
                    "title": "High-Risk Regional Performance",
                    "body": (
                        f"{len(high_risk_regions)} region(s) below the risk "
                        "threshold: "
                        + ", ".join(r["name"] for r in high_risk_regions[:3])
                    ),
                    "action": "Inspect High-Risk Regions",
                    "drill": "regions",
                }
            )
        if under_review:
            attention.append(
                {
                    "key": "projects",
                    "tone": "warning",
                    "title": "Special Project Under Review",
                    "body": f"{len(under_review)} project(s) need your review and decision.",
                    "action": "Review Special Projects",
                    "drill": "projects",
                }
            )
        if not annuals.exists():
            attention.append(
                {
                    "key": "annual",
                    "tone": "info",
                    "title": "Annual Budget Not Submitted",
                    "body": f"No FY {fy} Country Annual Budget has been prepared yet.",
                    "action": "Review Annual Budgets",
                    "drill": "approvals",
                }
            )
        attention = attention[:3]

        # ── recent decisions + strategy notes ────────────────────────────────
        decisions = [
            {
                "label": d.subject_label,
                "action": d.action.title(),
                "amount": _ugx_compact(d.amount) if d.amount else "—",
                "by": "RVP",
                "when": d.created_at,
            }
            for d in RVPApprovalDecision.objects.order_by("-created_at")[:5]
        ]

        notes = list(
            StrategyNote.objects.exclude(status="cancelled").order_by("-created_at")[:4]
        )

        from apps.debriefs.rollup_service import field_debrief_intelligence_summary

        field_debrief_intel = field_debrief_intelligence_summary(user)

        return {
            "fy": fy,
            "kpi_strip_items": kpis,
            "attention": attention,
            "overview": RVPDashboardService.performance_overview(cd, acts, fy),
            "regions": regions,
            "cds": cds,
            "budget_snapshot": {
                "monthly_pending": awaiting.count(),
                "monthly_pending_amt": _ugx_compact(awaiting_amt),
                "annual_pending": annual_pending.count(),
                "annual_pending_amt": _ugx_compact(
                    int(annual_pending.aggregate(s=Sum("total_amount"))["s"] or 0)
                ),
                "approved_fy_amt": _ugx_compact(approved_amt),
                "approved_fy_count": approved.count(),
                "total_amt": _ugx_compact(approved_amt + annual_total),
                "returned_count": returned.count(),
                "annual_dist": {
                    "approved": annual_approved.count(),
                    "pending": annual_pending.count(),
                    "returned": annuals.filter(status="returned_by_rvp").count(),
                    "draft": annuals.filter(status="draft").count(),
                },
                "recent_decisions": decisions,
            },
            "awaiting_rows": [RVPDashboardService._budget_row(b) for b in awaiting],
            "annual_rows": [
                RVPDashboardService._annual_row(b) for b in annuals.order_by("-fy")
            ],
            "projects": projects,
            "project_impact_dist": RVPDashboardService._impact_dist(projects),
            "partners": RVPDashboardService.partner_growth(cd, acts),
            "allocation": RVPDashboardService.resource_allocation(
                cd, acts, fy, reached
            ),
            "risks": RVPDashboardService.operational_risks(
                cd, acts, awaiting, projects
            ),
            "recommended": RVPDashboardService.recommended_actions(
                awaiting, annual_pending, high_risk_regions, under_review, notes
            ),
            "strategy_notes": notes,
            "field_debrief_intel": field_debrief_intel,
            "cd_options": [{"id": c["user_id"], "name": c["name"]} for c in cds],
            "quick_actions": [
                {
                    "label": "Review Monthly Budgets",
                    "url": "/country-budget/",
                    "icon": "report",
                },
                {
                    "label": "Review Annual Country Budgets",
                    "url": "#rvp-approvals",
                    "icon": "calendar",
                },
                {
                    "label": "Inspect High-Risk Regions",
                    "url": "#region-ranking",
                    "icon": "warning",
                },
                {
                    "label": "View Special Projects",
                    "url": "#special-projects",
                    "icon": "shield",
                },
                {
                    "label": "Review Partner Performance",
                    "url": "#partner-growth",
                    "icon": "users",
                },
                {"label": "Open Regional Report", "url": "/reports", "icon": "book"},
            ],
            "last_refreshed": timezone.now(),
        }

    # ── §7 performance overview ──────────────────────────────────────────────
    @staticmethod
    def performance_overview(cd, acts, fy):
        from apps.targets.fy_calendar import (
            MONTH_LABELS,
            FinancialYearCalendarService as Cal,
        )
        from apps.targets.models import TargetAchievementLedger

        planned, completed, verified, achievement = [], [], [], []
        validated_by_month = {
            r["credited_month"]: r["n"]
            for r in TargetAchievementLedger.objects.filter(
                fy=fy, validation_status="validated"
            )
            .values("credited_month")
            .annotate(n=Count("id"))
        }
        _, _, total_target = CDAnalyticsService._weighted_overall(cd)
        monthly_target = (total_target / 12.0) if total_target else 0
        for m in range(1, 13):
            start, end = Cal.month_range(fy, m)
            month_qs = acts.filter(planned_date__gte=start, planned_date__lt=end)
            planned.append(month_qs.count())
            completed.append(month_qs.filter(status__in=COMPLETED_STATUSES).count())
            verified.append(month_qs.filter(status__in=VERIFIED_STATUSES).count())
            v = validated_by_month.get(m, 0)
            achievement.append(round(v / monthly_target * 100) if monthly_target else 0)
        return {
            "labels": MONTH_LABELS,
            "planned": planned,
            "completed": completed,
            "verified": verified,
            "achievement": achievement,
        }

    # ── §8 region ranking (multi-factor, never % alone) ──────────────────────
    @staticmethod
    def region_ranking(cd, acts, fy):
        from apps.geography.models import Region
        from apps.ssa.models import SsaRecord

        latest, prev = _cycle_fys(cd.school_ids, fy)
        region_map = _region_of_school_map(cd)  # school_id -> region name
        region_schools: dict = {}
        for sid, rname in region_map.items():
            region_schools.setdefault(rname, []).append(sid)

        # Batch-fetch once instead of ~5 queries per region: every in-scope
        # activity's (school_id, status, salesforce_activity_id) and every
        # confirmed SSA record for the latest cycle, grouped by region name
        # in Python via region_map.
        region_counts: dict = {}  # region_name -> {"planned": n, "done": n, "ver": n, "sf_have": n}

        def _bucket(rname):
            return region_counts.setdefault(
                rname, {"planned": 0, "done": 0, "ver": 0, "sf_have": 0}
            )

        for sid, status, sf_id in acts.exclude(school_id__isnull=True).values_list(
            "school_id",
            "status",
            "salesforce_activity_id",
        ):
            rname = region_map.get(sid)
            if rname is None:
                continue
            b = _bucket(rname)
            b["planned"] += 1
            is_done = status in COMPLETED_STATUSES
            if is_done:
                b["done"] += 1
                if (sf_id or "").strip():
                    b["sf_have"] += 1
            if status in VERIFIED_STATUSES:
                b["ver"] += 1

        region_scores: dict = {}  # region_name -> [average_score, ...]
        if latest:
            for sid, score in SsaRecord.objects.filter(
                school_id__in=cd.school_ids,
                verification_status="confirmed",
                fy=latest,
            ).values_list("school_id", "average_score"):
                rname = region_map.get(sid)
                if rname is not None:
                    region_scores.setdefault(rname, []).append(score)

        def _mean(values):
            values = [v for v in values if v is not None]
            return (sum(values) / len(values)) if values else None

        rows = []
        for region in Region.objects.all():
            sids = region_schools.get(region.name)
            if not sids:
                continue
            counts = region_counts.get(
                region.name, {"planned": 0, "done": 0, "ver": 0, "sf_have": 0}
            )
            planned, done, ver, sf_have = (
                counts["planned"],
                counts["done"],
                counts["ver"],
                counts["sf_have"],
            )
            exec_rate = _pct(done, planned)
            verified_rate = _pct(ver, done)
            ssa = _norm(_mean(region_scores.get(region.name, []))) if latest else None
            sf_rate = _pct(sf_have, done) if done else 100
            score = round(
                exec_rate * 0.35
                + verified_rate * 0.2
                + (ssa or 0) * 0.25
                + sf_rate * 0.2
            )
            if score >= 80:
                status, tone = "Strong", "success"
            elif score >= 65:
                status, tone = "On Track", "success"
            elif score >= 50:
                status, tone = "Watch", "warning"
            elif score >= 35:
                status, tone = "High Risk", "danger"
            else:
                status, tone = "Critical", "danger"
            rows.append(
                {
                    "name": region.name,
                    "id": region.id,
                    "schools": len(sids),
                    "exec_rate": exec_rate,
                    "verified_rate": verified_rate,
                    "ssa": ssa,
                    "sf_rate": sf_rate,
                    "score": score,
                    "status": status,
                    "tone": tone,
                }
            )
        rows.sort(key=lambda r: -r["score"])
        for i, r in enumerate(rows):
            r["rank"] = i + 1
        return rows

    # ── §10 Country Director performance ─────────────────────────────────────
    @staticmethod
    def cd_performance(cd, acts, fy):
        from apps.accounts.models import User
        from apps.fund_requests.models import WeeklyFundRequest

        overall_pct, _, _ = CDAnalyticsService._weighted_overall(cd)
        acts.count()
        done_qs = acts.filter(status__in=COMPLETED_STATUSES)
        done = done_qs.count()
        ver = acts.filter(status__in=VERIFIED_STATUSES).count()
        sf_have = (
            done_qs.exclude(salesforce_activity_id__isnull=True)
            .exclude(salesforce_activity_id="")
            .count()
        )
        backlog = (done - sf_have) + acts.filter(
            status="awaiting_ia_verification"
        ).count()
        util = CDAnalyticsService._budget_utilization(cd)
        pending_cd = WeeklyFundRequest.objects.filter(status="submitted_to_cd").count()

        rows = []
        for u in User.objects.filter(
            roles__contains=["CountryDirector"],
            status="active",
            deleted_at__isnull=True,
        ):
            score = round(
                overall_pct * 0.4
                + _pct(ver, done) * 0.2
                + _pct(sf_have, done) * 0.2
                + min(util, 100) * 0.2
            )
            if score >= 75:
                risk, tone = "Strong", "success"
            elif score >= 60:
                risk, tone = "On Track", "success"
            elif score >= 45:
                risk, tone = "Watch", "warning"
            else:
                risk, tone = "High Risk", "danger"
            rows.append(
                {
                    "user_id": u.id,
                    "name": u.name,
                    "initials": (u.name or "??")[:2].upper(),
                    "country": "Uganda",
                    "target_pct": overall_pct,
                    "completed": done,
                    "verified_rate": _pct(ver, done),
                    "sf_rate": _pct(sf_have, done) if done else 100,
                    "backlog": backlog + pending_cd,
                    "budget_util": util,
                    "risk": risk,
                    "tone": tone,
                }
            )
        return rows

    # ── §16 special projects ─────────────────────────────────────────────────
    @staticmethod
    def special_projects(cd, acts, fy):
        from collections import defaultdict

        from apps.activities.models import Activity, ActivityScheduleCostLine
        from apps.projects.models import Project, ProjectSchoolAssignment
        from apps.ssa.models import SsaRecord

        latest, prev = _cycle_fys(cd.school_ids, fy)
        projects = list(Project.objects.filter(deleted_at__isnull=True))
        if not projects:
            return []

        # Two authoritative activity→project relationship paths — direct
        # Activity.project_id, and indirect via ActivityScheduleCostLine.project
        # (a cost line can reference a project even when the activity's own
        # project_id is unset, e.g. partner-costed project work). Consolidated
        # here into one project_id → {activity_id} map via two bulk queries
        # instead of a filter-per-project loop, so an activity reachable
        # through either (or both) paths is counted exactly once.
        project_activity_ids: dict[str, set[str]] = defaultdict(set)
        for pid, aid in acts.exclude(project_id__isnull=True).values_list(
            "project_id", "id"
        ):
            project_activity_ids[pid].add(aid)
        for pid, aid in (
            ActivityScheduleCostLine.objects.filter(
                activity__in=acts, project_id__isnull=False
            )
            .values_list("project_id", "activity_id")
            .distinct()
        ):
            project_activity_ids[pid].add(aid)

        all_activity_ids = set().union(*project_activity_ids.values())

        # Bulk activity status/school lookup — one query regardless of how
        # many projects exist.
        activity_info = {
            a["id"]: a
            for a in Activity.objects.filter(id__in=all_activity_ids).values(
                "id", "status", "school_id"
            )
        }

        # Bulk cost-line totals per activity — one query. Mirrors the prior
        # per-project aggregate: every cost line on an in-scope activity
        # contributes, not only lines tagged to that specific project.
        activity_cost = defaultdict(int)
        for aid, amt in ActivityScheduleCostLine.objects.filter(
            activity_id__in=all_activity_ids
        ).values_list("activity_id", "amount"):
            activity_cost[aid] += amt or 0

        # Authoritative school scope: explicit ProjectSchoolAssignment rows
        # when present, else derived from the project's own activities. (The
        # prior `hasattr(p, "school_links")` check was always False — Project
        # has no such attribute, so assignments were silently never used.)
        assigned_schools = defaultdict(set)
        for pid, sid in ProjectSchoolAssignment.objects.filter(
            project_id__in=[p.id for p in projects]
        ).values_list("project_id", "school_id"):
            assigned_schools[pid].add(sid)

        all_school_ids = (
            set().union(*assigned_schools.values()) if assigned_schools else set()
        )
        for aid in all_activity_ids:
            sid = activity_info.get(aid, {}).get("school_id")
            if sid:
                all_school_ids.add(sid)

        # Bulk SSA cycle scores for every school touched by any project — two
        # queries total instead of two per project. Grouped by school (not
        # collapsed to a single value) so the per-project average exactly
        # replicates the prior per-project Avg() aggregate.
        cur_by_school = defaultdict(list)
        old_by_school = defaultdict(list)
        if latest and prev and all_school_ids:
            for sid, sc in SsaRecord.objects.filter(
                school_id__in=all_school_ids, verification_status="confirmed", fy=latest
            ).values_list("school_id", "average_score"):
                cur_by_school[sid].append(sc)
            for sid, sc in SsaRecord.objects.filter(
                school_id__in=all_school_ids, verification_status="confirmed", fy=prev
            ).values_list("school_id", "average_score"):
                old_by_school[sid].append(sc)

        rows = []
        for p in projects:
            act_ids = project_activity_ids.get(p.id, set())
            planned = len(act_ids)
            done = sum(
                1
                for aid in act_ids
                if activity_info.get(aid, {}).get("status") in COMPLETED_STATUSES
            )
            ver = sum(
                1
                for aid in act_ids
                if activity_info.get(aid, {}).get("status") in VERIFIED_STATUSES
            )
            budget = sum(activity_cost.get(aid, 0) for aid in act_ids)
            school_ids = assigned_schools.get(p.id) or {
                activity_info[aid]["school_id"]
                for aid in act_ids
                if activity_info.get(aid, {}).get("school_id")
            }
            target_pct = _pct(done, planned)
            # Annual impact: verified baseline + latest annual delta on the
            # project's schools (never a monthly claim).
            impact, impact_tone, delta = "Impact Not Measurable Yet", "neutral", None
            if latest and prev and school_ids:
                cur_vals = [v for sid in school_ids for v in cur_by_school.get(sid, [])]
                old_vals = [v for sid in school_ids for v in old_by_school.get(sid, [])]
                cur = sum(cur_vals) / len(cur_vals) if cur_vals else None
                old = sum(old_vals) / len(old_vals) if old_vals else None
                if cur is not None and old is not None:
                    delta = round((cur - old) * 10, 1)
                    if delta >= 8:
                        impact, impact_tone = "Great Impact", "success"
                    elif delta > 0:
                        impact, impact_tone = "Positive Impact", "success"
                    elif delta == 0:
                        impact, impact_tone = "No Measurable Impact", "warning"
                    else:
                        impact, impact_tone = "Negative Impact", "danger"
            # §16 matrix: execution × impact → recommendation.
            high_exec = target_pct >= 60
            high_impact = impact in ("Great Impact", "Positive Impact")
            if not planned and not school_ids:
                rec = "Request More Evidence"
            elif impact == "Impact Not Measurable Yet":
                rec = "Request Additional Measurement"
            elif high_exec and high_impact:
                rec = "Scale Project"
            elif high_exec and not high_impact:
                rec = (
                    "Request Redesign"
                    if impact != "Negative Impact"
                    else "Put Under Review"
                )
            elif not high_exec and high_impact:
                rec = "Continue Project"
            else:
                rec = (
                    "Close Project"
                    if impact == "Negative Impact"
                    else "Put Under Review"
                )
            rows.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "code": p.code or "—",
                    "country": "Uganda",
                    "goal": p.get_category_display(),
                    "intervention": p.intervention or "—",
                    "budget": _ugx_compact(budget),
                    "budget_raw": budget,
                    "target_pct": target_pct,
                    "verified": ver,
                    "impact": impact,
                    "impact_tone": impact_tone,
                    "delta": delta,
                    "recommendation": rec,
                }
            )
        rows.sort(key=lambda r: -r["budget_raw"])
        return rows

    @staticmethod
    def _impact_dist(projects):
        keys = [
            "Great Impact",
            "Positive Impact",
            "No Measurable Impact",
            "Negative Impact",
            "Impact Not Measurable Yet",
        ]
        return [
            {"label": k, "count": sum(1 for p in projects if p["impact"] == k)}
            for k in keys
            if any(p["impact"] == k for p in projects)
        ]

    # ── §19 partner & stakeholder growth ─────────────────────────────────────
    @staticmethod
    def partner_growth(cd, acts):
        base = CDAnalyticsService.partner_performance(cd, acts)["rows"]
        out = []
        for r in base:
            out.append(
                {
                    **r,
                    "type": "Implementing Partner"
                    if r.get("schools_supported")
                    else "Strategic Partner",
                    "strategic_value": (
                        "Strong"
                        if (r.get("ssa_improve") or 0) > 5
                        else "Moderate"
                        if (r.get("ssa_improve") or 0) > 0
                        else "Watch"
                    ),
                }
            )
        return out

    # ── §21 resource allocation ──────────────────────────────────────────────
    @staticmethod
    def resource_allocation(cd, acts, fy, reached):
        from apps.activities.models import ActivityScheduleCostLine

        region_map = _region_of_school_map(cd)
        by_region: dict[str, int] = {}
        lines = (
            ActivityScheduleCostLine.objects.filter(
                activity__fy=fy, activity__deleted_at__isnull=True
            )
            .exclude(activity__school_id__isnull=True)
            .values("activity__school_id")
            .annotate(s=Sum("amount"))
        )
        for row in lines:
            rname = region_map.get(row["activity__school_id"])
            if rname:
                by_region[rname] = by_region.get(rname, 0) + int(row["s"] or 0)
        total = sum(by_region.values()) or 1
        school_by_region: dict[str, int] = {}
        for sid, rname in region_map.items():
            school_by_region[rname] = school_by_region.get(rname, 0) + 1
        total_schools = sum(school_by_region.values()) or 1
        funding = []
        for rname, amt in sorted(by_region.items(), key=lambda kv: -kv[1]):
            share = round(amt / total * 100)
            school_share = round(school_by_region.get(rname, 0) / total_schools * 100)
            flag = ""
            if share - school_share >= 15:
                flag = "over-funded vs footprint"
            elif school_share - share >= 15:
                flag = "under-funded vs footprint"
            funding.append(
                {
                    "region": rname,
                    "amt": _ugx_compact(amt),
                    "share": share,
                    "flag": flag,
                }
            )
        month_start = date.today().replace(day=1)
        new_schools = (
            acts.filter(status__in=COMPLETED_STATUSES, planned_date__gte=month_start)
            .exclude(school_id__isnull=True)
            .values("school_id")
            .distinct()
            .count()
        )
        learners = int(
            School.objects.filter(id__in=reached).aggregate(s=Sum("enrollment"))["s"]
            or 0
        )
        cost_per_school = _ugx_compact(round(total / max(1, len(reached))))
        return {
            "funding": funding,
            "schools_reached": len(reached),
            "new_schools_month": new_schools,
            "learners": learners,
            "cost_per_school": cost_per_school,
            "total": _ugx_compact(total if by_region else 0),
        }

    # ── §24 operational risks ────────────────────────────────────────────────
    @staticmethod
    def operational_risks(cd, acts, awaiting, projects):
        cards = [c for c in CDAnalyticsService.operational_risk(cd, acts) if c["count"]]
        stale = [
            b
            for b in awaiting
            if b.submitted_at and (timezone.now() - b.submitted_at).days > 7
        ]
        if stale:
            cards.append(
                {
                    "label": "Country Budget Approval Delayed",
                    "count": len(stale),
                    "tone": "danger",
                    "aging": "7+ days",
                    "link": "#rvp-approvals",
                }
            )
        weak = sum(
            1
            for p in projects
            if p["impact"] in ("Negative Impact", "No Measurable Impact")
        )
        if weak:
            cards.append(
                {
                    "label": "Projects Underperforming",
                    "count": weak,
                    "tone": "warning",
                    "aging": "",
                    "link": "#special-projects",
                }
            )
        return cards[:8]

    # ── §26 recommended next actions ─────────────────────────────────────────
    @staticmethod
    def recommended_actions(
        awaiting, annual_pending, high_risk_regions, under_review, notes
    ):
        out = []
        if awaiting.count():
            out.append(
                {
                    "label": f"Approve {awaiting.count()} pending monthly "
                    f"budget{'s' if awaiting.count() != 1 else ''}",
                    "priority": "high",
                    "url": "#rvp-approvals",
                }
            )
        if annual_pending.count():
            out.append(
                {
                    "label": f"Review {annual_pending.count()} annual budget "
                    "submission(s)",
                    "priority": "high",
                    "url": "#rvp-approvals",
                }
            )
        if high_risk_regions:
            out.append(
                {
                    "label": f"Review {len(high_risk_regions)} high-risk "
                    f"region{'s' if len(high_risk_regions) != 1 else ''}",
                    "priority": "high",
                    "url": "#region-ranking",
                }
            )
        if under_review:
            out.append(
                {
                    "label": f"Evaluate {len(under_review)} special "
                    f"project{'s' if len(under_review) != 1 else ''}",
                    "priority": "medium",
                    "url": "#special-projects",
                }
            )
        open_notes = [n for n in notes if n.status == "open"]
        if open_notes:
            out.append(
                {
                    "label": f"Follow up {len(open_notes)} open strategy "
                    f"note{'s' if len(open_notes) != 1 else ''}",
                    "priority": "medium",
                    "url": "#strategy-notes",
                }
            )
        return out[:6]

    # ── row shapers ──────────────────────────────────────────────────────────
    @staticmethod
    def _budget_row(b):
        return {
            "id": b.id,
            "month": b.month_key,
            "program": _ugx_compact(int(b.program_total or 0)),
            "admin": _ugx_compact(int(b.admin_total or 0)),
            "total": _ugx_compact(int(b.total_amount or 0)),
            "activities": b.activity_count,
            "status": b.get_status_display(),
            "status_key": b.status,
            "submitted": b.submitted_at,
        }

    @staticmethod
    def _annual_row(b):
        return {
            "id": b.id,
            "fy": b.fy,
            "total": _ugx_compact(int(b.total_amount or 0)),
            "program": _ugx_compact(int(b.program_total or 0)),
            "admin": _ugx_compact(int(b.admin_total or 0)),
            "projects": _ugx_compact(int(b.special_project_total or 0)),
            "status": b.get_status_display(),
            "status_key": b.status,
            "locked": b.baseline_locked_at is not None,
        }
