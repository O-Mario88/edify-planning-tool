from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Avg, Count, Sum
from django.utils import timezone
from datetime import datetime, timedelta

from apps.activities.models import Activity
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.fund_requests.models import FundRequest, WeeklyFundRequest
from apps.activities.models import ActivityScheduleCostLine
from apps.ssa.models import SsaRecord
from apps.accounts.models import User
from apps.command_center import services as cc_services
from apps.command_center.dashboard_service import DashboardMetricsService

@login_required(login_url="/login")
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

    context = {
        "alerts": alerts_list,
        "alerts_summary": alerts_summary,
        "today_context": today_context,
        "role": role,
        "user_name": user.name,
        "avatar_initials": avatar_initials,
        
        # Computed metrics
        "kpis": metrics["kpis"],
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
