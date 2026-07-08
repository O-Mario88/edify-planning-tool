from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from apps.core.permissions import require_page_permission
from apps.core.fy import fy_options
from apps.activities.models import Activity, ClosureBlocker, AnalyticsPublishRecord
from apps.activities.closure_services import (
    ClosureEligibilityService,
    ActivityClosureService,
    ActivityReopenService,
    AnalyticsPublishingService,
)


@require_page_permission("planning")  # Standard planner/admin roles
def closure_readiness_queue_view(request):
    """Closure Readiness Queue (Filterable Tabs)."""
    # Fetch all activities that are not planned/scheduled (executed or verification loop)
    activities = (
        Activity.objects.filter(deleted_at__isnull=True)
        .exclude(
            status__in=[
                "not_planned",
                "planned",
                "scheduled",
                "assigned_to_partner",
                "partner_scheduled",
            ]
        )
        .select_related("school", "cluster", "closure_checklist")
        .order_by("-updated_at")
    )

    # Run evaluation update on activities dynamically to ensure checklist exists
    for a in activities[:20]:
        ClosureEligibilityService.evaluate(a)

    # Categorize items into tabs
    ready_list = []
    finance_pending_list = []
    accountability_list = []
    analytics_list = []
    blocked_list = []
    closed_list = []

    for a in activities:
        if a.status == "closed":
            closed_list.append(a)
            continue

        checklist = getattr(a, "closure_checklist", None)
        if not checklist:
            continue

        is_ready = ClosureEligibilityService.is_eligible(a)
        if is_ready:
            ready_list.append(a)
        elif checklist.finance_required and not checklist.accounts_cleared:
            finance_pending_list.append(a)
        elif checklist.finance_required and not checklist.netsuite_id_entered:
            accountability_list.append(a)
        elif not checklist.analytics_published:
            analytics_list.append(a)
        else:
            blocked_list.append(a)

    kpi_strip_items = [
        {
            "label": "Ready to Close",
            "value": str(len(ready_list)),
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Finance Pending",
            "value": str(len(finance_pending_list)),
            "icon": "currency",
            "variant": "warning",
        },
        {
            "label": "Accountability Pending",
            "value": str(len(accountability_list)),
            "icon": "document",
            "variant": "warning",
        },
        {
            "label": "Analytics Pending",
            "value": str(len(analytics_list)),
            "icon": "chart",
            "variant": "info",
        },
        {
            "label": "Blocked",
            "value": str(len(blocked_list)),
            "icon": "warning",
            "variant": "danger",
        },
        {
            "label": "Closed",
            "value": str(len(closed_list)),
            "icon": "shield",
            "variant": "neutral",
        },
    ]

    context = {
        "ready": ready_list,
        "finance_pending": finance_pending_list,
        "accountability_pending": accountability_list,
        "analytics_pending": analytics_list,
        "blocked": blocked_list,
        "closed": closed_list,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/closure/readiness_queue.html", context)


@require_page_permission("planning")
def activity_closure_detail_view(request, activity_id):
    """One full closure workspace for a single activity."""
    a = get_object_or_404(Activity, id=activity_id)

    # Run dynamic evaluate to get latest checklist and blockers
    checklist, blockers = ClosureEligibilityService.evaluate(a)
    is_ready = ClosureEligibilityService.is_eligible(a)

    context = {
        "act": a,
        "checklist": checklist,
        "blockers": blockers,
        "is_ready": is_ready,
        "timeline": a.timeline_events.all().order_by("-timestamp"),
    }
    return render(request, "pages/closure/activity_closure_detail.html", context)


@require_page_permission("planning")
def close_activity_action(request, activity_id):
    """POST action to close activity."""
    a = get_object_or_404(Activity, id=activity_id)

    if request.method == "POST":
        try:
            # Check if analytics is published, if not, publish it first
            AnalyticsPublishingService.publish(a)
            # Re-evaluate
            ClosureEligibilityService.evaluate(a)

            ActivityClosureService.close(a, closed_by=request.user.user_id)
            messages.success(
                request,
                f"Activity #{a.id[:8]} closed, locked, and moved to Completed Activities.",
            )
        except Exception as e:
            messages.error(request, f"Closure failed: {e}")

    return redirect(f"/activities/{a.id}/closure/")


@require_page_permission("planning")
def completed_activities_view(request):
    """Permanent archive list of closed activities."""
    closed_activities = (
        Activity.objects.filter(deleted_at__isnull=True, status="closed")
        .select_related("school", "cluster")
        .order_by("-updated_at")
    )

    fy_filter = request.GET.get("fy", "")
    quarter_filter = request.GET.get("quarter", "")
    if fy_filter:
        closed_activities = closed_activities.filter(fy=fy_filter)
    if quarter_filter:
        closed_activities = closed_activities.filter(quarter=quarter_filter)

    total_closed = closed_activities.count()
    netsuite_linked = (
        closed_activities.filter(netsuite_expenses__isnull=False).distinct().count()
    )

    fy_field_options = [{"value": "", "label": "All FYs", "selected": not fy_filter}]
    for opt in fy_options():
        fy_field_options.append(
            {"value": opt, "label": f"FY{opt}", "selected": fy_filter == opt}
        )
    quarter_field_options = [
        {"value": "", "label": "All Quarters", "selected": not quarter_filter}
    ] + [
        {"value": q, "label": q, "selected": quarter_filter == q}
        for q in ["Q1", "Q2", "Q3", "Q4"]
    ]

    kpi_strip_items = [
        {
            "label": "Closed Activities",
            "value": str(total_closed),
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "NetSuite Linked",
            "value": str(netsuite_linked),
            "icon": "currency",
            "variant": "info",
            "helper": f"of {total_closed}",
        },
    ]

    context = {
        "closed": closed_activities,
        "filters": {"fy": fy_filter, "quarter": quarter_filter},
        "fy_field_options": fy_field_options,
        "quarter_field_options": quarter_field_options,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/closure/completed_activities.html", context)


@require_page_permission("planning")
def completed_activity_detail_view(request, activity_id):
    """Read-only final record details."""
    a = get_object_or_404(Activity, id=activity_id, status="closed")
    snapshot = getattr(a, "completed_snapshot", None)
    checklist = getattr(a, "closure_checklist", None)

    context = {
        "act": a,
        "snapshot": snapshot,
        "checklist": checklist,
        "evidence": a.evidence.all(),
        "timeline": a.timeline_events.all().order_by("-timestamp"),
    }
    return render(request, "pages/closure/completed_detail.html", context)


@require_page_permission("planning")
def blocked_closure_view(request):
    """Blocked Closure Page."""
    blockers = ClosureBlocker.objects.all().select_related(
        "activity", "activity__school"
    )

    from django.db.models import Count

    by_role = {
        row["responsible_role"]: row["n"]
        for row in blockers.values("responsible_role").annotate(n=Count("id"))
    }

    kpi_strip_items = [
        {
            "label": "Total Blockers",
            "value": str(blockers.count()),
            "icon": "warning",
            "variant": "danger",
        },
        {
            "label": "CCEO Action",
            "value": str(by_role.get("CCEO", 0)),
            "icon": "users",
            "variant": "warning",
        },
        {
            "label": "Impact Assessment",
            "value": str(by_role.get("ImpactAssessment", 0)),
            "icon": "shield",
            "variant": "info",
        },
        {
            "label": "Accountant",
            "value": str(by_role.get("Accountant", 0)),
            "icon": "currency",
            "variant": "neutral",
        },
    ]

    context = {"blockers": blockers, "kpi_strip_items": kpi_strip_items}
    return render(request, "pages/closure/blocked_closure.html", context)


@require_page_permission("planning")
def reopen_activity_action(request, activity_id):
    """POST to reopen activity."""
    a = get_object_or_404(Activity, id=activity_id)

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        category = request.POST.get("category", "other")

        try:
            ActivityReopenService.reopen(a, reason, category, request.user.user_id)
            messages.success(
                request,
                f"Activity #{a.id[:8]} reopened and returned to responsible queues.",
            )
        except Exception as e:
            messages.error(request, f"Reopen failed: {e}")

    return redirect(f"/activities/{a.id}/closure/")


@require_page_permission("activity_timeline")
def activity_timeline_view(request, activity_id):
    """Timeline journey view."""
    a = get_object_or_404(Activity, id=activity_id)
    events = a.timeline_events.all().order_by("-timestamp")

    context = {"act": a, "events": events}
    return render(request, "pages/closure/activity_timeline.html", context)


@require_page_permission("planning")
def analytics_publishing_status_view(request):
    """Analytics Publishing Status Page."""
    records = AnalyticsPublishRecord.objects.all().select_related(
        "activity", "activity__school"
    )

    context = {"records": records}
    return render(request, "pages/analytics/publishing_status.html", context)
