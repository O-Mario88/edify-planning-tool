from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from apps.core.permissions import require_page_permission
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

    context = {
        "ready": ready_list,
        "finance_pending": finance_pending_list,
        "accountability_pending": accountability_list,
        "analytics_pending": analytics_list,
        "blocked": blocked_list,
        "closed": closed_list,
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

    context = {"closed": closed_activities}
    return render(request, "pages/closure/completed_activities.html", context)


@require_page_permission("planning")
def completed_activity_detail_view(request, activity_id):
    """Read-only final record details."""
    a = get_object_or_404(Activity, id=activity_id, status="closed")
    snapshot = getattr(a, "completed_snapshot", None)

    context = {
        "act": a,
        "snapshot": snapshot,
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

    context = {"blockers": blockers}
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
