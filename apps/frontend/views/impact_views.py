import json

from django.shortcuts import render

from apps.core.permissions import require_page_permission


@require_page_permission("impact_analytics")
def impact_analytics_view(request):
    """Statistical impact intelligence: did visits, trainings, and money move
    the SSA scores — and what does the field say where they didn't?"""
    from apps.analytics.decision_engine import impact_analytics_dashboard

    dashboard = impact_analytics_dashboard(request.user, request.GET.dict())
    impact_chart_payload = {
        key: json.loads(value) if isinstance(value, str) else value
        for key, value in dashboard.get("charts", {}).items()
    }
    template = (
        "partials/analytics/impact_workspace.html"
        if request.headers.get("HX-Request") == "true"
        else "pages/analytics/impact.html"
    )
    return render(
        request,
        template,
        {
            "dashboard": dashboard,
            "impact_chart_payload": impact_chart_payload,
        },
    )
