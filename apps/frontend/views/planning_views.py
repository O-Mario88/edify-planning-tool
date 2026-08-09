import json

from django.shortcuts import render, redirect, get_object_or_404
from apps.core.htmx_errors import error_fragment
from apps.core.exceptions import BadRequest
from apps.core.permissions import (
    require_export_permission,
    require_page_permission,
    RolePermissionService,
    get_scoped_object_or_404,
)
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from urllib.parse import urlencode

from apps.planning.services import schedule_school_visit, schedule_cluster_activity
from apps.budget.costing_service import preview as cost_preview
from apps.schools.lifecycle_service import active_schools
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.partners.models import Partner, PartnerAssignment
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


def _my_plan_url_for_scheduled_date(raw_date: str | None) -> str:
    """Open My Plan on the exact week containing a just-saved activity."""
    from datetime import date

    try:
        scheduled_for = date.fromisoformat(str(raw_date or "")[:10])
    except ValueError:
        return "/my-plan"

    return "/my-plan?" + urlencode(
        {
            "fy": get_operational_fy(scheduled_for),
            "month": scheduled_for.month,
            "week": min(5, (scheduled_for.day - 1) // 7 + 1),
            "period": "week",
        }
    )


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
        return HttpResponseForbidden(
            "You do not have permission to schedule activities."
        )

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
                    status="pending_scheduling",
                ).exists()
                if duplicate:
                    continue
                PartnerAssignment.objects.create(
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
                    status="pending_scheduling",
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
    fy = get_operational_fy()

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
        "per_page": request.GET.get("per_page", 10),
    }

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

    # 2. Query Dashboard data from Service
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
    partners = assignable_partners()

    # Pagination pages list
    total_pages = data["total_pages"]
    from apps.core.pagination import make_pagination_window

    pages_list = make_pagination_window(int(filters["page"]), total_pages)

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

    # 4. Construct context
    context = {
        "any_clustered_school": any_clustered_school,
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
        # Guards
        "can_schedule": RolePermissionService.can_schedule_activity(request.user),
        "can_assign_partner": RolePermissionService.can_assign_to_partner(request.user),
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


@require_page_permission("planning")
def schedule_modal_view(request):
    if not RolePermissionService.can_schedule_activity(request.user):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to schedule activities."
        )

    cluster_id = request.GET.get("cluster_id")
    if cluster_id:
        cluster = get_scoped_object_or_404(Cluster, request.user, id=cluster_id)
        action = request.GET.get("action", "training")
        partners = assignable_partners()
        from apps.clusters.services import active_school_count
        from apps.projects.presentation import training_project_options

        project_options = training_project_options() if action == "training" else []

        context = {
            "cluster": cluster,
            "action": action,
            "partners": partners,
            "interventions": SsaIntervention.choices,
            "drawer_size": "md",
            # Read-only, and from the canonical counter. The drawer shows it so
            # the multiplication is visible; the backend recomputes it at
            # submission so a stale drawer cannot price an activity.
            "cluster_school_count": active_school_count(cluster.id),
            "projects": project_options,
            "projects_json": json.dumps(project_options),
            # §16 — certified agencies only. `partners` above is the ordinary
            # assignable-partner list and must not be offered for booking.
            "certified_agencies": _certified_agency_options(
                district_name=(cluster.district.name if cluster.district_id else "")
            ),
        }
        return render(
            request, "partials/planning/schedule_cluster_drawer.html", context
        )

    school_id = request.GET.get("school_id")
    school = get_scoped_object_or_404(
        School, request.user, Q(id=school_id) | Q(school_id=school_id)
    )
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
    recommended_focus_intervention = (
        first_catalogue_item["targetIntervention"]
        if first_catalogue_item
        else request.GET.get("focus_intervention", "")
    )
    recommended_visit_purpose = normalise_visit_purpose(
        None,
        for_partner=False,
        fallback_activity_type=recommended_activity_type,
    )

    from apps.projects.presentation import training_project_options

    project_options = training_project_options()

    context = {
        "school": school,
        "recommendations": recommendations,
        "interventions": SsaIntervention.choices,
        "partners": partners,
        "drawer_size": "md",
        "recommended_activity_type": recommended_activity_type,
        "recommended_activity_label": recommended_activity_label,
        "activity_type_options": activity_type_options,
        "recommended_focus_intervention": recommended_focus_intervention,
        "staff_visit_purposes": STAFF_VISIT_PURPOSES,
        # Drives which purposes stay selectable when delivery is Partner.
        "partner_visit_purposes": PARTNER_VISIT_PURPOSES,
        "recommended_visit_purpose": recommended_visit_purpose,
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
        # In-school Training is frequently a Project's own curriculum. The
        # picker is the same honest inventory the Group Training drawer uses —
        # every Project listed, unusable ones disabled with the reason — and
        # the Project's configured intervention fills the field below it, so
        # Project reporting and intervention reporting cannot drift apart.
        "projects": project_options,
        "projects_json": json.dumps(project_options),
        "certified_agencies": _certified_agency_options(
            district_name=(school.district.name if school.district_id else "")
        ),
    }
    return render(request, "partials/planning/schedule_drawer.html", context)


@require_page_permission("planning")
def schedule_action_view(request):
    if not RolePermissionService.can_schedule_activity(request.user):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to schedule activities."
        )

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    activity_type = request.POST.get("activity_type", "school_visit")
    purpose_of_visit = request.POST.get("purpose_of_visit", "").strip()
    school_id = request.POST.get("school_id")
    cluster_id = request.POST.get("cluster_id")
    scheduled_date = request.POST.get("scheduled_date")
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
    project_id = request.POST.get("project_id", "").strip()
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    recommendation_reason = request.POST.get("recommendation_reason", "").strip()
    override_reason = request.POST.get("override_reason", "").strip()
    source_activity_id = request.POST.get("source_activity_id", "").strip() or None
    source_activity_id = request.POST.get("source_activity_id", "").strip()
    if cluster_id and activity_type == "cluster_training":
        if not project_id:
            return error_fragment(
                BadRequest("Select the Project this Group Training delivers."),
                status=400,
            )
        # Project configuration owns intervention attribution. Do not trust a
        # browser-supplied hidden value when the server can derive it.
        focus_intervention = ""
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

    from datetime import date

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
    }
    if source_activity_id:
        payload["sourceActivityId"] = source_activity_id

    if scheduled_date:
        try:
            dt = date.fromisoformat(scheduled_date)
            payload["plannedMonth"] = dt.month
            payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
        except ValueError:
            pass

    if school_id:
        payload["schoolId"] = school_id
    if cluster_id:
        payload["clusterId"] = cluster_id
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
    for key, raw in (
        ("teachersPerSchool", teachers_per_school),
        ("leadersPerSchool", leaders_per_school),
        ("otherPerSchool", other_per_school),
    ):
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

    try:
        if school_id:
            # A single scheduled visit uses the same direct, immediate-cost
            # workflow as training and meetings.  Daily batching remains a
            # planning/reporting tool for deliberate bulk schedules, not a
            # set of rules that can prevent a field worker from booking work.
            schedule_school_visit(payload, request.user)
            messages.success(request, "School visit scheduled successfully.")
        else:
            schedule_cluster_activity(payload, request.user)
            messages.success(request, "Cluster activity scheduled successfully.")
        # Redirect to My Plan and close drawer via client headers.
        # APPEND_SLASH is off and "/my-plan" has no trailing-slash route, so a
        # redirect to "/my-plan/" 404s — the activity saves but the user lands
        # on an error page and never sees confirmation.
        plan_url = (
            "/projects/my-plan"
            if project_id
            else _my_plan_url_for_scheduled_date(scheduled_date)
        )
        response = HttpResponse(
            f'<script>window.location.href = "{plan_url}";</script>'
        )
        response["HX-Trigger"] = "close-drawer"
        return response
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
    if school_id:
        school = get_scoped_object_or_404(
            School, request.user, Q(id=school_id) | Q(school_id=school_id)
        )
    if cluster_id:
        cluster = get_scoped_object_or_404(Cluster, request.user, id=cluster_id)

    partners = assignable_partners()
    project_id = request.GET.get("project_id", "")
    partner_catalogue_recommendations = None
    if school:
        from apps.activity_catalogue.services import recommend_activities

        partner_catalogue_recommendations = recommend_activities(
            school=school,
            principal=request.user,
            project=project_id or None,
            executor_type="partner",
            limit=3,
        )
    elif cluster:
        from apps.activity_catalogue.services import recommend_cluster_activities

        partner_catalogue_recommendations = recommend_cluster_activities(
            cluster=cluster,
            principal=request.user,
            project=project_id or None,
            executor_type="partner",
            limit=3,
        )

    context = {
        "school": school,
        "cluster": cluster,
        "partners": partners,
        "interventions": SsaIntervention.choices,
        "drawer_size": "md",
        "drawer_type": "center",
        # Optional project context — stamps the partner activity for the loop.
        "project_id": project_id,
        "recommended_focus_intervention": request.GET.get("focus_intervention", ""),
        "partner_visit_purposes": PARTNER_VISIT_PURPOSES,
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
        "monitoring_staff_name": resolve_monitoring_staff(school, request.user)[1],
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
    """Who monitors a partner handoff: the school's own staff member.

    The single resolver behind both the drawer's "Monitored by" line and the
    `monitored_by_staff_id` written on the assignment. They must agree — My
    Plan surfaces partner work through `monitored_by_staff_id`, so a drawer
    that named the school's owner while the record stored whoever clicked
    Handoff would promise oversight to one person and deliver the row to
    another.

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
    project_id = request.POST.get("project_id", "").strip() or None
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    recommendation_reason = request.POST.get("recommendation_reason", "").strip()
    override_reason = request.POST.get("override_reason", "").strip()
    source_activity_id = request.POST.get("source_activity_id", "").strip() or None

    from datetime import date as _date

    expected_date_raw = request.POST.get("expected_date", "").strip()
    expected_date = None
    if expected_date_raw:
        try:
            expected_date = _date.fromisoformat(expected_date_raw)
        except ValueError:
            pass
    if project_id and not expected_date:
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Choose an assignment due date for this special-project handoff. Final cost is calculated only after the Partner schedules.</div>',
            status=400,
        )

    try:
        partner = get_object_or_404(Partner, id=partner_id)
        catalogue_item = None
        source_ssa = None
        source_activity = None
        if school_id or cluster_id:
            if not catalogue_item_id:
                raise BadRequest("Select an approved Activity Catalogue item.")
            from apps.activity_catalogue.services import (
                get_selectable_item,
                resolve_activity_intervention,
                validate_context,
            )
            from apps.projects.models import Project
            from apps.ssa.services import latest_applicable_record

            catalogue_item = get_selectable_item(catalogue_item_id)
            project = (
                Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
                if project_id
                else None
            )
            school_for_validation = (
                get_scoped_object_or_404(
                    School, request.user, Q(id=school_id) | Q(school_id=school_id)
                )
                if school_id
                else None
            )
            cluster_for_validation = (
                get_scoped_object_or_404(Cluster, request.user, id=cluster_id)
                if cluster_id
                else None
            )
            validate_context(
                catalogue_item,
                school=school_for_validation,
                cluster=cluster_for_validation,
                project=project,
                executor_type="partner",
            )
            source_ssa = (
                latest_applicable_record(school_for_validation)
                if school_for_validation
                else None
            )
            if source_activity_id:
                from apps.activities.models import Activity

                source_activity = Activity.objects.filter(
                    id=source_activity_id,
                    school=school_for_validation,
                    cluster=cluster_for_validation,
                    deleted_at__isnull=True,
                ).first()
                if source_activity is None:
                    raise BadRequest(
                        "Choose a valid prior Activity for this School to follow up."
                    )
            if (
                catalogue_item.requires_current_ssa
                and school_for_validation
                and source_ssa is None
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
            from apps.activity_catalogue.models import MappingMode
            from apps.activity_catalogue.services import (
                recommend_activities,
                recommend_cluster_activities,
            )

            recommendation_result = (
                recommend_activities(
                    school=school_for_validation,
                    principal=request.user,
                    project=project,
                    executor_type="partner",
                    limit=3,
                )
                if school_for_validation
                else recommend_cluster_activities(
                    cluster=cluster_for_validation,
                    principal=request.user,
                    project=project,
                    executor_type="partner",
                    limit=3,
                )
            )
            rows = [
                *recommendation_result["primary"],
                *recommendation_result["otherEligible"],
            ]
            match = next(
                (row for row in rows if row["catalogueItemId"] == catalogue_item.id),
                None,
            )
            primary_ids = {
                row["catalogueItemId"] for row in recommendation_result["primary"]
            }
            dynamic = catalogue_item.intervention_mappings.filter(
                active=True,
                mapping_mode=MappingMode.INHERIT_FROM_SOURCE_ACTIVITY,
            ).exists()
            if (
                catalogue_item.id not in primary_ids
                and not dynamic
                and not override_reason
            ):
                raise BadRequest(
                    "Record an authorized reason for selecting a non-primary "
                    "Partner Activity."
                )
            recommendation_reason = (
                match["recommendationReason"]
                if match
                else "Authorized alternative Catalogue Activity."
            )

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
            school = get_scoped_object_or_404(
                School, request.user, Q(id=school_id) | Q(school_id=school_id)
            )
            purpose_of_visit = normalise_visit_purpose(
                purpose_of_visit,
                for_partner=True,
                fallback_activity_type=activity_type,
            )
            assignment_purpose = purpose or catalogue_item.display_name
            normalized_type = catalogue_item.workflow_kind
            # The same resolver the drawer displayed, so the record agrees with
            # what the person was shown — and so the partner's work lands on
            # the owning staff member's My Plan rather than the assigner's.
            monitoring_staff_id = resolve_monitoring_staff(school, request.user)[0]
            dup = _recent_duplicate(school=school, act_type=normalized_type)
            if dup:
                target = "/projects/my-plan" if project_id else None
                response = HttpResponse(
                    f'<script>window.location.href="{target}";</script>'
                    if target
                    else "<script>window.location.reload();</script>"
                )
                response["HX-Trigger"] = "close-drawer"
                return response
            with transaction.atomic():
                PartnerAssignment.objects.create(
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
                    status="pending_scheduling",
                )

        if cluster_id:
            cluster = get_scoped_object_or_404(Cluster, request.user, id=cluster_id)
            assignment_purpose = purpose or catalogue_item.display_name
            act_type = catalogue_item.workflow_kind
            dup = _recent_duplicate(cluster=cluster, act_type=act_type)
            if dup:
                response = HttpResponse("<script>window.location.reload();</script>")
                response["HX-Trigger"] = "close-drawer"
                return response
            with transaction.atomic():
                # Create PartnerAssignment for cluster
                PartnerAssignment.objects.create(
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
                    status="pending_scheduling",
                )

        # Return refresh trigger and close drawer
        response = HttpResponse(
            '<script>window.location.href="/projects/my-plan";</script>'
            if project_id
            else "<script>window.location.reload();</script>"
        )
        response["HX-Trigger"] = "close-drawer"
        return response
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

    schools = School.objects.filter(school_id__in=school_ids)

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
                    PartnerAssignment.objects.create(
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
                        status="pending_scheduling",
                    )
            return HttpResponse("<script>window.location.reload();</script>")
        except Exception as exc:
            return error_fragment(exc, status=400)

    elif action == "schedule":
        # Each School uses its own top eligible Catalogue recommendation.
        if not RolePermissionService.can_schedule_activity(request.user):
            return HttpResponseForbidden(
                "Access Denied: You do not have permission to schedule activities."
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
                for school in schools:
                    result = recommend_activities(
                        school=school,
                        principal=request.user,
                        executor_type="staff",
                        limit=1,
                    )
                    if not result["primary"]:
                        raise BadRequest(
                            f"No staff-deliverable Catalogue Activity is eligible for {school.name}."
                        )
                    recommendation = result["primary"][0]
                    create_activity(
                        {
                            "catalogueItemId": recommendation["catalogueItemId"],
                            "requireCatalogue": True,
                            "schoolId": school.school_id,
                            "scheduledDate": scheduled_date_raw,
                            "activityPurposeText": request.POST.get(
                                "activity_goal", "Bulk-scheduled visit"
                            ),
                            "focusIntervention": recommendation["targetIntervention"],
                            "recommendationReason": recommendation[
                                "recommendationReason"
                            ],
                            "deliveryType": "staff",
                        },
                        principal=request.user,
                    )
            response = HttpResponse(
                f'<script>window.location.href = "{_my_plan_url_for_scheduled_date(scheduled_date_raw)}";</script>'
            )
            response["HX-Trigger"] = "close-drawer"
            return response
        except BadRequest as e:
            return error_fragment(e, status=400)

    return HttpResponse("Action processed", status=200)


@require_page_permission("planning")
def schedule_activity_form_view(request):
    action = request.GET.get("action", "visit")  # visit, training, meeting
    school_id = request.GET.get("school", "")
    cluster_id = request.GET.get("cluster", "")

    from apps.core.scoping import cluster_queryset, resolve_user_scope

    # Populate lookups. Schools were scoped here and clusters were not — the
    # picker offered every cluster in the country beside a correctly narrowed
    # school list, so the two dropdowns on one form disagreed about whose work
    # this is.
    scope = resolve_user_scope(request.user)
    schools = active_schools().order_by("name")
    clusters = cluster_queryset(scope).order_by("name")
    partners = assignable_partners()

    selected_school = (
        School.objects.filter(Q(id=school_id) | Q(school_id=school_id)).first()
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
                "Access Denied: You do not have permission to schedule activities."
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
        "schools": schools,
        "clusters": clusters,
        "partners": partners,
        "selected_school": selected_school,
        "selected_cluster": selected_cluster,
        "recommendations": recommendations,
        "interventions": SsaIntervention.choices,
    }
    return render(request, "pages/planning/schedule.html", context)


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
        preview_data = cost_preview(payload)
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
