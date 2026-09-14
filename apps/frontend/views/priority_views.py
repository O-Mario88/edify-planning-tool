from functools import wraps

from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.permissions import has_permission, require_page_permission
from apps.core.rbac import Permission
from apps.hr.milestone_allocations import approve_allocation, create_allocation
from apps.hr.models import (
    MilestoneAllocationMethod,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
)
from apps.hr.priority_services import (
    approve_cycle,
    approve_milestone,
    define_milestone,
    edit_milestone_targets,
    remove_milestone,
    remove_priority,
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
    # strategy pages are for the RVP/CD authors plus Admin/HR validation —
    # broad STRATEGIC_PRIORITIES_VIEW alone must not open it to every role —
    # and the requested FY is validated/rebuilt, never echoed into filters.
    from apps.core.permissions import render_access_denied
    from apps.frontend.views.hr_views import (
        _STRATEGY_AUTHORS,
        _requested_fy,
    )
    from apps.frontend.views.priority_workspace import (
        PRIORITY_SETTING_VIEWERS,
        priority_workspace_tabs,
        wants_panel_only,
    )

    role = getattr(request.user, "active_role", "")
    # Priority Setting is now a TAB of the Priorities page, so its readers are
    # the page's readers: the strategy authors and validators as before, plus
    # Impact Assessment and the Program Leads the owner added on 2026-09-07.
    # Read only — can_author below still names who may act, and every action
    # keeps its own permission decorator.
    if role not in PRIORITY_SETTING_VIEWERS:
        return render_access_denied(
            request,
            "Strategic priorities are set by the RVP and Country Director and "
            "validated by HR.",
        )
    # Strategy often opens before the operational FY changes.  When navigation
    # does not name a year, open the newest governed cycle instead of showing
    # an empty operational-year page while next year's RVP plan already exists.
    # An explicit (including invalid) value still goes through _requested_fy so
    # the existing validation and safe fallback contract remains intact.
    raw_fy = (request.GET.get("fy") or "").strip()
    if raw_fy:
        fy = _requested_fy(request)
    else:
        fy = StrategicPriorityCycle.objects.exclude(status="archived").order_by(
            "-financial_year"
        ).values_list("financial_year", flat=True).first() or _requested_fy(request)

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

    staff = (
        StaffProfile.objects.select_related("user")
        .filter(
            deleted_at__isnull=True,
            user__status="active",
        )
        .order_by("user__name")
    )
    supervisor_ids = StaffSupervisorAssignment.objects.values_list(
        "supervisor_id", flat=True
    ).distinct()

    priorities = list(cycle.priorities.all()) if cycle else []
    # Linked to the plan (owner, 2026-09-07): every milestone row carries its
    # planned / completed / verified figures against its target, read from
    # the activities that match its rules. One query set for the whole cycle.
    from apps.hr.target_distribution import milestone_plan_progress

    plan_progress = milestone_plan_progress(
        [m for priority in priorities for m in priority.milestones.all()],
        fy=fy,
    )
    group_rows = []
    milestone_rows = []
    milestone_count = 0
    needs_definition_count = 0
    defined_count = 0
    approved_count = 0
    allocation_count = 0
    # Editing and removing (owner, 2026-09-14): the numbers are editable by
    # the roles the matrix gives strategicPriorities.edit — the CD and IA (and
    # the RVP) — and never by the Program Lead, who reads this tab to receive
    # the number they distribute. The same permission gates the POSTs below.
    can_edit = has_permission(request.user, Permission.STRATEGIC_PRIORITIES_EDIT.value)
    for priority in priorities:
        milestones = list(priority.milestones.all())
        milestone_rows.extend(
            {
                "priority": priority,
                "milestone": milestone,
                "progress": plan_progress.get(milestone.id),
                # Allocations are prefetched with the cycle; counting in
                # Python keeps the edit form's warning off the query count.
                "approved_allocation_count": sum(
                    1
                    for allocation in milestone.allocations.all()
                    if allocation.status == "approved"
                ),
                "remove_title": f"Remove {milestone.title} from FY{fy}?",
                "remove_body": (
                    "It leaves this year's priority set for good, with its "
                    "source wording kept in the audit trail. A milestone with "
                    "targets already distributed cannot be removed."
                ),
            }
            for milestone in milestones
        )
        group_needs_definition = sum(
            1 for milestone in milestones if milestone.requires_definition
        )
        group_defined = len(milestones) - group_needs_definition
        group_allocations = sum(
            len(milestone.allocations.all()) for milestone in milestones
        )
        milestone_count += len(milestones)
        needs_definition_count += group_needs_definition
        defined_count += group_defined
        approved_count += sum(
            1 for milestone in milestones if milestone.definition_status == "approved"
        )
        allocation_count += group_allocations
        group_rows.append(
            {
                "priority": priority,
                "milestones": milestones,
                "milestone_count": len(milestones),
                "needs_definition_count": group_needs_definition,
                "defined_count": group_defined,
                "allocation_count": group_allocations,
                "remove_aria": f"Remove {priority.title} from FY{fy}",
                "remove_title": f"Remove {priority.title} from FY{fy}?",
                "remove_body": (
                    f"For a priority the country will not work on this FY. Its "
                    f"{len(milestones)} milestone"
                    f"{'s' if len(milestones) != 1 else ''} leave with it; "
                    "the audit trail keeps what they said. A group with "
                    "targets already distributed cannot be removed."
                ),
            }
        )

    cycle_years = list(
        StrategicPriorityCycle.objects.order_by("-financial_year").values_list(
            "financial_year", flat=True
        )
    )
    if fy not in cycle_years:
        cycle_years.append(fy)

    context = {
        "cycle": cycle,
        "fy": fy,
        # Same meaning as the page this replaced: RVP/CD author strategy;
        # Admin/HR reach the page to validate coverage only.
        "can_author": role in _STRATEGY_AUTHORS,
        "priorities": priorities,
        "group_rows": group_rows,
        # The configuration template paginates this flattened collection.
        # Keeping the priority beside each milestone avoids eagerly
        # rendering every nested definition/allocation form in the cycle.
        "milestone_rows": milestone_rows,
        "plan_progress": plan_progress,
        "linked_count": len(plan_progress),
        "cycle_years": cycle_years,
        "milestone_count": milestone_count,
        "needs_definition_count": needs_definition_count,
        "defined_count": defined_count,
        "approved_count": approved_count,
        "pending_approval_count": milestone_count - approved_count,
        "allocation_count": allocation_count,
        "undefined": (
            PriorityMilestone.objects.filter(
                priority__cycle=cycle, requires_definition=True
            )
            if cycle
            else []
        ),
        "staff": staff,
        "teams": staff.filter(id__in=supervisor_ids),
        "can_edit": can_edit,
        "allocation_methods": MilestoneAllocationMethod.choices,
        "countries": sorted(
            {country for country in staff.values_list("country", flat=True) if country}
        ),
        "projects": scoped_projects(request.user),
        "can_define": has_permission(request.user, Permission.MILESTONES_DEFINE.value),
        "can_approve": has_permission(
            request.user, Permission.STRATEGIC_PRIORITIES_APPROVE.value
        ),
        # Allocating on this page places an approved target with a country,
        # team, employee or project: the distribution authority, which is
        # strategicPriorities.allocate. milestones.allocate alone is the Program
        # Lead's authority to divide their OWN team target on the My Team tab,
        # so on its own it no longer offers this form (Program Lead alignment,
        # 2026-09-13: Priority Setting is read-only for the lead).
        "can_allocate": has_permission(
            request.user, Permission.MILESTONES_ALLOCATE.value
        )
        and has_permission(
            request.user, Permission.STRATEGIC_PRIORITIES_ALLOCATE.value
        ),
    }
    context["dashboard_tabs"] = priority_workspace_tabs(
        request,
        active="setting",
        view_template="partials/priorities/setting_view.html",
    )
    # A tab press asks for the rail and the panel together, to swap into the
    # shell already on the page — the same contract the dashboard views use.
    if context["dashboard_tabs"] and wants_panel_only(request):
        return render(
            request,
            "partials/dashboards/_view_tabs.html",
            {**context, "dashboard_tabs_inner": True},
        )
    return render(request, "pages/hr/priority_configuration.html", context)


@require_POST
@_permission(Permission.MILESTONES_DEFINE.value)
def milestone_define_action(request, milestone_id):
    milestone = get_object_or_404(PriorityMilestone, id=milestone_id)
    payload = request.POST.dict()
    payload["responsibleRoles"] = request.POST.getlist(
        "responsibleRoles"
    ) or request.POST.get("responsibleRoles", "")
    define_milestone(milestone, data=payload, principal=request.user)
    return redirect("/strategic-priorities?fy=" + milestone.priority.fy)


@require_POST
@_permission(Permission.STRATEGIC_PRIORITIES_APPROVE.value)
def milestone_approve_action(request, milestone_id):
    milestone = get_object_or_404(PriorityMilestone, id=milestone_id)
    approve_milestone(milestone, principal=request.user)
    return redirect("/strategic-priorities?fy=" + milestone.priority.fy)


# Both permissions, like the form that posts here (see can_allocate above): a
# Program Lead holds milestones.allocate for their own team distribution and
# must not reach the country-wide allocation door with it.
@require_POST
@_permission(Permission.MILESTONES_ALLOCATE.value)
@_permission(Permission.STRATEGIC_PRIORITIES_ALLOCATE.value)
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


def _back_to_setting(fy: str) -> str:
    return "/strategic-priorities?fy=" + fy


# The three actions the owner asked for on 2026-09-14 — edit the figures,
# remove a milestone, remove a priority group — share one gate, the matrix's
# strategicPriorities.edit (CD, IA, RVP), and one failure contract: a refusal
# the service raises on purpose (BadRequest / Forbidden) is shown back on the
# page as an error flash, never as a 500 or a JSON envelope.
@require_POST
@_permission(Permission.STRATEGIC_PRIORITIES_EDIT.value)
def milestone_edit_action(request, milestone_id):
    milestone = get_object_or_404(
        PriorityMilestone.objects.select_related("priority"), id=milestone_id
    )
    back = _back_to_setting(milestone.priority.fy)
    try:
        edit_milestone_targets(
            milestone, data=request.POST.dict(), principal=request.user
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, f"{milestone.title}: {exc.detail}")
        return redirect(back)
    messages.success(request, f"{milestone.title}: targets saved.")
    return redirect(back)


@require_POST
@_permission(Permission.STRATEGIC_PRIORITIES_EDIT.value)
def milestone_remove_action(request, milestone_id):
    milestone = get_object_or_404(
        PriorityMilestone.objects.select_related("priority"), id=milestone_id
    )
    fy = milestone.priority.fy
    try:
        remove_milestone(
            milestone, principal=request.user, reason=request.POST.get("reason")
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc.detail))
        return redirect(_back_to_setting(fy))
    messages.success(request, f"{milestone.title} removed from FY{fy}.")
    return redirect(_back_to_setting(fy))


@require_POST
@_permission(Permission.STRATEGIC_PRIORITIES_EDIT.value)
def priority_remove_action(request, priority_id):
    priority = get_object_or_404(StrategicPriority, id=priority_id)
    fy = priority.fy
    try:
        removed = remove_priority(
            priority, principal=request.user, reason=request.POST.get("reason")
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc.detail))
        return redirect(_back_to_setting(fy))
    count = len(removed["milestones"])
    messages.success(
        request,
        f"{priority.title} removed from FY{fy} with its {count} "
        f"milestone{'s' if count != 1 else ''}.",
    )
    return redirect(_back_to_setting(fy))
