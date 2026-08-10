import hashlib
import json

from django.conf import settings
from django.shortcuts import render

from apps.core.cache_utils import stampede_safe_get_or_compute
from apps.core.permissions import require_page_permission
from apps.core.metrics import DataState, MetricValue, render_kpi_item


@require_page_permission("impact_analytics")
def impact_analytics_view(request):
    """Statistical impact intelligence: did visits, trainings, and money move
    the SSA scores — and what does the field say where they didn't?"""
    from apps.analytics.decision_engine import impact_analytics_dashboard

    # Cached like the Analytics dashboard next door, and for a stronger
    # reason: this page pulls ~125k improvement rows into pandas and runs
    # Kruskal-Wallis over them, so it was the single most expensive page on
    # the platform and it recomputed on EVERY load — including a second load
    # of the same page by the same person. Keyed by user and role because the
    # engine scopes to what the viewer may see; a shared key would leak one
    # region's schools into another's dashboard.
    query = request.GET.dict()
    fingerprint = hashlib.sha256(
        json.dumps(query, sort_keys=True, default=str).encode()
    ).hexdigest()[:20]
    dashboard = stampede_safe_get_or_compute(
        f"impact-dashboard:v1:{request.user.id}:"
        f"{request.user.active_role}:{fingerprint}",
        lambda: impact_analytics_dashboard(request.user, query),
        timeout=settings.IMPACT_DASHBOARD_CACHE_SECONDS,
    )
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
