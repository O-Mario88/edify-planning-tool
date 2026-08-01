import json

from django.shortcuts import render

from apps.core.permissions import require_page_permission
from apps.core.metrics import DataState, MetricValue, render_kpi_item


@require_page_permission("impact_analytics")
def impact_analytics_view(request):
    """Statistical impact intelligence: did visits, trainings, and money move
    the SSA scores — and what does the field say where they didn't?"""
    from apps.analytics.decision_engine import impact_analytics_dashboard

    dashboard = impact_analytics_dashboard(request.user, request.GET.dict())
    kpis = dashboard["kpis"]
    paired_schools = dashboard["coverage"]["schools_paired"]
    impact_kpi_items = [
        render_kpi_item(
            "impact_schools_analysed",
            MetricValue.measured(paired_schools),
            helper="Assessed in both cycles",
            tone="info",
        ),
        render_kpi_item(
            "impact_median_school_delta",
            MetricValue.measured(kpis["median_delta"])
            if kpis["median_delta"] is not None
            else MetricValue.absent(DataState.NOT_YET_MEASURABLE),
            helper=f"Score points vs FY {dashboard['filters']['prev_fy']}",
            tone="success" if (kpis["median_delta"] or 0) > 0 else "warning",
        ),
        render_kpi_item(
            "impact_schools_improved_rate",
            MetricValue.measured(kpis["improved_pct"], denominator=paired_schools)
            if kpis["improved_pct"] is not None and paired_schools
            else MetricValue.absent(DataState.NOT_YET_MEASURABLE),
            helper="Mean delta above +0.3",
            tone="success",
        ),
        render_kpi_item(
            "impact_accepted_spend",
            MetricValue.measured(kpis["total_accepted_spend_value"]),
            helper=(
                f"{kpis['ugx_per_point']} per net score point"
                if kpis.get("ugx_per_point")
                else "No net improvement to price yet"
            ),
            tone="info",
        ),
    ]
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
            "impact_kpi_items": impact_kpi_items,
        },
    )
