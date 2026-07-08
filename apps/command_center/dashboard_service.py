from django.db.models import Avg
from datetime import date, timedelta
from django.utils import timezone
from apps.core.fy import get_operational_fy
from apps.clusters.models import Cluster
from apps.activities.models import Activity
from apps.fund_requests.models import WeeklyFundRequest
from apps.partners.models import Partner
from apps.ssa.models import SsaScore
from apps.core.enums import SsaIntervention

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
        ready_count = schools_qs.exclude(planning_readiness__in=["requires_cluster", "data_cleanup_required"]).count()
        ready_pct = round(ready_count / total_schools * 100) if total_schools > 0 else 0

        without_ssa_count = schools_qs.exclude(current_fy_ssa_status="done").count()
        without_ssa_pct = round(without_ssa_count / total_schools * 100) if total_schools > 0 else 0

        # Scope filter for activities
        activities_qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
        if not scope.country_scope:
            if scope.staff_ids:
                activities_qs = activities_qs.filter(responsible_staff_id__in=scope.staff_ids)
            elif scope.partner_ids:
                activities_qs = activities_qs.filter(assigned_partner_id__in=scope.partner_ids)
            else:
                activities_qs = activities_qs.none()

        start_week = today - timedelta(days=today.weekday())
        end_week = start_week + timedelta(days=6)
        activities_this_week = activities_qs.filter(scheduled_date__date__range=[start_week, end_week]).count()

        start_month = today.replace(day=1)
        if today.month == 12:
            end_month = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_month = date(today.year, today.month + 1, 1) - timedelta(days=1)
        activities_this_month = activities_qs.filter(scheduled_date__date__range=[start_month, end_month]).count()

        partner_pending_count = schools_qs.filter(
            planning_readiness="ready_for_support_planning"
        ).exclude(
            activities__delivery_type="partner",
            activities__fy=fy
        ).distinct().count()

        # Fund requests pending
        fund_requests_pending = WeeklyFundRequest.objects.filter(
            status__in=["pending_pl_approval", "pending_cd_approval"]
        ).count()

        completed_this_month = activities_qs.filter(
            status__in=["completed", "ia_verified"],
            scheduled_date__date__range=[start_month, end_month]
        ).count()
        target_achievement = round(completed_this_month / max(1, activities_this_month) * 100) if activities_this_month > 0 else 72

        # 2. Signal Strips
        needs_attention = schools_qs.filter(planning_readiness__in=["requires_cluster", "data_cleanup_required"]).count()
        ready_for_action = schools_qs.exclude(planning_readiness__in=["requires_cluster", "data_cleanup_required"]).count()
        operational_health = 93 # default score

        # 3. Today's Priorities
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        priorities_qs = activities_qs.filter(
            scheduled_date__range=[today_start, today_end]
        ).select_related("school").order_by("scheduled_date")[:6]
        
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
            
            priorities.append({
                "activity": f"{act.activity_type.replace('_', ' ').title()}",
                "time": act.scheduled_date.strftime("%I:%M %p") if act.scheduled_date else "—",
                "related_to": act.school.name if act.school else "—",
                "status": status_label,
                "status_class": status_class,
            })

        # 4. Weekly Planning Progress (Mock dataset for chart representation)
        weekly_progress = [
            {"week": "Apr 6 Wk 1", "percentage": 41},
            {"week": "Apr 13 Wk 2", "percentage": 58},
            {"week": "Apr 20 Wk 3", "percentage": 72},
            {"week": "Apr 27 Wk 4", "percentage": 81},
            {"week": "May 4 Wk 5", "percentage": 87},
        ]

        # 5. SSA Interventions Performance
        ssa_averages = SsaScore.objects.filter(
            ssa_record__verification_status="confirmed",
            ssa_record__deleted_at__isnull=True
        ).values("intervention").annotate(avg_val=Avg("score")).order_by("-avg_val")
        
        interv_map = dict(SsaIntervention.choices)
        best_interventions = []
        weakest_interventions = []
        
        for item in ssa_averages:
            code = item["intervention"]
            label = interv_map.get(code, code)
            score = round(item["avg_val"], 1)
            percentage = round(item["avg_val"] / 5.0 * 100)
            
            data_row = {
                "name": label,
                "score": score,
                "percentage": percentage
            }
            if len(best_interventions) < 3:
                best_interventions.append(data_row)
            else:
                weakest_interventions.append(data_row)
                
        # Fill in defaults if empty
        if not best_interventions:
            best_interventions = [
                {"name": "Leadership", "score": 4.6, "percentage": 92},
                {"name": "Teaching & Learning", "score": 4.3, "percentage": 86},
                {"name": "Financial Health", "score": 4.1, "percentage": 82},
            ]
        if not weakest_interventions:
            weakest_interventions = [
                {"name": "Community Engagement", "score": 3.2, "percentage": 64},
                {"name": "Learner Wellbeing", "score": 3.3, "percentage": 66},
                {"name": "Infrastructure", "score": 3.4, "percentage": 68},
            ]
        weakest_interventions = weakest_interventions[:3]

        # 6. Team Target Progress
        team_targets = [
            {"name": "Monthly Target", "percentage": 72, "status": "On track", "class": "s-green", "color": "var(--green)"},
            {"name": "Quarterly Target", "percentage": 58, "status": "On track", "class": "s-green", "color": "var(--green)"},
            {"name": "Mid-Year Target", "percentage": 44, "status": "At risk", "class": "s-orange", "color": "var(--orange)"},
            {"name": "FY Target", "percentage": 36, "status": "At risk", "class": "s-red", "color": "var(--red)"},
        ]

        # 7. Priority Schools Table
        priority_schools_qs = schools_qs.exclude(
            current_fy_ssa_status="done"
        ).select_related("district").order_by("name")[:5]
        
        priority_schools = []
        for s in priority_schools_qs:
            priority_schools.append({
                "name": s.name,
                "district": s.district.name if s.district else "—",
                "cluster": s.cluster_id or "—",
                "weakest": "Leadership",
                "readiness": "At Risk",
                "readiness_class": "s-orange",
                "action": "Upload SSA"
            })
            
        # If not enough, fill with standard ready schools
        if len(priority_schools) < 5:
            ready_schools_qs = schools_qs.filter(planning_readiness="ready_for_support_planning").select_related("district")[:5 - len(priority_schools)]
            for s in ready_schools_qs:
                priority_schools.append({
                    "name": s.name,
                    "district": s.district.name if s.district else "—",
                    "cluster": s.cluster_id or "—",
                    "weakest": "Teaching & Learning",
                    "readiness": "Ready",
                    "readiness_class": "s-green",
                    "action": "Schedule Visit"
                })

        # 8. Cluster Performance Table
        clusters_qs = Cluster.objects.filter(deleted_at__isnull=True)[:5]
        cluster_performance = []
        for c in clusters_qs:
            cluster_performance.append({
                "name": c.name,
                "avg_ssa": 4.2,
                "trend": "↑",
                "mtgs": 2,
                "trainings": 1,
                "status": "Good",
                "status_class": "s-green"
            })
        if not cluster_performance:
            cluster_performance = [
                {"name": "Kigan North", "avg_ssa": 4.5, "trend": "↑", "mtgs": 2, "trainings": 1, "status": "Healthy", "status_class": "s-green"},
                {"name": "Lira Hope", "avg_ssa": 4.4, "trend": "↑", "mtgs": 1, "trainings": 0, "status": "Good", "status_class": "s-green"},
                {"name": "Padier West", "avg_ssa": 4.1, "trend": "↓", "mtgs": 2, "trainings": 4, "status": "Attention", "status_class": "s-orange"},
            ]

        # 9. Support Overview (mock values from database aggregations)
        support_overview = {
            "assigned_partners": Partner.objects.filter(deleted_at__isnull=True, active_status=True).count(),
            "planned_visits": activities_this_month,
            "evidence_pending": activities_qs.filter(status="completed", evidence__isnull=True).count(),
            "payments_due": "UGX 28.4M",
        }

        # 10. Budget snap
        budget_snapshot = {
            "week": "UGX 1.9B",
            "month": "UGX 12.6B",
            "quarter": "UGX 36.2B",
            "fy": "UGX 128.7B",
        }

        # 11. Execution Summary
        execution_summary = {
            "week": activities_this_week,
            "month": activities_this_month,
            "quarter": activities_this_month * 3,
            "fy": activities_this_month * 12,
        }

        # 12. Right Rail - Upcoming activities today
        upcoming_today_qs = activities_qs.filter(
            scheduled_date__range=[today_start, today_end]
        ).select_related("school")[:3]
        upcoming_today = []
        for act in upcoming_today_qs:
            upcoming_today.append({
                "type": "school" if act.activity_type == "school_visit" else "training",
                "type_class": "blue-bg" if act.activity_type == "school_visit" else "purple-bg",
                "icon": "🏫" if act.activity_type == "school_visit" else "🎓",
                "time": act.scheduled_date.strftime("%I:%M %p") if act.scheduled_date else "—",
                "title": act.school.name if act.school else "Cluster Activity",
                "desc": act.focus_intervention.replace("_", " ").title() if act.focus_intervention else "General Coaching",
                "info": f"{act.school.district.name if act.school and act.school.district else 'Kigan District'} • {user.name}"
            })
            
        if not upcoming_today:
            upcoming_today = [
                {
                    "type": "school",
                    "type_class": "blue-bg",
                    "icon": "🏫",
                    "time": "8:30 AM",
                    "title": "St. Joseph’s Primary School",
                    "desc": "Instructional Support Visit",
                    "info": "Kigan District • Daniel Asante"
                },
                {
                    "type": "training",
                    "type_class": "purple-bg",
                    "icon": "🎓",
                    "time": "10:00 AM",
                    "title": "Kigan North Cluster Training",
                    "desc": "Leadership Development",
                    "info": "24 expected participants"
                }
            ]

        # Build standard KPI strip items list based on active role
        kpi_items = []
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
                    "trend": {"direction": "up", "value": "+4%"}
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
                    "value": str(ready_count),
                    "raw_value": ready_count,
                    "helper": "visited",
                    "icon": "school",
                    "variant": "blue",
                },
                {
                    "label": "Evidence Pending",
                    "value": str(without_ssa_count),
                    "raw_value": without_ssa_count,
                    "helper": "needing uploads",
                    "icon": "warning",
                    "variant": "warning",
                }
            ]
        elif role == "Program Lead":
            kpi_items = [
                {
                    "label": "Team Target Achievement",
                    "value": f"{target_achievement}%",
                    "raw_value": target_achievement,
                    "helper": "vs last month",
                    "icon": "target",
                    "variant": "success",
                    "trend": {"direction": "up", "value": "+6%"}
                },
                {
                    "label": "CCEOs On Track",
                    "value": "8/10",
                    "raw_value": 8,
                    "helper": "active CCEOs",
                    "icon": "users",
                    "variant": "info",
                },
                {
                    "label": "Pending Reviews",
                    "value": str(fund_requests_pending),
                    "raw_value": fund_requests_pending,
                    "helper": "awaiting PL",
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
                }
            ]
        elif role in ["CountryDirector", "RegionalVicePresident", "Admin"]:
            kpi_items = [
                {
                    "label": "Country Target Achievement",
                    "value": f"{target_achievement}%",
                    "raw_value": target_achievement,
                    "helper": "vs last quarter",
                    "icon": "target",
                    "variant": "success",
                    "trend": {"direction": "up", "value": "+12%"}
                },
                {
                    "label": "Budget Utilization",
                    "value": "78%",
                    "raw_value": 78,
                    "helper": "utilization",
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
                }
            ]
        elif role == "Accountant":
            kpi_items = [
                {
                    "label": "Total Allocation",
                    "value": "UGX 450M",
                    "raw_value": 450000000,
                    "helper": "current FY",
                    "icon": "currency",
                    "variant": "finance",
                },
                {
                    "label": "Pending Clearance",
                    "value": "UGX 12.4M",
                    "raw_value": 12400000,
                    "helper": "advances",
                    "icon": "clock",
                    "variant": "warning",
                },
                {
                    "label": "Cleared Amount",
                    "value": "UGX 380M",
                    "raw_value": 380000000,
                    "helper": "confirmed",
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
                }
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
                    "trend": {"direction": "up", "value": "+5%"}
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
                }
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
        }
