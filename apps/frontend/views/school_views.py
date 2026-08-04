import json

from django.shortcuts import render, redirect, get_object_or_404
from apps.core.redirects import local_redirect
from apps.core.donut import build_gauge
from apps.core.permissions import (
    RolePermissionService,
    get_scoped_object_or_404,
    require_page_permission,
)
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.html import escape
from django.utils.dateparse import parse_date
from django.urls import reverse
from urllib.parse import urlencode

from apps.schools.models import School
from apps.geography.models import Region, District, Parish, SubCounty
from apps.core.enums import SchoolType, PlanningReadiness
from apps.schools.upload_service import upload_school_file
from apps.schools.services import create_one as create_school
from apps.schools.services import get_one as get_school_one
from apps.analytics.services import school_impact
from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.accounts.staff_matching import OWNER_ROLES, on_staff
from apps.clusters.models import Cluster
from apps.clusters.services import (
    assign_school as assign_school_to_cluster,
    create_cluster as create_cluster_service,
    set_school_cluster_membership,
)
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.permissions import has_permission, render_access_denied
from apps.core.rbac import Permission
from apps.projects.models import (
    OPEN_PROJECT_STATUSES,
    Project,
    ProjectSchoolAssignment,
)
from apps.core.scoping import resolve_user_scope, school_queryset
from apps.frontend.view_models import SchoolDirectoryViewModel


def _may_upload_schools(request) -> bool:
    return has_permission(request.user, Permission.SCHOOL_UPLOAD.value)


def _may_upload_ssa(request) -> bool:
    return has_permission(request.user, Permission.SSA_UPLOAD.value)


def _school_owner_queryset():
    """Active CCEO/Program Lead profiles eligible to own a school."""
    return (
        on_staff(StaffProfile.objects)
        .filter(
            # on_staff, not is_active: a CCEO auto-created by a school upload
            # is a pending invite and already owns the schools that created
            # her. Filtering on login-ability hid real owners from the owner
            # picker.
            user__roles__overlap=list(OWNER_ROLES),
        )
        .select_related("user")
        .order_by("user__name")
    )


def _create_manual_school(request) -> School:
    """Validate and persist one school through the canonical school service."""
    district_id = request.POST.get("district_id", "").strip()
    district = (
        District.objects.select_related("region").filter(id=district_id).first()
        if district_id
        else None
    )
    if district is None:
        raise BadRequest("Select a valid district.")

    sub_county_id = request.POST.get("sub_county_id", "").strip()
    sub_county = None
    if sub_county_id:
        sub_county = SubCounty.objects.filter(
            id=sub_county_id,
            district_id=district.id,
        ).first()
        if sub_county is None:
            raise BadRequest("Select a valid sub-county within the district.")

    owner_id = request.POST.get("account_owner_id", "").strip()
    owner = _school_owner_queryset().filter(id=owner_id).first() if owner_id else None
    if owner is None:
        raise BadRequest("Select a valid CCEO or Program Lead as Staff Name.")

    with transaction.atomic():
        school = create_school(
            {
                "schoolId": request.POST.get("school_id", ""),
                "name": request.POST.get("name", ""),
                "regionId": district.region_id,
                "districtId": district.id,
                "subCountyId": sub_county.id if sub_county else None,
                "schoolType": request.POST.get("school_type", SchoolType.CLIENT),
                "enrollment": request.POST.get("enrollment", ""),
                "accountOwnerName": owner.user.name,
            },
            request.user,
        )
        school.account_owner_id = owner.id
        school.account_owner_name_raw = owner.user.name
        school.account_owner_status = "matched"
        school.save(
            update_fields=[
                "account_owner_id",
                "account_owner_name_raw",
                "account_owner_status",
                "updated_at",
            ]
        )
        StaffSchoolAssignment.objects.get_or_create(
            staff=owner,
            school_id=school.id,
        )

        cluster_id = request.POST.get("cluster_id", "").strip()
        if cluster_id:
            cluster = Cluster.objects.filter(
                id=cluster_id,
                deleted_at__isnull=True,
                status="active",
            ).first()
            if cluster is None:
                raise BadRequest("Select a valid active cluster.")
            set_school_cluster_membership(
                school,
                cluster,
                request.user.user_id,
            )

    return school


def _get_school_intelligence_data(school):
    cluster_name = "Unassigned"
    if school.cluster_id:
        cluster = Cluster.objects.filter(
            id=school.cluster_id, deleted_at__isnull=True
        ).first()
        if cluster:
            cluster_name = cluster.name

    project_assignments = (
        school.project_assignments.all()
        if hasattr(school, "project_assignments")
        else ProjectSchoolAssignment.objects.filter(school=school)
    )
    project_names = [pa.project.name for pa in project_assignments]
    project_text = ", ".join(project_names) if project_names else "None"

    is_clustered = school.cluster_id is not None or school.cluster_status == "clustered"
    is_project_assigned = project_assignments.exists()

    next_step_action = None
    next_step_text = ""
    next_step_button = ""

    if school.school_type == "core":
        if not is_clustered:
            next_step_text = "Core School — Requires Cluster. Add this school to a cluster before core planning can begin."
            next_step_action = "add_to_cluster"
            next_step_button = "Add to Cluster"
        else:
            next_step_text = "Core School clustered. Eligible for Core Assessment and core package planning."
            next_step_action = "view_core_planning"
            next_step_button = "Core Schools Planning"
    else:
        if not is_clustered:
            next_step_text = "Add this school to a cluster."
            next_step_action = "add_to_cluster"
            next_step_button = "Add to Cluster"
        elif not is_project_assigned:
            next_step_text = (
                "Assign to project if needed, or continue planning through cluster."
            )
            next_step_action = "assign_to_project"
            next_step_button = "Assign to Project"
        else:
            next_step_text = "Open project plan."
            next_step_action = "open_project_plan"
            next_step_button = "Open Project Plan"

    return {
        "school": school,
        "cluster_name": cluster_name,
        "project_text": project_text,
        "school_contact": school.primary_contact_name or "—",
        "next_step_text": next_step_text,
        "next_step_action": next_step_action,
        "next_step_button": next_step_button,
    }


@require_page_permission("school_directory")
def school_intelligence_partial(request, school_id):
    school = get_scoped_object_or_404(
        School, request.user, id=school_id, deleted_at__isnull=True
    )
    intel_data = _get_school_intelligence_data(school)
    can_toggle_core = request.user.active_role in (
        "Admin",
        "CountryDirector",
        "ImpactAssessment",
    )
    return render(
        request,
        "partials/schools/directory_intelligence.html",
        {"intelligence": intel_data, "can_toggle_core": can_toggle_core},
    )


@require_page_permission("school_directory")
def school_directory_view(request):
    user = request.user
    scope = resolve_user_scope(user)

    # Scoped base query
    base_qs = school_queryset(scope).filter(deleted_at__isnull=True)

    # Input parameters
    q = request.GET.get("q", "").strip()
    fy = request.GET.get("fy", "2026").strip()
    region_id = request.GET.get("region", "").strip()
    district_id = request.GET.get("district", "").strip()
    sub_county_id = request.GET.get("sub_county", "").strip()
    # Sub-county is a dependent filter. If the district changes, discard a
    # stale sub-county value from the previous district before querying.
    if sub_county_id and (
        not district_id
        or not SubCounty.objects.filter(
            id=sub_county_id,
            district_id=district_id,
        ).exists()
    ):
        sub_county_id = ""
    school_type = request.GET.get("school_type", "").strip()
    cluster_status = request.GET.get("cluster_status", "").strip()
    project_status = request.GET.get("project_status", "").strip()
    active_tab = request.GET.get("tab", "all").strip()
    if active_tab not in {
        "all",
        "unclustered",
        "clustered",
        "not_assigned",
        "assigned",
    }:
        active_tab = "all"
    page_number = request.GET.get("page", 1)
    try:
        per_page = int(request.GET.get("per_page", 15))
    except (TypeError, ValueError):
        per_page = 15
    if per_page not in {15, 25, 50}:
        per_page = 15

    # Apply dropdown filters
    filtered_qs = base_qs.order_by("name")
    if q:
        # The directory's search contract. Name and School ID alone meant a user
        # who knew a school only by where it sits, who owns it, or which cluster
        # it belongs to could not find it at all.
        #
        # Every term below is either a column on School or a forward FK, so none
        # of them fan the row out and none of them need distinct() — which
        # matters here, because distinct() on this queryset would fight the
        # order_by("name") applied above.
        #
        # cluster_id is a CharField rather than a relation, so cluster names are
        # resolved through a subquery instead of a join.
        # The uploaded_* text columns are searched alongside the structured ones
        # so schools whose geography never matched a UBOS record stay findable
        # by the district and sub-county their upload actually named.
        filtered_qs = filtered_qs.filter(
            Q(name__icontains=q)
            | Q(school_id__icontains=q)
            | Q(district__name__icontains=q)
            | Q(sub_county__name__icontains=q)
            | Q(uploaded_district_text__icontains=q)
            | Q(uploaded_sub_county_text__icontains=q)
            | Q(account_owner_name_raw__icontains=q)
            | Q(cluster_id__in=Cluster.objects.filter(name__icontains=q).values("id"))
        )
    if region_id:
        filtered_qs = filtered_qs.filter(region_id=region_id)
    if district_id:
        filtered_qs = filtered_qs.filter(district_id=district_id)
    if sub_county_id:
        filtered_qs = filtered_qs.filter(sub_county_id=sub_county_id)
    if school_type:
        filtered_qs = filtered_qs.filter(school_type=school_type)
    if cluster_status:
        filtered_qs = filtered_qs.filter(cluster_status=cluster_status)
    if project_status:
        if project_status == "assigned":
            filtered_qs = filtered_qs.filter(
                project_assignments__isnull=False
            ).distinct()
        elif project_status == "unassigned":
            filtered_qs = filtered_qs.exclude(
                project_assignments__isnull=False
            ).distinct()

    # Compute Tab Counts on the filtered list (before active tab filtering)
    all_count = filtered_qs.count()
    unclustered_count = filtered_qs.filter(cluster_status="unclustered").count()
    clustered_count = filtered_qs.filter(cluster_status="clustered").count()
    not_assigned_count = (
        filtered_qs.exclude(project_assignments__isnull=False).distinct().count()
    )
    assigned_count = (
        filtered_qs.filter(project_assignments__isnull=False).distinct().count()
    )

    # Apply Tab Filter
    schools_qs = filtered_qs
    if active_tab == "unclustered":
        schools_qs = schools_qs.filter(cluster_status="unclustered")
    elif active_tab == "clustered":
        schools_qs = schools_qs.filter(cluster_status="clustered")
    elif active_tab == "not_assigned":
        schools_qs = schools_qs.exclude(project_assignments__isnull=False).distinct()
    elif active_tab == "assigned":
        schools_qs = schools_qs.filter(project_assignments__isnull=False).distinct()

    # Export the currently filtered list in the format promised by the UI.
    export_format = request.GET.get("export", "").strip()
    if export_format in ("csv", "xlsx"):
        import csv
        from io import BytesIO
        from django.http import HttpResponse

        headers = [
            "School ID",
            "Name",
            "Type",
            "District",
            "Sub-county",
            "Region",
            "Enrollment",
            "Cluster Status",
            "SSA Status",
            "Planning Readiness",
        ]
        export_rows = (
            [
                school.school_id,
                school.name,
                school.school_type,
                school.district.name if school.district else "",
                school.sub_county.name if school.sub_county else "",
                school.region.name if school.region else "",
                school.enrollment or "",
                school.cluster_status or "",
                school.current_fy_ssa_status or "",
                school.planning_readiness or "",
            ]
            for school in schools_qs.select_related("district", "sub_county", "region")[
                :5000
            ]
        )

        if export_format == "xlsx":
            from openpyxl import Workbook

            workbook = Workbook(write_only=True)
            worksheet = workbook.create_sheet("Schools")
            worksheet.append(headers)
            for row in export_rows:
                worksheet.append(row)
            output = BytesIO()
            workbook.save(output)
            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = (
                'attachment; filename="schools_export.xlsx"'
            )
            return response

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="schools_export.csv"'
        writer = csv.writer(response)
        writer.writerow(headers)
        writer.writerows(export_rows)
        return response

    # KPIs describe the population the table shows. Computed from `base_qs`
    # they ignored every filter, so narrowing to one district left twelve rows
    # under a "Total Schools 1,043" headline — three different populations on
    # one screen. `filtered_qs` is pre-tab, which is the same population the
    # tab counts already use.
    kpi_qs = filtered_qs
    total_schools = kpi_qs.count()
    client_schools = kpi_qs.filter(school_type="client").count()
    core_schools = kpi_qs.filter(school_type="core").count()
    unclustered_schools = kpi_qs.filter(cluster_status="unclustered").count()
    no_ssa_schools = kpi_qs.filter(current_fy_ssa_status="not_done").count()
    staff_setup_schools = kpi_qs.filter(
        Q(account_owner_id__isnull=True)
        | Q(account_owner_id="")
        | Q(account_owner_status="pending")
    ).count()
    planning_ready_schools = kpi_qs.filter(
        planning_readiness__in=PlanningReadiness.planning_ready_values()
    ).count()
    duplicate_schools = kpi_qs.filter(duplicate_status="duplicate").count()
    district_count = (
        kpi_qs.exclude(district_id__isnull=True)
        .values("district_id")
        .distinct()
        .count()
    )

    needs_setup = staff_setup_schools
    needs_ssa = no_ssa_schools
    ready_for_planning = planning_ready_schools

    # Construct unified KPI strip items
    kpi_strip_items = [
        {
            "label": "Total Schools",
            "value": str(total_schools),
            "raw_value": total_schools,
            "helper": f"Across {district_count} district{'' if district_count == 1 else 's'}",
            "icon": "school",
            "variant": "primary",
        },
        {
            "label": "Client Schools",
            "value": str(client_schools),
            "raw_value": client_schools,
            "helper": f"{round(client_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            "icon": "school",
            "variant": "success",
        },
        {
            "label": "Core Schools",
            "value": str(core_schools),
            "raw_value": core_schools,
            "helper": f"{round(core_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            "icon": "school",
            "variant": "purple",
        },
        {
            "label": "Unclustered",
            "value": str(unclustered_schools),
            "raw_value": unclustered_schools,
            "helper": f"{round(unclustered_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            "icon": "school",
            "variant": "warning",
        },
        {
            "label": "No SSA",
            "value": str(no_ssa_schools),
            "raw_value": no_ssa_schools,
            "helper": f"{round(no_ssa_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            "icon": "warning",
            "variant": "danger",
        },
        {
            "label": "Staff Required",
            "value": str(staff_setup_schools),
            "raw_value": staff_setup_schools,
            "helper": f"{round(staff_setup_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            "icon": "users",
            "variant": "warning",
        },
        {
            "label": "Planning Ready",
            "value": str(planning_ready_schools),
            "raw_value": planning_ready_schools,
            "helper": f"{round(planning_ready_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Duplicates",
            "value": str(duplicate_schools),
            "raw_value": duplicate_schools,
            "helper": f"{round(duplicate_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            "icon": "warning",
            "variant": "neutral",
        },
    ]

    # Paginate list
    schools_qs = schools_qs.select_related(
        "district", "sub_county", "parish"
    ).prefetch_related("project_assignments__project")
    schools_qs = schools_qs.annotate(
        _project_count=Count("project_assignments", distinct=True)
    )
    paginator = Paginator(schools_qs, per_page)
    page_obj = paginator.get_page(page_number)
    pages_list = list(
        page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=2, on_ends=1
        )
    )

    clusters_dict = {
        c.id: c.name for c in Cluster.objects.filter(deleted_at__isnull=True)
    }
    active_projects_exist = Project.objects.filter(deleted_at__isnull=True).exists()

    # Batch-compute SSA/visit/training progress for this page of schools in
    # a handful of queries instead of ~5-7 per-row queries inside from_school
    # (was a confirmed N+1 on the school directory list).
    page_school_ids = [s.id for s in page_obj]
    progress_by_school = SchoolDirectoryViewModel.bulk_progress(page_school_ids, fy=fy)
    owner_ids = {
        school.account_owner_id for school in page_obj if school.account_owner_id
    }
    staff_names_by_owner_id = {}
    if owner_ids:
        for staff in (
            StaffProfile.objects.filter(deleted_at__isnull=True)
            .filter(Q(id__in=owner_ids) | Q(user_id__in=owner_ids))
            .select_related("user")
        ):
            if staff.user_id and staff.user.name:
                staff_names_by_owner_id[staff.id] = staff.user.name
                staff_names_by_owner_id[staff.user_id] = staff.user.name

    view_models = [
        SchoolDirectoryViewModel.from_school(
            s,
            user,
            clusters_dict,
            active_projects_exist,
            progress=progress_by_school.get(s.id),
            staff_names_by_owner_id=staff_names_by_owner_id,
        )
        for s in page_obj
    ]

    # Default Selected School Intelligence
    selected_school_data = None
    if page_obj.object_list:
        default_school = page_obj.object_list[0]
        selected_school_data = _get_school_intelligence_data(default_school)

    # Populating filter and data-entry options.
    #
    # Once schools exist, directory filters remain scoped to places that can
    # produce a result. After a school-data purge, however, that rule used to
    # make the geography reference data appear deleted. Fall back to the full
    # district reference list in the empty state, then reveal sub-counties for
    # the selected district.
    scoped_district_ids = base_qs.values("district_id")
    scoped_sub_county_ids = base_qs.exclude(sub_county__isnull=True).values(
        "sub_county_id"
    )
    regions = Region.objects.all().order_by("name")
    reference_districts = District.objects.select_related("region").order_by("name")
    has_scoped_schools = base_qs.exists()
    if has_scoped_schools:
        districts = (
            District.objects.filter(id__in=scoped_district_ids)
            .distinct()
            .order_by("name")
        )
    else:
        districts = reference_districts
    if district_id:
        sub_counties = SubCounty.objects.filter(district_id=district_id).order_by(
            "name"
        )
    elif has_scoped_schools:
        sub_counties = (
            SubCounty.objects.filter(id__in=scoped_sub_county_ids)
            .distinct()
            .order_by("name")
        )
    else:
        sub_counties = SubCounty.objects.none()
    staff_profiles = (
        StaffProfile.objects.filter(deleted_at__isnull=True)
        .select_related("user")
        .order_by("user__name")
    )
    school_owners = _school_owner_queryset()
    clusters = Cluster.objects.filter(deleted_at__isnull=True).order_by("name")
    from apps.projects.scoping import scoped_projects

    projects = scoped_projects(user).filter(
        status__in=[status.value for status in OPEN_PROJECT_STATUSES],
    )
    if user.active_role not in (
        "ImpactAssessment",
        "CountryDirector",
        "Admin",
    ):
        projects = projects.filter(
            Q(manager_staff_id=getattr(user, "staff_profile_id", None))
            | Q(
                staff_assignments__staff_id=getattr(user, "staff_profile_id", None),
                staff_assignments__is_active=True,
            )
        )
    projects = projects.distinct().order_by("name")

    context = {
        "page_obj": page_obj,
        "pages_list": pages_list,
        "per_page": per_page,
        "view_models": view_models,
        "kpi_strip_items": kpi_strip_items,
        "regions": regions,
        "districts": districts,
        "sub_counties": sub_counties,
        "reference_districts": reference_districts,
        "staff_profiles": staff_profiles,
        "school_owners": school_owners,
        "clusters": clusters,
        "projects": projects,
        "school_types": SchoolType.choices,
        "readiness_choices": PlanningReadiness.choices,
        # Selected states
        "q": q,
        "topbar_search": {
            # Names what this page actually searches. It carried the platform's
            # generic default, which both undersold the field set (School IDs,
            # sub-counties and clusters are all matched) and implied a staff
            # directory the page does not offer.
            "placeholder": "Search schools, School IDs, districts, sub-counties…",
            "label": (
                "Search schools by name, School ID, district, sub-county, "
                "cluster or assigned owner"
            ),
            "input_id": "topbar-search-input",
            "value": q,
            "hx_get": "/schools",
            "hx_target": "#schools-table-container",
            "hx_trigger": "keyup delay:300ms, search",
            "hx_include": "#filters-form",
        },
        "selected_fy": fy,
        "selected_region": region_id,
        "selected_district": district_id,
        "selected_sub_county": sub_county_id,
        "selected_type": school_type,
        "selected_cluster_status": cluster_status,
        "selected_project_status": project_status,
        "active_tab": active_tab,
        # KPI Row
        "total_schools": total_schools,
        "client_schools": client_schools,
        "core_schools": core_schools,
        "unclustered_schools": unclustered_schools,
        "no_ssa_schools": no_ssa_schools,
        "staff_setup_schools": staff_setup_schools,
        "planning_ready_schools": planning_ready_schools,
        "duplicate_schools": duplicate_schools,
        # Priority Strip
        "needs_setup": needs_setup,
        "needs_ssa": needs_ssa,
        "ready_for_planning": ready_for_planning,
        # Tab counts
        "all_count": all_count,
        "unclustered_count": unclustered_count,
        "clustered_count": clustered_count,
        "not_assigned_count": not_assigned_count,
        "assigned_count": assigned_count,
        # Selected school intelligence
        "intelligence": selected_school_data,
        "can_toggle_core": user.active_role
        in ("Admin", "CountryDirector", "ImpactAssessment"),
        "can_schedule": RolePermissionService.can_schedule_activity(user),
        "can_upload_schools": _may_upload_schools(request),
        "can_add_ssa": _may_upload_ssa(request),
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/schools/htmx_response.html", context)

    return render(request, "pages/schools/index.html", context)


@require_page_permission("school_directory")
def school_sub_county_options_view(request):
    """Return native select options for a district-dependent school form."""
    district_id = request.GET.get("district_id", "").strip()
    sub_counties = (
        SubCounty.objects.filter(district_id=district_id).order_by("name")
        if district_id
        else SubCounty.objects.none()
    )
    return render(
        request,
        "partials/schools/sub_county_options.html",
        {"sub_counties": sub_counties},
    )


@require_page_permission("school_directory")
def school_parish_options_view(request):
    """Return native select options for a sub-county-dependent school form."""
    sub_county_id = request.GET.get("sub_county_id", "").strip()
    parishes = (
        Parish.objects.filter(sub_county_id=sub_county_id).order_by("name")
        if sub_county_id
        else Parish.objects.none()
    )
    return render(
        request,
        "partials/schools/parish_options.html",
        {"parishes": parishes},
    )


@require_page_permission("school_directory")
def add_to_cluster_drawer_view(request, school_id):
    school = get_scoped_object_or_404(
        School, request.user, id=school_id, deleted_at__isnull=True
    )
    user = request.user

    from apps.core.permissions import has_permission

    if not has_permission(user, "cluster.assign"):
        return render(
            request,
            "partials/schools/drawer_error.html",
            {"error": "You do not have permission to assign clusters."},
        )

    def get_existing_covering_cluster(sch):
        """Resolve both primary and multi-sub-county cluster coverage."""
        if not sch.sub_county_id:
            return None
        return (
            Cluster.objects.filter(
                district_id=sch.district_id,
                deleted_at__isnull=True,
                status="active",
            )
            .filter(
                Q(sub_county_id=sch.sub_county_id)
                | Q(covered_sub_counties__sub_county_id=sch.sub_county_id)
            )
            .select_related("district", "sub_county")
            .distinct()
            .order_by("name")
            .first()
        )

    def get_responsible_staff(sch):
        """Use the school's owner; fall back to its portfolio assignment."""
        if sch.account_owner_id:
            owner = (
                StaffProfile.objects.filter(
                    Q(id=sch.account_owner_id) | Q(user_id=sch.account_owner_id),
                    deleted_at__isnull=True,
                    user__is_active=True,
                )
                .select_related("user")
                .first()
            )
            if owner:
                return owner
        assigned_profiles = list(
            StaffProfile.objects.filter(
                school_links__school_id=sch.id,
                deleted_at__isnull=True,
                user__is_active=True,
            )
            .select_related("user")
            .order_by("user__name", "id")[:2]
        )
        return assigned_profiles[0] if len(assigned_profiles) == 1 else None

    existing_covering_cluster = get_existing_covering_cluster(school)
    responsible_staff = get_responsible_staff(school)
    show_cluster_directory = bool(
        school.sub_county_id and existing_covering_cluster is None
    )

    def drawer_context(validation_error=None):
        nearby_clusters = Cluster.objects.none()
        if show_cluster_directory:
            nearby_clusters = (
                Cluster.objects.filter(
                    district_id=school.district_id,
                    deleted_at__isnull=True,
                    status="active",
                )
                .select_related("district", "sub_county")
                .annotate(schools_count=Count("assignments", distinct=True))
                .order_by("name")
            )
        return {
            "school": school,
            "responsible_staff": responsible_staff,
            "all_clusters": nearby_clusters,
            "existing_covering_cluster": existing_covering_cluster,
            "show_cluster_directory": show_cluster_directory,
            "validation_error": validation_error,
            "drawer_type": "center",
            "drawer_size": "md",
        }

    # 1. Enforce Minimum Data Needed for Clustering
    # Minimum data gate: school_id, name, and district are required.
    # Sub-county is NOT required — staff can cluster at district level.
    if not school.school_id or not school.name or not school.district_id:
        return render(
            request,
            "partials/schools/add_to_cluster_drawer.html",
            drawer_context(
                "This school needs a School ID, Name, and District before it can "
                "be clustered. Sub-county is optional."
            ),
        )

    if request.method == "POST":
        action_type = request.POST.get(
            "cluster_action_type",
            "existing" if show_cluster_directory else "new",
        )
        cluster = existing_covering_cluster

        if cluster is None and action_type == "existing":
            if not show_cluster_directory:
                return render(
                    request,
                    "partials/schools/add_to_cluster_drawer.html",
                    drawer_context(
                        "Add a sub-county to the school before selecting a nearby "
                        "cluster."
                    ),
                )
            cluster_id = request.POST.get("existing_cluster_id")
            cluster = (
                Cluster.objects.filter(
                    id=cluster_id,
                    district_id=school.district_id,
                    deleted_at__isnull=True,
                    status="active",
                )
                .select_related("district")
                .first()
            )
            if cluster is None:
                return render(
                    request,
                    "partials/schools/add_to_cluster_drawer.html",
                    drawer_context("Select a nearby cluster."),
                )

        if cluster is None:
            # Create new cluster
            cluster_name = request.POST.get("new_cluster_name", "").strip()
            district_id = request.POST.get("new_district_id")
            new_sub_county_ids = request.POST.getlist("new_sub_county_ids")

            # Enforce that the school's own sub-county is always included in the cluster coverage
            # Only include the school's own sub-county if it has one.
            if school.sub_county_id:
                school_sub_county_id_str = str(school.sub_county_id)
                if school_sub_county_id_str not in new_sub_county_ids:
                    new_sub_county_ids.append(school_sub_county_id_str)

            if (
                not cluster_name
                or not district_id
                or str(district_id) != str(school.district_id)
            ):
                return render(
                    request,
                    "partials/schools/add_to_cluster_drawer.html",
                    drawer_context("Enter a cluster name to continue."),
                )

            # Route through the real create_cluster() service instead of the
            # ORM directly — it enforces the sub-county-uniqueness rule (one
            # active cluster per sub-county unless the caller holds
            # CLUSTER_OVERRIDE + states a reason). Building the Cluster here
            # directly let a CCEO holding only CLUSTER_ASSIGN create an
            # overlapping-sub-county cluster the dedicated Create-Cluster flow
            # would correctly reject.
            try:
                cluster_data = create_cluster_service(
                    {
                        "name": cluster_name,
                        "regionId": school.region_id,
                        "districtId": district_id,
                        "subCountyIds": new_sub_county_ids,
                        "responsibleStaffId": responsible_staff.id
                        if responsible_staff
                        else None,
                    },
                    user,
                )
            except (BadRequest, Forbidden) as e:
                return render(
                    request,
                    "partials/schools/add_to_cluster_drawer.html",
                    drawer_context(str(e)),
                )
            cluster = get_object_or_404(
                Cluster, id=cluster_data["id"], deleted_at__isnull=True
            )

        # Responsible staff is always derived from the school's owner. Posted
        # staff ids and assignment notes are deliberately ignored.
        if responsible_staff and cluster.responsible_staff_id != responsible_staff.id:
            cluster.responsible_staff_id = responsible_staff.id
            cluster.save(update_fields=["responsible_staff_id", "updated_at"])
        # Audited inside set_school_cluster_membership() (the canonical
        # service assign_school_to_cluster delegates to) — not duplicated
        # here.
        #
        # Wrapped like the create_cluster_service call above, which it was not:
        # assign_school raises BadRequest, NotFoundError and Forbidden, and
        # set_school_cluster_membership underneath it raises BadRequest when a
        # school's district does not match the cluster's, or when the cluster
        # is no longer active. Unhandled, every one of those reached the user
        # as a 500 (INC-000001) instead of the sentence explaining what was
        # wrong. The withdrawn-cluster case is a genuine race: the drawer lists
        # a cluster, someone retires it, and the assignment arrives afterwards.
        try:
            assign_school_to_cluster(school.school_id, {"clusterId": cluster.id}, user)
        except (BadRequest, Forbidden, NotFoundError) as exc:
            return render(
                request,
                "partials/schools/add_to_cluster_drawer.html",
                drawer_context(str(getattr(exc, "detail", exc))),
            )

        response = render(
            request,
            "partials/schools/toast_success.html",
            {"message": "School added to cluster successfully."},
        )
        response["HX-Trigger"] = "schools-updated"
        return response

    return render(
        request,
        "partials/schools/add_to_cluster_drawer.html",
        drawer_context(),
    )


@require_page_permission("school_directory")
def assign_to_project_drawer_view(request, school_id):
    school = get_scoped_object_or_404(
        School, request.user, id=school_id, deleted_at__isnull=True
    )
    user = request.user

    from apps.core.permissions import has_permission

    if not has_permission(user, "project.assignSchool"):
        return render(
            request,
            "partials/schools/drawer_error.html",
            {"error": "You do not have permission to assign projects."},
        )

    def _drawer_context(extra=None):
        """Full option set for the drawer — shared by GET and validation re-renders."""
        from apps.core.enums import SsaIntervention

        try:
            from apps.accounts.models import StaffProfile

            coordinators = list(
                StaffProfile.objects.filter(
                    user__roles__contains=["ProjectCoordinator"]
                ).select_related("user")
            )
        except Exception:  # noqa: BLE001
            coordinators = []
        from apps.projects.scoping import scoped_projects

        projects = scoped_projects(user).filter(
            status__in=[s.value for s in OPEN_PROJECT_STATUSES],
        )
        if user.active_role not in (
            "ImpactAssessment",
            "CountryDirector",
            "Admin",
        ):
            projects = projects.filter(
                Q(manager_staff_id=getattr(user, "staff_profile_id", None))
                | Q(
                    staff_assignments__staff_id=getattr(user, "staff_profile_id", None),
                    staff_assignments__is_active=True,
                )
            )
        ctx = {
            "school": school,
            "school_contact": school.primary_contact_name or "—",
            # Only projects still accepting work are offerable — a paused or
            # closed project should not be selectable in the first place.
            "projects": projects.distinct().order_by("name"),
            "interventions": SsaIntervention.choices,
            "coordinators": coordinators,
        }
        if extra:
            ctx.update(extra)
        return ctx

    if request.method == "POST":
        project_id = request.POST.get("project_id")
        project_type = request.POST.get("project_type", "").strip()
        participation_type = request.POST.get("participation_type", "").strip()
        start_date_str = request.POST.get("start_date", "").strip()
        support_area = request.POST.get("support_area", "").strip()
        coordinator_id = request.POST.get("coordinator_id", "").strip()
        notes = request.POST.get("notes", "").strip()

        if not project_id:
            return render(
                request,
                "partials/schools/assign_to_project_drawer.html",
                _drawer_context({"validation_error": "Please select a project."}),
            )

        project = get_object_or_404(Project, id=project_id, deleted_at__isnull=True)

        already_assigned = ProjectSchoolAssignment.objects.filter(
            project=project, school=school
        ).exists()
        if already_assigned:
            return render(
                request,
                "partials/schools/assign_to_project_drawer.html",
                _drawer_context(
                    {"validation_error": "School is already assigned to this project."}
                ),
            )

        if not project.accepts_new_work:
            return render(
                request,
                "partials/schools/assign_to_project_drawer.html",
                _drawer_context(
                    {
                        "validation_error": (
                            f"'{project.name}' is {project.status_label.lower()} — "
                            "no new schools can be assigned to it."
                        )
                    }
                ),
            )

        start_date = None
        if start_date_str:
            import datetime

            try:
                start_date = datetime.datetime.strptime(
                    start_date_str, "%Y-%m-%d"
                ).date()
            except ValueError:
                pass

        # One canonical service enforces SSA need, Project staff scope, school
        # focus, and the Client=1/Core=4 Project portfolio limit.
        from apps.projects.services import assign_school as assign_project_school

        try:
            assign_project_school(
                project.id,
                {
                    "schoolId": school.school_id,
                    "projectType": project_type,
                    "participationType": participation_type,
                    "startDate": start_date,
                    "supportArea": support_area,
                    "notes": notes,
                    "reason": notes,
                },
                user,
            )
        except (BadRequest, Forbidden) as exc:
            return render(
                request,
                "partials/schools/assign_to_project_drawer.html",
                _drawer_context({"validation_error": str(exc)}),
            )

        # Set the project's coordinator if one was chosen and none is set yet
        # (a per-school action shouldn't silently reassign an owned project).
        if coordinator_id and not project.manager_staff_id:
            project.manager_staff_id = coordinator_id
            project.save(update_fields=["manager_staff_id", "updated_at"])

        # Notify the effective Project Coordinator (resolve staff -> user id).
        target_staff_id = project.manager_staff_id or coordinator_id
        if target_staff_id:
            try:
                from apps.accounts.models import StaffProfile
                from apps.notifications.services import WorkflowNotificationService

                sp = (
                    StaffProfile.objects.filter(id=target_staff_id)
                    .select_related("user")
                    .first()
                )
                if sp and sp.user_id:
                    WorkflowNotificationService.trigger(
                        event_type="project_school_assigned",
                        category="project",
                        priority="normal",
                        title="New project school assigned",
                        body=(
                            f"{school.name} has been assigned to {project.name}. "
                            "Review it in your project planning queue."
                        ),
                        context_type="School",
                        context_id=school.id,
                        recipients=[sp.user_id],
                    )
            except Exception:  # noqa: BLE001 - notification must never block assignment
                pass

        from apps.audit.services import log as audit_log

        audit_log(
            action="school.assign_project",
            subject_kind="School",
            subject_id=school.id,
            actor_id=user.user_id,
            actor_role=user.active_role,
            success=True,
            payload={
                "project_id": project.id,
                "project_name": project.name,
                "project_type": project_type,
                "participation_type": participation_type,
                "support_area": support_area,
                "coordinator_staff_id": target_staff_id,
            },
        )

        response = render(
            request,
            "partials/schools/toast_success.html",
            {"message": f"{school.name} assigned to {project.name}."},
        )
        response["HX-Trigger"] = "schools-updated"
        return response

    return render(
        request,
        "partials/schools/assign_to_project_drawer.html",
        _drawer_context(),
    )


@require_page_permission("school_upload")
def school_template_download_view(request):
    """Download a CSV template with the correct school-upload column headers."""
    from django.http import HttpResponse
    import csv

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        'attachment; filename="school_upload_template.csv"'
    )
    writer = csv.writer(response)
    # Required columns first, followed by optional profile fields.
    writer.writerow(
        [
            "School ID",
            "School Name",
            "District",
            "Sub County",
            "Current Partner Type",
            "Staff Name",
            "Enrolment",
            "Last Date of Enrolment",
            "Phone",
            "Primary Contact",
            "School Shipping Address",
        ]
    )
    # Minimal valid sample row: every field after School Name is optional.
    writer.writerow(
        [
            "SCH-0001",
            "St. Mary's Primary School",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    return response


@require_page_permission("school_upload")
def school_upload_view(request):
    if request.user.active_role not in ["Admin", "ImpactAssessment"]:
        messages.error(
            request, "Access restricted: Insufficient permissions for data upload."
        )
        return redirect("/dashboard")

    if request.method == "POST":
        schools_file = request.FILES.get("schools_file")

        if schools_file:
            update_existing = request.POST.get("update_existing") == "on"
            try:
                result = upload_school_file(
                    schools_file, request.user, update_existing=update_existing
                )
                result["type"] = "schools"
                return render(
                    request, "partials/upload_result.html", {"result": result}
                )
            except Exception as e:
                return render(request, "partials/upload_result.html", {"error": str(e)})

        return render(
            request,
            "partials/upload_result.html",
            {"error": "Select a school roster file to upload."},
        )

    return render(request, "pages/schools/upload.html")


@require_page_permission("school_profile")
def school_detail_view(request, school_id):
    school = get_school_one(school_id, request.user)
    school.assigned_staff = (
        school.account_owner_name_raw or school.account_owner_id or "Unassigned"
    )
    latest_ssa = (
        school.ssa_records.filter(deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )
    ssa_scores_list = []
    if latest_ssa:
        ssa_scores_list = list(latest_ssa.scores.all().order_by("-score"))

    historical_ssas = school.ssa_records.filter(deleted_at__isnull=True).order_by(
        "-date_of_ssa"
    )[1:]
    activities = school.activities.filter(deleted_at__isnull=True).order_by(
        "-planned_date"
    )
    impact_data = school_impact(school_id, request.user)

    from apps.ssa.services import get_ssa_progress_by_fy
    from apps.schools.models import School

    ssa_progress_history = get_ssa_progress_by_fy(School.objects.filter(id=school.id))

    # The ring carries the same four states the status pill does, so the two
    # cannot disagree about what "Needs Cleanup" looks like.
    quality_colour = {
        "Clean": "var(--edify-chart-green)",
        "Needs Review": "var(--edify-chart-blue)",
        "Needs Cleanup": "var(--edify-chart-amber)",
    }.get(school.data_quality_status, "var(--edify-chart-red)")
    quality_gauge = build_gauge(
        school.data_quality_score, label="Data quality", color=quality_colour
    )

    from apps.core.navigation import get_user_role_slug

    context = {
        "school": school,
        "latest_ssa": latest_ssa,
        "ssa_scores": ssa_scores_list,
        "historical_ssas": historical_ssas,
        "ssa_progress_history": ssa_progress_history,
        "activities": activities,
        "impact_data": impact_data,
        "quality_gauge": quality_gauge,
        # Deletion is Admin-only (enforced server-side by delete_school; this
        # flag only controls whether the Danger Zone renders).
        "can_delete_school": get_user_role_slug(request.user) == "ADMIN",
    }
    return render(request, "pages/schools/detail.html", context)


@require_page_permission("school_profile")
def school_delete_view(request, school_id):
    """Admin-only school deletion (POST). Guard rails live in the service."""
    from apps.core.exceptions import BadRequest, NotFoundError
    from apps.schools.services import delete_school

    if request.method != "POST":
        return redirect("frontend:school_detail", school_id=school_id)
    try:
        result = delete_school(school_id, request.user)
    except NotFoundError:
        messages.error(request, "School not found.")
        return redirect("frontend:schools_directory")
    except BadRequest as exc:
        messages.error(request, str(exc.detail))
        return redirect("frontend:school_detail", school_id=school_id)
    messages.warning(
        request,
        f"School '{result['name']}' deleted. SSA history and audit logs are retained.",
    )
    return redirect("frontend:schools_directory")


@require_page_permission("school_directory")
def bulk_assign_cluster_view(request):
    if request.method == "POST":
        school_ids = request.POST.get("school_ids", "").split(",")
        cluster_id = request.POST.get("cluster_id", "").strip()
        if school_ids and cluster_id:
            cluster = get_object_or_404(Cluster, id=cluster_id, deleted_at__isnull=True)
            scope = resolve_user_scope(request.user)
            schools = school_queryset(scope).filter(
                id__in=school_ids, deleted_at__isnull=True
            )
            already_clustered = schools.filter(cluster_status="clustered")
            if already_clustered.exists():
                skipped_names = ", ".join([s.name for s in already_clustered])
                messages.warning(
                    request, f"Skipped already-clustered schools: {skipped_names}."
                )
                schools = schools.exclude(cluster_status="clustered")

            count = 0
            for s in schools:
                assign_school_to_cluster(
                    s.school_id, {"clusterId": cluster.id}, request.user
                )
                count += 1
            if count > 0:
                messages.success(
                    request,
                    f"Successfully assigned {count} schools to cluster '{cluster.name}'.",
                )
            else:
                messages.error(request, "No unclustered schools were selected.")
        else:
            messages.error(request, "Failed to perform assignment: missing fields.")
    return redirect("/schools")


@require_page_permission("school_directory")
def bulk_assign_project_view(request):
    # Same two gates as the single-school drawer: the assignSchool permission,
    # and the ecosystem rule that a school either shows confirmed SSA need in a
    # target intervention or carries a written override reason. Without these
    # the bulk path was a way to attach off-recommendation cohorts with no
    # permission check and no recorded justification.
    from apps.core.permissions import has_permission

    if not has_permission(request.user, "project.assignSchool"):
        messages.error(request, "You do not have permission to assign projects.")
        return redirect("/schools")

    if request.method == "POST":
        school_ids = [s for s in request.POST.get("school_ids", "").split(",") if s]
        project_id = request.POST.get("project_id", "").strip()
        override_reason = (request.POST.get("override_reason") or "").strip()
        if school_ids and project_id:
            project = get_object_or_404(Project, id=project_id, deleted_at__isnull=True)
            if not project.accepts_new_work:
                messages.error(
                    request,
                    f"'{project.name}' is {project.status_label.lower()} — no new "
                    "schools can be assigned to it.",
                )
                return redirect("/schools")
            # Same scope constraint as bulk_match_staff_view above: the
            # project.assignSchool permission gates *whether* the caller may
            # assign, not *which* schools they may reach.
            scope = resolve_user_scope(request.user)
            schools = school_queryset(scope).filter(
                id__in=school_ids, deleted_at__isnull=True
            )

            from apps.projects.services import assign_school as assign_project_school

            count = 0
            duplicates = 0
            skipped_errors = []
            for s in schools:
                already_assigned = ProjectSchoolAssignment.objects.filter(
                    project=project, school=s
                ).exists()
                if already_assigned:
                    duplicates += 1
                    continue

                try:
                    assign_project_school(
                        project.id,
                        {
                            "schoolId": s.school_id,
                            "notes": override_reason,
                            "reason": override_reason,
                        },
                        request.user,
                    )
                    count += 1
                except (BadRequest, Forbidden) as exc:
                    skipped_errors.append((s.name, str(exc)))

            if count:
                from apps.audit.services import log as audit_log

                audit_log(
                    action="school.bulk_assign_project",
                    subject_kind="Project",
                    subject_id=project.id,
                    actor_id=request.user.user_id,
                    actor_role=getattr(request.user, "active_role", None),
                    reason=override_reason or None,
                    payload={
                        "projectName": project.name,
                        "assigned": count,
                        "skipped": len(skipped_errors),
                        "duplicates": duplicates,
                    },
                )

            if duplicates > 0:
                messages.warning(
                    request,
                    f"Skipped {duplicates} school(s) already assigned to this project.",
                )
            if skipped_errors:
                shown = "; ".join(
                    f"{name}: {reason}" for name, reason in skipped_errors[:3]
                )
                more = (
                    f" and {len(skipped_errors) - 3} more"
                    if len(skipped_errors) > 3
                    else ""
                )
                messages.error(
                    request,
                    f"Skipped {len(skipped_errors)} school(s): {shown}{more}.",
                )
            if count > 0:
                messages.success(
                    request,
                    f"Successfully assigned {count} school(s) to project '{project.name}'.",
                )
            elif not skipped_errors:
                messages.error(request, "No new project assignments were made.")
        else:
            messages.error(request, "Failed to perform assignment: missing fields.")
    return redirect("/schools")


@require_page_permission("school_directory")
def bulk_match_staff_view(request):
    if request.method == "POST":
        school_ids = request.POST.get("school_ids", "").split(",")
        staff_id = request.POST.get("staff_id", "").strip()
        if school_ids and staff_id:
            staff = get_object_or_404(
                StaffProfile, id=staff_id, deleted_at__isnull=True
            )
            # Scope-constrained, like every single-school path in this module and
            # like bulk_assign_cluster_view. require_page_permission only answers
            # "may this role open the directory" — it says nothing about *which*
            # schools, so an unscoped queryset here accepted any id the caller
            # cared to post. Six roles reach this view, including CCEO, and
            # account ownership is the root of the whole scoping chain: it feeds
            # StaffSchoolAssignment, which feeds planning, targets and budgets.
            scope = resolve_user_scope(request.user)
            schools = school_queryset(scope).filter(
                id__in=school_ids, deleted_at__isnull=True
            )
            for s in schools:
                s.account_owner_id = staff.id
                s.account_owner_name_raw = staff.user.name
                s.account_owner_status = "active"
                s.save()
                StaffSchoolAssignment.objects.get_or_create(school_id=s.id, staff=staff)
            messages.success(
                request,
                f"Successfully matched {schools.count()} schools to CCEO '{staff.user.name}'.",
            )
        else:
            messages.error(request, "Failed to match staff: missing fields.")
    return redirect("/schools")


@require_page_permission("school_directory")
def add_school_view(request):
    if request.method != "POST":
        return redirect("/schools")
    if not _may_upload_schools(request):
        return render_access_denied(
            request,
            "Only Impact Assessment and administrators may add schools.",
        )

    try:
        school = _create_manual_school(request)
    except BadRequest as exc:
        messages.error(request, str(exc))
        return redirect("/schools")

    messages.success(
        request,
        f"School '{school.name}' ({school.school_id}) was added to the directory.",
    )
    if request.POST.get("next") == "ssa" and _may_upload_ssa(request):
        query = urlencode({"school_id": school.school_id})
        return local_redirect(f"/ssa/manual/?{query}")
    return redirect("/schools")


@require_page_permission("school_directory")
def school_change_type_view(request, school_id):
    if request.method != "POST":
        return HttpResponseForbidden("Method not allowed")

    # Check permissions (CD, IA, Admin)
    user = request.user
    if user.active_role not in ("Admin", "CountryDirector", "ImpactAssessment"):
        return HttpResponseForbidden(
            "You do not have permission to change school type."
        )

    school = get_scoped_object_or_404(
        School, request.user, id=school_id, deleted_at__isnull=True
    )
    new_type = request.POST.get("school_type")

    from apps.schools.services import set_type

    try:
        set_type(user, school.school_id, new_type)
        type_label = dict(SchoolType.choices)[new_type]
        messages.success(
            request, f"Current partner type changed to {type_label} successfully."
        )
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")

    return HttpResponse("<script>window.location.reload();</script>")


@require_page_permission("school_upload")
def school_upload_preview_view(request, batch_id):
    from apps.schools.models import SchoolImportBatch
    from django.shortcuts import render, get_object_or_404, redirect
    from django.contrib import messages

    batch = get_object_or_404(SchoolImportBatch, id=batch_id)
    tab = request.GET.get("tab", "ready")
    rows = batch.rows.filter(status=tab)

    stats = {
        "ready": batch.rows.filter(status="ready").count(),
        "update": batch.rows.filter(status="update").count(),
        "review": batch.rows.filter(status="review").count(),
        "duplicate": batch.rows.filter(status="duplicate").count(),
        "blocked": batch.rows.filter(status="blocked").count(),
    }

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "confirm":
            from apps.schools.upload_service import import_school_batch

            import_school_batch(batch, request.user)
            messages.success(request, "Schools successfully imported into directory!")
            return local_redirect(f"/schools/uploads/{batch.id}/result")
        elif action == "cancel":
            from apps.schools.upload_service import cancel_school_import_batch

            cancel_school_import_batch(batch.id, request.user)
            messages.info(request, "Import cancelled.")
            return redirect("/schools/upload")

    context = {"batch": batch, "rows": rows, "tab": tab, "stats": stats}
    return render(request, "pages/schools/upload_preview.html", context)


@require_page_permission("school_upload")
def school_import_result_view(request, batch_id):
    from apps.schools.models import SchoolImportBatch
    from django.shortcuts import render, get_object_or_404

    batch = get_object_or_404(SchoolImportBatch, id=batch_id)

    stats = {
        "created": batch.rows.filter(status="ready").count(),
        "updated": batch.rows.filter(status="update").count(),
        "duplicate": batch.rows.filter(status="duplicate").count(),
        "blocked": batch.rows.filter(status="blocked").count(),
        "clean": batch.rows.filter(status="ready").count(),
    }

    context = {"batch": batch, "stats": stats}
    return render(request, "pages/schools/import_result.html", context)


@require_page_permission("school_directory")
def school_edit_drawer_view(request, school_id):
    school = get_scoped_object_or_404(
        School.objects.select_related("district", "sub_county", "parish"),
        request.user,
        id=school_id,
        deleted_at__isnull=True,
    )
    selected_district_id = (
        (request.POST.get("district_id") or "").strip()
        if request.method == "POST"
        else school.district_id
    )
    districts = District.objects.select_related("region").order_by("name")
    clusters = (
        Cluster.objects.filter(
            deleted_at__isnull=True,
            status="active",
            district_id=selected_district_id,
        )
        .select_related("district")
        .order_by("name")
    )
    staff = _school_owner_queryset()
    sub_counties = SubCounty.objects.filter(district_id=selected_district_id).order_by(
        "name"
    )
    parishes = (
        Parish.objects.filter(sub_county__district_id=selected_district_id)
        .select_related("sub_county")
        .order_by("sub_county__name", "name")
    )

    def drawer_context(validation_error=None):
        return {
            "school": school,
            "districts": districts,
            "clusters": clusters,
            "staff": staff,
            "school_types": SchoolType.choices,
            "sub_counties": sub_counties,
            "parishes": parishes,
            "validation_error": validation_error,
        }

    def optional_float(field, label, low, high):
        raw = (request.POST.get(field) or "").strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise BadRequest(f"{label} must be a valid number.") from exc
        import math

        if not math.isfinite(value) or not low <= value <= high:
            raise BadRequest(f"{label} must be between {low} and {high}.")
        return value

    if request.method == "POST":
        try:
            official_school_id = (request.POST.get("school_id") or "").strip()
            if not official_school_id:
                raise BadRequest("School ID is required.")
            if len(official_school_id) > School._meta.get_field("school_id").max_length:
                raise BadRequest("School ID must be 64 characters or fewer.")
            if (
                School.all_objects.filter(school_id=official_school_id)
                .exclude(pk=school.pk)
                .exists()
            ):
                raise BadRequest(
                    "That School ID is already in use. Enter a unique School ID."
                )

            name = (request.POST.get("name") or "").strip()
            if not name:
                raise BadRequest("School name is required.")

            school_type = (request.POST.get("school_type") or "").strip()
            if school_type not in {value for value, _label in SchoolType.choices}:
                raise BadRequest("Select a valid current partner type.")

            district_id = (request.POST.get("district_id") or "").strip()
            district = (
                District.objects.select_related("region").filter(id=district_id).first()
                if district_id
                else None
            )
            if district is None:
                raise BadRequest("District is required. Select a valid district.")

            enroll_raw = (request.POST.get("enrollment") or "").strip()
            enrollment = None
            if enroll_raw:
                try:
                    enrollment = int(enroll_raw)
                except (TypeError, ValueError) as exc:
                    raise BadRequest("Enrolment must be a whole number.") from exc
                if enrollment <= 0:
                    raise BadRequest("Enrolment must be greater than zero.")
                if enrollment > 2_147_483_647:
                    raise BadRequest("Enrolment is too large.")

            last_enrollment_date_raw = (
                request.POST.get("last_enrollment_date") or ""
            ).strip()
            last_enrollment_date = None
            if last_enrollment_date_raw:
                last_enrollment_date = parse_date(last_enrollment_date_raw)
                if last_enrollment_date is None:
                    raise BadRequest(
                        "Last enrolment date must use the YYYY-MM-DD format."
                    )

            latitude = optional_float("latitude", "Latitude", -90, 90)
            longitude = optional_float("longitude", "Longitude", -180, 180)
            if (latitude is None) != (longitude is None):
                raise BadRequest(
                    "Enter both latitude and longitude, or leave both blank."
                )

            sub_county_id = (request.POST.get("sub_county_id") or "").strip()
            sub_county = None
            if sub_county_id:
                sub_county = SubCounty.objects.filter(
                    id=sub_county_id,
                    district_id=district.id,
                ).first()
                if sub_county is None:
                    raise BadRequest("Select a sub-county within the district.")

            parish_id = (request.POST.get("parish_id") or "").strip()
            parish = None
            if parish_id:
                if sub_county is None:
                    raise BadRequest("Select a sub-county before selecting a parish.")
                parish = Parish.objects.filter(
                    id=parish_id,
                    sub_county_id=sub_county.id,
                ).first()
                if parish is None:
                    raise BadRequest("Select a parish within the selected sub-county.")

            cluster_id = (request.POST.get("cluster_id") or "").strip()
            new_cluster = None
            if cluster_id:
                new_cluster = Cluster.objects.filter(
                    id=cluster_id,
                    district_id=district.id,
                    deleted_at__isnull=True,
                    status="active",
                ).first()
                if new_cluster is None:
                    raise BadRequest(
                        "Select an active cluster within the school's district."
                    )

            owner_id = (request.POST.get("account_owner_id") or "").strip()
            staff_owner = (
                _school_owner_queryset().filter(id=owner_id).first()
                if owner_id
                else None
            )
            if staff_owner is None:
                raise BadRequest(
                    "Staff Name is required. Select an active CCEO or Program Lead."
                )
        except BadRequest as exc:
            return render(
                request,
                "partials/schools/edit_drawer.html",
                drawer_context(str(exc.detail)),
            )

        previous = {
            "school_id": school.school_id,
            "name": school.name,
            "school_type": school.school_type,
            "enrollment": school.enrollment,
            "last_enrollment_date": school.last_enrollment_date,
            "school_phone": school.school_phone,
            "primary_contact_name": school.primary_contact_name,
            "primary_contact_phone": school.primary_contact_phone,
            "director_name": school.director_name,
            "headteacher_name": school.headteacher_name,
            "shipping_address": school.shipping_address,
            "district_id": school.district_id,
            "region_id": school.region_id,
            "sub_county_id": school.sub_county_id,
            "parish_id": school.parish_id,
            "latitude": school.latitude,
            "longitude": school.longitude,
            "account_owner_id": school.account_owner_id,
        }

        school.school_id = official_school_id
        school.name = name
        school.school_type = school_type
        school.school_phone = (request.POST.get("school_phone") or "").strip() or None
        school.primary_contact_name = (
            request.POST.get("primary_contact_name") or ""
        ).strip() or None
        school.primary_contact_phone = (
            request.POST.get("primary_contact_phone") or ""
        ).strip() or None
        school.director_name = (request.POST.get("director_name") or "").strip() or None
        school.headteacher_name = (
            request.POST.get("headteacher_name") or ""
        ).strip() or None
        school.shipping_address = (
            request.POST.get("shipping_address") or ""
        ).strip() or None
        if last_enrollment_date is not None:
            school.last_enrollment_date = last_enrollment_date
        elif school.enrollment != enrollment and enrollment is not None:
            from django.utils import timezone

            school.last_enrollment_date = timezone.localdate()
        elif enrollment is None:
            school.last_enrollment_date = None
        school.enrollment = enrollment
        school.district = district
        school.region = district.region
        school.sub_county = sub_county
        school.parish = parish
        school.latitude = latitude
        school.longitude = longitude

        school.account_owner_id = owner_id
        school.account_owner_name_raw = staff_owner.user.name
        school.account_owner_status = "matched"

        with transaction.atomic():
            school.save()
            StaffSchoolAssignment.objects.filter(school_id=school.id).exclude(
                staff_id=owner_id
            ).delete()
            StaffSchoolAssignment.objects.get_or_create(
                school_id=school.id,
                staff_id=owner_id,
            )
            school = set_school_cluster_membership(
                school,
                new_cluster,
                request.user.user_id,
            )

        current = {
            "school_id": school.school_id,
            "name": school.name,
            "school_type": school.school_type,
            "enrollment": school.enrollment,
            "last_enrollment_date": school.last_enrollment_date,
            "school_phone": school.school_phone,
            "primary_contact_name": school.primary_contact_name,
            "primary_contact_phone": school.primary_contact_phone,
            "director_name": school.director_name,
            "headteacher_name": school.headteacher_name,
            "shipping_address": school.shipping_address,
            "district_id": school.district_id,
            "region_id": school.region_id,
            "sub_county_id": school.sub_county_id,
            "parish_id": school.parish_id,
            "latitude": school.latitude,
            "longitude": school.longitude,
            "account_owner_id": school.account_owner_id,
        }
        from apps.audit.services import log as audit_log

        audit_log(
            action="school.profile_updated",
            subject_kind="school",
            subject_id=school.id,
            actor_id=request.user.user_id,
            actor_role=request.user.active_role,
            payload={
                "changed_fields": [
                    field
                    for field, value in current.items()
                    if previous[field] != value
                ]
            },
        )

        messages.success(
            request,
            f"School '{school.name}' updated. Data quality was recalculated.",
        )
        if previous["school_id"] != school.school_id:
            # The profile route uses the official School ID. Send both an HTMX
            # redirect and a JavaScript fallback so changing that identifier
            # never reloads the now-stale profile URL.
            profile_url = reverse("frontend:school_detail", args=[school.school_id])
            response = HttpResponse(
                f"<script>window.location.assign({json.dumps(profile_url)});</script>"
            )
            response["HX-Redirect"] = profile_url
            return response
        return HttpResponse("<script>window.location.reload();</script>")

    return render(
        request,
        "partials/schools/edit_drawer.html",
        drawer_context(),
    )


@require_page_permission("school_directory")
def school_onboard_drawer_view(request):
    if not _may_upload_schools(request):
        return render_access_denied(
            request,
            "Only Impact Assessment and administrators may add schools.",
        )

    districts = District.objects.select_related("region").order_by("name")
    clusters = Cluster.objects.filter(deleted_at__isnull=True, status="active")
    staff = _school_owner_queryset()

    # Pre-populated cluster if any
    cluster_id = request.GET.get("cluster_id", "").strip()

    if request.method == "POST":
        try:
            school = _create_manual_school(request)
        except BadRequest as exc:
            return HttpResponse(
                (
                    '<div role="alert" class="p-3 bg-rose-50 text-rose-700 '
                    'rounded-surface text-[12px] font-bold">'
                    f"{escape(str(exc))}</div>"
                ),
                status=400,
            )

        messages.success(
            request,
            f"School '{school.name}' ({school.school_id}) was added to the directory.",
        )
        if request.POST.get("next") == "ssa" and _may_upload_ssa(request):
            query = urlencode({"school_id": school.school_id})
            response = HttpResponse(status=204)
            response["HX-Redirect"] = f"/ssa/manual/?{query}"
            return response

        return HttpResponse("<script>window.location.reload();</script>")

    context = {
        "districts": districts,
        "clusters": clusters,
        "staff": staff,
        "school_types": SchoolType.choices,
        "pre_cluster_id": cluster_id,
        "can_add_ssa": _may_upload_ssa(request),
    }
    return render(request, "partials/schools/onboard_drawer.html", context)
