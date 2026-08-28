from apps.core.metrics import render_precomputed_metric_item
from apps.core.activity_types import COMPLETED_WORK_STATUSES
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Avg, Count, Sum
from django.utils import timezone

from apps.activities.models import Activity
from apps.clusters.models import Cluster, SchoolClusterAssignment
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.command_center.planning_progress import (
    PERIOD_DESCRIPTION,
    normalise_period,
    series as planning_progress_series,
    tabs as planning_progress_tabs,
)
from apps.fund_requests.models import WeeklyFundRequest
from apps.partners.models import Partner
from apps.ssa.models import SsaScore


def _ugx_compact_top(val):
    """Compact UGX formatting (mirrors budget_views.format_ugx_compact)."""
    if not val:
        return "UGX 0"
    if val >= 1_000_000_000:
        return f"UGX {val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"UGX {val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"UGX {val / 1_000:.0f}K"
    return f"UGX {val}"


class DashboardMetricsService:
    @staticmethod
    def get_dashboard_metrics(user, progress_period: str = "week"):
        fy = get_operational_fy()
        today = date.today()
        progress_period = normalise_period(progress_period)

        # Resolve scoping
        from apps.analytics.services import _scoped_schools

        schools_qs, scope = _scoped_schools(user)
        total_schools = schools_qs.count()

        # 1. KPI Cards calculations
        ready_count = schools_qs.exclude(
            planning_readiness__in=["requires_cluster", "data_cleanup_required"]
        ).count()
        ready_pct = round(ready_count / total_schools * 100) if total_schools > 0 else 0

        without_ssa_count = schools_qs.exclude(current_fy_ssa_status="done").count()
        without_ssa_pct = (
            round(without_ssa_count / total_schools * 100) if total_schools > 0 else 0
        )

        # Scope filter for activities
        activities_qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
        if not scope.country_scope:
            if scope.staff_ids:
                activities_qs = activities_qs.filter(
                    responsible_staff_id__in=scope.staff_ids
                )
            elif scope.partner_ids:
                activities_qs = activities_qs.filter(
                    assigned_partner_id__in=scope.partner_ids
                )
            else:
                activities_qs = activities_qs.none()

        start_week = today - timedelta(days=today.weekday())
        end_week = start_week + timedelta(days=6)
        activities_this_week = activities_qs.filter(
            scheduled_date__date__range=[start_week, end_week]
        ).count()

        start_month = today.replace(day=1)
        if today.month == 12:
            end_month = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_month = date(today.year, today.month + 1, 1) - timedelta(days=1)
        activities_this_month = activities_qs.filter(
            scheduled_date__date__range=[start_month, end_month]
        ).count()

        partner_pending_count = (
            schools_qs.filter(planning_readiness="ready_for_support_planning")
            .exclude(activities__delivery_type="partner", activities__fy=fy)
            .distinct()
            .count()
        )

        # Fund requests pending
        fund_requests_pending = WeeklyFundRequest.objects.filter(
            status__in=["submitted_to_pl", "submitted_to_cd"]
        ).count()

        # The local ["completed", "ia_verified"] pair silently excluded `closed`
        # and `accountant_confirmed`. Both sets happen to agree on today's data,
        # so no number moves -- but the moment work reaches those two statuses
        # the old filter would have stopped counting finished work, which is the
        # regression apps/core/activity_types.py exists to prevent.
        completed_this_month = activities_qs.filter(
            status__in=COMPLETED_WORK_STATUSES,
            scheduled_date__date__range=[start_month, end_month],
        ).count()
        # No fabricated fallback: nothing planned this month is an honest 0%,
        # never an invented number.
        target_achievement = (
            round(completed_this_month / activities_this_month * 100)
            if activities_this_month > 0
            else 0
        )

        # 2. Signal Strips
        needs_attention = schools_qs.filter(
            planning_readiness__in=["requires_cluster", "data_cleanup_required"]
        ).count()
        ready_for_action = schools_qs.exclude(
            planning_readiness__in=["requires_cluster", "data_cleanup_required"]
        ).count()
        # Real composite, not a fabricated constant: school planning readiness
        # and this-month activity delivery are the two workstream health
        # signals already computed above -- simple average of the two.
        operational_health = round((ready_pct + target_achievement) / 2)

        # 3. Today's Priorities
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        priorities_qs = (
            activities_qs.filter(scheduled_date__range=[today_start, today_end])
            .select_related("school")
            .order_by("scheduled_date")[:6]
        )

        priorities = []
        for act in priorities_qs:
            status_label = "Scheduled"
            status_class = "s-blue"
            if act.status == "completed":
                status_label = "Completed"
                status_class = "s-green"
            elif act.status in ("in_progress", "completion_started"):
                status_label = "Started"
                status_class = "s-orange"

            priorities.append(
                {
                    "activity": f"{act.activity_type.replace('_', ' ').title()}",
                    "time": act.scheduled_date.strftime("%I:%M %p")
                    if act.scheduled_date
                    else "—",
                    "related_to": act.school.name if act.school else "—",
                    "status": status_label,
                    "status_class": status_class,
                }
            )

        # 4. Planning Progress over the selected period (week/month/quarter/FY).
        #
        # The card's four period tabs were decorative <span>s; the series is now
        # built for whichever one is chosen. Deliberately built from a queryset
        # that is NOT filtered to a single financial year -- the FY view spans
        # three, and an fy-filtered queryset would report two empty years beside
        # the current one. See apps/command_center/planning_progress.py.
        progress_qs = Activity.objects.filter(deleted_at__isnull=True)
        if not scope.country_scope:
            if scope.staff_ids:
                progress_qs = progress_qs.filter(
                    responsible_staff_id__in=scope.staff_ids
                )
            elif scope.partner_ids:
                progress_qs = progress_qs.filter(
                    assigned_partner_id__in=scope.partner_ids
                )
            else:
                progress_qs = progress_qs.none()

        weekly_progress = planning_progress_series(progress_qs, progress_period, today)

        # 5. SSA Interventions Performance
        ssa_averages = (
            SsaScore.objects.filter(
                ssa_record__verification_status="confirmed",
                ssa_record__deleted_at__isnull=True,
            )
            .values("intervention")
            .annotate(avg_val=Avg("score"))
            .order_by("-avg_val")
        )

        interv_map = dict(SsaIntervention.choices)
        best_interventions = []
        weakest_interventions = []

        for item in ssa_averages:
            code = item["intervention"]
            label = interv_map.get(code, code)
            score = round(item["avg_val"], 1)
            percentage = min(
                100, round(item["avg_val"] / 10.0 * 100)
            )  # SSA scores are 0-10

            data_row = {"name": label, "score": score, "percentage": percentage}
            if len(best_interventions) < 3:
                best_interventions.append(data_row)
            else:
                weakest_interventions.append(data_row)

        # No verified SSA data -> empty lists (template sections render empty,
        # never invented interventions).
        #
        # ssa_averages is ordered by -avg_val (BEST first), so after the top 3
        # are taken as `best_interventions` the remainder is still in
        # descending order. Slicing [:3] therefore returned the 4th/5th/6th
        # BEST interventions and labelled them "Weakest" on the dashboard,
        # while the two genuinely lowest-scoring interventions were never
        # shown at all. Take the tail and reverse it so this panel actually
        # lists the worst performers, worst first.
        weakest_interventions = list(reversed(weakest_interventions[-3:]))

        # 6. Team Target Progress — real completion rate per horizon.
        def _target_row(name, qs):
            total = qs.count()
            # Canonical set: the local triple here omitted `accountant_confirmed`,
            # so work that reached the accountant stopped counting as done.
            done = qs.filter(status__in=COMPLETED_WORK_STATUSES).count()
            pct = round(done * 100 / total) if total else 0
            if pct >= 60:
                status, cls, color = "On track", "s-green", "var(--green)"
            elif pct >= 40:
                status, cls, color = "At risk", "s-orange", "var(--orange)"
            else:
                status, cls, color = "Behind", "s-red", "var(--red)"
            return {
                "name": name,
                "percentage": pct,
                "status": status,
                "class": cls,
                "color": color,
            }

        current_quarter = get_quarter_for_date(today)
        team_targets = [
            _target_row(
                "Monthly Target", activities_qs.filter(planned_month=today.month)
            ),
            _target_row(
                "Quarterly Target", activities_qs.filter(quarter=current_quarter)
            ),
            _target_row("FY Target", activities_qs),
        ]

        # 7. Priority Schools Table
        #
        # This used to be alphabetical order presented as prioritisation:
        # schools without a done SSA, ordered by name, padded to five with any
        # ready school, and a hardcoded em-dash in the column headed "weakest".
        # Nothing about it was a priority and nothing filled the one field a
        # reader would act on.
        #
        # It now reads the live SSA recommendation queue, which ranks by
        # measured weakness and carries its own explanation. Schools with no
        # confirmed assessment still appear — they are genuinely a priority —
        # but as their own honest category, because "we do not know yet" is a
        # different problem from "we know, and it is bad".
        from apps.ssa.recommendation_service import open_recommendations

        school_ids = list(schools_qs.values_list("id", flat=True))
        priority_schools = []
        seen_schools: set[str] = set()

        for recommendation in open_recommendations(school_ids=school_ids, fy=fy)[:5]:
            school = recommendation.school
            seen_schools.add(school.id)
            band = (recommendation.score_band or "").lower()
            priority_schools.append(
                {
                    "school_id": school.school_id,
                    "name": school.name,
                    "district": school.district.name if school.district else "—",
                    "cluster": school.cluster_id or "—",
                    "weakest": recommendation.get_intervention_display(),
                    "readiness": recommendation.score_band or "Assessed",
                    "readiness_class": (
                        "s-red"
                        if band == "critical"
                        else "s-orange"
                        if band == "warning"
                        else "s-green"
                    ),
                    "action": "Plan support",
                    "reason": recommendation.reason,
                }
            )

        # Unassessed schools: the SSA-collection visit is what resolves them,
        # and that is exactly the visit the platform allows without an SSA.
        if len(priority_schools) < 5:
            unassessed = (
                schools_qs.exclude(current_fy_ssa_status="done")
                .exclude(id__in=seen_schools)
                .select_related("district")
                .order_by("name")[: 5 - len(priority_schools)]
            )
            for school in unassessed:
                priority_schools.append(
                    {
                        "school_id": school.school_id,
                        "name": school.name,
                        "district": school.district.name if school.district else "—",
                        "cluster": school.cluster_id or "—",
                        "weakest": "Not assessed",
                        "readiness": "No SSA",
                        "readiness_class": "s-orange",
                        "action": "Collect SSA",
                        "reason": (
                            "No confirmed assessment this year, so no need has "
                            "been measured yet."
                        ),
                    }
                )

        # 8. Cluster Performance Table — real per-cluster aggregates (empty when
        # no clusters exist; the section renders empty rather than invented rows).
        from apps.ssa.models import SsaRecord

        clusters = list(Cluster.objects.filter(deleted_at__isnull=True)[:5])
        cluster_ids = [c.id for c in clusters]

        # Five clusters used to mean five school-id reads, five SSA averages and
        # ten activity COUNTs -- twenty round trips for one five-row table. Each
        # of those is now a single grouped query over all five clusters.
        schools_by_cluster: dict[str, list[str]] = defaultdict(list)
        for cluster_id, school_id in SchoolClusterAssignment.objects.filter(
            cluster_id__in=cluster_ids
        ).values_list("cluster_id", "school_id"):
            schools_by_cluster[cluster_id].append(school_id)

        all_school_ids = [s for ids in schools_by_cluster.values() for s in ids]
        # Sum and count per school, not the per-school average: the figure this
        # replaces was AVG over *every* record for the cluster's schools, and a
        # mean of school means is a different number whenever schools hold
        # unequal record counts. Carrying sum and count lets the cluster average
        # be recombined exactly.
        ssa_totals_by_school = {
            school_id: (total or 0, count)
            for school_id, total, count in SsaRecord.objects.filter(
                school_id__in=all_school_ids, fy=fy, deleted_at__isnull=True
            )
            .values_list("school_id")
            .annotate(total=Sum("average_score"), count=Count("id"))
        }

        activity_counts: dict[tuple[str, str], int] = {}
        for cluster_id, activity_type, total in (
            activities_qs.filter(cluster_id__in=cluster_ids)
            .values_list("cluster_id", "activity_type")
            .annotate(n=Count("id"))
        ):
            activity_counts[(cluster_id, activity_type)] = total

        cluster_performance = []
        for c in clusters:
            school_ids = schools_by_cluster.get(c.id, [])
            score_total = sum(
                ssa_totals_by_school.get(s, (0, 0))[0] for s in school_ids
            )
            score_count = sum(
                ssa_totals_by_school.get(s, (0, 0))[1] for s in school_ids
            )
            avg_ssa = (score_total / score_count) if score_count else None
            mtgs = sum(
                activity_counts.get((c.id, t), 0)
                for t in ("cluster_meeting", "cluster_meeting_ssa_review")
            )
            trainings = sum(
                activity_counts.get((c.id, t), 0)
                for t in (
                    "cluster_training",
                    "cluster_training_ssa_collection",
                    "core_training",
                )
            )
            good = avg_ssa is not None and avg_ssa >= 5
            cluster_performance.append(
                {
                    "name": c.name,
                    "avg_ssa": round(avg_ssa, 1) if avg_ssa is not None else "—",
                    "trend": "",
                    "mtgs": mtgs,
                    "trainings": trainings,
                    "status": "Good"
                    if good
                    else ("Attention" if avg_ssa is not None else "No SSA"),
                    "status_class": "s-green" if good else "s-orange",
                }
            )

        # 9. Support Overview (mock values from database aggregations)
        support_overview = {
            "assigned_partners": Partner.objects.filter(
                deleted_at__isnull=True, active_status=True
            ).count(),
            "planned_visits": activities_this_month,
            "evidence_pending": activities_qs.filter(
                status__in=COMPLETED_WORK_STATUSES, evidence__isnull=True
            ).count(),
            "payments_due": _ugx_compact_top(
                WeeklyFundRequest.objects.filter(
                    fy=fy,
                    status="confirmed_for_advance",
                ).aggregate(s=Sum("total_amount"))["s"]
                or 0
            ),
        }

        # 10. Budget snapshot — real scheduled-budget sums from cost lines.
        from apps.activities.models import ActivityScheduleCostLine

        _lines = ActivityScheduleCostLine.objects.filter(
            fiscal_year=fy, activity__deleted_at__isnull=True
        ).exclude(activity__status="cancelled")
        budget_snapshot = {
            "week": _ugx_compact_top(
                _lines.filter(
                    planned_date__gte=start_week,
                    planned_date__lte=start_week + timedelta(days=6),
                ).aggregate(s=Sum("amount"))["s"]
                or 0
            ),
            "month": _ugx_compact_top(
                _lines.filter(month=today.month).aggregate(s=Sum("amount"))["s"] or 0
            ),
            "quarter": _ugx_compact_top(
                _lines.filter(quarter=get_quarter_for_date(today)).aggregate(
                    s=Sum("amount")
                )["s"]
                or 0
            ),
            "fy": _ugx_compact_top(_lines.aggregate(s=Sum("amount"))["s"] or 0),
        }

        # 11. Execution Summary — real counts per horizon (previously month×3/×12).
        execution_summary = {
            "week": activities_this_week,
            "month": activities_this_month,
            "quarter": activities_qs.filter(
                quarter=get_quarter_for_date(today)
            ).count(),
            "fy": activities_qs.count(),
        }

        # 11b. Attention Needed — real counts only; empty list when clean.
        attention_items = []
        if without_ssa_count:
            attention_items.append(
                {
                    "icon": "⚠",
                    "cls": "red-bg",
                    "title": f"{without_ssa_count} schools",
                    "detail": "Missing a verified SSA this year",
                    "href": "/ssa",
                }
            )
        _fund_pending = WeeklyFundRequest.objects.filter(
            fy=fy, status__startswith="submitted"
        ).count()
        if _fund_pending:
            attention_items.append(
                {
                    "icon": "◉",
                    "cls": "orange-bg",
                    "title": f"{_fund_pending} fund requests",
                    "detail": "Awaiting approval",
                    "href": "/fund-requests/weekly",
                }
            )
        _evidence_pending = activities_qs.filter(
            status__in=COMPLETED_WORK_STATUSES, evidence__isnull=True
        ).count()
        if _evidence_pending:
            attention_items.append(
                {
                    "icon": "◫",
                    "cls": "purple-bg",
                    "title": f"{_evidence_pending} evidence submissions",
                    "detail": "Not yet uploaded",
                    "href": "/evidence/",
                }
            )

        # 11c. Next Recommended Action — derived from the same real counts as
        # Attention Needed above (highest-priority open item), never a
        # hardcoded suggestion. None when there is genuinely nothing to act on
        # (honest empty state, no fabricated fallback).
        recommended_action = None
        if _fund_pending:
            recommended_action = {
                "title": "Confirm pending fund request"
                + ("s" if _fund_pending > 1 else ""),
                "detail": f"{_fund_pending} weekly fund request"
                + ("s" if _fund_pending > 1 else "")
                + " awaiting approval.",
                "cta_label": "Review Fund Requests",
                "cta_href": "/fund-requests/weekly",
            }
        elif without_ssa_count:
            recommended_action = {
                "title": "Close the SSA coverage gap",
                "detail": f"{without_ssa_count} school"
                + ("s" if without_ssa_count > 1 else "")
                + " missing a verified SSA this year.",
                "cta_label": "Go to SSA",
                "cta_href": "/ssa",
            }
        elif _evidence_pending:
            recommended_action = {
                "title": "Upload outstanding evidence",
                "detail": f"{_evidence_pending} completed activit"
                + ("ies" if _evidence_pending > 1 else "y")
                + " still need evidence.",
                "cta_label": "Go to Evidence",
                "cta_href": "/evidence/",
            }

        # 12. Right Rail - Upcoming activities today
        upcoming_today_qs = activities_qs.filter(
            scheduled_date__range=[today_start, today_end]
        ).select_related("school")[:3]
        upcoming_today = []
        for act in upcoming_today_qs:
            upcoming_today.append(
                {
                    "type": "school"
                    if act.activity_type == "school_visit"
                    else "training",
                    "type_class": "blue-bg"
                    if act.activity_type == "school_visit"
                    else "purple-bg",
                    "icon": "🏫" if act.activity_type == "school_visit" else "🎓",
                    "time": act.scheduled_date.strftime("%I:%M %p")
                    if act.scheduled_date
                    else "—",
                    "title": act.school.name if act.school else "Cluster Activity",
                    "desc": act.focus_intervention.replace("_", " ").title()
                    if act.focus_intervention
                    else "General Coaching",
                    "info": f"{act.school.district.name if act.school and act.school.district else 'Kigan District'} • {user.name}",
                }
            )

        # No fabricated fallback: an empty agenda renders an empty state.

        # Build standard KPI strip items list based on active role
        kpi_items = []
        role = getattr(user, "active_role", None)

        if role == "CCEO":
            kpi_items = [
                render_precomputed_metric_item(
                    "command_center_dashboard_service_my_target_achievement",
                    f"{target_achievement}%",
                    raw_value=target_achievement,
                    helper="completed vs scheduled",
                    icon="target",
                    variant="success",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_planned_this_week",
                    str(activities_this_week),
                    raw_value=activities_this_week,
                    helper="scheduled",
                    icon="calendar",
                    variant="info",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_schools_visited",
                    str(ready_count),
                    raw_value=ready_count,
                    helper="visited",
                    icon="school",
                    variant="blue",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_evidence_pending",
                    str(without_ssa_count),
                    raw_value=without_ssa_count,
                    helper="needing uploads",
                    icon="warning",
                    variant="warning",
                ),
            ]
        elif role == "Program Lead":
            # Reuse the canonical PL team-execution formula (same source as
            # the PL Analytics "Team Execution Progress %" card) instead of
            # a locally-derived number under a label reserved for it, and a
            # fabricated CCEOs-On-Track count.
            from apps.analytics.pl_analytics_service import (
                PLAnalyticsService,
                resolve_pl_scope,
            )

            pl_scope = resolve_pl_scope(user)
            team_execution_pct, cceos_on_track = PLAnalyticsService._team_target(
                pl_scope, fy, current_quarter
            )
            kpi_items = [
                render_precomputed_metric_item(
                    "command_center_dashboard_service_team_execution_progress",
                    f"{team_execution_pct}%",
                    raw_value=team_execution_pct,
                    helper="field completions vs target (not IA-verified)",
                    icon="target",
                    variant="success",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_cceos_on_track",
                    f"{cceos_on_track} / {len(pl_scope.cceos)}",
                    raw_value=cceos_on_track,
                    helper="at or above pace",
                    icon="users",
                    variant="info",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_pending_reviews",
                    str(fund_requests_pending),
                    raw_value=fund_requests_pending,
                    helper="awaiting PL",
                    icon="clock",
                    variant="warning",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_scheduled_this_week",
                    str(activities_this_week),
                    raw_value=activities_this_week,
                    helper="across team",
                    icon="calendar",
                    variant="blue",
                ),
            ]
        elif role in ["CountryDirector", "RegionalVicePresident", "Admin"]:
            # Real country-wide disbursed/approved utilization for the FY
            # (same disbursed/approved ratio as PLAnalyticsService._budget_utilization,
            # applied without a per-PL user filter since this KPI is country-scoped).
            country_fy_requests = WeeklyFundRequest.objects.filter(fy=fy)
            country_approved = (
                country_fy_requests.filter(
                    status__in=["confirmed_for_advance", "disbursed", "accounted"]
                ).aggregate(Sum("total_amount"))["total_amount__sum"]
                or 0
            )
            country_disbursed = (
                country_fy_requests.filter(
                    status__in=["disbursed", "accounted"]
                ).aggregate(Sum("disbursed_amount"))["disbursed_amount__sum"]
                or 0
            )
            budget_utilization_pct = (
                round(country_disbursed / country_approved * 100)
                if country_approved
                else 0
            )
            # "Schools Impacted" was bound to `total_schools` -- every school in
            # scope -- under the helper "total reached". On the seed that read
            # 702 where 261 schools had any completed work, so a leadership
            # dashboard overstated reach by the entire un-worked portfolio.
            # AnalyticsDashboardService already publishes this metric as
            # distinct reached schools; this now means the same thing, so the
            # two pages stop disagreeing under one label.
            schools_impacted = (
                activities_qs.filter(status__in=COMPLETED_WORK_STATUSES)
                .exclude(school_id__isnull=True)
                .values("school_id")
                .distinct()
                .count()
            )
            kpi_items = [
                render_precomputed_metric_item(
                    "command_center_dashboard_service_country_activities_completed_this_month",
                    f"{target_achievement}%",
                    raw_value=target_achievement,
                    helper=f"{completed_this_month:,} of "
                    f"{activities_this_month:,} scheduled this month",
                    icon="target",
                    variant="success",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_budget_utilization",
                    f"{budget_utilization_pct}%",
                    raw_value=budget_utilization_pct,
                    helper="disbursed / approved",
                    icon="currency",
                    variant="finance",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_schools_impacted",
                    str(schools_impacted),
                    raw_value=schools_impacted,
                    helper=f"reached, of {total_schools:,} in scope",
                    icon="school",
                    variant="blue",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_pending_approvals",
                    str(fund_requests_pending),
                    raw_value=fund_requests_pending,
                    helper="needs action",
                    icon="warning",
                    variant="warning",
                ),
            ]
        elif role == "Accountant":
            # Real FY aggregates from WeeklyFundRequest (mirrors
            # apps/frontend/views/finance_operating_views.accountant_dashboard_view).
            def _ugx_compact(val):
                if not val:
                    return "UGX 0"
                if val >= 1_000_000_000:
                    return f"UGX {val / 1_000_000_000:.1f}B"
                if val >= 1_000_000:
                    return f"UGX {val / 1_000_000:.1f}M"
                if val >= 1_000:
                    return f"UGX {val / 1_000:.0f}K"
                return f"UGX {val}"

            fy_requests = WeeklyFundRequest.objects.filter(fy=fy)
            total_allocation = (
                fy_requests.filter(
                    status__in=[
                        "confirmed_for_advance",
                        "disbursed",
                        "accounted",
                    ]
                ).aggregate(Sum("total_amount"))["total_amount__sum"]
                or 0
            )
            pending_clearance = (
                fy_requests.filter(status="disbursed").aggregate(
                    Sum("disbursed_amount")
                )["disbursed_amount__sum"]
                or 0
            )
            cleared_amount = (
                fy_requests.aggregate(Sum("accounted_amount"))["accounted_amount__sum"]
                or 0
            )

            kpi_items = [
                render_precomputed_metric_item(
                    "command_center_dashboard_service_total_allocation",
                    _ugx_compact(total_allocation),
                    raw_value=total_allocation,
                    helper="approved current FY",
                    icon="currency",
                    variant="finance",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_pending_clearance",
                    _ugx_compact(pending_clearance),
                    raw_value=pending_clearance,
                    helper="advances",
                    icon="clock",
                    variant="warning",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_cleared_amount",
                    _ugx_compact(cleared_amount),
                    raw_value=cleared_amount,
                    helper="accounted",
                    icon="check",
                    variant="success",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_planned_activities",
                    str(activities_this_month),
                    raw_value=activities_this_month,
                    helper="this month",
                    icon="calendar",
                    variant="info",
                ),
            ]
        else:
            kpi_items = [
                render_precomputed_metric_item(
                    "command_center_dashboard_service_schools_ready_for_planning",
                    str(ready_count),
                    raw_value=ready_count,
                    helper=f"{ready_pct}% of total",
                    icon="school",
                    variant="success",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_schools_without_ssa",
                    str(without_ssa_count),
                    raw_value=without_ssa_count,
                    helper=f"{without_ssa_pct}% of total",
                    icon="warning",
                    variant="danger",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_activities_this_week",
                    str(activities_this_week),
                    raw_value=activities_this_week,
                    helper="scheduled",
                    icon="calendar",
                    variant="info",
                ),
                render_precomputed_metric_item(
                    "command_center_dashboard_service_planned_this_month",
                    str(activities_this_month),
                    raw_value=activities_this_month,
                    helper="scheduled",
                    icon="chart",
                    variant="blue",
                ),
            ]

        return {
            "kpi_strip_items": kpi_items,
            "kpis": {
                "ready": ready_count,
                "ready_pct": ready_pct,
                "without_ssa": without_ssa_count,
                "without_ssa_pct": without_ssa_pct,
                "week_activities": activities_this_week,
                "month_activities": activities_this_month,
                "partner_pending": partner_pending_count,
                "fund_requests_pending": fund_requests_pending,
                "target_achievement": target_achievement,
            },
            "signals": {
                "needs_attention": needs_attention,
                "ready_for_action": ready_for_action,
                "operational_health": operational_health,
            },
            "priorities": priorities,
            "attention_items": attention_items,
            "recommended_action": recommended_action,
            "weekly_progress": weekly_progress,
            "progress_period": progress_period,
            "progress_tabs": planning_progress_tabs(progress_period),
            "progress_description": PERIOD_DESCRIPTION[progress_period],
            "best_interventions": best_interventions,
            "weakest_interventions": weakest_interventions,
            "team_targets": team_targets,
            "priority_schools": priority_schools,
            "cluster_performance": cluster_performance,
            "support_overview": support_overview,
            "budget_snapshot": budget_snapshot,
            "execution_summary": execution_summary,
            "upcoming_today": upcoming_today,
        }
