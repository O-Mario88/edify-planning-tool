from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from apps.analytics.services import leadership_summary, recruitment_recommendation
from apps.system_health.services import report as system_health_report
from apps.core.fy import get_operational_fy

@login_required(login_url="/login")
def analytics_dashboard_view(request):
    fy = get_operational_fy()
    summary = leadership_summary(request.user, {"fy": fy})
    recommendations = recruitment_recommendation(request.user, {"fy": fy})
    
    context = {
        "summary": summary,
        "recommendations": recommendations,
        "fy": fy,
    }
    return render(request, "pages/analytics/index.html", context)

@login_required(login_url="/login")
def system_health_view(request):
    health = system_health_report()
    context = {
        "health": health,
    }
    return render(request, "pages/system_health/index.html", context)
