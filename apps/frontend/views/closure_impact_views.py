"""School closures, the Country Director's view.

A different question from the IA closure-quality page, and deliberately a
separate surface. IA asks which closure records are wrong; the CD asks where
the programme is losing schools and what that loss did to the plan. Merging
them into one dashboard would leave nobody sure which numbers they are
accountable for.

One page, two audiences, scope applied by the service — the same arrangement
Visit Effectiveness uses. The Country Director's remit is the country; an RVP
sees their assigned regions, or the whole deployment when no geography is
configured, because `scoped_school_queryset` is the one definition of what an
analytics surface may aggregate over.

**Nothing here is a school-level row**, which is what makes the page safe to
share with a summary-only role. Every table aggregates to a district, a region,
a reason or a month. A test asserts no school name reaches an RVP's render, so
adding a per-school list later fails loudly rather than leaking quietly.
"""

from __future__ import annotations

from django.shortcuts import render

from apps.core.permissions import require_page_permission


@require_page_permission("closure_impact")
def closure_impact_view(request):
    from apps.core.fy import get_fy_date_range, get_operational_fy
    from apps.core.scoping import resolve_user_scope
    from apps.schools import closure_analytics

    scope = resolve_user_scope(request.user)
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
        "summary": closure_analytics.country_summary(fy_start, fy_end, scope),
        "places": closure_analytics.by_place(grouping, fy_start, fy_end, scope=scope),
        "by_reason": closure_analytics.by_reason(fy_start, fy_end, scope),
        "trend": closure_analytics.monthly_trend(scope=scope),
        "period": period,
        "grouping": grouping,
        "fy": fy,
        # An RVP sees summaries only, and the page says whose ground it is
        # describing rather than calling every scope "the country".
        "is_summary_only": scope.can_view_summary_only,
        "region_scoped": scope.rvp_region_scoped,
        "scope_label": _scope_label(scope),
    }
    if request.headers.get("HX-Request") == "true":
        return render(
            request, "partials/analytics/closure_impact_workspace.html", context
        )
    return render(request, "pages/analytics/closure_impact.html", context)


def _scope_label(scope) -> str:
    """Whose ground these numbers describe.

    An RVP reading "the country lost 40 schools" would reasonably assume the
    country, when the figure covers their regions. Naming the scope is cheaper
    than the misread it prevents — and an RVP with no geography configured
    genuinely does oversee everything, so that case says so.
    """
    if not scope.rvp_region_scoped:
        return "Country"
    try:
        from apps.geography.models import Region

        names = list(
            Region.objects.filter(id__in=scope.region_ids)
            .order_by("name")
            .values_list("name", flat=True)
        )
    except Exception:  # noqa: BLE001 - geography may not be ready
        names = []
    if not names:
        return "Your regions"
    if len(names) <= 3:
        return " · ".join(names)
    return f"{len(names)} regions"
