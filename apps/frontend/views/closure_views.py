from django.db.models import Q
from django.http import Http404
from django.shortcuts import render, redirect
from django.contrib import messages

from apps.core.permissions import require_page_permission
from apps.core.scoping import resolve_user_scope
from apps.activities.models import Activity, ClosureBlocker, AnalyticsPublishRecord
from apps.activities.closure_services import (
    ClosureEligibilityService,
    ActivityClosureService,
    ActivityReopenService,
    AnalyticsPublishingService,
)


def _in_scope(request, queryset):
    """Narrow an Activity queryset to what the caller may actually see.

    @require_page_permission is role-only and does no data scoping, so every
    view in this module previously read and mutated activities country-wide:
    the 'planning' permission is held by CCEO, Program Lead and Project
    Coordinator, any of whom could close or reopen another region's work.
    Closing someone else's activity credits their target and locks their
    budget line, so this is a write hole, not just a read one.
    """
    scope = resolve_user_scope(request.user)
    if scope.country_scope:
        return queryset
    # Activity ownership is a legacy dual-id field: responsible_staff_id holds
    # either a StaffProfile id or a User id depending on which surface wrote
    # it. resolve_user_scope returns only StaffProfile ids, so matching on
    # those alone hides a user's own work from them. The Calendar audience
    # helper documents the same trap.
    staff_ids = list(scope.staff_ids or [])
    for extra in (request.user.id, request.user.staff_profile_id):
        if extra and extra not in staff_ids:
            staff_ids.append(extra)
    partner_ids = list(scope.partner_ids or [])
    school_ids = list(scope.school_ids or [])
    if not (staff_ids or partner_ids or school_ids):
        return queryset.none()
    conds = Q(pk__in=[])
    if staff_ids:
        conds |= Q(responsible_staff_id__in=staff_ids)
    if partner_ids:
        conds |= Q(assigned_partner_id__in=partner_ids)
    if school_ids:
        conds |= Q(school_id__in=school_ids)
    return queryset.filter(conds)


def _scoped_activity(request, activity_id, **extra):
    """Object-level equivalent of _in_scope, for the detail and action views.

    Raises 404 rather than 403 for an out-of-scope activity: confirming that
    an id exists is itself a disclosure.
    """
    activity = _in_scope(
        request, Activity.objects.filter(id=activity_id, **extra)
    ).first()
    if activity is None:
        raise Http404("Activity not found.")
    return activity


@require_page_permission("planning")  # Standard planner/admin roles
def closure_readiness_queue_view(request):
    """Closure Readiness Queue (Filterable Tabs)."""
    # Fetch all activities that are not planned/scheduled (executed or verification loop)
    activities = (
        _in_scope(request, Activity.objects.filter(deleted_at__isnull=True))
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

    # Run evaluation update on activities dynamically to ensure checklist exists.
    # Must cover the full queryset -- the categorization loop below iterates
    # every row in `activities`, so a partial refresh window would leave rows
    # beyond it bucketed on stale/None checklists and able to silently vanish
    # from tabs.
    for a in activities:
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
    a = _scoped_activity(request, activity_id)

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
    a = _scoped_activity(request, activity_id)

    if request.method == "POST":
        try:
            # Analytics only counts as "published" once the activity has
            # actually earned it (executed, evidence, SF ID, IA verified,
            # finance cleared if required) — never force-satisfied, or a
            # failed/ineligible close attempt would leave a false
            # "published" record behind.
            AnalyticsPublishingService.publish_if_ready(a)

            ActivityClosureService.close(a, closed_by=request.user.user_id)
            messages.success(
                request,
                f"Activity #{a.id[:8]} closed, locked, and moved to Completed Activities.",
            )
        except Exception as e:
            messages.error(request, f"Closure failed: {e}")

    return redirect(f"/activities/{a.id}/closure/")


@require_page_permission("completed_activities")
def completed_activities_view(request):
    """Permanent archive list of closed activities."""
    closed_activities = (
        _in_scope(
            request, Activity.objects.filter(deleted_at__isnull=True, status="closed")
        )
        .select_related("school", "cluster", "closure_checklist")
        .order_by("-updated_at")
    )

    context = {"closed": closed_activities}
    return render(request, "pages/closure/completed_activities.html", context)


@require_page_permission("planning")
def completed_activity_detail_view(request, activity_id):
    """Read-only final record details."""
    a = _scoped_activity(request, activity_id, status="closed")
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
    # Scope through the related activity: a blocker names a school and a
    # reason, so listing them all leaks the same information the activity
    # queue would.
    visible = _in_scope(request, Activity.objects.all()).values("id")
    blockers = ClosureBlocker.objects.filter(
        activity_id__in=visible
    ).select_related("activity", "activity__school")

    context = {"blockers": blockers}
    return render(request, "pages/closure/blocked_closure.html", context)


@require_page_permission("planning")
def reopen_activity_action(request, activity_id):
    """POST to reopen activity."""
    a = _scoped_activity(request, activity_id)

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


@require_page_permission("planning")
def activity_timeline_view(request, activity_id):
    """Timeline journey view."""
    a = _scoped_activity(request, activity_id)
    events = a.timeline_events.all().order_by("-timestamp")

    context = {"act": a, "events": events}
    return render(request, "pages/closure/activity_timeline.html", context)


@require_page_permission("analytics_publishing")
def analytics_publishing_status_view(request):
    """Analytics Publishing Status Page."""
    records = AnalyticsPublishRecord.objects.all().select_related(
        "activity", "activity__school"
    )

    context = {"records": records}
    return render(request, "pages/analytics/publishing_status.html", context)
