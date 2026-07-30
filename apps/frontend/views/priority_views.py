from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.permissions import has_permission, require_page_permission
from apps.core.rbac import Permission
from apps.hr.milestone_allocations import approve_allocation, create_allocation
from apps.hr.models import (
    PriorityMilestone,
    StrategicPriorityCycle,
)
from apps.hr.priority_services import (
    approve_cycle,
    approve_milestone,
    define_milestone,
)


def _permission(permission):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not getattr(request.user, "is_authenticated", False):
                return redirect("/login")
            if not has_permission(request.user, permission):
                return HttpResponseForbidden("Strategic priority access denied.")
            return view(request, *args, **kwargs)

        # The production-readiness route scanner recognises guarded page views
        # by this attribute (the same contract require_page_permission uses).
        wrapped.has_permission_guard = True
        return wrapped

    return decorator


# require_page_permission carries the page↔role mapping the surface inventory
# reads (PAGE_PERMISSIONS["strategic_priorities"]); the permission decorator
# beneath enforces the granular RBAC permission on top of it.
@require_page_permission("strategic_priorities")
@_permission(Permission.STRATEGIC_PRIORITIES_VIEW.value)
def priority_configuration_page(request):
    # Contract carried over from the page this view replaced
    # (hr_views.strategic_priorities_view, see test_priority_cascade):
    # strategy pages are for the RVP/CD/Admin authors plus HR validation —
    # broad STRATEGIC_PRIORITIES_VIEW alone must not open it to every role —
    # and the requested FY is validated/rebuilt, never echoed into filters.
    from apps.core.permissions import render_access_denied
    from apps.frontend.views.hr_views import (
        _STRATEGY_AUTHORS,
        _STRATEGY_VIEWERS,
        _requested_fy,
    )

    role = getattr(request.user, "active_role", "")
    if role not in _STRATEGY_VIEWERS:
        return render_access_denied(
            request,
            "Strategic priorities are set by the RVP and Country Director and "
            "validated by HR.",
        )
    fy = _requested_fy(request)

    cycle = (
        StrategicPriorityCycle.objects.prefetch_related(
            "priorities__milestones__metric_definition",
            "priorities__milestones__allocations",
        )
        .filter(financial_year=fy)
        .first()
    )
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
    from apps.projects.scoping import scoped_projects

    staff = StaffProfile.objects.select_related("user").filter(
        deleted_at__isnull=True,
        user__status="active",
    ).order_by("user__name")
    supervisor_ids = StaffSupervisorAssignment.objects.values_list(
        "supervisor_id", flat=True
    ).distinct()

    return render(
        request,
        "pages/hr/priority_configuration.html",
        {
            "cycle": cycle,
            "fy": fy,
            # Same meaning as the page this replaced: RVP/CD/Admin author
            # strategy; HR reaches the page to validate coverage only.
            "can_author": role in _STRATEGY_AUTHORS,
            "priorities": cycle.priorities.all() if cycle else [],
            "undefined": (
                PriorityMilestone.objects.filter(
                    priority__cycle=cycle, requires_definition=True
                )
                if cycle
                else []
            ),
            "staff": staff,
            "teams": staff.filter(id__in=supervisor_ids),
            "countries": sorted(
                {
                    country
                    for country in staff.values_list("country", flat=True)
                    if country
                }
            ),
            "projects": scoped_projects(request.user),
            "can_define": has_permission(
                request.user, Permission.MILESTONES_DEFINE.value
            ),
            "can_approve": has_permission(
                request.user, Permission.STRATEGIC_PRIORITIES_APPROVE.value
            ),
            "can_allocate": has_permission(
                request.user, Permission.MILESTONES_ALLOCATE.value
            ),
        },
    )


@require_POST
@_permission(Permission.MILESTONES_DEFINE.value)
def milestone_define_action(request, milestone_id):
    milestone = get_object_or_404(PriorityMilestone, id=milestone_id)
    payload = request.POST.dict()
    payload["responsibleRoles"] = request.POST.getlist("responsibleRoles") or request.POST.get(
        "responsibleRoles", ""
    )
    define_milestone(milestone, data=payload, principal=request.user)
    return redirect("/strategic-priorities?fy=" + milestone.priority.fy)


@require_POST
@_permission(Permission.STRATEGIC_PRIORITIES_APPROVE.value)
def milestone_approve_action(request, milestone_id):
    milestone = get_object_or_404(PriorityMilestone, id=milestone_id)
    approve_milestone(milestone, principal=request.user)
    return redirect("/strategic-priorities?fy=" + milestone.priority.fy)


@require_POST
@_permission(Permission.MILESTONES_ALLOCATE.value)
def milestone_allocate_action(request, milestone_id):
    milestone = get_object_or_404(PriorityMilestone, id=milestone_id)
    allocation = create_allocation(
        milestone=milestone,
        data=request.POST.dict(),
        principal=request.user,
    )
    if request.POST.get("approve") == "yes":
        approve_allocation(allocation, principal=request.user)
    return redirect("/strategic-priorities?fy=" + milestone.priority.fy)


@require_POST
@_permission(Permission.STRATEGIC_PRIORITIES_APPROVE.value)
def cycle_approve_action(request, cycle_id):
    cycle = get_object_or_404(StrategicPriorityCycle, id=cycle_id)
    approve_cycle(cycle, principal=request.user)
    return redirect("/strategic-priorities?fy=" + cycle.financial_year)
