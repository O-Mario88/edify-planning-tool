"""School closures, the Country Director's view.

A different question from the IA closure-quality page, and deliberately a
separate surface. IA asks which closure records are wrong; the CD asks where
the programme is losing schools and what that loss did to the plan. Merging
them into one dashboard would leave nobody sure which numbers they are
accountable for.

Nothing here is scoped: the Country Director's remit is the country. When RVP
gets this view it will need region scoping, and that is why `by_place` already
takes the grouping field rather than hardcoding district.
"""

from __future__ import annotations

from django.shortcuts import render

from apps.core.permissions import require_page_permission


@require_page_permission("closure_impact")
def closure_impact_view(request):
    from apps.core.fy import get_fy_date_range, get_operational_fy
    from apps.schools import closure_analytics

    fy = get_operational_fy()
    # The current FY is the default here, unlike the IA worklist which defaults
    # to all time. A country performance question is about a reporting period;
    # an unresolved-data question is not.
    period = request.GET.get("period") or "fy"
    fy_start = fy_end = None
    if period == "fy":
        start, end = get_fy_date_range(fy)
        fy_start, fy_end = start.date(), end.date()

    grouping = request.GET.get("by")
    if grouping not in {"district", "region"}:
        grouping = "district"

    context = {
        "summary": closure_analytics.country_summary(fy_start, fy_end),
        "places": closure_analytics.by_place(grouping, fy_start, fy_end),
        "by_reason": closure_analytics.by_reason(fy_start, fy_end),
        "trend": closure_analytics.monthly_trend(),
        "period": period,
        "grouping": grouping,
        "fy": fy,
    }
    if request.headers.get("HX-Request") == "true":
        return render(
            request, "partials/analytics/closure_impact_workspace.html", context
        )
    return render(request, "pages/analytics/closure_impact.html", context)
