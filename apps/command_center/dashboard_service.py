from django.db.models import Avg, Sum
from datetime import date, timedelta
from django.utils import timezone
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.clusters.models import Cluster
from apps.activities.models import Activity
from apps.fund_requests.models import WeeklyFundRequest
from apps.partners.models import Partner
from apps.ssa.models import SsaRecord, SsaScore
from apps.core.enums import SsaIntervention

COMPLETED_STATUSES = ["completed", "ia_verified"]

# WeeklyFundRequest statuses that mean "awaiting someone's action".
WFR_PENDING_STATUSES = ["pending_responsible_confirmation", "confirmed_for_advance"]


def _ugx_compact(val):
    """Format an integer UGX amount compactly (e.g. UGX 2.4B / 186.4M / 65K)."""
    if not val:
        return "UGX 0"
    if val >= 1_000_000_000:
        return f"UGX {val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"UGX {val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"UGX {val / 1_000:.0f}K"
    return f"UGX {val:,}"


def _ssa_status(avg):
    """Canonical SSA severity bands: 0-4 Critical / 5-6 Support / 7-8 Good / 9-10 Strong."""
    if avg is None:
        return "No data", "s-orange"
    if avg < 5:
        return "Critical", "s-red"
    if avg < 7:
        return "Support", "s-orange"
    if avg < 9:
        return "Good", "s-green"
    return "Strong", "s-green"


def _target_status(pct):
    if pct >= 70:
        return "On track", "s-green", "var(--green)"
    if pct >= 40:
        return "At risk", "s-orange", "var(--orange)"
    return "Behind", "s-red", "var(--red)"


class DashboardMetricsService:
    @staticmethod
    def get_dashboard_metrics(user):
        fy = get_operational_fy()
        today = date.today()

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

        quarter = get_quarter_for_date(today)
        quarter_key = getattr(quarter, "value", quarter)
        activities_this_quarter = activities_qs.filter(quarter=quarter_key).count()
        activities_this_fy = activities_qs.count()

        partner_pending_count = (
            schools_qs.filter(planning_readiness="ready_for_support_planning")
            .exclude(activities__delivery_type="partner", activities__fy=fy)
            .distinct()
            .count()
        )

        # Fund requests awaiting action (confirmation or disbursement)
        fund_requests_pending = WeeklyFundRequest.objects.filter(
            fy=fy, status__in=WFR_PENDING_STATUSES
        ).count()

        completed_this_month = activities_qs.filter(
            status__in=COMPLETED_STATUSES,
            scheduled_date__date__range=[start_month, end_month],
        ).count()
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
        operational_health = (
            round(ready_for_action / total_schools * 100) if total_schools > 0 else 0
        )

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
            elif act.status == "started":
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

        # 4. Weekly Planning Progress — completed vs scheduled per week, last 5 weeks (live)
        weekly_progress = []
        for wk_offset in range(4, -1, -1):
            ws = start_week - timedelta(weeks=wk_offset)
            we = ws + timedelta(days=6)
            wk_qs = activities_qs.filter(scheduled_date__date__range=[ws, we])
            scheduled_n = wk_qs.count()
            completed_n = wk_qs.filter(status__in=COMPLETED_STATUSES).count()
            pct = round(completed_n / scheduled_n * 100) if scheduled_n else 0
            weekly_progress.append({"week": ws.strftime("%b %d"), "percentage": pct})

        # 5. SSA Interventions Performance (scores are 0–10; scoped to the caller's schools)
        ssa_averages = list(
            SsaScore.objects.filter(
                ssa_record__school__in=schools_qs,
                ssa_record__verification_status="confirmed",
                ssa_record__deleted_at__isnull=True,
            )
            .values("intervention")
            .annotate(avg_val=Avg("score"))
            .order_by("-avg_val")
        )

        interv_map = dict(SsaIntervention.choices)
        rows = []
        for item in ssa_averages:
            rows.append(
                {
                    "name": interv_map.get(item["intervention"], item["intervention"]),
                    "score": round(item["avg_val"], 1),
                    "percentage": round(item["avg_val"] / 10.0 * 100),
                }
            )
        best_interventions = rows[:3]
        weakest_interventions = [
            r for r in reversed(rows) if r not in best_interventions
        ][:3]

        # 6. Team Target Progress — completed vs scheduled per period (live)
        completed_this_quarter = activities_qs.filter(
            quarter=quarter_key, status__in=COMPLETED_STATUSES
        ).count()
        completed_this_fy = activities_qs.filter(status__in=COMPLETED_STATUSES).count()
        team_targets = []
        for name, done, planned in [
            ("Monthly Target", completed_this_month, activities_this_month),
            ("Quarterly Target", completed_this_quarter, activities_this_quarter),
            ("FY Target", completed_this_fy, activities_this_fy),
        ]:
            pct = round(done / planned * 100) if planned else 0
            status, cls, color = _target_status(pct)
            team_targets.append(
                {
                    "name": name,
                    "percentage": pct,
                    "status": status,
                    "class": cls,
                    "color": color,
                }
            )

        # 7. Priority Schools Table — weakest intervention computed from live SSA scores
        priority_schools_qs = list(
            schools_qs.exclude(current_fy_ssa_status="done")
            .select_related("district")
            .order_by("name")[:5]
        )
        ready_extra = []
        if len(priority_schools_qs) < 5:
            ready_extra = list(
                schools_qs.filter(
                    planning_readiness="ready_for_support_planning"
                ).select_related("district")[: 5 - len(priority_schools_qs)]
            )

        shown_ids = [s.id for s in priority_schools_qs + ready_extra]
        weakest_by_school = {}
        weakest_rows = (
            SsaScore.objects.filter(
                ssa_record__school_id__in=shown_ids,
                ssa_record__deleted_at__isnull=True,
            )
            .values("ssa_record__school_id", "intervention")
            .annotate(avg_val=Avg("score"))
        )
        for row in weakest_rows:
            sid = row["ssa_record__school_id"]
            cur = weakest_by_school.get(sid)
            if cur is None or row["avg_val"] < cur[1]:
                weakest_by_school[sid] = (
                    interv_map.get(row["intervention"], row["intervention"]),
                    row["avg_val"],
                )

        priority_schools = []
        for s in priority_schools_qs:
            priority_schools.append(
                {
                    "name": s.name,
                    "district": s.district.name if s.district else "—",
                    "cluster": s.cluster_id or "—",
                    "weakest": weakest_by_school.get(s.id, ("—",))[0],
                    "readiness": "At Risk",
                    "readiness_class": "s-orange",
                    "action": "Upload SSA",
                }
            )
        for s in ready_extra:
            priority_schools.append(
                {
                    "name": s.name,
                    "district": s.district.name if s.district else "—",
                    "cluster": s.cluster_id or "—",
                    "weakest": weakest_by_school.get(s.id, ("—",))[0],
                    "readiness": "Ready",
                    "readiness_class": "s-green",
                    "action": "Schedule Visit",
                }
            )

        # 8. Cluster Performance Table — live per-cluster SSA averages and activity counts
        clusters_qs = Cluster.objects.filter(deleted_at__isnull=True)[:5]
        cluster_performance = []
        for c in clusters_qs:
            member_ids = list(c.assignments.values_list("school_id", flat=True))
            avg = None
            if member_ids:
                avg = SsaRecord.objects.filter(
                    school_id__in=member_ids,
                    deleted_at__isnull=True,
                    verification_status="confirmed",
                ).aggregate(v=Avg("average_score"))["v"]
            status, status_class = _ssa_status(avg)
            cluster_performance.append(
                {
                    "name": c.name,
                    "avg_ssa": round(avg, 1) if avg is not None else "—",
                    "trend": "→",
                    "mtgs": c.activities.filter(
                        deleted_at__isnull=True, fy=fy, activity_type="cluster_meeting"
                    ).count(),
                    "trainings": c.activities.filter(
                        deleted_at__isnull=True, fy=fy, activity_type="cluster_training"
                    ).count(),
                    "status": status,
                    "status_class": status_class,
                }
            )

        # 9. Support Overview (live aggregations)
        payments_due_amount = sum(
            (w.total_amount or 0) - (w.disbursed_amount or 0)
            for w in WeeklyFundRequest.objects.filter(
                fy=fy, status="confirmed_for_advance"
            )
        )
        support_overview = {
            "assigned_partners": Partner.objects.filter(
                deleted_at__isnull=True, active_status=True
            ).count(),
            "planned_visits": activities_this_month,
            "evidence_pending": activities_qs.filter(
                status="completed", evidence__isnull=True
            ).count(),
            "payments_due": _ugx_compact(payments_due_amount),
        }
        evidence_pending_count = support_overview["evidence_pending"]

        # 10. Budget snapshot — summed from scheduled activities' cost lines (live)
        def _cost_sum(qs):
            return qs.aggregate(v=Sum("schedule_cost_lines__amount"))["v"] or 0

        budget_snapshot = {
            "week": _ugx_compact(
                _cost_sum(
                    activities_qs.filter(
                        scheduled_date__date__range=[start_week, end_week]
                    )
                )
            ),
            "month": _ugx_compact(
                _cost_sum(
                    activities_qs.filter(
                        scheduled_date__date__range=[start_month, end_month]
                    )
                )
            ),
            "quarter": _ugx_compact(
                _cost_sum(activities_qs.filter(quarter=quarter_key))
            ),
            "fy": _ugx_compact(_cost_sum(activities_qs)),
        }

        # 11. Execution Summary (live counts per period)
        execution_summary = {
            "week": activities_this_week,
            "month": activities_this_month,
            "quarter": activities_this_quarter,
            "fy": activities_this_fy,
        }

        # 12. Right Rail - Upcoming activities today (empty list -> template empty state)
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
                    "info": f"{act.school.district.name if act.school and act.school.district else '—'} • {user.name}",
                }
            )

        # Finance rollups reused by role KPI strips
        fy_wfr_qs = WeeklyFundRequest.objects.filter(fy=fy)
        wfr_confirmed_total = (
            fy_wfr_qs.filter(
                status__in=[
                    "confirmed_for_advance",
                    "disbursed",
                    "paid",
                    "closed",
                    "cleared",
                    "self_funded",
                    "self_funded_pending_reimbursement",
                ]
            ).aggregate(v=Sum("total_amount"))["v"]
            or 0
        )
        wfr_disbursed_total = fy_wfr_qs.aggregate(v=Sum("disbursed_amount"))["v"] or 0
        budget_util_pct = (
            round(wfr_disbursed_total / wfr_confirmed_total * 100)
            if wfr_confirmed_total
            else 0
        )

        schools_visited = (
            activities_qs.filter(status__in=COMPLETED_STATUSES, school__isnull=False)
            .values("school_id")
            .distinct()
            .count()
        )

        # Build standard KPI strip items list based on active role
        role = getattr(user, "active_role", None)

        if role == "CCEO":
            kpi_items = [
                {
                    "label": "My Target Achievement",
                    "value": f"{target_achievement}%",
                    "raw_value": target_achievement,
                    "helper": "completed vs scheduled",
                    "icon": "target",
                    "variant": "success",
                },
                {
                    "label": "Planned This Week",
                    "value": str(activities_this_week),
                    "raw_value": activities_this_week,
                    "helper": "scheduled",
                    "icon": "calendar",
                    "variant": "info",
                },
                {
                    "label": "Schools Visited",
                    "value": str(schools_visited),
                    "raw_value": schools_visited,
                    "helper": "this FY",
                    "icon": "school",
                    "variant": "blue",
                },
                {
                    "label": "Evidence Pending",
                    "value": str(evidence_pending_count),
                    "raw_value": evidence_pending_count,
                    "helper": "needing uploads",
                    "icon": "warning",
                    "variant": "warning",
                },
            ]
        elif role == "Program Lead":
            supervisee_count = 0
            profile = getattr(user, "staff_profile", None)
            if profile is not None:
                from apps.accounts.models import StaffSupervisorAssignment

                supervisee_count = StaffSupervisorAssignment.objects.filter(
                    supervisor=profile
                ).count()
            kpi_items = [
                {
                    "label": "Team Target Achievement",
                    "value": f"{target_achievement}%",
                    "raw_value": target_achievement,
                    "helper": "completed vs scheduled",
                    "icon": "target",
                    "variant": "success",
                },
                {
                    "label": "Supervised CCEOs",
                    "value": str(supervisee_count),
                    "raw_value": supervisee_count,
                    "helper": "active CCEOs",
                    "icon": "users",
                    "variant": "info",
                },
                {
                    "label": "Pending Fund Requests",
                    "value": str(fund_requests_pending),
                    "raw_value": fund_requests_pending,
                    "helper": "awaiting action",
                    "icon": "clock",
                    "variant": "warning",
                },
                {
                    "label": "Scheduled This Week",
                    "value": str(activities_this_week),
                    "raw_value": activities_this_week,
                    "helper": "across team",
                    "icon": "calendar",
                    "variant": "blue",
                },
            ]
        elif role in ["CountryDirector", "RegionalVicePresident", "Admin"]:
            kpi_items = [
                {
                    "label": "Country Target Achievement",
                    "value": f"{target_achievement}%",
                    "raw_value": target_achievement,
                    "helper": "completed vs scheduled",
                    "icon": "target",
                    "variant": "success",
                },
                {
                    "label": "Budget Utilization",
                    "value": f"{budget_util_pct}%",
                    "raw_value": budget_util_pct,
                    "helper": "disbursed vs confirmed",
                    "icon": "currency",
                    "variant": "finance",
                },
                {
                    "label": "Schools Impacted",
                    "value": str(total_schools),
                    "raw_value": total_schools,
                    "helper": "total reached",
                    "icon": "school",
                    "variant": "blue",
                },
                {
                    "label": "Pending Approvals",
                    "value": str(fund_requests_pending),
                    "raw_value": fund_requests_pending,
                    "helper": "needs action",
                    "icon": "warning",
                    "variant": "warning",
                },
            ]
        elif role == "Accountant":
            pending_clearance = sum(
                (w.total_amount or 0) - (w.disbursed_amount or 0)
                for w in fy_wfr_qs.filter(status="confirmed_for_advance")
            )
            kpi_items = [
                {
                    "label": "Confirmed This FY",
                    "value": _ugx_compact(wfr_confirmed_total),
                    "raw_value": wfr_confirmed_total,
                    "helper": "current FY",
                    "icon": "currency",
                    "variant": "finance",
                },
                {
                    "label": "Pending Disbursement",
                    "value": _ugx_compact(pending_clearance),
                    "raw_value": pending_clearance,
                    "helper": "advances",
                    "icon": "clock",
                    "variant": "warning",
                },
                {
                    "label": "Disbursed",
                    "value": _ugx_compact(wfr_disbursed_total),
                    "raw_value": wfr_disbursed_total,
                    "helper": "this FY",
                    "icon": "check",
                    "variant": "success",
                },
                {
                    "label": "Planned Activities",
                    "value": str(activities_this_month),
                    "raw_value": activities_this_month,
                    "helper": "this month",
                    "icon": "calendar",
                    "variant": "info",
                },
            ]
        else:
            kpi_items = [
                {
                    "label": "Schools Ready for Planning",
                    "value": str(ready_count),
                    "raw_value": ready_count,
                    "helper": f"{ready_pct}% of total",
                    "icon": "school",
                    "variant": "success",
                },
                {
                    "label": "Schools Without SSA",
                    "value": str(without_ssa_count),
                    "raw_value": without_ssa_count,
                    "helper": f"{without_ssa_pct}% of total",
                    "icon": "warning",
                    "variant": "danger",
                },
                {
                    "label": "Activities This Week",
                    "value": str(activities_this_week),
                    "raw_value": activities_this_week,
                    "helper": "scheduled",
                    "icon": "calendar",
                    "variant": "info",
                },
                {
                    "label": "Planned This Month",
                    "value": str(activities_this_month),
                    "raw_value": activities_this_month,
                    "helper": "scheduled",
                    "icon": "chart",
                    "variant": "blue",
                },
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
            "weekly_progress": weekly_progress,
            "best_interventions": best_interventions,
            "weakest_interventions": weakest_interventions,
            "team_targets": team_targets,
            "priority_schools": priority_schools,
            "cluster_performance": cluster_performance,
            "support_overview": support_overview,
            "budget_snapshot": budget_snapshot,
            "execution_summary": execution_summary,
            "upcoming_today": upcoming_today,
            "evidence_pending": evidence_pending_count,
        }
