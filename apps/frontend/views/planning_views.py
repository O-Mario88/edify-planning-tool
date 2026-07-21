from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import (
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
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.partners.models import Partner, PartnerAssignment
from apps.partners.purposes import (
    PARTNER_VISIT_PURPOSES,
    STAFF_VISIT_PURPOSES,
    normalise_visit_purpose,
    purpose_activity_type,
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
        return render(
            request,
            "partials/projects/bulk_schedule_drawer.html",
            {
                "assignments": assignments,
                "assignment_ids": ",".join(item.id for item in assignments),
                "interventions": SsaIntervention.choices,
                "drawer_size": "md",
            },
        )

    scheduled_date = request.POST.get("scheduled_date", "").strip()
    activity_type = request.POST.get("activity_type", "school_visit").strip()
    focus = request.POST.get("focus_intervention", "").strip()
    if not scheduled_date:
        return HttpResponse(
            '<div class="p-3 text-rose-700 bg-rose-50 rounded-lg">Choose a delivery date.</div>',
            status=400,
        )

    try:
        with transaction.atomic():
            for assignment in assignments:
                payload = {
                    "schoolId": assignment.school.school_id,
                    "projectId": assignment.project_id,
                    "activityType": activity_type,
                    "scheduledDate": scheduled_date,
                    "deliveryType": "staff",
                    "ssaCollectionExpected": activity_type
                    in {"baseline_ssa_visit", "school_visit_ssa_collection"},
                    "activityPurposeText": f"Special project support: {assignment.project.name}",
                    "expectedOutcome": "Complete the planned project support and record evidence.",
                }
                if focus:
                    payload["focusIntervention"] = focus
                    payload["purposeIntervention"] = focus
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
        return HttpResponse(
            f'<div class="p-3 text-rose-700 bg-rose-50 rounded-lg">Could not schedule the selection: {exc}</div>',
            status=400,
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

    partners = Partner.objects.filter(
        deleted_at__isnull=True, active_status=True
    ).order_by("name")
    if request.method == "GET":
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
            },
        )

    from datetime import date
    from apps.activities.models import Activity
    from apps.activities.services import create as create_activity

    partner = get_object_or_404(partners, id=request.POST.get("partner_id"))
    scheduled_date = request.POST.get("scheduled_date", "").strip()
    activity_type = request.POST.get("activity_type", "school_visit").strip()
    purpose_of_visit = request.POST.get("purpose_of_visit", "").strip()
    focus = request.POST.get("focus_intervention", "").strip() or None
    try:
        purpose_of_visit = normalise_visit_purpose(
            purpose_of_visit,
            for_partner=True,
            fallback_activity_type=activity_type,
        )
    except Exception as exc:
        return HttpResponse(
            f'<div class="p-3 text-rose-700 bg-rose-50 rounded-lg">{exc}</div>',
            status=400,
        )
    activity_type = purpose_activity_type(purpose_of_visit, activity_type)
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
        created = 0
        with transaction.atomic():
            for assignment in assignments:
                duplicate = Activity.objects.filter(
                    deleted_at__isnull=True,
                    project_id=assignment.project_id,
                    school=assignment.school,
                    assigned_partner_id=partner.id,
                    planned_date=parsed_date,
                    activity_type=activity_type,
                ).exists()
                if duplicate:
                    continue
                pa = PartnerAssignment.objects.create(
                    school=assignment.school,
                    partner=partner,
                    assigning_staff_id=(
                        request.user.staff_profile_id
                        or request.user.user_id
                        or request.user.id
                    ),
                    purpose=f"Special project support: {assignment.project.name}",
                    purpose_of_visit=purpose_of_visit,
                    focus_intervention=focus,
                    expected_activity_type=activity_type,
                    scheduled_date=parsed_date,
                    status="partner_scheduled",
                    notes=f"Project: {assignment.project.name}",
                )
                payload = {
                    "schoolId": assignment.school.school_id,
                    "projectId": assignment.project_id,
                    "activityType": activity_type,
                    "scheduledDate": scheduled_date,
                    "deliveryType": "partner",
                    "assignedPartnerId": partner.id,
                    "ssaCollectionExpected": activity_type
                    in {"baseline_ssa_visit", "school_visit_ssa_collection"},
                    "activityPurposeText": pa.purpose,
                    "purposeType": purpose_of_visit,
                    "expectedOutcome": "Partner completes delivery and submits project evidence.",
                }
                if focus:
                    payload["focusIntervention"] = focus
                    payload["purposeIntervention"] = focus
                create_activity(payload, principal=request.user)
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
        return HttpResponse(
            f'<div class="p-3 text-rose-700 bg-rose-50 rounded-lg">Could not assign the selection: {exc}</div>',
            status=400,
        )


@require_page_permission("planning")
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

    # 3. Dropdowns options
    districts = District.objects.all().order_by("name")

    # Filter sub-counties by district if a district is selected
    if filters["district"] and filters["district"] != "All":
        sub_counties = SubCounty.objects.filter(
            district_id=filters["district"]
        ).order_by("name")
    else:
        sub_counties = SubCounty.objects.all().order_by("name")

    staff_members = (
        StaffProfile.objects.filter(deleted_at__isnull=True)
        .select_related("user")
        .order_by("user__name")
    )
    partners = Partner.objects.filter(
        deleted_at__isnull=True, active_status=True
    ).order_by("name")

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

    # 4. Construct context
    context = {
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
        partners = Partner.objects.filter(
            deleted_at__isnull=True, active_status=True
        ).order_by("name")
        context = {
            "cluster": cluster,
            "action": action,
            "partners": partners,
            "interventions": SsaIntervention.choices,
            "drawer_size": "lg",
        }
        return render(
            request, "partials/planning/schedule_cluster_drawer.html", context
        )

    school_id = request.GET.get("school_id")
    school = get_scoped_object_or_404(
        School, request.user, Q(id=school_id) | Q(school_id=school_id)
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
        scores = sorted(
            list(latest_ssa.scores.all().values("intervention", "score")),
            key=lambda s: s["score"],
        )
        for s in scores[:2]:
            code = s["intervention"]
            label = dict(SsaIntervention.choices).get(code, code)
            recommendations.append({"code": code, "label": label, "score": s["score"]})

    partners = Partner.objects.filter(
        deleted_at__isnull=True, active_status=True
    ).order_by("name")

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
    recommended_activity_type = request.GET.get(
        "recommended_activity_type", ActivityType.SCHOOL_VISIT
    )
    if recommended_activity_type not in school_activity_types:
        recommended_activity_type = ActivityType.SCHOOL_VISIT
    if school.current_fy_ssa_status != "done" and recommended_activity_type not in {
        ActivityType.BASELINE_SSA_VISIT,
        ActivityType.SCHOOL_VISIT_SSA_COLLECTION,
        ActivityType.SCHOOL_VISIT,
    }:
        recommended_activity_type = ActivityType.BASELINE_SSA_VISIT
    recommended_activity_label = dict(ActivityType.choices).get(
        recommended_activity_type, "School Visit"
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
    recommended_focus_intervention = request.GET.get("focus_intervention", "")
    recommended_visit_purpose = normalise_visit_purpose(
        None,
        for_partner=False,
        fallback_activity_type=recommended_activity_type,
    )

    context = {
        "school": school,
        "recommendations": recommendations,
        "interventions": SsaIntervention.choices,
        "partners": partners,
        "drawer_size": "lg",
        "recommended_activity_type": recommended_activity_type,
        "recommended_activity_label": recommended_activity_label,
        "activity_type_options": activity_type_options,
        "recommended_focus_intervention": recommended_focus_intervention,
        "staff_visit_purposes": STAFF_VISIT_PURPOSES,
        "recommended_visit_purpose": recommended_visit_purpose,
        # Optional project context — stamps the scheduled activity so it flows
        # into the Special Projects dashboard / analytics / My Plan.
        "project_id": request.GET.get("project_id", ""),
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
    delivery_type = request.POST.get("delivery_type", "staff")
    partner_id = request.POST.get("assigned_partner_id", "").strip()
    project_id = request.POST.get("project_id", "").strip()

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
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">{exc}</div>',
                status=400,
            )
        activity_type = purpose_activity_type(purpose_of_visit, activity_type)

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
    }

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
        return HttpResponse(
            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
            status=400,
        )


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

    partners = Partner.objects.filter(
        deleted_at__isnull=True, active_status=True
    ).order_by("name")

    context = {
        "school": school,
        "cluster": cluster,
        "partners": partners,
        "interventions": SsaIntervention.choices,
        "drawer_size": "md",
        "drawer_type": "center",
        # Optional project context — stamps the partner activity for the loop.
        "project_id": request.GET.get("project_id", ""),
        "recommended_focus_intervention": request.GET.get("focus_intervention", ""),
        "partner_visit_purposes": PARTNER_VISIT_PURPOSES,
    }
    return render(request, "partials/planning/assign_partner_drawer.html", context)


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
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Choose a delivery date so the partner activity can be costed and linked to this project.</div>',
            status=400,
        )

    try:
        partner = get_object_or_404(Partner, id=partner_id)

        from apps.activities.services import create as create_activity

        # PartnerAssignment and Activity.monitor fields use the StaffProfile
        # CUID when one exists.  Falling back to the User id keeps Admins
        # without a profile attributable without creating a second identity
        # scheme for normal field staff.
        monitored_by_staff_id = (
            request.user.staff_profile_id or request.user.user_id or request.user.id
        )

        def _finalize(pa, *, school=None, cluster=None, act_type, extra_fields=None):
            """Convert a freshly-created PartnerAssignment into a properly
            validated + costed Activity via activities.services.create() —
            the SAME funnel every other scheduling path goes through
            (SSA-justification check, structured-purpose validation, the
            assert_schedulable() cost-catalogue gate), instead of writing
            the Activity via raw ORM. Only runs once a target date is
            already known — partner_schedule() (used by Core Schools) is
            what later lazily creates the Activity for a still-unscheduled
            PartnerAssignment once a date IS picked (e.g. the partner's own
            self-schedule endpoint), so no un-costed activity is ever
            persisted either way."""
            if not expected_date:
                return
            data = {
                "activityType": act_type,
                "deliveryType": "partner",
                "assignedPartnerId": partner.id,
                "focusIntervention": focus_intervention,
                "activityPurposeText": pa.purpose,
                "scheduledDate": expected_date_raw,
            }
            if school is not None:
                data["schoolId"] = school.school_id
            if cluster is not None:
                data["clusterId"] = cluster.id
            if extra_fields:
                data.update(extra_fields)
            create_activity(data, principal=request.user)
            # activities.services.create() records the monitor using the
            # canonical StaffProfile/User owner id used by My Plan.  Do not
            # overwrite it with this view's raw User id: that creates a
            # second identity scheme and can hide partner work from its
            # assigned monitor.
            # Keep the PartnerAssignment in sync with the Activity it now
            # owns instead of leaving it stuck at pending_scheduling.
            pa.status = "partner_scheduled"
            pa.scheduled_date = expected_date
            pa.save(update_fields=["status", "scheduled_date", "updated_at"])

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
            assignment_purpose = purpose or f"Assigned for {activity_type}"
            normalized_type = purpose_activity_type(purpose_of_visit, activity_type)
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
                pa = PartnerAssignment.objects.create(
                    school=school,
                    partner=partner,
                    assigning_staff_id=monitored_by_staff_id,
                    purpose=assignment_purpose,
                    purpose_of_visit=purpose_of_visit,
                    focus_intervention=focus_intervention,
                    expected_activity_type=normalized_type,
                    scheduled_date=expected_date,
                    notes=notes,
                    status="pending_scheduling",
                )
                _finalize(
                    pa,
                    school=school,
                    act_type=normalized_type,
                    extra_fields={
                        **({"projectId": project_id} if project_id else {}),
                        "purposeType": purpose_of_visit,
                    },
                )
                # Update status
                school.current_fy_ssa_status = "partner_assigned"
                school.save(
                    update_fields=[
                        "current_fy_ssa_status",
                        "planning_readiness",
                        "updated_at",
                    ]
                )

        if cluster_id:
            cluster = get_scoped_object_or_404(Cluster, request.user, id=cluster_id)
            assignment_purpose = purpose or f"Cluster assignment: {cluster.name}"
            act_type = (
                "cluster_meeting" if activity_type == "meeting" else "cluster_training"
            )
            dup = _recent_duplicate(cluster=cluster, act_type=act_type)
            if dup:
                response = HttpResponse("<script>window.location.reload();</script>")
                response["HX-Trigger"] = "close-drawer"
                return response
            with transaction.atomic():
                # Create PartnerAssignment for cluster
                pa = PartnerAssignment.objects.create(
                    cluster=cluster,
                    partner=partner,
                    assigning_staff_id=monitored_by_staff_id,
                    purpose=assignment_purpose,
                    focus_intervention=focus_intervention,
                    expected_activity_type=act_type,
                    scheduled_date=expected_date,
                    notes=notes,
                    status="pending_scheduling",
                )
                _finalize(pa, cluster=cluster, act_type=act_type)

                # Assign all schools in the cluster
                for school in School.objects.filter(
                    cluster_id=cluster.id, deleted_at__isnull=True
                ):
                    PartnerAssignment.objects.create(
                        school=school,
                        partner=partner,
                        assigning_staff_id=monitored_by_staff_id,
                        purpose=assignment_purpose,
                        purpose_of_visit=purpose_of_visit,
                        focus_intervention=focus_intervention,
                        expected_activity_type=activity_type,
                        scheduled_date=expected_date,
                        notes=notes,
                        status="pending_scheduling",
                    )
                    school.current_fy_ssa_status = "partner_assigned"
                    school.save(
                        update_fields=[
                            "current_fy_ssa_status",
                            "planning_readiness",
                            "updated_at",
                        ]
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
        return HttpResponse(
            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
            status=400,
        )


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
        scores = sorted(
            list(latest_ssa.scores.all().values("intervention", "score")),
            key=lambda s: s["score"],
        )
        if scores:
            weakest_area = dict(SsaIntervention.choices).get(
                scores[0]["intervention"], scores[0]["intervention"]
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
        raw_bulk_purpose = request.POST.get("purpose_of_visit", "").strip()
        try:
            bulk_purpose_of_visit = normalise_visit_purpose(
                raw_bulk_purpose,
                for_partner=True,
                fallback_activity_type="school_visit",
            )
        except Exception as exc:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">{exc}</div>',
                status=400,
            )
        # Preserve the legacy bulk submission contract until this compact
        # toolbar receives its own purpose picker. New callers that do send a
        # purpose receive its exact operational type; older callers stay on
        # School Visit while still gaining a partner-safe purpose record.
        bulk_activity_type = (
            purpose_activity_type(bulk_purpose_of_visit, "school_visit")
            if raw_bulk_purpose
            else "school_visit"
        )

        from datetime import date as _date

        from apps.activities.services import create as create_activity

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

        for s in schools:
            if PartnerAssignment.objects.filter(
                school=s,
                partner=partner,
                assigning_staff_id=monitored_by_staff_id,
                expected_activity_type=bulk_activity_type,
                created_at__gte=timezone.now() - dedup_window,
            ).exists():
                continue
            with transaction.atomic():
                pa = PartnerAssignment.objects.create(
                    school=s,
                    partner=partner,
                    assigning_staff_id=monitored_by_staff_id,
                    purpose="Bulk Partner Assignment",
                    purpose_of_visit=bulk_purpose_of_visit,
                    expected_activity_type=bulk_activity_type,
                    scheduled_date=bulk_date,
                    notes="Bulk Partner Assignment",
                    status="pending_scheduling",
                )
                # Same funnel as the single-item assign action
                # (activities.services.create — the SSA-justification,
                # structured-purpose, and assert_schedulable cost-catalogue
                # gates every other creation path goes through): create the
                # Activity immediately, atomically, with a real cost
                # snapshot, when a date is already known, so this handoff is
                # visible on both the partner's My Plan feed and the
                # assigning staff's Partner Monitoring bucket. No bulk date
                # collected yet? Correctly defer Activity creation to
                # schedule-time — apps.activities.services.partner_schedule
                # (used by Core Schools) is what lazily creates it off this
                # same PartnerAssignment once a date IS picked — instead of
                # ever persisting an un-costed activity.
                if bulk_date:
                    create_activity(
                        {
                            "activityType": bulk_activity_type,
                            "schoolId": s.school_id,
                            "deliveryType": "partner",
                            "assignedPartnerId": partner.id,
                            "activityPurposeText": pa.purpose,
                            "purposeType": bulk_purpose_of_visit,
                            "scheduledDate": bulk_date_raw,
                        },
                        principal=request.user,
                    )
                    pa.status = "partner_scheduled"
                    pa.scheduled_date = bulk_date
                    pa.save(update_fields=["status", "scheduled_date", "updated_at"])
                s.current_fy_ssa_status = "partner_assigned"
                s.save(
                    update_fields=[
                        "current_fy_ssa_status",
                        "planning_readiness",
                        "updated_at",
                    ]
                )

        return HttpResponse("<script>window.location.reload();</script>")

    elif action == "schedule":
        # Bulk school visits use the same direct scheduling path as an
        # individual visit.  This deliberately avoids daily-target, grouping,
        # and reason rules while still creating a real cost snapshot and
        # budget line for every selected school immediately.
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

        from apps.activities.services import create as create_activity
        from apps.core.exceptions import BadRequest

        try:
            with transaction.atomic():
                for school in schools:
                    create_activity(
                        {
                            "activityType": "school_visit",
                            "schoolId": school.school_id,
                            "scheduledDate": scheduled_date_raw,
                            "activityPurposeText": request.POST.get(
                                "activity_goal", "Bulk-scheduled visit"
                            ),
                            "focusIntervention": request.POST.get("focus_intervention")
                            or None,
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
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {e}</div>',
                status=400,
            )

    return HttpResponse("Action processed", status=200)


@require_page_permission("planning")
def schedule_activity_form_view(request):
    action = request.GET.get("action", "visit")  # visit, training, meeting
    school_id = request.GET.get("school", "")
    cluster_id = request.GET.get("cluster", "")

    # Populate lookups
    schools = School.objects.filter(deleted_at__isnull=True).order_by("name")
    clusters = Cluster.objects.filter(deleted_at__isnull=True).order_by("name")
    partners = Partner.objects.filter(
        deleted_at__isnull=True, active_status=True
    ).order_by("name")

    selected_school = (
        School.objects.filter(Q(id=school_id) | Q(school_id=school_id)).first()
        if school_id
        else None
    )
    selected_cluster = (
        Cluster.objects.filter(id=cluster_id).first() if cluster_id else None
    )

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
            scores = sorted(
                list(latest_ssa.scores.all().values("intervention", "score")),
                key=lambda s: s["score"],
            )
            for s in scores[:2]:
                code = s["intervention"]
                label = dict(SsaIntervention.choices).get(code, code)
                recommendations.append(
                    {"code": code, "label": label, "score": s["score"]}
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
