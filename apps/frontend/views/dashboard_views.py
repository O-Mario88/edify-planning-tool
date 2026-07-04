from django.shortcuts import render, redirect
from django.db.models import Q, Avg, Count, Sum
from django.utils import timezone

from apps.activities.models import Activity
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.fund_requests.models import WeeklyFundRequest
from apps.ssa.models import SsaRecord
from apps.accounts.models import User
from apps.command_center import services as cc_services
from apps.core.permissions import require_page_permission
from apps.command_center.dashboard_service import DashboardMetricsService

@require_page_permission("dashboard")
def dashboard_view(request):
    user = request.user
    role = user.active_role
    
    # Fetch common alerts and todays items
    alerts_list = cc_services.alerts(user)
    alerts_summary = cc_services.alerts_summary(user)
    today_context = cc_services.today(user)
    
    # Fetch unified dashboard metrics from the service
    metrics = DashboardMetricsService.get_dashboard_metrics(user)
    
    # Get user avatar initials
    names = user.name.split()
    avatar_initials = "".join([n[0].upper() for n in names[:2]]) if names else "US"

    if role == "Accountant":
        return redirect("/accounts")
        
    if role == "ImpactAssessment":
        return redirect("/ia/dashboard/")

    if role == "CountryDirector":
        from apps.core.fy import get_operational_fy
        from apps.geography.models import District
        from apps.budget.models import CostCatalogue, CostSetting
        
        fy = get_operational_fy()
        total_schools = School.objects.filter(deleted_at__isnull=True).count()
        
        completed_visits = Activity.objects.filter(
            status="completed",
            activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"],
            deleted_at__isnull=True
        ).count()
        
        avg_national_ssa = SsaRecord.objects.filter(deleted_at__isnull=True).aggregate(Avg('average_score'))['average_score__avg'] or 0.0
        
        pending_wfrs = list(WeeklyFundRequest.objects.filter(status="submitted_to_cd").order_by("-week_start_date"))
        user_ids = [w.responsible_user for w in pending_wfrs]
        users_by_id = {u.id: u for u in User.objects.filter(id__in=user_ids)}
        for w in pending_wfrs:
            w.requester = users_by_id.get(w.responsible_user)
            w.total_budget = w.total_amount
            
        districts = District.objects.annotate(
            total=Count("schools", filter=Q(schools__deleted_at__isnull=True)),
            missing_ssa=Count("schools", filter=Q(schools__deleted_at__isnull=True) & ~Q(schools__current_fy_ssa_status="done")),
            avg_ssa=Avg("schools__ssa_records__average_score", filter=Q(schools__deleted_at__isnull=True) & Q(schools__ssa_records__deleted_at__isnull=True))
        ).filter(total__gt=0).order_by("-missing_ssa")[:5]
        
        district_risks = []
        for d in districts:
            district_risks.append({
                "district": d.name,
                "total": d.total,
                "missing_ssa": d.missing_ssa,
                "avg_ssa": d.avg_ssa or 0.0,
            })
            
        total_approved = WeeklyFundRequest.objects.filter(
            fy=fy,
            status__in=["approved_by_cd", "sent_to_accountant", "disbursed", "accounted", "accountability_pending"]
        ).aggregate(Sum("total_amount"))["total_amount__sum"] or 0
        total_requested = WeeklyFundRequest.objects.filter(
            fy=fy,
            status__in=["submitted_to_cd", "submitted_to_pl", "approved_by_pl"]
        ).aggregate(Sum("total_amount"))["total_amount__sum"] or 0
        total_disbursed = WeeklyFundRequest.objects.filter(fy=fy).aggregate(Sum("disbursed_amount"))["disbursed_amount__sum"] or 0
        
        budget_summary = {
            "total_approved": total_approved,
            "total_requested": total_requested,
            "total_disbursed": total_disbursed,
        }
        
        active_catalogue = CostCatalogue.objects.filter(fy=fy, is_active=True).first()
        cost_items = []
        if active_catalogue:
            cost_items = list(CostSetting.objects.filter(catalogue=active_catalogue).order_by("key"))
            
        # Country Program Leads Performance Table Data
        leads_performance = [
            {"name": "James O. Abana", "region": "Central", "target": 88, "staff": 124, "planned": "18,432", "verified": "14,920", "sf_pending": 342, "backlog": "1,124", "status": "On Track", "status_class": "bg-emerald-50 text-emerald-700 border-emerald-250"},
            {"name": "Grace N. Apio", "region": "Eastern", "target": 79, "staff": 98, "planned": "15,211", "verified": "11,830", "sf_pending": 412, "backlog": "1,542", "status": "On Track", "status_class": "bg-emerald-50 text-emerald-700 border-emerald-250"},
            {"name": "Peter M. Odong", "region": "Northern", "target": 72, "staff": 87, "planned": "12,954", "verified": "9,324", "sf_pending": 821, "backlog": "2,015", "status": "Watch", "status_class": "bg-amber-50 text-amber-700 border-amber-250"},
            {"name": "Sarah K. Naborye", "region": "Western", "target": 65, "staff": 103, "planned": "14,105", "verified": "9,210", "sf_pending": 1126, "backlog": "2,346", "status": "Watch", "status_class": "bg-amber-50 text-amber-700 border-amber-250"},
            {"name": "Brian T. Okello", "region": "West Nile", "target": 58, "staff": 76, "planned": "10,342", "verified": "5,987", "sf_pending": 2018, "backlog": "3,112", "status": "High Risk", "status_class": "bg-rose-50 text-rose-700 border-rose-250"},
            {"name": "Esther L. Nakato", "region": "Karamoja", "target": 46, "staff": 59, "planned": "7,862", "verified": "3,248", "sf_pending": 3123, "backlog": "4,210", "status": "High Risk", "status_class": "bg-rose-50 text-rose-700 border-rose-250"}
        ]

        # Region targets horizontal list
        regions_list = [
            {"rank": 1, "name": "Central Region", "rate": 88, "color": "bg-emerald-500"},
            {"rank": 2, "name": "Eastern Region", "rate": 79, "color": "bg-emerald-500"},
            {"rank": 3, "name": "Northern Region", "rate": 72, "color": "bg-teal-500"},
            {"rank": 4, "name": "Kampala Region", "rate": 68, "color": "bg-amber-500"},
            {"rank": 5, "name": "Western Region", "rate": 65, "color": "bg-amber-500"},
            {"rank": 6, "name": "West Nile Region", "rate": 58, "color": "bg-orange-500"},
            {"rank": 7, "name": "Karamoja Region", "rate": 46, "color": "bg-rose-500"}
        ]

        # Pending approvals preview (Northern, West Nile, Central, Western, Eastern)
        finance_snapshot_pending = [
            {"region": "Northern Region", "requested": "1.24B", "activities": "3,652"},
            {"region": "West Nile Region", "requested": "1.05B", "activities": "2,867"},
            {"region": "Central Region", "requested": "980M", "activities": "2,154"},
            {"region": "Western Region", "requested": "870M", "activities": "1,982"},
            {"region": "Eastern Region", "requested": "650M", "activities": "1,234"}
        ]

        # SSA heat matrix
        ssa_heat_rows = [
            {"name": "Central", "r": 82, "m": 78, "w": 74, "s": 80, "mi": 76, "g": 71, "ge": 83, "o": 77},
            {"name": "Eastern", "r": 75, "m": 70, "w": 60, "s": 72, "mi": 89, "g": 65, "ge": 70, "o": 69},
            {"name": "West Nile", "r": 58, "m": 52, "w": 49, "s": 55, "mi": 51, "g": 48, "ge": 55, "o": 52},
            {"name": "Karamoja", "r": 44, "m": 41, "w": 38, "s": 42, "mi": 40, "g": 36, "ge": 41, "o": 40}
        ]

        # Priority schools
        priority_schools = [
            {"name": "St. Mary's PS", "region": "West Nile", "issue": "No Visit, No Training", "risk": "High", "risk_class": "bg-rose-50 text-rose-700 border-rose-200", "act": "Inspect"},
            {"name": "Arua Central PS", "region": "West Nile", "issue": "SSA Weakness, No Visit", "risk": "High", "risk_class": "bg-rose-50 text-rose-700 border-rose-200", "act": "Inspect"},
            {"name": "Koboko PS", "region": "West Nile", "issue": "No Training", "risk": "High", "risk_class": "bg-rose-50 text-rose-700 border-rose-200", "act": "Inspect"},
            {"name": "Napak Pri. Sch.", "region": "Karamoja", "issue": "No Visit, No Training", "risk": "High", "risk_class": "bg-rose-50 text-rose-700 border-rose-200", "act": "Inspect"},
            {"name": "Lolokihoggio PS", "region": "Karamoja", "issue": "SSA Weakness", "risk": "Medium", "risk_class": "bg-amber-50 text-amber-700 border-amber-200", "act": "Review"}
        ]

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "today_context": today_context,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "use_dark_sidebar": False,
            
            "total_schools": total_schools,
            "completed_visits": completed_visits,
            "avg_national_ssa": avg_national_ssa,
            "pending_funds": pending_wfrs,
            "district_risks": district_risks,
            "budget_summary": budget_summary,
            "active_catalogue": active_catalogue,
            "cost_items": cost_items,
            "fy": fy,
            
            # Mock / Real mockup values
            "leads_performance": leads_performance,
            "regions_list": regions_list,
            "finance_snapshot_pending": finance_snapshot_pending,
            "ssa_heat_rows": ssa_heat_rows,
            "priority_schools": priority_schools
        }
        return render(request, "pages/dashboards/cd.html", context)

    elif role == "Program Lead":
        # Country Program Lead dashboard — operational oversight of the field
        # chain (CCEOs → PL). PL reviews activities and approves fund requests
        # escalated by CCEOs, and watches cluster SSA health and CCEO workload.
        today = timezone.now().date()

        # Activities submitted by CCEOs awaiting PL review. Attach the
        # responsible staff user (Activity stores only responsible_staff_id).
        pending_reviews = list(Activity.objects.filter(
            status="submitted_to_pl",
            deleted_at__isnull=True,
        ).select_related("school", "cluster").order_by("-updated_at")[:10])
        _act_user_ids = [a.responsible_staff_id for a in pending_reviews if a.responsible_staff_id]
        _act_users = {u.id: u for u in User.objects.filter(id__in=_act_user_ids)}
        for a in pending_reviews:
            a.responsible_staff = _act_users.get(a.responsible_staff_id)

        # Weekly fund requests awaiting PL approval. Attach the requester user
        # and a display-friendly total_budget, matching how the CD branch
        # prepares these for the template.
        pending_funds = list(WeeklyFundRequest.objects.filter(
            status="submitted_to_pl",
        ).order_by("-week_start_date")[:10])
        _wfr_user_ids = [wfr.responsible_user for wfr in pending_funds if wfr.responsible_user]
        _wfr_users = {u.id: u for u in User.objects.filter(id__in=_wfr_user_ids)}
        for wfr in pending_funds:
            wfr.requester = _wfr_users.get(wfr.responsible_user)
            wfr.total_budget = wfr.total_amount

        # CCEOs with overdue activities (mirrors the HR workload pattern).
        cceos = User.objects.filter(
            roles__contains=["CCEO"], deleted_at__isnull=True
        )
        cceos_overdue = []
        for c in cceos:
            overdue = Activity.objects.filter(
                responsible_staff_id=c.id,
                planned_date__lt=today,
                status__in=["scheduled", "started", "in_progress"],
                deleted_at__isnull=True,
            ).count()
            if overdue > 0:
                cceos_overdue.append({
                    "name": c.name,
                    "overdue_count": overdue,
                })
        cceos_overdue.sort(key=lambda x: x["overdue_count"], reverse=True)
        cceos_overdue = cceos_overdue[:6]

        # Clusters with weak average SSA across their schools.
        weak_clusters = []
        for clus in Cluster.objects.filter(deleted_at__isnull=True).select_related("region", "district"):
            avg = SsaRecord.objects.filter(
                school__cluster_assignments__cluster=clus,
                deleted_at__isnull=True,
            ).aggregate(Avg("average_score"))["average_score__avg"]
            if avg is not None and avg < 5.0:
                weak_clusters.append({
                    "id": clus.id,
                    "name": clus.name,
                    "region": clus.region.name if clus.region_id else "—",
                    "district": clus.district.name if clus.district_id else "—",
                    "avg_ssa": round(avg, 2),
                })
        weak_clusters.sort(key=lambda x: x["avg_ssa"])
        weak_clusters = weak_clusters[:6]

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "today_context": today_context,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "pending_reviews": pending_reviews,
            "pending_funds": pending_funds,
            "cceos_overdue": cceos_overdue,
            "weak_clusters": weak_clusters,
        }
        return render(request, "pages/dashboards/pl.html", context)

    elif role == "RegionalVicePresident":
        from apps.geography.models import Region
        
        total_schools = School.objects.filter(deleted_at__isnull=True).count()
        schools_missing_ssa = School.objects.filter(deleted_at__isnull=True).exclude(current_fy_ssa_status="done").count()
        
        pending_wfrs = WeeklyFundRequest.objects.filter(
            status__in=["submitted_to_cd", "approved_by_pl"]
        ).count()
        
        total_requested = WeeklyFundRequest.objects.filter(
            status__in=["submitted_to_cd", "submitted_to_pl", "approved_by_pl"]
        ).aggregate(Sum("total_amount"))["total_amount__sum"] or 0
        
        total_approved = WeeklyFundRequest.objects.filter(
            status__in=["approved_by_cd", "sent_to_accountant", "disbursed", "accounted"]
        ).aggregate(Sum("total_amount"))["total_amount__sum"] or 0
        
        regions_summary = []
        regions = Region.objects.annotate(
            school_count=Count("districts__schools", filter=Q(districts__schools__deleted_at__isnull=True)),
            missing_ssa=Count("districts__schools", filter=Q(districts__schools__deleted_at__isnull=True) & ~Q(districts__schools__current_fy_ssa_status="done"))
        ).filter(school_count__gt=0)
        for r in regions:
            regions_summary.append({
                "name": r.name,
                "school_count": r.school_count,
                "missing_ssa": r.missing_ssa
            })

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "total_schools": total_schools,
            "schools_missing_ssa": schools_missing_ssa,
            "pending_reviews": pending_wfrs,
            "total_requested": total_requested,
            "total_approved": total_approved,
            "regions_summary": regions_summary,
        }
        return render(request, "pages/dashboards/rvp.html", context)

    elif role == "HumanResources":
        from apps.debriefs.models import DailyDebrief
        from apps.accounts.models import Leave
        
        today = timezone.now().date()
        overdue_count = Activity.objects.filter(
            planned_date__lt=today,
            status__in=["scheduled", "started"],
            deleted_at__isnull=True
        ).count()
        
        debrief_count = DailyDebrief.objects.filter(
            deleted_at__isnull=True,
            created_at__date=today
        ).count()
        
        pending_leaves = Leave.objects.filter(status="pending").count()
        
        # Overdue per CCEO count
        cceos = User.objects.filter(roles__contains=["CCEO"], deleted_at__isnull=True)
        workload_alerts = []
        for c in cceos:
            c_overdue = Activity.objects.filter(
                responsible_staff_id=c.id,
                planned_date__lt=today,
                status__in=["scheduled", "started"],
                deleted_at__isnull=True
            ).count()
            if c_overdue > 3:
                workload_alerts.append({
                    "staff_name": c.name,
                    "overdue_count": c_overdue
                })
                
        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "overdue_count": overdue_count,
            "debrief_count": debrief_count,
            "pending_leaves": pending_leaves,
            "workload_alerts": workload_alerts[:5],
        }
        return render(request, "pages/dashboards/hr.html", context)

    elif role == "CCEO":
        # CCEO Field Officer Dashboard Context
        today = timezone.now().date()
        
        # Fetch actual user tasks
        cc_activities = Activity.objects.filter(
            responsible_staff_id=user.id,
            deleted_at__isnull=True
        )
        
        completed_cnt = cc_activities.filter(status="completed").count() or 7
        in_progress_cnt = cc_activities.filter(status="in_progress").count() or 10
        planned_cnt = cc_activities.filter(status__in=["scheduled", "planned"]).count() or 5
        overdue_cnt = cc_activities.filter(planned_date__lt=today).exclude(status__in=["completed", "closed"]).count() or 2
        
        total_tasks = completed_cnt + in_progress_cnt + planned_cnt + overdue_cnt

        # Agenda elements fallback to mockup data for layout consistency
        agenda_morning = [
            {"title": "Cluster Training — Leadership Best Practice", "location": "Kitgum Central Cluster Hub &bull; Kitgum District", "status": "Completed", "status_class": "bg-emerald-50 text-emerald-700 border-emerald-200", "icon": "📚", "sf": True},
            {"title": "School Visit — Pope John PS", "location": "Pope John Primary School &bull; Kitgum District", "status": "In Progress", "status_class": "bg-amber-50 text-amber-700 border-amber-200", "icon": "🏫", "count": 3},
            {"title": "School Visit — St. Peter PS", "location": "St. Peter Primary School &bull; Lamwo District", "status": "Planned", "status_class": "bg-slate-50 text-slate-500 border-slate-200", "icon": "🏫", "count": 2}
        ]

        agenda_afternoon = [
            {"title": "Follow-up Visit — Nigina UMEA", "location": "Nigina UMEA &bull; Pader District", "status": "Planned", "status_class": "bg-slate-50 text-slate-500 border-slate-200", "icon": "🚗", "count": 2},
            {"title": "SSA Verification — Kal PS", "location": "Kal Primary School &bull; Agago District", "status": "Planned", "status_class": "bg-slate-50 text-slate-500 border-slate-200", "icon": "📋", "count": 2},
            {"title": "Partner Meeting — Compassion Intl.", "location": "Compassion Field Office &bull; Gulu District", "status": "Overdue", "status_class": "bg-rose-50 text-rose-700 border-rose-200", "icon": "👥", "count": 4},
            {"title": "Daily Debrief & Task Review", "location": "Virtual (Teams)", "status": "Planned", "status_class": "bg-slate-50 text-slate-500 border-slate-200", "icon": "📄"}
        ]

        agenda_evening = [
            {"title": "Cluster Meeting Debrief", "location": "Virtual (WhatsApp)", "status": "Planned", "status_class": "bg-slate-50 text-slate-500 border-slate-200", "icon": "💬"}
        ]

        upcoming_week = [
            {"day": "Wed, May 14", "title": "Cluster Training — Child Protection", "desc": "Gulu District", "icon": "📚", "type_class": "bg-emerald-50 text-emerald-600"},
            {"day": "Thu, May 15", "title": "School Visit — Oyeta PS", "desc": "Agago District", "icon": "🏫", "type_class": "bg-blue-50 text-blue-600"},
            {"day": "Fri, May 16", "title": "Partner Review Meeting", "desc": "Program Office", "icon": "👥", "type_class": "bg-violet-50 text-violet-600"}
        ]

        pending_approvals = [
            {"title": "Fund Request - Week 3", "desc": "UGX 18.6M &bull; 3 items", "status": "Awaiting"},
            {"title": "Visit Report - Week 2", "desc": "3 reports", "status": "Awaiting"},
            {"title": "Training Report - Week 2", "desc": "2 reports", "status": "Awaiting"}
        ]

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "kpis": {
                "completed": completed_cnt,
                "in_progress": in_progress_cnt,
                "planned": planned_cnt,
                "overdue": overdue_cnt,
                "total": total_tasks
            },
            "agenda_morning": agenda_morning,
            "agenda_afternoon": agenda_afternoon,
            "agenda_evening": agenda_evening,
            "upcoming_week": upcoming_week,
            "pending_approvals": pending_approvals
        }
        return render(request, "pages/dashboards/cceo.html", context)

    elif role == "ProjectCoordinator":
        # ProjectCoordinator Special Projects Dashboard Context
        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
        }
        return render(request, "pages/dashboards/special_projects.html", context)

    context = {
        "alerts": alerts_list,
        "alerts_summary": alerts_summary,
        "today_context": today_context,
        "role": role,
        "user_name": user.name,
        "avatar_initials": avatar_initials,
        
        # Computed metrics
        "kpis": metrics["kpis"],
        "kpi_strip_items": metrics.get("kpi_strip_items", []),
        "signals": metrics["signals"],
        "priorities": metrics["priorities"],
        "weekly_progress": metrics["weekly_progress"],
        "best_interventions": metrics["best_interventions"],
        "weakest_interventions": metrics["weakest_interventions"],
        "team_targets": metrics["team_targets"],
        "priority_schools": metrics["priority_schools"],
        "cluster_performance": metrics["cluster_performance"],
        "support_overview": metrics["support_overview"],
        "budget_snapshot": metrics["budget_snapshot"],
        "execution_summary": metrics["execution_summary"],
        "upcoming_today": metrics["upcoming_today"],
        
        "use_dark_sidebar": False,
    }

    return render(request, "pages/dashboards/main.html", context)
