import json

from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from apps.core.htmx_errors import error_fragment
from apps.core.exceptions import BadRequest
from apps.core.permissions import (
    get_visit_target_school_or_404,
    require_any_page_permission,
    require_export_permission,
    require_page_permission,
    RolePermissionService,
    get_operational_cluster_or_404,
    get_operational_school_or_404,
)
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from urllib.parse import urlencode

from apps.planning.services import (
    schedule_cluster_activity,
    schedule_in_school_training_pair,
    schedule_school_visit,
)
from apps.budget.costing_service import preview as cost_preview
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.partners.models import Partner, PartnerAssignment
from apps.partners import services as partner_services
from apps.partners.services import assignable_partners
from apps.partners.purposes import (
    PARTNER_VISIT_PURPOSES,
    STAFF_VISIT_PURPOSES,
    normalise_visit_purpose,
    purpose_activity_type,
    visit_purpose_label,
)
from apps.core.enums import (
    ActivityType,
    SsaIntervention,
    PlanningReadiness,
    SsaStatus,
    SchoolType,
    ClusterStatus,
)
from apps.core.fy import get_operational_fy, get_quarter_for_date, fy_options
from apps.geography.models import District, SubCounty
from apps.accounts.models import StaffProfile
from apps.planning.planning_service import PlanningDashboardService


def _purpose_workflow_profiles(purposes) -> dict:
    """The Workflow Profile behind every purpose the drawer offers (§7).

    The drawer is generated from this, rather than carrying one universal
    form with every possible field and hiding the irrelevant ones. Hiding is
    what produced the participant bug: ``x-show`` removes a field from view
    but the input still submits, so a planner who typed 30 participants for a
    Training and then switched to a Visit posted 30 participants on a visit.

    Keyed by purpose because that is what the planner actually chooses; the
    purpose resolves to an activity type, and the activity type to the one
    standard-support Catalogue item that prices it.
    """
    from apps.activity_catalogue.services import resolve_item_for_workflow_kind

    profiles = {}
    for value, label in purposes:
        workflow_kind = purpose_activity_type(value)
        item = resolve_item_for_workflow_kind(workflow_kind)
        if item is None:
            # No single costing for this purpose. Say so in the profile so
            # the drawer can disable the option with a reason, instead of
            # accepting the choice and failing at submit.
            profiles[value] = {
                "purpose": value,
                "label": label,
                "workflowKind": workflow_kind,
                "schedulable": False,
                "participantMode": "none",
                "requiresParticipants": False,
                "participantsPerSchool": False,
                "participantCategories": False,
                "requiresProject": False,
                "certifiedAgencyDeliveryAllowed": False,
                "unavailableReason": (
                    "No single approved Cost Catalogue entry prices this "
                    "purpose. Ask the Country Director to define one."
                ),
            }
            continue
        profiles[value] = {
            **item.workflow_profile(),
            "purpose": value,
            "label": label,
            "schedulable": True,
            "unavailableReason": "",
        }
    return profiles


def _certified_agency_options(district_name: str = "", activity_type: str = ""):
    from apps.partners.services import bookable_certified_agencies

    return list(
        bookable_certified_agencies(
            district_name=district_name, activity_type=activity_type
        ).values("id", "name")
    )


def _follow_up_requires_training() -> bool:
    """The governed follow-up rule for the operational fiscal year."""
    from apps.planning.fy_policy import follow_up_requires_prior_training

    return follow_up_requires_prior_training(get_operational_fy())


def _school_training_follow_up_options(school) -> list[dict]:
    """Completed current-FY trainings this school did, by either route.

    In-school and Core trainings at the school, and cluster trainings or
    meetings it is recorded as attending (a cluster invitation is not
    attendance). The create service repeats every one of these checks.
    """
    from apps.activities.training_history import follow_up_options

    return follow_up_options(school, fy=get_operational_fy())


def _scheduled_into_own_plan(created, principal) -> tuple[bool, str]:
    """Will the activity just created show on this person's My Plan?

    My Plan selects on `responsible_staff_id` (plus the monitoring staff member
    on partner delivery), and `responsible_staff` is derived from the school's
    owner — never from whoever pressed Schedule. So a country role scheduling
    at somebody else's school creates real work that lands in *their* plan, and
    redirecting the creator to their own My Plan drops them on a page the new
    activity can never appear on. That looks exactly like a failed save.

    Returns the answer and, when it is no, the name of the person who now owns
    the work, so the confirmation can say where it went.
    """
    from apps.accounts.models import StaffProfile
    from apps.activities.models import Activity
    from apps.core.scoping import owner_ids

    activity_id = (created or {}).get("id") if isinstance(created, dict) else None
    if not activity_id:
        return True, ""  # nothing to correct; keep the established behaviour
    activity = (
        Activity.objects.filter(id=activity_id)
        .only("id", "responsible_staff_id", "monitored_by_staff_id", "delivery_type")
        .first()
    )
    if activity is None:
        return True, ""
    mine = set(owner_ids(principal))
    if activity.responsible_staff_id in mine:
        return True, ""
    if activity.delivery_type == "partner" and activity.monitored_by_staff_id in mine:
        return True, ""
    owner = (
        StaffProfile.objects.filter(id=activity.responsible_staff_id)
        .select_related("user")
        .first()
    )
    return False, (owner.user.name if owner and owner.user else "the school's CCEO")


def _no_scheduling_permission_message(user, *, cluster: bool = False) -> str:
    """Why this person cannot schedule, phrased for the person reading it.

    "You do not have permission" is the right answer for a role that simply
    lacks the capability. It is the wrong answer for an Admin, who holds every
    permission there is: nothing is missing, and the refusal is a deliberate
    boundary with a way around it. Saying so stops it reading as a bug in the
    permission system.
    """
    from apps.activities.services import ADMIN_IS_NOT_A_PLANNER_MESSAGE
    from apps.core.rbac import EdifyRole

    if getattr(user, "active_role", None) == EdifyRole.ADMIN.value:
        return ADMIN_IS_NOT_A_PLANNER_MESSAGE
    what = "cluster activities" if cluster else "activities"
    return f"Access Denied: You do not have permission to schedule {what}."


def _calendar_url_for_scheduled_date(raw_date: str | None) -> str:
    """The month of the calendar that does show somebody else's scheduled work.

    The calendar is scoped by role rather than by ownership, so it is the one
    list surface a country role can watch work it planned but does not own.
    """
    from datetime import date

    try:
        scheduled_for = date.fromisoformat(str(raw_date or "")[:10])
    except ValueError:
        return "/calendar"
    return "/calendar?" + urlencode(
        {"month": scheduled_for.month, "year": scheduled_for.year}
    )


def _my_plan_url_for_scheduled_date(raw_date: str | None) -> str:
    """Open My Plan on the month containing a just-saved activity.

    It used to open the WEEK, back when My Plan's own view was a week. That
    view is gone — My Plan now filters by FY, quarter and month and groups the
    rows by month (owner, 2026-09-17) — so a week=N&period=week link landed
    the scheduler on a slice the filter bar can no longer show or clear, and
    any other work they had that month was missing from it.
    """
    from datetime import date

    try:
        scheduled_for = date.fromisoformat(str(raw_date or "")[:10])
    except ValueError:
        return "/my-plan"

    return "/my-plan?" + urlencode(
        {
            "fy": get_operational_fy(scheduled_for),
            "month": scheduled_for.month,
            "period": "month",
        }
    )


def _saved_without_leaving(
    message: str, *, plan_url: str = "", plan_link_label: str = ""
) -> HttpResponse:
    """Confirm a save and stay on the page the planner is working on.

    Owner, 2026-09-18: scheduling used to navigate straight to My Plan, so
    planning a second school meant walking back to the planning page every
    time. The work still lands on My Plan — that never depended on opening it
    — and the planner opens it when they are done rather than once per
    activity.

    Three things have to happen in place of the navigation, or "stay here"
    becomes "did that save?":

    * the drawer closes (`close-drawer`);
    * the list behind it refreshes (`planning-saved`), because a row still
      offering to schedule work that is already scheduled is how the same
      visit gets planned twice;
    * the confirmation is painted now, out-of-band into the toast container.
      `messages.success` paints on a page load, and this flow deliberately has
      none — a queued message would surface on whatever page the planner
      opened next, long after it stopped meaning anything.

    The toast carries the link to My Plan rather than following it.
    """
    html = render_to_string(
        "partials/planning/saved_toast.html",
        {
            "message": message,
            "plan_url": plan_url,
            "plan_link_label": plan_link_label,
        },
    )
    response = HttpResponse(html)
    response["HX-Trigger"] = json.dumps({"close-drawer": True, "planning-saved": True})
    return response


def _scoped_project_assignments(request, raw_ids):
    """Resolve selected School Directory → Project assignments in caller scope."""
    from apps.projects.models import ProjectSchoolAssignment
    from apps.projects.planning_service import _scoped_projects

    ids = [value.strip() for value in str(raw_ids or "").split(",") if value.strip()]
    ids = list(dict.fromkeys(ids))[:50]
    project_ids = _scoped_projects(request.user).values_list("id", flat=True)
    return list(
        ProjectSchoolAssignment.objects.filter(id__in=ids, project_id__in=project_ids)
        .select_related("school", "project")
        .order_by("school__name")
    )


def _common_project_recommendations(assignments, *, principal, executor_type):
    """Only Activities eligible for every selected project-school pair."""
    from apps.activity_catalogue.services import recommend_activities

    by_assignment = {}
    common_ids = None
    representative = {}
    for assignment in assignments:
        result = recommend_activities(
            school=assignment.school,
            principal=principal,
            project=assignment.project,
            executor_type=executor_type,
            limit=100,
        )
        rows = result["primary"]
        keyed = {row["catalogueItemId"]: row for row in rows}
        by_assignment[assignment.id] = keyed
        representative.update(keyed)
        common_ids = (
            set(keyed) if common_ids is None else common_ids.intersection(keyed)
        )
    common = [
        {
            **representative[item_id],
            "recommendationReason": (
                f"Eligible for all {len(assignments)} selected Project School(s)."
            ),
        }
        for item_id in sorted(
            common_ids or set(),
            key=lambda item_id: (
                representative[item_id]["rank"],
                representative[item_id]["displayName"].casefold(),
            ),
        )
    ]
    return common, by_assignment


@require_page_permission("projects")
def special_projects_bulk_schedule_view(request):
    """Schedule the same dated visit for selected project-school pairs."""
    if not RolePermissionService.can_schedule_activity(request.user):
        return HttpResponseForbidden(_no_scheduling_permission_message(request.user))

    assignments = _scoped_project_assignments(
        request,
        request.POST.get("assignments")
        if request.method == "POST"
        else request.GET.get("assignments"),
    )
    if not assignments:
        return HttpResponse("No in-scope project schools were selected.", status=400)

    if request.method == "GET":
        catalogue_items, _ = _common_project_recommendations(
            assignments,
            principal=request.user,
            executor_type="staff",
        )
        return render(
            request,
            "partials/projects/bulk_schedule_drawer.html",
            {
                "assignments": assignments,
                "assignment_ids": ",".join(item.id for item in assignments),
                "interventions": SsaIntervention.choices,
                "drawer_size": "md",
                "catalogue_items": catalogue_items,
            },
        )

    scheduled_date = request.POST.get("scheduled_date", "").strip()
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    if not scheduled_date:
        return HttpResponse(
            '<div class="p-3 text-rose-700 bg-rose-50 rounded-lg">Choose a delivery date.</div>',
            status=400,
        )

    try:
        common, by_assignment = _common_project_recommendations(
            assignments,
            principal=request.user,
            executor_type="staff",
        )
        if catalogue_item_id not in {row["catalogueItemId"] for row in common}:
            raise BadRequest(
                "Select a Catalogue Activity eligible for every selected Project School."
            )
        with transaction.atomic():
            for assignment in assignments:
                recommendation = by_assignment[assignment.id][catalogue_item_id]
                payload = {
                    "schoolId": assignment.school.school_id,
                    "projectId": assignment.project_id,
                    "scheduledDate": scheduled_date,
                    "deliveryType": "staff",
                    "catalogueItemId": catalogue_item_id,
                    "requireCatalogue": True,
                    "focusIntervention": recommendation["targetIntervention"],
                    "recommendationReason": recommendation["recommendationReason"],
                    "activityPurposeText": f"Special project support: {assignment.project.name}",
                    "expectedOutcome": "Complete the planned project support and record evidence.",
                }
                schedule_school_visit(payload, request.user)
        messages.success(
            request, f"Scheduled {len(assignments)} project school activities."
        )
        response = HttpResponse(
            '<script>window.location.href="/projects/my-plan";</script>'
        )
        response["HX-Trigger"] = "close-drawer"
        return response
    except Exception as exc:
        return error_fragment(
            exc, action="Could not schedule the selection", status=400
        )


@require_page_permission("projects")
def special_projects_bulk_partner_view(request):
    """Create traceable partner activities for selected project-school pairs."""
    if not RolePermissionService.can_assign_to_partner(request.user):
        return HttpResponseForbidden(
            "You do not have permission to assign to a partner."
        )

    assignments = _scoped_project_assignments(
        request,
        request.POST.get("assignments")
        if request.method == "POST"
        else request.GET.get("assignments"),
    )
    if not assignments:
        return HttpResponse("No in-scope project schools were selected.", status=400)

    partners = assignable_partners()
    if request.method == "GET":
        catalogue_items, _ = _common_project_recommendations(
            assignments,
            principal=request.user,
            executor_type="partner",
        )
        return render(
            request,
            "partials/projects/bulk_partner_drawer.html",
            {
                "assignments": assignments,
                "assignment_ids": ",".join(item.id for item in assignments),
                "partners": partners,
                "interventions": SsaIntervention.choices,
                "partner_visit_purposes": PARTNER_VISIT_PURPOSES,
                "drawer_size": "md",
                "catalogue_items": catalogue_items,
            },
        )

    from datetime import date

    partner = get_object_or_404(partners, id=request.POST.get("partner_id"))
    scheduled_date = request.POST.get("scheduled_date", "").strip()
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    purpose_of_visit = request.POST.get("purpose_of_visit", "").strip()
    if not scheduled_date:
        return HttpResponse(
            '<div class="p-3 text-rose-700 bg-rose-50 rounded-lg">Choose a partner delivery date.</div>',
            status=400,
        )
    try:
        parsed_date = date.fromisoformat(scheduled_date)
    except ValueError:
        return HttpResponse(
            '<div class="p-3 text-rose-700 bg-rose-50 rounded-lg">Choose a valid delivery date.</div>',
            status=400,
        )

    try:
        common, by_assignment = _common_project_recommendations(
            assignments,
            principal=request.user,
            executor_type="partner",
        )
        if catalogue_item_id not in {row["catalogueItemId"] for row in common}:
            raise BadRequest(
                "Select a Catalogue Activity eligible for every selected Project School."
            )
        from apps.activity_catalogue.services import get_selectable_item
        from apps.ssa.services import latest_applicable_record

        catalogue_item = get_selectable_item(catalogue_item_id)
        # The purpose fallback is the catalogue item's workflow kind, so it
        # can only be normalised once the item is resolved.
        purpose_of_visit = normalise_visit_purpose(
            purpose_of_visit,
            for_partner=True,
            fallback_activity_type=catalogue_item.workflow_kind,
        )
        created = 0
        with transaction.atomic():
            for assignment in assignments:
                recommendation = by_assignment[assignment.id][catalogue_item_id]
                duplicate = PartnerAssignment.objects.filter(
                    school=assignment.school,
                    partner=partner,
                    project_id=assignment.project_id,
                    catalogue_item=catalogue_item,
                    status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
                ).exists()
                if duplicate:
                    continue
                partner_services.create_assignment(
                    school=assignment.school,
                    partner=partner,
                    assigning_staff_id=(
                        request.user.staff_profile_id
                        or request.user.user_id
                        or request.user.id
                    ),
                    assignment_mode="specific_activity",
                    catalogue_item=catalogue_item,
                    project=assignment.project,
                    source_ssa=latest_applicable_record(assignment.school),
                    recommendation_reason=recommendation["recommendationReason"],
                    catalogue_snapshot=catalogue_item.snapshot(),
                    purpose=f"Special project support: {assignment.project.name}",
                    purpose_of_visit=purpose_of_visit,
                    focus_intervention=recommendation["targetIntervention"],
                    expected_activity_type=catalogue_item.workflow_kind,
                    scheduled_date=parsed_date,
                    notes=f"Project: {assignment.project.name}",
                )
                created += 1
        messages.success(
            request, f"Assigned {created} project school activities to {partner.name}."
        )
        response = HttpResponse(
            '<script>window.location.href="/projects/my-plan";</script>'
        )
        response["HX-Trigger"] = "close-drawer"
        return response
    except Exception as exc:
        return error_fragment(exc, action="Could not assign the selection", status=400)


@require_page_permission("planning")
@require_export_permission
def planning_dashboard_view(request):
    fy = request.GET.get("fy") or get_operational_fy()
    priority_allocation_id = (request.GET.get("priority_allocation") or "").strip()
    planning_priority = None
    if priority_allocation_id:
        try:
            from apps.hr.priority_linking import allocation_for_planning

            planning_priority = allocation_for_planning(
                allocation_id=priority_allocation_id, principal=request.user
            )
        except Exception as exc:  # rendered as a normal page-level correction
            messages.error(request, str(exc))
            priority_allocation_id = ""

    # 1. Gather all filters from GET
    filters = {
        "fy": request.GET.get("fy", fy),
        "quarter": request.GET.get(
            "quarter", get_quarter_for_date(timezone.now().date())
        ),
        "district": request.GET.get("district", "All"),
        "sub_county": request.GET.get("sub_county", "All"),
        "staff": request.GET.get("staff", "All"),
        "school_type": request.GET.get("school_type", "All"),
        "planning_readiness": request.GET.get("planning_readiness", "All"),
        "ssa_status": request.GET.get("ssa_status", "All"),
        "cluster_status": request.GET.get("cluster_status", "All"),
        "partner": request.GET.get("partner", "All"),
        "q": request.GET.get("q", ""),
        "tab": request.GET.get("tab", "client"),
        "page": request.GET.get("page", 1),
        "per_page": request.GET.get("per_page", 15),
    }
    # Grouped by Program Lead and CCEO for a country role — IA, the CD — who
    # reads the whole portfolio (owner, 2026-09-11); by name for someone whose
    # portfolio IS their list. Absent means the default; an explicit value,
    # either way, is the reader's choice and travels with every filter.
    _group = request.GET.get("group")
    if _group is None:
        from apps.core.scoping import resolve_user_scope as _rus

        _group = "owner" if _rus(request.user).country_scope else "name"
    filters["group"] = "owner" if _group == "owner" else "name"

    # CSV export of the currently filtered list (same pattern as /clusters).
    if request.GET.get("export", "").strip() == "csv":
        import csv
        from django.http import HttpResponse

        export_filters = dict(filters, page=1, per_page=5000)
        export_data = PlanningDashboardService.get_dashboard_data(
            request.user, export_filters
        )
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="planning_export.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "School ID",
                "Name",
                "District",
                "Type",
                "SSA Status",
                "Weakest Intervention",
                "Planning Readiness",
                "Recommended Action",
                "Owner",
            ]
        )
        for s in export_data["schools"]:
            writer.writerow(
                [
                    s["schoolId"],
                    s["name"],
                    s["district"],
                    s["schoolType"],
                    s["ssaStatus"],
                    s["weakestIntervention"],
                    s["planningReadiness"],
                    s["recommendedAction"],
                    s["ownerName"],
                ]
            )
        return response

    # 2. Query Dashboard data from Service — inside a memo scope, so the
    # page's primers have a store to fill whether or not a middleware opened one.
    from apps.core.request_cache import scoped

    with scoped():
        data = PlanningDashboardService.get_dashboard_data(request.user, filters)

    # 3. Dropdowns options — only places holding schools this user can plan for.
    from apps.core.scoping import resolve_user_scope, school_queryset

    # direct_only, to match the create-time guard. Offering a supervised
    # CCEO's school in a planning dropdown and then refusing the save is the
    # drawer-promises-what-the-service-rejects shape; the team's work belongs
    # on Team Planning Oversight, read-only.
    _planning_schools = school_queryset(
        resolve_user_scope(request.user), direct_only=True
    ).filter(deleted_at__isnull=True)

    districts = (
        District.objects.filter(id__in=_planning_schools.values("district_id"))
        .distinct()
        .order_by("name")
    )

    # Sub-counties narrow to the chosen district as before, but the unfiltered
    # branch no longer offers every sub-county in the country — only those that
    # hold a school in scope, so no option is a dead end.
    if filters["district"] and filters["district"] != "All":
        sub_counties = SubCounty.objects.filter(
            district_id=filters["district"]
        ).order_by("name")
    else:
        sub_counties = (
            SubCounty.objects.filter(
                id__in=_planning_schools.exclude(sub_county__isnull=True).values(
                    "sub_county_id"
                )
            )
            .distinct()
            .order_by("name")
        )

    staff_members = (
        StaffProfile.objects.filter(deleted_at__isnull=True)
        .select_related("user")
        .order_by("user__name")
    )
    # The Staff filter offers the people who HOLD schools in scope, grouped
    # under their Program Lead — the same shape as the grouped list.
    from apps.planning.owner_groups import owner_filter_groups

    owner_groups = owner_filter_groups(_planning_schools)
    partners = assignable_partners()

    # Pagination pages list
    total_pages = data["total_pages"]
    from apps.core.pagination import make_pagination_window

    pages_list = make_pagination_window(
        int(filters["page"]), total_pages, window_size=1
    )

    showing_start = (
        (int(filters["page"]) - 1) * int(filters["per_page"]) + 1
        if data["total_count"] > 0
        else 0
    )
    showing_end = min(
        int(filters["page"]) * int(filters["per_page"]), data["total_count"]
    )

    # Query scheduled activities if tab is scheduled for FullCalendar.js representation
    scheduled_activities = []
    if filters["tab"] == "scheduled":
        from apps.activities.models import Activity

        scheduled_activities = Activity.objects.filter(
            deleted_at__isnull=True,
            status__in=[
                "planned",
                "scheduled",
                "partner_scheduled",
                "in_progress",
                "completed",
                "ia_verified",
            ],
            fy=fy,
        ).select_related("school")
        if request.user.active_role == "CCEO":
            scheduled_activities = scheduled_activities.filter(
                responsible_staff_id=request.user.id
            )

    # Distinguishes "your filters match nothing" from "nothing is clustered
    # yet", which look identical on screen and need opposite responses. Scoped
    # to what this user can see, so a lead whose own team has no clustered
    # school is told that, not told to clear filters that are not the problem.
    any_clustered_school = (
        _planning_schools.filter(cluster_status="clustered")
        .exclude(cluster_id__isnull=True)
        .exclude(cluster_id="")
        .exists()
    )

    from apps.core.permissions import has_permission as _has_permission
    from apps.core.rbac import Permission as _Permission

    # 4. Construct context
    context = {
        "any_clustered_school": any_clustered_school,
        # Field events (district meetings, boot camps…) plan from the same
        # governed drawer the Work Plan uses; the button needs the same gate.
        "can_add_non_school_activity": _has_permission(
            request.user, _Permission.MANUAL_ACTIVITY_CREATE.value
        ),
        "schools": data["schools"],
        "clusters": data.get("clusters", []),
        "kpis": data["kpis"],
        "kpi_strip_items": data.get("kpi_strip_items", []),
        "cluster_planning": data["cluster_planning"],
        "core_summary": data["core_summary"],
        "total_count": data["total_count"],
        "scheduled_activities": scheduled_activities,
        # Options
        "districts": districts,
        "sub_counties": sub_counties,
        "staff_members": staff_members,
        "owner_groups": owner_groups,
        "selected_group": filters["group"],
        "group_by_owner": filters["group"] == "owner",
        "partners": partners,
        "fy_options": fy_options(),
        "quarter_options": ["Q1", "Q2", "Q3", "Q4"],
        "school_types": SchoolType.choices,
        "readiness_choices": PlanningReadiness.choices,
        "ssa_statuses": SsaStatus.choices,
        "cluster_statuses": ClusterStatus.choices,
        "interventions": SsaIntervention.choices,
        # Selected filters/states
        "selected_fy": filters["fy"],
        "selected_quarter": filters["quarter"],
        "selected_district": filters["district"],
        "selected_sub_county": filters["sub_county"],
        "selected_staff": filters["staff"],
        "selected_school_type": filters["school_type"],
        "selected_readiness": filters["planning_readiness"],
        "selected_ssa_status": filters["ssa_status"],
        "selected_cluster_status": filters["cluster_status"],
        "selected_partner": filters["partner"],
        "search_q": filters["q"],
        "active_tab": filters["tab"],
        # Pagination
        "page": int(filters["page"]),
        "per_page": int(filters["per_page"]),
        "total_pages": total_pages,
        "pages_list": pages_list,
        "showing_start": showing_start,
        "showing_end": showing_end,
        # Base Template choice for HTMX vs direct visits
        "base_template": "layouts/blank.html"
        if request.headers.get("HX-Request") == "true"
        and not request.headers.get("HX-Target")
        else "layouts/shell.html",
        "use_dark_sidebar": False,
        # Guards. A request-only country role gets the same button: the
        # drawer it opens files a request for the owner to decide, not a plan.
        "can_schedule": _may_open_schedule_drawer(request.user),
        # Cluster meetings and trainings are the cluster owner's programme;
        # the request-only country roles schedule school visits only.
        "can_plan_clusters": RolePermissionService.can_schedule_activity(request.user),
        "can_assign_partner": RolePermissionService.can_assign_to_partner(request.user),
        "planning_priority": planning_priority,
        "priority_allocation_id": priority_allocation_id,
    }

    # If the target is only the school table
    if request.headers.get("HX-Target") == "schools-table-container":
        context["is_planning_htmx_table"] = True
        return render(request, "partials/planning/school_table.html", context)

    # One persistent search: the top bar, attached to the page filter form.
    context["topbar_search"] = {
        "placeholder": "Search planning schools…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "hx_get": "/planning",
        "hx_target": "#schools-table-container",
        "hx_trigger": "keyup changed delay:250ms, search",
        "hx_include": "#filters-form",
    }
    return render(request, "pages/planning/index.html", context)


def _may_open_schedule_drawer(user) -> bool:
    """Planners plan; the request-only country roles ask. Same drawer."""
    return RolePermissionService.can_schedule_activity(
        user
    ) or RolePermissionService.can_request_school_visit(user)


def _requester_identity(user) -> str | None:
    return (
        getattr(user, "staff_profile_id", None)
        or getattr(user, "user_id", None)
        or getattr(user, "id", None)
    )


@require_any_page_permission("planning", "visit_requests")
def schedule_modal_view(request):
    if not _may_open_schedule_drawer(request.user):
        return HttpResponseForbidden(_no_scheduling_permission_message(request.user))

    priority_allocation_id = (request.GET.get("priority_allocation") or "").strip()
    planning_priority = None
    if priority_allocation_id:
        from apps.hr.priority_linking import allocation_for_planning

        planning_priority = allocation_for_planning(
            allocation_id=priority_allocation_id, principal=request.user
        )
    cluster_id = request.GET.get("cluster_id")
    # `action` on its own opens the cluster drawer with no cluster chosen yet:
    # that is how the Clusters page's own "Schedule Group Training" and
    # "Schedule Cluster Meeting" buttons arrive, since they name the kind of
    # session but not which cluster. One drawer serves both (owner,
    # 2026-09-17: "make sure that the cluster planning (group training and
    # meeting) scheduling is uniform irrespective of where the user is
    # planning from"), so the picker appears exactly when the caller did not
    # bring a cluster.
    wants_cluster = request.GET.get("action") in ("training", "meeting")
    if cluster_id or wants_cluster:
        if not RolePermissionService.can_schedule_activity(request.user):
            from apps.planning.visit_requests import CLUSTER_REFUSED

            return HttpResponseForbidden(CLUSTER_REFUSED)
        # The same list the Clusters page's own drawer offers, from the same
        # canonical scoping helper (owner, 2026-09-17: "Use the same cluster
        # list on the cluster page everywhere"). cluster_queryset is the set
        # form of cluster_in_scope, so the picker cannot offer a cluster the
        # service would then refuse.
        from apps.core.scoping import cluster_queryset, resolve_user_scope

        pickable = cluster_queryset(
            resolve_user_scope(request.user), direct_only=True
        ).filter(status="active")
        if cluster_id:
            cluster = get_operational_cluster_or_404(request.user, id=cluster_id)
        else:
            cluster = pickable.first()
            if cluster is None:
                return HttpResponse(
                    '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface '
                    'text-[12px] font-bold">No cluster in your reach yet. '
                    "Create one on the Clusters page first.</div>",
                    status=400,
                )
        # Fixed when the caller named the cluster — from a cluster card, a
        # cluster profile or a Planning row. Pickable when they did not, and
        # `pick` keeps it pickable across the re-render the chooser triggers,
        # which necessarily arrives WITH a cluster_id.
        fixed_cluster = bool(cluster_id) and not request.GET.get("pick")
        action = request.GET.get("action", "training")
        partners = assignable_partners()
        from apps.clusters.services import active_school_count, active_schools
        from apps.activity_catalogue.availability import (
            CLUSTER,
            training_activity_options,
        )

        training_options = (
            training_activity_options(planning_context=CLUSTER, cluster=cluster)
            if action == "training"
            else []
        )
        # Ticked by name rather than counted into a box, so the number that
        # multiplies into the budget is derived from the list and the two
        # cannot disagree — and completion opens with the register already
        # filled in. Everyone is ticked on first open, which is what the
        # number it replaces defaulted to.
        member_schools = [
            {"id": s.id, "name": s.name, "school_id": s.school_id, "invited": True}
            for s in active_schools(cluster.id)
        ]
        # Owner, 2026-09-13: cluster sessions are SSA informed too. The drawer
        # used to offer a course or a meeting with no member evidence at all;
        # it now shows the verified need across the member schools, puts the
        # courses that answer a cluster priority first, and preselects the
        # weakest intervention for a meeting (apps.ssa.plan_alignment).
        from apps.ssa.plan_alignment import cluster_need

        ssa_need = cluster_need(cluster.id)
        need_by_code = {row["intervention"]: row for row in ssa_need.rows}
        for option in training_options:
            row = need_by_code.get(option.get("ssaIntervention"))
            option["addressesPriority"] = (
                option.get("ssaIntervention") in ssa_need.priorities
            )
            option["clusterAverage"] = row["average"] if row else None
            option["label"] = (
                f"{option['label']} · priority need"
                if option["addressesPriority"]
                else option["label"]
            )
        training_options.sort(key=lambda option: not option["addressesPriority"])

        from apps.accounts.models import StaffProfile

        context = {
            "cluster": cluster,
            # The picker and its list, so the Clusters page's cluster-less
            # entry points render one drawer with a chooser rather than a
            # second drawer of their own.
            "clusters": pickable.order_by("name"),
            "fixed_cluster": fixed_cluster,
            # Who the session belongs to. A Programme Lead or Admin may hand
            # it to somebody else; everybody else sees their own name, which
            # is what the Clusters drawer did and the reason it existed
            # alongside this one.
            "staff_profiles": StaffProfile.objects.filter(deleted_at__isnull=True)
            .select_related("user")
            .order_by("user__name"),
            "action": action,
            "partners": partners,
            "interventions": SsaIntervention.choices,
            "drawer_size": "md",
            # Read-only, and from the canonical counter. The drawer shows it so
            # the multiplication is visible; the backend recomputes it at
            # submission so a stale drawer cannot price an activity.
            "cluster_school_count": active_school_count(cluster.id),
            "member_schools": member_schools,
            "schools_invited": len(member_schools),
            "training_activity_options": training_options,
            "training_activity_options_json": json.dumps(training_options),
            # §16 — certified agencies only. `partners` above is the ordinary
            # assignable-partner list and must not be offered for booking.
            "certified_agencies": _certified_agency_options(
                district_name=(cluster.district.name if cluster.district_id else "")
            ),
            "planning_priority": planning_priority,
            "priority_allocation_id": priority_allocation_id,
            "ssa_need": ssa_need,
            "ssa_need_rows": ssa_need.rows[:4],
            "ssa_priority_rows": [
                row
                for row in ssa_need.rows
                if row["intervention"] in ssa_need.priorities
            ],
            "selected_focus_intervention": (
                ssa_need.priorities[0]
                if action == "meeting" and ssa_need.priorities
                else ""
            ),
            "intervention_need_options": [
                (code, label, need_by_code.get(code))
                for code, label in SsaIntervention.choices
            ],
        }
        return render(
            request, "partials/planning/schedule_cluster_drawer.html", context
        )

    school_id = request.GET.get("school_id")
    school = get_visit_target_school_or_404(
        request.user, Q(id=school_id) | Q(school_id=school_id)
    )
    # The school's own visit rule (owner, 2026-09-15). The Schedule button is
    # greyed for the same reason; a stale row or a typed URL gets the
    # sentence, not a form the service will refuse.
    from apps.planning.visit_gate import visit_gate

    _gate = visit_gate(school)
    if _gate.staff_locked:
        return render(
            request,
            "partials/schools/drawer_error.html",
            {"error": _gate.staff_locked_reason},
        )
    # A used follow-up visit greys the visit purposes; in-school training,
    # donor and social visits stay open (owner, 2026-09-15). For a core
    # school the follow-up purposes are general support outside the package
    # and stay open; the package's own visits are gated on the Core page.
    from apps.planning.visit_gate import FOLLOW_UP_PURPOSES

    locked_visit_purposes = (
        list(FOLLOW_UP_PURPOSES)
        if _gate.rule == "client" and not _gate.staff_can_schedule
        else []
    )
    locked_visit_reason = _gate.staff_reason if locked_visit_purposes else ""
    project_id = request.GET.get("project_id", "")
    from apps.activity_catalogue.services import recommend_activities

    catalogue_recommendations = recommend_activities(
        school=school,
        principal=request.user,
        project=project_id or None,
        executor_type="staff",
        limit=3,
    )
    primary_catalogue_items = catalogue_recommendations["primary"]
    other_catalogue_items = catalogue_recommendations["otherEligible"]
    first_catalogue_item = (
        primary_catalogue_items[0] if primary_catalogue_items else None
    )

    # Resolve focus recommendations
    recommendations = []
    latest_ssa = (
        school.ssa_records.filter(
            deleted_at__isnull=True, verification_status="confirmed"
        )
        .order_by("-date_of_ssa")
        .first()
    )
    if latest_ssa:
        # Canonical ranking — the inline ascending sort had no tie-break, so
        # tied scores ordered nondeterministically and this surface disagreed
        # with the engine on ~19% of schools.
        from apps.ssa.recommendation_engine import prioritized_interventions

        # The drawer names these as "performing poorly", so only interventions
        # that actually are may appear. prioritized_interventions returns the
        # LOWEST scoring, which is not the same thing: a school whose two
        # weakest are 1.0 and 9.0 was being shown a 9.0/10 under that heading.
        # A number presented as a problem when it is not is how people stop
        # believing the numbers.
        from apps.core.enums import ssa_score_band

        for item in prioritized_interventions(school, n=4):
            score = item.get("score")
            band, _hex, _tone = ssa_score_band(score)
            if band in ("Strong", "No SSA"):
                continue
            code = item["intervention"]
            label = dict(SsaIntervention.choices).get(code, code)
            recommendations.append(
                {"code": code, "label": label, "score": score, "band": band}
            )
            if len(recommendations) == 3:
                break

    partners = assignable_partners()

    school_activity_types = {
        ActivityType.SCHOOL_VISIT,
        ActivityType.FOLLOW_UP_VISIT,
        ActivityType.COACHING_VISIT,
        ActivityType.IN_SCHOOL_SUPPORT,
        ActivityType.DONOR_VISIT,
        ActivityType.STORY_GATHERING_VISIT,
        ActivityType.SCHOOL_INVITATION,
        ActivityType.SOCIAL_VISIT,
        ActivityType.TRAINING_FOLLOW_UP_VISIT,
        ActivityType.IN_SCHOOL_COACHING_VISIT,
        ActivityType.IN_SCHOOL_TRAINING,
        ActivityType.SCHOOL_IMPROVEMENT_TRAINING,
        ActivityType.BASELINE_SSA_VISIT,
        ActivityType.SCHOOL_VISIT_SSA_COLLECTION,
    }
    ssa_collection_activity_types = {
        ActivityType.BASELINE_SSA_VISIT,
        ActivityType.SCHOOL_VISIT_SSA_COLLECTION,
        ActivityType.SCHOOL_VISIT,
    }
    recommended_activity_type = (
        first_catalogue_item["workflowKind"]
        if first_catalogue_item
        else request.GET.get("recommended_activity_type", ActivityType.SCHOOL_VISIT)
    )
    if recommended_activity_type not in school_activity_types:
        recommended_activity_type = ActivityType.SCHOOL_VISIT
    if school.current_fy_ssa_status != "done" and recommended_activity_type not in {
        ActivityType.BASELINE_SSA_VISIT,
        ActivityType.SCHOOL_VISIT_SSA_COLLECTION,
        ActivityType.SCHOOL_VISIT,
    }:
        recommended_activity_type = ActivityType.BASELINE_SSA_VISIT
    recommended_activity_label = (
        first_catalogue_item["displayName"]
        if first_catalogue_item
        else dict(ActivityType.choices).get(recommended_activity_type, "School Visit")
    )
    # The chooser is derived from the same enum accepted by the scheduling
    # service.  Do not let a recommendation title drift from the form value:
    # every option rendered here is a valid direct-school ActivityType.
    # A missing SSA is a useful prompt, not a reason to block other school
    # support. Field teams may still need to host a donor visit, collect a
    # story, or provide time-sensitive coaching before SSA is complete.
    selectable_activity_types = (
        school_activity_types
        if school.current_fy_ssa_status != "done"
        else school_activity_types - ssa_collection_activity_types
    )
    activity_type_options = [
        (value, label)
        for value, label in ActivityType.choices
        if value in selectable_activity_types
    ]
    # The focus a standard purpose opens on is the need the SSA ranks first.
    # It used to be the first NAMED catalogue suggestion's target, which is a
    # lower need whenever the top one has no school-level course — the drawer
    # then headed itself "Top SSA recommendation: Financial Health" while the
    # focus select read Leadership (2026-09-13).
    from apps.ssa.plan_alignment import school_need

    ranked_need = school_need(school)
    recommended_focus_intervention = (
        request.GET.get("focus_intervention", "")
        or (ranked_need.priorities[0] if ranked_need.priorities else "")
        or (first_catalogue_item["targetIntervention"] if first_catalogue_item else "")
    )
    recommended_visit_purpose = normalise_visit_purpose(
        None,
        for_partner=False,
        fallback_activity_type=recommended_activity_type,
    )

    from apps.activity_catalogue.availability import (
        in_school_training_course_options,
    )

    training_options = in_school_training_course_options(
        school=school,
    )
    follow_up_options = _school_training_follow_up_options(school)
    responsible_staff_id, responsible_staff_name = resolve_monitoring_staff(
        school, request.user
    )
    # A request-only role at somebody else's school: the drawer asks for the
    # reason, names the owner who will decide, and files the visit against the
    # person going rather than the person being asked.
    from apps.planning.visit_requests import approval_owner_for, staff_name

    visit_request_owner_id = approval_owner_for(school, request.user)
    visit_request_owner_name = ""
    if visit_request_owner_id:
        visit_request_owner_name = (
            staff_name(visit_request_owner_id) or "the school's owner"
        )
        responsible_staff_id = _requester_identity(request.user)
        responsible_staff_name = getattr(request.user, "name", "") or "You"

    context = {
        "school": school,
        "visit_request_owner_name": visit_request_owner_name,
        "recommendations": recommendations,
        "interventions": SsaIntervention.choices,
        "partners": partners,
        "drawer_size": "md",
        "recommended_activity_type": recommended_activity_type,
        "recommended_activity_label": recommended_activity_label,
        "activity_type_options": activity_type_options,
        "recommended_focus_intervention": recommended_focus_intervention,
        # What the drawer warns against: a focus outside the SSA's priorities.
        "ssa_priorities_json": json.dumps(list(ranked_need.priorities)),
        "ssa_top_label": dict(SsaIntervention.choices).get(
            ranked_need.priorities[0] if ranked_need.priorities else "", ""
        ),
        "ssa_stale": ranked_need.stale,
        "staff_visit_purposes": STAFF_VISIT_PURPOSES,
        # Drives which purposes stay selectable when delivery is Partner.
        "partner_visit_purposes": PARTNER_VISIT_PURPOSES,
        "locked_visit_purposes": locked_visit_purposes,
        "locked_visit_reason": locked_visit_reason,
        "recommended_visit_purpose": (
            ""
            if recommended_visit_purpose in locked_visit_purposes
            else recommended_visit_purpose
        ),
        "catalogue_recommendations": catalogue_recommendations,
        "primary_catalogue_items": primary_catalogue_items,
        "other_catalogue_items": other_catalogue_items,
        "selected_catalogue_item": first_catalogue_item,
        # Optional project context — stamps the scheduled activity so it flows
        # into the Special Projects dashboard / analytics / My Plan. Never
        # required for ordinary support: a Project is asked for only when the
        # selected purpose's Workflow Profile says requiresProject.
        "project_id": project_id,
        # §7/§29 — the drawer's fields come from here, one profile per purpose.
        "purpose_profiles": json.dumps(
            _purpose_workflow_profiles(STAFF_VISIT_PURPOSES)
        ),
        # General training scheduling chooses the governed Activity itself.
        # The selected intervention filters this list in the drawer and the
        # same mapping is validated again by activities.services.create().
        "training_activity_options": training_options,
        "training_activity_options_json": json.dumps(training_options),
        "follow_up_activity_options": follow_up_options,
        "follow_up_activity_options_json": json.dumps(follow_up_options),
        "follow_up_fy": get_operational_fy(),
        "follow_up_requires_training": _follow_up_requires_training(),
        "responsible_staff_id": responsible_staff_id,
        "responsible_staff_name": responsible_staff_name,
        "certified_agencies": _certified_agency_options(
            district_name=(school.district.name if school.district_id else "")
        ),
        "planning_priority": planning_priority,
        "priority_allocation_id": priority_allocation_id,
    }
    return render(request, "partials/planning/schedule_drawer.html", context)


@require_any_page_permission("planning", "visit_requests")
def schedule_action_view(request):
    if not _may_open_schedule_drawer(request.user):
        return HttpResponseForbidden(_no_scheduling_permission_message(request.user))

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    activity_type = request.POST.get("activity_type", "school_visit")
    purpose_of_visit = request.POST.get("purpose_of_visit", "").strip()
    school_id = request.POST.get("school_id")
    cluster_id = request.POST.get("cluster_id")
    scheduled_date = (request.POST.get("scheduled_date") or "").strip()
    focus_intervention = request.POST.get("focus_intervention")
    purpose_type = request.POST.get("purpose_type", "focus_intervention")
    purpose_text = (
        request.POST.get("activity_goal")
        or request.POST.get("activity_purpose_text")
        or ""
    ).strip()
    expected_outcome = request.POST.get("expected_outcome", "").strip()
    expected_participants = request.POST.get("expected_participants", "").strip()
    participants_per_school = request.POST.get("participants_per_school", "").strip()
    schools_invited = request.POST.get("schools_invited", "").strip()
    # Cluster work is planned per member school, and by category: who is
    # invited from each school, not just how many. The per-school figure is
    # their sum and is derived in the service, so the drawer never sends one.
    teachers_per_school = request.POST.get("teachers_per_school", "").strip()
    leaders_per_school = request.POST.get("leaders_per_school", "").strip()
    other_per_school = request.POST.get("other_per_school", "").strip()
    teachers_attended = request.POST.get("teachers_attended", "").strip()
    leaders_attended = request.POST.get("leaders_attended", "").strip()
    other_participants = request.POST.get("other_participants", "").strip()
    delivery_type = request.POST.get("delivery_type", "staff")
    # §14 — which of the three delivery models. The service is the authority
    # on what this means for status, executor and My Plan ownership; the view
    # only passes the planner's choice through.
    executor_type = request.POST.get("executor_type", "").strip()
    partner_id = request.POST.get("assigned_partner_id", "").strip()
    # A Project id is accepted only as context from a Project-owned entry
    # point. General training drawers no longer ask the planner to choose one.
    project_id = request.POST.get("project_id", "").strip()
    priority_allocation_id = request.POST.get("priority_allocation_id", "").strip()
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    recommendation_reason = request.POST.get("recommendation_reason", "").strip()
    override_reason = request.POST.get("override_reason", "").strip()
    # One read. The second assignment used to overwrite the first and drop the
    # `or None`, so an unset field arrived as "" instead of None.
    source_activity_id = request.POST.get("source_activity_id", "").strip() or None

    # Imported before first use, not further down: a function-local import
    # binds the name for the whole function scope.
    from datetime import datetime

    # A date, refused here rather than trusted from the form.
    #
    # The drawer marks its date input `required`, but the input is
    # `type="hidden"` (the visible control is an Alpine calendar that writes
    # into it), and browsers skip constraint validation on hidden inputs
    # entirely. So the attribute never blocked anything: submitting without
    # picking a day posted an empty string, which flowed through as
    # `scheduledDate: ""` and persisted an activity with scheduled_date NULL.
    #
    # That activity is real but unreachable — every plan surface selects by
    # date, so it appears in no week, month, quarter or calendar — and its
    # daily rates cannot be priced without a day, so it also costs nothing.
    # A planner sees the drawer close successfully and then cannot find the
    # visit anywhere: the exact shape of "scheduling does not save".
    #
    # The bulk and cluster paths already refuse this; the single-activity
    # path, which is the one the drawers use most, did not.
    if not scheduled_date:
        return error_fragment(
            BadRequest("Pick the date this is planned for before scheduling it."),
            status=400,
        )
    try:
        datetime.fromisoformat(scheduled_date)
    except ValueError:
        return error_fragment(
            BadRequest("That scheduled date is not a valid calendar date."),
            status=400,
        )

    if cluster_id and activity_type == "cluster_training":
        if not catalogue_item_id:
            return error_fragment(
                BadRequest("Select the Training to deliver."),
                status=400,
            )
        try:
            from apps.activity_catalogue.availability import (
                CLUSTER,
                validate_priority_training_selection,
            )

            selected_training = validate_priority_training_selection(
                catalogue_item_id,
                planning_context=CLUSTER,
            )
            focus_intervention = selected_training["ssaIntervention"] or None
        except BadRequest as exc:
            return error_fragment(exc, status=400)
    if school_id and purpose_of_visit == "in_school_training":
        if not catalogue_item_id:
            return error_fragment(
                BadRequest("Select the Training to deliver."),
                status=400,
            )
        try:
            from apps.activity_catalogue.availability import (
                validate_in_school_training_course_selection,
            )

            selected_training = validate_in_school_training_course_selection(
                catalogue_item_id,
            )
            focus_intervention = selected_training["ssaIntervention"] or None
        except BadRequest as exc:
            return error_fragment(exc, status=400)
    if request.POST.get("require_catalogue") == "yes" and not catalogue_item_id:
        # The drawer asks for a purpose, not a catalogue row. Derive the
        # costing link from the purpose before refusing: purpose ->
        # activity type (PURPOSE_ACTIVITY_TYPES) -> the catalogue item that
        # costs that type. This keeps every scheduled visit costed against the
        # CD catalogue exactly as before, while leaving the field officer with
        # the one question they can actually answer.
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind

        derived_type = (
            purpose_activity_type(purpose_of_visit, activity_type)
            if purpose_of_visit
            else activity_type
        )
        resolved = resolve_item_for_workflow_kind(derived_type)
        if resolved is not None:
            catalogue_item_id = resolved.id
        else:
            # Either nothing costs this purpose, or more than one thing does.
            # Both are catalogue-governance problems and both need a person,
            # so say which purpose could not be costed rather than asking for
            # a catalogue item the drawer never offered.
            label = visit_purpose_label(purpose_of_visit, fallback=derived_type)
            return error_fragment(
                ValueError(
                    f"No single approved Catalogue Activity costs "
                    f"\u201c{label}\u201d. Ask the Country Director to define "
                    f"one costing for it before scheduling this purpose."
                ),
                status=400,
            )

    # Purpose of Visit is the plain-language reason staff select. Activity
    # Type stays an internal/costing classification, derived from that reason
    # whenever the refreshed form supplies one. Legacy clients can continue
    # posting a raw activity_type while their forms are rolled forward.
    if purpose_of_visit:
        try:
            purpose_of_visit = normalise_visit_purpose(
                purpose_of_visit,
                for_partner=delivery_type == "partner" or bool(partner_id),
                fallback_activity_type=activity_type,
            )
        except Exception as exc:
            return error_fragment(exc, status=400)
        activity_type = purpose_activity_type(purpose_of_visit, activity_type)

        # Reconcile the pinned catalogue item with the purpose the planner
        # actually chose. The drawer writes catalogue_item_id ONCE, from the
        # SSA-ranked top recommendation, and never rebinds it when Purpose of
        # Visit changes (the Core drawers do rebind, on @change). Because
        # services.create() takes activity_type from catalogue_item
        # .workflow_kind, a stale pin silently overrode the planner: choosing
        # "Donor Visit" at a school whose top pick was an in-school training
        # created -- and costed, and reported -- an in_school_training.
        #
        # Only a genuine conflict counts. A governed item may carry a broader
        # kind than the purpose's own (an SSA-recommended curriculum title is
        # `training` while "In-school Training" derives `in_school_training`),
        # and several governed items can share one kind -- which is exactly
        # why the drawer posts the visible recommendation instead of letting
        # the ambiguity-safe resolver refuse. So the pin is only overridden
        # when its kind is the signature kind of a DIFFERENT purpose, i.e.
        # when the planner demonstrably named something else.
        if catalogue_item_id and not cluster_id:
            from apps.activity_catalogue.models import ActivityCatalogueItem
            from apps.activity_catalogue.services import (
                resolve_item_for_workflow_kind,
            )
            from apps.partners.purposes import PURPOSE_ACTIVITY_TYPES

            purpose_of_kind = {
                kind: purpose for purpose, kind in PURPOSE_ACTIVITY_TYPES.items()
            }
            pinned = ActivityCatalogueItem.objects.filter(id=catalogue_item_id).first()
            conflicting = (
                pinned is not None
                and pinned.workflow_kind != activity_type
                and purpose_of_kind.get(pinned.workflow_kind)
                not in (None, purpose_of_visit)
            )
            if conflicting:
                resolved = resolve_item_for_workflow_kind(activity_type)
                if resolved is None:
                    label = visit_purpose_label(
                        purpose_of_visit, fallback=activity_type
                    )
                    return error_fragment(
                        ValueError(
                            f"No single approved Catalogue Activity costs "
                            f"“{label}”. Ask the Country Director to "
                            f"define one costing for it before scheduling this "
                            f"purpose."
                        ),
                        status=400,
                    )
                catalogue_item_id = resolved.id
                # That reason described the SSA recommendation for the item we
                # just replaced; keeping it would attribute this activity to a
                # recommendation it no longer follows.
                recommendation_reason = ""

    if cluster_id and not catalogue_item_id:
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind

        resolved = resolve_item_for_workflow_kind(activity_type)
        if resolved is None:
            return error_fragment(
                BadRequest(
                    "No single approved Activity Catalogue item costs this "
                    "cluster activity. Ask the Country Director to configure it."
                ),
                status=400,
            )
        catalogue_item_id = resolved.id

    # Build payload
    is_ssa_expected = request.POST.get(
        "ssa_collection_expected"
    ) == "yes" or activity_type in [
        "baseline_ssa_visit",
        "school_visit_ssa_collection",
        "cluster_training_ssa_collection",
        "cluster_meeting_ssa_review",
        "partner_ssa_collection",
        "core_assessment_visit",
    ]
    payload = {
        "activityType": activity_type,
        "scheduledDate": scheduled_date,
        "activityPurposeText": purpose_text,
        "purposeType": purpose_of_visit or purpose_type,
        "expectedOutcome": expected_outcome,
        "deliveryType": delivery_type,
        "ssaCollectionExpected": is_ssa_expected,
        "catalogueItemId": catalogue_item_id,
        "requireCatalogue": True,
        "recommendationReason": recommendation_reason,
        "overrideReason": override_reason,
        # The drawers ask a planner to explain a plan the SSA does not
        # support (apps.activities.services.create; owner, 2026-09-14).
        "requireSsaReason": True,
        "ssaDeviationReason": request.POST.get("ssa_deviation_reason", ""),
    }
    if source_activity_id:
        payload["sourceActivityId"] = source_activity_id

    if scheduled_date:
        try:
            dt = datetime.fromisoformat(scheduled_date).date()
            payload["plannedMonth"] = dt.month
            payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
        except ValueError:
            pass

    visit_request_owner_id = None
    if school_id:
        payload["schoolId"] = school_id
        # School scheduling is owned by the portfolio owner, not whichever
        # authorised staff member happened to open the drawer.  Resolve again
        # on POST so a forged/stale hidden field cannot reassign the work.
        owner_school = get_visit_target_school_or_404(
            request.user, Q(id=school_id) | Q(school_id=school_id)
        )
        responsible_staff_id, _name = resolve_monitoring_staff(
            owner_school, request.user
        )
        from apps.planning.visit_requests import approval_owner_for

        visit_request_owner_id = approval_owner_for(owner_school, request.user)
        if visit_request_owner_id:
            # Asking, not planning: the requester is the one going, and the
            # reason travels with the request. The service refuses a request
            # without one.
            responsible_staff_id = _requester_identity(request.user)
            payload["visitJustification"] = request.POST.get(
                "visit_justification", ""
            ).strip()
        if delivery_type == "staff" and not partner_id:
            payload["responsibleStaffId"] = responsible_staff_id
    if cluster_id:
        payload["clusterId"] = cluster_id
        # Who the cluster session belongs to. The drawer offers this only to a
        # Programme Lead or Admin (the roles the Clusters drawer offered it
        # to), and it is honoured only for those roles here, so a crafted POST
        # cannot hand somebody else's name to the work. Anyone else's session
        # is resolved downstream from the cluster, exactly as before.
        from apps.core.rbac import EdifyRole

        chosen_staff = (request.POST.get("responsible_staff_id") or "").strip()
        if chosen_staff and getattr(request.user, "active_role", "") in (
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            EdifyRole.ADMIN.value,
        ):
            payload["responsibleStaffId"] = chosen_staff
    if focus_intervention:
        payload["focusIntervention"] = focus_intervention
        payload["purposeIntervention"] = focus_intervention
    if purpose_type and not purpose_of_visit:
        payload["purposeType"] = purpose_type
    if expected_participants:
        payload["expectedParticipants"] = int(expected_participants)
    if participants_per_school:
        # Passed through as-is; activities.services validates it and derives
        # the total from live cluster membership, overwriting any
        # expectedParticipants the form happened to carry. The browser's
        # multiplication is a preview, not an input.
        payload["participantsPerSchool"] = participants_per_school
    if schools_invited:
        payload["schoolsInvited"] = schools_invited
    # The schools ticked by name. Without them the session recorded no
    # invitation at all, so nothing could tell a checked school from one that
    # happened to walk in (the Core training credit reads both).
    invited_school_ids = [
        s.strip() for s in request.POST.getlist("invited_school_ids") if s.strip()
    ]
    if cluster_id and invited_school_ids:
        payload["invitedSchoolIds"] = invited_school_ids
        payload["schoolsInvited"] = str(len(invited_school_ids))
    for key, raw in (
        ("teachersPerSchool", teachers_per_school),
        ("leadersPerSchool", leaders_per_school),
        ("otherPerSchool", other_per_school),
    ):
        if raw:
            payload[key] = raw
    # Training materials by the page (owner, 2026-09-15). Passed through as
    # typed; the service reads a blank as none and refuses a non-number.
    for key, form_key in (
        ("printingPages", "printing_pages"),
        ("photocopyPages", "photocopy_pages"),
        ("photocopyCopies", "photocopy_copies"),
    ):
        raw = request.POST.get(form_key, "").strip()
        if raw:
            payload[key] = raw
    for key, raw in (
        ("teachersAttended", teachers_attended),
        ("leadersAttended", leaders_attended),
        ("otherParticipants", other_participants),
    ):
        if raw:
            payload[key] = raw
    if executor_type:
        payload["executorType"] = executor_type
    if partner_id:
        payload["assignedPartnerId"] = partner_id
    if project_id:
        payload["projectId"] = project_id
    if priority_allocation_id:
        payload["priorityAllocationId"] = priority_allocation_id

    try:
        if school_id:
            # A single scheduled visit uses the same direct, immediate-cost
            # workflow as training and meetings.  Daily batching remains a
            # planning/reporting tool for deliberate bulk schedules, not a
            # set of rules that can prevent a field worker from booking work.
            if purpose_of_visit == "in_school_training":
                created = schedule_in_school_training_pair(payload, request.user)
                noun = "In-school training and school visit"
            else:
                created = schedule_school_visit(payload, request.user)
                noun = "School visit"
        else:
            created = schedule_cluster_activity(payload, request.user)
            noun = "Cluster activity"
        if visit_request_owner_id:
            # Not on anyone's plan yet. Say who decides and where to follow it.
            from apps.planning.visit_requests import QUEUE_URL, staff_name

            who = staff_name(visit_request_owner_id) or "the school's owner"
            return _saved_without_leaving(
                f"Requested, pending {who}'s approval. It takes effect on your "
                "plan and enters your budget once approved.",
                plan_url=QUEUE_URL,
                plan_link_label="Open the request queue",
            )
        # Confirm where it went, not just that it happened. When the work is
        # filed against somebody else the creator must be told so, because the
        # next screen will not show it and silence there reads as a failure.
        lands_here, owner_name = _scheduled_into_own_plan(created, request.user)
        # The link still has to point somewhere the work is actually visible.
        # My Plan is scoped to the viewer's own work, so offering it for an
        # activity filed against somebody else is offering a blank page as
        # proof of success — that one points at the Calendar instead.
        #
        # "/my-plan" has no trailing-slash route and APPEND_SLASH is off, so
        # "/my-plan/" 404s; `_my_plan_url_for_scheduled_date` builds the
        # working form.
        if project_id:
            plan_url, link_label = "/projects/my-plan", "Open My Plan"
        elif lands_here:
            plan_url = _my_plan_url_for_scheduled_date(scheduled_date)
            link_label = "Open My Plan"
        else:
            plan_url = _calendar_url_for_scheduled_date(scheduled_date)
            link_label = "Open the Calendar"
        if lands_here:
            message = f"{noun} scheduled. It is on your My Plan — keep planning."
        else:
            message = (
                f"{noun} scheduled onto {owner_name}'s My Plan, because the "
                "responsible staff member comes from the school's owner."
            )
        return _saved_without_leaving(
            message, plan_url=plan_url, plan_link_label=link_label
        )
    except Exception as e:
        return error_fragment(e, status=400)


@require_page_permission("planning")
def assign_partner_modal_view(request):
    if not RolePermissionService.can_assign_to_partner(request.user):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to assign to partner."
        )

    school_id = request.GET.get("school_id")
    cluster_id = request.GET.get("cluster_id")

    school = None
    cluster = None
    locked_visit_purposes: list[str] = []
    locked_visit_reason = ""
    if school_id:
        school = get_operational_school_or_404(
            request.user, Q(id=school_id) | Q(school_id=school_id)
        )
        from apps.planning.visit_gate import visit_gate

        _gate = visit_gate(school)
        if not _gate.can_assign_partner:
            return render(
                request,
                "partials/schools/drawer_error.html",
                {"error": _gate.assign_reason},
            )
        from apps.planning.visit_gate import FOLLOW_UP_PURPOSES

        if _gate.rule == "client" and not _gate.can_assign_visit:
            locked_visit_purposes = list(FOLLOW_UP_PURPOSES)
            locked_visit_reason = _gate.assign_visit_reason
    if cluster_id:
        cluster = get_operational_cluster_or_404(request.user, id=cluster_id)

    partners = assignable_partners()
    partner_catalogue_recommendations = None
    if cluster:
        from apps.activity_catalogue.services import recommend_cluster_activities

        partner_catalogue_recommendations = recommend_cluster_activities(
            cluster=cluster,
            principal=request.user,
            project=None,
            executor_type="partner",
            limit=3,
        )

    from apps.activity_catalogue.availability import SCHOOL, training_activity_options

    partner_training_options = [
        option
        for option in training_activity_options(
            planning_context=SCHOOL,
            school=school,
            executor_type="partner",
        )
        if option["partnerDeliveryAllowed"]
    ]
    follow_up_options = _school_training_follow_up_options(school) if school else []

    context = {
        "school": school,
        "cluster": cluster,
        "partners": partners,
        "interventions": SsaIntervention.choices,
        "drawer_size": "md",
        "drawer_type": "center",
        "recommended_focus_intervention": request.GET.get("focus_intervention", ""),
        "partner_visit_purposes": PARTNER_VISIT_PURPOSES,
        "locked_visit_purposes": locked_visit_purposes,
        "locked_visit_reason": locked_visit_reason,
        "catalogue_recommendations": partner_catalogue_recommendations,
        "primary_catalogue_items": (
            partner_catalogue_recommendations["primary"]
            if partner_catalogue_recommendations
            else []
        ),
        "other_catalogue_items": (
            partner_catalogue_recommendations["otherEligible"]
            if partner_catalogue_recommendations
            else []
        ),
        # Who monitors the partner. Never a field to fill: the school already
        # belongs to somebody, so asking again invites a different answer from
        # the assignment record and two versions of who is accountable.
        "monitoring_staff_name": request.user.name or "You",
        "training_activity_options_json": json.dumps(partner_training_options),
        "follow_up_activity_options_json": json.dumps(follow_up_options),
        "follow_up_fy": get_operational_fy(),
        "follow_up_requires_training": _follow_up_requires_training(),
        # What happened to this school's partner work before. Shown because
        # the person choosing a partner is the one who most needs to know the
        # last one was withdrawn for capacity — and because handing the same
        # school back to the partner it was just taken from is a mistake worth
        # catching before it is made rather than after.
        "prior_withdrawals": _prior_withdrawals(school),
    }
    return render(request, "partials/planning/assign_partner_drawer.html", context)


def _prior_withdrawals(school):
    """This school's withdrawal history, newest first.

    Attribution travels with each one, so a partner withdrawn because the
    school was closed does not read here as a partner who failed.
    """
    if school is None:
        return []
    from apps.partners.withdrawal_models import (
        PartnerAssignmentWithdrawal,
        WithdrawalState,
    )

    return [
        {
            "partner": getattr(w.partner, "name", ""),
            "kind": w.get_kind_display(),
            "reason": w.get_reason_category_display(),
            "attribution": w.get_attribution_display(),
            "counts_against_partner": w.counts_against_partner,
            "when": w.effective_at or w.requested_at,
        }
        for w in PartnerAssignmentWithdrawal.objects.filter(school=school)
        .exclude(state__in=(WithdrawalState.REJECTED, WithdrawalState.CANCELLED))
        .select_related("partner")
        .order_by("-requested_at")[:5]
    ]


def resolve_monitoring_staff(school, actor):
    """Who owns school work and monitors a partner handoff.

    The single resolver behind the scheduling drawer's Responsible Person,
    the partner drawer's "Monitored by" line, and both persisted identities.
    They must agree — naming the school's owner while storing whoever clicked
    would promise accountability to one person and put the work on another
    person's My Plan.

    Falls back to the person handing off when there is nobody to fall back
    *from*: a cluster has no single owner, and a school may not be assigned
    yet. Returns (staff_profile_id, display_name).
    """
    if school is not None:
        from apps.planning.action_service import ResponsibleActorService

        staff, _role = ResponsibleActorService.for_school(school.id)
        if staff:
            name = getattr(getattr(staff, "user", None), "name", "")
            if name:
                return staff.id, name
        # ``account_owner_id`` is the canonical portfolio-owner column. Some
        # imported schools predate the StaffSchoolAssignment projection, so
        # use the canonical owner before falling back to the person clicking.
        from apps.clusters.eligibility import portfolio_owner_profile_id

        owner_id = portfolio_owner_profile_id(school)
        owner = (
            StaffProfile.objects.filter(id=owner_id, deleted_at__isnull=True)
            .select_related("user")
            .first()
            if owner_id
            else None
        )
        if owner and owner.user_id:
            return (
                owner.id,
                owner.user.name or school.account_owner_name_raw or "Staff owner",
            )
    return (
        getattr(actor, "staff_profile_id", None)
        or getattr(actor, "user_id", None)
        or getattr(actor, "id", None),
        getattr(actor, "name", "") or "You",
    )


@require_page_permission("planning")
def assign_partner_action_view(request):
    if not RolePermissionService.can_assign_to_partner(request.user):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to assign to partner."
        )

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    school_id = request.POST.get("school_id")
    cluster_id = request.POST.get("cluster_id")
    partner_id = request.POST.get("partner_id")
    activity_type = request.POST.get("activity_type", "school_visit")
    purpose_of_visit = request.POST.get("purpose_of_visit", "").strip()
    focus_intervention = request.POST.get("focus_intervention") or None
    purpose = request.POST.get("purpose", "").strip()
    notes = request.POST.get("notes", "").strip() or None
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    recommendation_reason = request.POST.get("recommendation_reason", "").strip()
    override_reason = request.POST.get("override_reason", "").strip()
    source_activity_id = request.POST.get("source_activity_id", "").strip() or None

    # School support handoffs are not Project planning. The assignment holds
    # the approved support reason and the Partner supplies the delivery date.
    project_id = None
    expected_date = None

    try:
        partner = get_object_or_404(Partner, id=partner_id)
        catalogue_item = None
        source_ssa = None
        source_activity = None
        if school_id or cluster_id:
            from apps.activity_catalogue.services import (
                get_selectable_item,
                resolve_activity_intervention,
                resolve_assignment_item,
                validate_context,
            )
            from apps.ssa.services import latest_applicable_record

            school_for_validation = (
                get_operational_school_or_404(
                    request.user, Q(id=school_id) | Q(school_id=school_id)
                )
                if school_id
                else None
            )
            cluster_for_validation = (
                get_operational_cluster_or_404(request.user, id=cluster_id)
                if cluster_id
                else None
            )
            if school_for_validation:
                purpose_of_visit = normalise_visit_purpose(
                    purpose_of_visit,
                    for_partner=True,
                    fallback_activity_type=activity_type,
                )
                if purpose_of_visit == "in_school_training":
                    if not catalogue_item_id:
                        raise BadRequest("Select the Activity / Training to assign.")
                    from apps.activity_catalogue.availability import (
                        SCHOOL,
                        validate_priority_training_selection,
                    )

                    selected_training = validate_priority_training_selection(
                        catalogue_item_id,
                        planning_context=SCHOOL,
                    )
                    focus_intervention = selected_training["ssaIntervention"] or None
                    if not selected_training["partnerDeliveryAllowed"]:
                        raise BadRequest(
                            "The selected Activity / Training is not approved for "
                            "Partner delivery."
                        )
                    linked_priorities = ", ".join(selected_training["priorityTitles"])
                    recommendation_reason = (
                        f"Priority activity: {linked_priorities}"
                        if linked_priorities
                        else f"Governed {selected_training['category']} training."
                    )
                else:
                    derived = resolve_assignment_item(
                        purpose_of_visit=purpose_of_visit,
                        expected_activity_type=purpose_activity_type(
                            purpose_of_visit, activity_type
                        ),
                    )
                    if derived is None:
                        raise BadRequest(
                            "No approved Partner Activity is configured for this reason."
                        )
                    catalogue_item_id = derived.id
                    recommendation_reason = (
                        f"{visit_purpose_label(purpose_of_visit)} selected by "
                        "the assigning staff member."
                    )
            elif not catalogue_item_id:
                raise BadRequest("Select an approved Activity Catalogue item.")

            catalogue_item = get_selectable_item(catalogue_item_id)
            activity_type = catalogue_item.workflow_kind
            validate_context(
                catalogue_item,
                school=school_for_validation,
                cluster=cluster_for_validation,
                project=None,
                executor_type="partner",
            )
            source_ssa = (
                latest_applicable_record(school_for_validation)
                if school_for_validation
                else None
            )
            if (
                school_for_validation
                and purpose_of_visit == "training_follow_up"
                and not source_activity_id
            ):
                from apps.planning.fy_policy import follow_up_requires_prior_training

                if follow_up_requires_prior_training(get_operational_fy()):
                    raise BadRequest(
                        "Select the completed training this assignment follows up."
                    )
                if not focus_intervention:
                    # No prior training recorded, and the policy allows the
                    # follow-up (owner, 2026-09-15): the SSA's first-ranked
                    # need is what the partner's visit is meant to move.
                    from apps.ssa.plan_alignment import school_need

                    need = school_need(school_for_validation)
                    focus_intervention = need.priorities[0] if need.priorities else None
            elif school_for_validation and purpose_of_visit == "training_follow_up":
                from apps.activities.models import Activity

                eligible_source_ids = {
                    option["id"]
                    for option in _school_training_follow_up_options(
                        school_for_validation
                    )
                }
                if source_activity_id not in eligible_source_ids:
                    raise BadRequest(
                        "Choose a completed current-FY training this School did."
                    )
                source_activity = Activity.objects.filter(
                    id=source_activity_id,
                    deleted_at__isnull=True,
                ).first()
                focus_intervention = source_activity.focus_intervention
            elif source_activity_id:
                raise BadRequest(
                    "A source session is only valid for Training Follow Up."
                )
            if (
                catalogue_item.requires_current_ssa
                and school_for_validation
                and source_ssa is None
                and purpose_of_visit != "training_follow_up"
            ):
                raise BadRequest(
                    "Complete the School SSA first. Intervention-specific support "
                    "cannot be assigned without an applicable SSA."
                )
            focus_intervention = resolve_activity_intervention(
                catalogue_item,
                requested_intervention=focus_intervention,
                source_activity=source_activity,
            )
            if cluster_for_validation and not recommendation_reason:
                recommendation_reason = "Approved Cluster Activity assignment."

        # PartnerAssignment and Activity.monitor fields use the StaffProfile
        # CUID when one exists.  Falling back to the User id keeps Admins
        # without a profile attributable without creating a second identity
        # scheme for normal field staff.
        monitored_by_staff_id = (
            request.user.staff_profile_id or request.user.user_id or request.user.id
        )

        # Idempotency guard: a double-click or a retried htmx POST must not
        # create a second PartnerAssignment (and, worse, a second costed
        # Activity + budget line) for the same handoff. A near-identical row
        # created moments ago by the same staff member is treated as the
        # same submission, not a new one.
        DEDUP_WINDOW = timezone.timedelta(seconds=15)

        def _recent_duplicate(*, school=None, cluster=None, act_type):
            qs = PartnerAssignment.objects.filter(
                partner=partner,
                assigning_staff_id=monitored_by_staff_id,
                expected_activity_type=act_type,
                created_at__gte=timezone.now() - DEDUP_WINDOW,
            )
            qs = (
                qs.filter(school=school)
                if school is not None
                else qs.filter(cluster=cluster)
            )
            return qs.order_by("-created_at").first()

        if school_id:
            school = get_operational_school_or_404(
                request.user, Q(id=school_id) | Q(school_id=school_id)
            )
            purpose_of_visit = normalise_visit_purpose(
                purpose_of_visit,
                for_partner=True,
                fallback_activity_type=activity_type,
            )
            assignment_purpose = purpose or catalogue_item.display_name
            normalized_type = catalogue_item.workflow_kind
            # The person making the handoff remains its monitor. This is the
            # same identity shown read-only in the drawer.
            monitoring_staff_id = monitored_by_staff_id
            dup = _recent_duplicate(school=school, act_type=normalized_type)
            if dup:
                response = _saved_without_leaving(
                    f"{school.name} already has this work planned, so nothing "
                    "was added.",
                    plan_url="/projects/my-plan" if project_id else "",
                )
                return response
            # §F fail-fast at ASSIGNMENT: if this school's partner allowance
            # is already used this FY, the assigner finds out here — not the
            # partner, days later, at scheduling. The scheduling-time check
            # stays as the authoritative last gate.
            from apps.partners.services import assert_partner_activity_allowance

            assert_partner_activity_allowance(
                partner.id,
                school.id,
                normalized_type,
                get_operational_fy(expected_date)
                if expected_date
                else get_operational_fy(),
            )
            # A school already visited this year, or already with a partner,
            # is not handed over again (owner, 2026-09-15). The Assign button
            # is greyed for the same reason; a stale row lands here.
            from apps.planning.visit_gate import (
                assert_may_assign_partner_visit,
                is_gated_visit,
                rule_for,
                visit_gate,
            )

            _gate = visit_gate(school)
            if not _gate.can_assign_partner:
                raise BadRequest(_gate.assign_reason)
            if is_gated_visit(
                rule_for(school.school_type), normalized_type, catalogue_item
            ):
                assert_may_assign_partner_visit(school)
            with transaction.atomic():
                partner_services.create_assignment(
                    school=school,
                    partner=partner,
                    assigning_staff_id=monitored_by_staff_id,
                    monitoring_staff_id=monitoring_staff_id,
                    assignment_mode="specific_activity",
                    catalogue_item=catalogue_item,
                    source_ssa=source_ssa,
                    source_activity=source_activity,
                    project_id=project_id,
                    recommendation_reason=recommendation_reason,
                    override_reason=override_reason,
                    catalogue_snapshot=catalogue_item.snapshot(),
                    purpose=assignment_purpose,
                    purpose_of_visit=purpose_of_visit,
                    focus_intervention=focus_intervention,
                    expected_activity_type=normalized_type,
                    scheduled_date=expected_date,
                    notes=notes,
                )

        if cluster_id:
            cluster = get_operational_cluster_or_404(request.user, id=cluster_id)
            assignment_purpose = purpose or catalogue_item.display_name
            act_type = catalogue_item.workflow_kind
            dup = _recent_duplicate(cluster=cluster, act_type=act_type)
            if dup:
                response = HttpResponse("<script>window.location.reload();</script>")
                response["HX-Trigger"] = "close-drawer"
                return response
            with transaction.atomic():
                # Create PartnerAssignment for cluster
                partner_services.create_assignment(
                    cluster=cluster,
                    partner=partner,
                    assigning_staff_id=monitored_by_staff_id,
                    assignment_mode="specific_activity",
                    catalogue_item=catalogue_item,
                    source_activity=source_activity,
                    project_id=project_id,
                    recommendation_reason=recommendation_reason,
                    override_reason=override_reason,
                    catalogue_snapshot=catalogue_item.snapshot(),
                    purpose=assignment_purpose,
                    focus_intervention=focus_intervention,
                    expected_activity_type=act_type,
                    scheduled_date=expected_date,
                    notes=notes,
                )

        # Close the drawer and refresh the list in place rather than reloading
        # the page or leaving it: an assigner works through a list of schools,
        # and a full reload costs them their scroll position and their filters
        # after every single one (owner, 2026-09-18).
        return _saved_without_leaving(
            f"Assigned to {partner.name}. The partner schedules it from here.",
            plan_url="/projects/my-plan" if project_id else "/partner-assignments",
            plan_link_label=(
                "Open My Plan" if project_id else "Open partner assignments"
            ),
        )
    except Exception as e:
        return error_fragment(e, status=400)


@require_page_permission("planning")
def planning_intelligence_view(request):
    school_id = request.GET.get("school_id")
    if not school_id:
        return HttpResponse(
            '<p class="text-slate-400 text-[11.5px] font-bold py-6 text-center">Select a school to view planning intelligence.</p>'
        )

    # Scoped lookup — this panel returned any school's latest SSA date,
    # weakest intervention and score for an arbitrary ?school_id=. The same
    # file already uses the scoped helper twice; this call site did not.
    from apps.core.scoping import resolve_user_scope, school_queryset

    school = (
        school_queryset(resolve_user_scope(request.user))
        .filter(Q(id=school_id) | Q(school_id=school_id))
        .first()
    )
    if not school:
        return HttpResponse(
            '<p class="text-rose-500 text-[11.5px] font-bold py-6 text-center">School not found.</p>'
        )

    # Fetch latest SSA date
    latest_ssa = (
        school.ssa_records.filter(
            deleted_at__isnull=True, verification_status="confirmed"
        )
        .order_by("-date_of_ssa")
        .first()
    )
    last_ssa_date = latest_ssa.date_of_ssa.strftime("%d %b %Y") if latest_ssa else "—"

    # Weakest area
    weakest_area = "—"
    if latest_ssa:
        from apps.ssa.recommendation_engine import prioritized_interventions

        ranked = prioritized_interventions(school, n=1)
        if ranked:
            weakest_area = dict(SsaIntervention.choices).get(
                ranked[0]["intervention"], ranked[0]["intervention"]
            )

    # Assigned staff
    assigned_staff = "—"
    if school.account_owner_id:
        owner_profile = (
            StaffProfile.objects.filter(user_id=school.account_owner_id)
            .select_related("user")
            .first()
        )
        if owner_profile:
            assigned_staff = owner_profile.user.name

    # recommended step
    recommended_step = "Schedule visit"
    recommended_desc = "SSA is complete and the school is ready for planning."

    if school.current_fy_ssa_status != "done":
        recommended_step = "Upload SSA before planning"
        recommended_desc = "SSA has not been recorded for this FY yet."
    elif not school.cluster_id:
        recommended_step = "Assign school to cluster"
        recommended_desc = "School must be grouped in a cluster first."
    elif not school.account_owner_id:
        recommended_step = "Match staff profile"
        recommended_desc = "Staff matching is required for accountability."

    # Cluster name
    cluster_name = "—"
    if school.cluster_id:
        c_obj = Cluster.objects.filter(id=school.cluster_id).first()
        if c_obj:
            cluster_name = c_obj.name

    context = {
        "school": school,
        "last_ssa_date": last_ssa_date,
        "weakest_intervention": weakest_area,
        "assigned_staff": assigned_staff,
        "recommended_step": recommended_step,
        "recommended_desc": recommended_desc,
        "cluster_name": cluster_name,
    }
    return render(request, "partials/planning/right_panel.html", context)


@require_page_permission("planning")
@require_export_permission
def bulk_action_view(request):
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    action = request.POST.get("action")
    school_ids = request.POST.getlist("school_ids")

    if not school_ids:
        return HttpResponse("No schools selected", status=400)

    from apps.core.scoping import resolve_user_scope, school_queryset

    # The Planning table's own scope. Every bulk action used to accept any
    # school code posted to it: the export wrote out schools in other
    # portfolios and countries, and the partner action assigned work there
    # (2026-09-13). The schedule action's funnel checked scope per school; the
    # other two never did.
    schools = school_queryset(
        resolve_user_scope(request.user), direct_only=True
    ).filter(deleted_at__isnull=True, school_id__in=school_ids)
    if schools.count() != len(set(school_ids)):
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">'
            "One or more selected schools are outside your planning portfolio."
            "</div>",
            status=403,
        )

    if action == "export":
        # CSV Export simple response
        import csv

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="bulk_planning_export.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            ["School ID", "Name", "District", "Cluster", "Planning Readiness"]
        )
        for s in schools:
            writer.writerow(
                [
                    s.school_id,
                    s.name,
                    s.district.name,
                    s.cluster_id or "—",
                    s.planning_readiness,
                ]
            )
        return response

    elif action == "partner":
        # Bulk Assign Partner
        if not RolePermissionService.can_assign_to_partner(request.user):
            return HttpResponseForbidden(
                "Access Denied: You do not have permission to assign to partner."
            )

        partner_id = request.POST.get("partner_id")
        if not partner_id:
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Select a partner before confirming.</div>',
                status=400,
            )
        partner = get_object_or_404(Partner, id=partner_id)
        from datetime import date as _date
        from apps.activity_catalogue.services import recommend_activities
        from apps.ssa.services import latest_applicable_record

        bulk_date_raw = request.POST.get("scheduled_date", "").strip()
        bulk_date = None
        if bulk_date_raw:
            try:
                bulk_date = _date.fromisoformat(bulk_date_raw)
            except ValueError:
                pass

        monitored_by_staff_id = (
            request.user.staff_profile_id or request.user.user_id or request.user.id
        )
        dedup_window = timezone.timedelta(seconds=15)

        try:
            with transaction.atomic():
                for s in schools:
                    result = recommend_activities(
                        school=s,
                        principal=request.user,
                        executor_type="partner",
                        limit=1,
                    )
                    if not result["primary"]:
                        raise BadRequest(
                            f"No Partner-deliverable Catalogue Activity is eligible for {s.name}."
                        )
                    recommendation = result["primary"][0]
                    if PartnerAssignment.objects.filter(
                        school=s,
                        partner=partner,
                        assigning_staff_id=monitored_by_staff_id,
                        catalogue_item_id=recommendation["catalogueItemId"],
                        created_at__gte=timezone.now() - dedup_window,
                    ).exists():
                        continue
                    from apps.activity_catalogue.models import ActivityCatalogueItem

                    item = ActivityCatalogueItem.objects.get(
                        id=recommendation["catalogueItemId"]
                    )
                    partner_services.create_assignment(
                        school=s,
                        partner=partner,
                        assigning_staff_id=monitored_by_staff_id,
                        assignment_mode="specific_activity",
                        catalogue_item=item,
                        source_ssa=latest_applicable_record(s),
                        recommendation_reason=recommendation["recommendationReason"],
                        catalogue_snapshot=item.snapshot(),
                        purpose=item.display_name,
                        purpose_of_visit="ssa_support",
                        focus_intervention=recommendation["targetIntervention"],
                        expected_activity_type=item.workflow_kind,
                        scheduled_date=bulk_date,
                        notes=(
                            "Bulk Partner Assignment · final schedule and cost pending"
                        ),
                    )
            return HttpResponse("<script>window.location.reload();</script>")
        except Exception as exc:
            return error_fragment(exc, status=400)

    elif action == "schedule":
        # Each School uses its own top eligible Catalogue recommendation.
        if not RolePermissionService.can_schedule_activity(request.user):
            return HttpResponseForbidden(
                _no_scheduling_permission_message(request.user)
            )

        from datetime import date as _date

        scheduled_date_raw = request.POST.get("scheduled_date", "").strip()
        if not scheduled_date_raw:
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Scheduled date is required.</div>',
                status=400,
            )
        try:
            _date.fromisoformat(scheduled_date_raw)
        except ValueError:
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Invalid date.</div>',
                status=400,
            )

        from apps.activity_catalogue.services import recommend_activities
        from apps.activities.services import create as create_activity

        try:
            with transaction.atomic():
                from apps.activity_catalogue.services import (
                    resolve_item_for_workflow_kind,
                )

                standard_visit = resolve_item_for_workflow_kind("school_visit")
                for school in schools:
                    result = recommend_activities(
                        school=school,
                        principal=request.user,
                        executor_type="staff",
                        limit=1,
                    )
                    recommendation = result["primary"][0] if result["primary"] else None
                    unmet = result.get("unmetPriority")
                    if (
                        standard_visit is not None
                        and result.get("hasApplicableSsa")
                        and (recommendation is None or unmet)
                    ):
                        # SSA informed: when no named school-level activity
                        # answers the school's top need, a standard school
                        # visit targets that need rather than a named activity
                        # for a lesser one (or a refusal).
                        need = result["priority"]
                        payload = {
                            "catalogueItemId": standard_visit.id,
                            "focusIntervention": need["intervention"],
                            "recommendationReason": (
                                f"{need['label']} is {need['band']} at "
                                f"{need['score']}/10, the school's top SSA need."
                            ),
                        }
                    elif recommendation is not None:
                        payload = {
                            "catalogueItemId": recommendation["catalogueItemId"],
                            "focusIntervention": recommendation["targetIntervention"],
                            "recommendationReason": recommendation[
                                "recommendationReason"
                            ],
                        }
                    else:
                        raise BadRequest(
                            f"No staff-deliverable Catalogue Activity is eligible for {school.name}."
                        )
                    create_activity(
                        {
                            **payload,
                            "requireCatalogue": True,
                            "schoolId": school.school_id,
                            "scheduledDate": scheduled_date_raw,
                            "activityPurposeText": request.POST.get(
                                "activity_goal", "Bulk-scheduled visit"
                            ),
                            "deliveryType": "staff",
                        },
                        principal=request.user,
                    )
            return _saved_without_leaving(
                "Scheduled. It is on your My Plan — keep planning.",
                plan_url=_my_plan_url_for_scheduled_date(scheduled_date_raw),
            )
        except BadRequest as e:
            return error_fragment(e, status=400)

    return HttpResponse("Action processed", status=200)


@require_page_permission("planning")
def schedule_activity_form_view(request):
    action = request.GET.get("action", "visit")  # visit, training, meeting
    school_id = request.GET.get("school", "")
    cluster_id = request.GET.get("cluster", "")

    from apps.core.scoping import (
        cluster_queryset,
        direct_portfolio_schools,
        resolve_user_scope,
    )

    # Populate lookups. Neither dropdown was scoped to what a save would
    # accept: the school list was `active_schools()` — every operating school
    # in the country — and the cluster list was every cluster in it. Both now
    # come from the direct portfolio, which is the set the create-time guard
    # checks against.
    scope = resolve_user_scope(request.user)
    schools = direct_portfolio_schools(scope) or School.objects.none()
    # `direct_only`, matching the create-time guard in `_target_in_direct_
    # portfolio`. A supervisor's CCEO clusters are read-only oversight; listing
    # them here promised a save the service would refuse.
    clusters = cluster_queryset(scope, direct_only=True).order_by("name")
    partners = assignable_partners()

    selected_school = (
        schools.filter(Q(id=school_id) | Q(school_id=school_id))
        .select_related("district")
        .first()
        if school_id
        else None
    )
    # Read back through the same scope: a cluster id arriving in the query
    # string must not preselect what the dropdown would not have listed.
    selected_cluster = clusters.filter(id=cluster_id).first() if cluster_id else None

    # Resolve focus recommendations if school chosen
    recommendations = []
    if selected_school:
        latest_ssa = (
            selected_school.ssa_records.filter(
                deleted_at__isnull=True, verification_status="confirmed"
            )
            .order_by("-date_of_ssa")
            .first()
        )
        if latest_ssa:
            from apps.ssa.recommendation_engine import prioritized_interventions

            for item in prioritized_interventions(selected_school, n=2):
                code = item["intervention"]
                label = dict(SsaIntervention.choices).get(code, code)
                recommendations.append(
                    {"code": code, "label": label, "score": item.get("score")}
                )

    if request.method == "POST":
        if not RolePermissionService.can_schedule_activity(request.user):
            return HttpResponseForbidden(
                _no_scheduling_permission_message(request.user)
            )

        activity_type = request.POST.get("activity_type", "")
        school_id_str = request.POST.get("school_id", "").strip()
        cluster_id_str = request.POST.get("cluster_id", "").strip()
        scheduled_date = request.POST.get("scheduled_date", "")
        focus_intervention = request.POST.get("focus_intervention", "")
        purpose_type = request.POST.get("purpose_type", "focus_intervention")
        purpose_text = request.POST.get("activity_purpose_text", "").strip()
        expected_outcome = request.POST.get("expected_outcome", "").strip()
        expected_participants = request.POST.get("expected_participants", "").strip()
        delivery_type = request.POST.get("delivery_type", "staff")
        partner_id = request.POST.get("assigned_partner_id", "").strip()

        from datetime import date

        # Build payload
        payload = {
            "activityType": activity_type,
            "scheduledDate": scheduled_date,
            "activityPurposeText": purpose_text,
            "expectedOutcome": expected_outcome,
            "deliveryType": delivery_type,
        }

        if scheduled_date:
            try:
                dt = date.fromisoformat(scheduled_date)
                payload["plannedMonth"] = dt.month
                payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
            except ValueError:
                pass

        if school_id_str:
            payload["schoolId"] = school_id_str
        if cluster_id_str:
            payload["clusterId"] = cluster_id_str
        if focus_intervention:
            payload["focusIntervention"] = focus_intervention
            payload["purposeIntervention"] = focus_intervention
        if purpose_type:
            payload["purposeType"] = purpose_type
        if expected_participants:
            payload["expectedParticipants"] = int(expected_participants)
        if partner_id:
            payload["assignedPartnerId"] = partner_id

        try:
            if activity_type == "school_visit":
                schedule_school_visit(payload, request.user)
                messages.success(request, "School visit scheduled successfully.")
            else:
                schedule_cluster_activity(payload, request.user)
                messages.success(request, "Cluster activity scheduled successfully.")
            return redirect("/planning")
        except Exception as e:
            messages.error(request, f"Error: {e}")
            # fallthrough to re-render form with error message

    context = {
        "action": action,
        "schools": [selected_school] if selected_school else [],
        "clusters": clusters,
        "partners": partners,
        "selected_school": selected_school,
        "selected_cluster": selected_cluster,
        "recommendations": recommendations,
        "interventions": SsaIntervention.choices,
    }
    return render(request, "pages/planning/schedule.html", context)


@require_page_permission("planning")
def schedule_school_options_view(request):
    """Small, direct-portfolio lookup for the legacy scheduling page."""
    from apps.core.scoping import direct_portfolio_schools, resolve_user_scope

    query = request.GET.get("school_id", "").strip()
    schools = direct_portfolio_schools(resolve_user_scope(request.user))
    if schools is None or len(query) < 2:
        schools = School.objects.none()
    else:
        schools = (
            schools.filter(deleted_at__isnull=True)
            .filter(Q(school_id__istartswith=query) | Q(name__icontains=query))
            .select_related("district")
            .order_by("school_id")[:25]
        )
    return render(
        request,
        "partials/planning/schedule_school_options.html",
        {"schools": schools},
    )


@require_page_permission("planning")
def cost_preview_partial(request):
    activity_type = request.POST.get("activity_type", "").strip()
    scheduled_date = request.POST.get("scheduled_date", "").strip()
    school_id = request.POST.get("school_id", "").strip()
    cluster_id = request.POST.get("cluster_id", "").strip()
    expected_participants = request.POST.get("expected_participants", "").strip()
    delivery_type = request.POST.get("delivery_type", "staff").strip()
    partner_id = request.POST.get("assigned_partner_id", "").strip()

    payload = {
        "activityType": activity_type,
        "plannedDate": scheduled_date,
        "deliveryType": delivery_type,
    }
    if school_id:
        # Resolve human school ID
        sch = School.objects.filter(Q(id=school_id) | Q(school_id=school_id)).first()
        if sch:
            payload["schoolId"] = sch.school_id
    if cluster_id:
        payload["clusterId"] = cluster_id
    if expected_participants:
        try:
            payload["expectedParticipants"] = int(expected_participants)
        except ValueError:
            pass
    if partner_id:
        payload["assignedPartnerId"] = partner_id

    try:
        from apps.budget.costing_service import planning_preview_owner

        preview_data = cost_preview(
            payload,
            minimum=True,
            responsible_user_id=planning_preview_owner(
                request.user, request.POST.get("responsible_staff_id")
            ),
        )
        context = {
            "preview": preview_data,
            "success": True,
        }
    except Exception as e:
        context = {
            "error_msg": str(e),
            "success": False,
        }

    return render(request, "partials/cost_preview.html", context)


@require_page_permission("planning")
def route_preview_view(request):
    """Live Route Intelligence preview for the scheduling drawer/popover.

    Read-only: same math as the persisted DailyVisitRouteBatch (location
    hierarchy → grouping → working-day feasibility → quality score → CD-target
    check → recommendations) but nothing is scheduled or persisted. Accepts
    `school_ids` (bulk popover) or `school_id` (single-visit drawer)."""
    if not RolePermissionService.can_schedule_activity(request.user):
        return HttpResponseForbidden("Access Denied")

    from apps.routes.engine import PlanningRoutePreviewService

    params = request.POST if request.method == "POST" else request.GET
    school_ids = [s for s in params.getlist("school_ids") if s.strip()]
    single = (params.get("school_id") or "").strip()
    if single and single not in school_ids:
        school_ids.append(single)
    if not school_ids:
        return render(
            request, "partials/planning/route_preview.html", {"preview": None}
        )

    from datetime import date as _date

    visit_date = None
    raw_date = (params.get("scheduled_date") or "").strip()
    if raw_date:
        try:
            visit_date = _date.fromisoformat(raw_date)
        except ValueError:
            visit_date = None

    preview = PlanningRoutePreviewService.preview(
        school_ids=school_ids,
        responsible_user=request.user.user_id,
        visit_date=visit_date,
    )
    return render(request, "partials/planning/route_preview.html", {"preview": preview})
