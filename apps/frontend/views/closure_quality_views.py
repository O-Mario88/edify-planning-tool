"""Closure quality — the Impact Assessment view of school closures.

Not the leadership view. A Country Director asks how many schools the country
lost and where; this page asks which of those records should not be believed,
because a duplicate counted as a closure reports a school loss that never
happened and every number built on top of it inherits the error.

The page is deliberately a worklist with a summary above it, not a chart wall.
Every tile counts rows that are listed further down, so a number can be
followed to the closures it describes.
"""

from __future__ import annotations

from django.shortcuts import render

from apps.core.permissions import require_page_permission


@require_page_permission("closure_quality")
def closure_quality_view(request):
    from apps.core.fy import get_operational_fy
    from apps.schools import closure_analytics

    # All-time by default. A data-quality queue that hid last year's unresolved
    # duplicates behind a period filter would report a clean desk that is only
    # clean because of where the window starts.
    period = request.GET.get("period") or "all"
    fy_start = fy_end = None
    fy = get_operational_fy()
    if period == "fy":
        from apps.core.fy import get_fy_date_range

        start, end = get_fy_date_range(fy)
        fy_start, fy_end = start.date(), end.date()

    summary = closure_analytics.closure_quality(fy_start, fy_end)
    attention = closure_analytics.needs_attention()

    context = {
        "summary": summary,
        "by_reason": closure_analytics.by_reason(fy_start, fy_end),
        "trend": closure_analytics.monthly_trend(),
        "attention": attention,
        "reopenings": closure_analytics.reopenings(),
        "period": period,
        "fy": fy,
        "stale_days": closure_analytics.STALE_RECORDING_DAYS,
    }
    if request.headers.get("HX-Request") == "true":
        return render(
            request, "partials/analytics/closure_quality_workspace.html", context
        )
    return render(request, "pages/analytics/closure_quality.html", context)
