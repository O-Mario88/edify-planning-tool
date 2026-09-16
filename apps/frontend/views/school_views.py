from apps.core.metrics import render_precomputed_metric_item
import json

from django.shortcuts import render, redirect, get_object_or_404
from apps.core.redirects import local_redirect
from apps.core.donut import build_gauge
from apps.core.permissions import (
    RolePermissionService,
    get_scoped_object_or_404,
    require_export_permission,
    require_page_permission,
)
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count, Sum
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.html import escape
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from django.urls import reverse
from urllib.parse import urlencode

from apps.activities.salesforce import normalize_salesforce_id
from apps.schools.models import School
from apps.geography.models import Region, District, Parish, SubCounty
from apps.core.enums import SchoolType, PlanningReadiness
from apps.schools.upload_service import upload_school_file
from apps.schools.services import create_one as create_school
from apps.schools.services import get_one as get_school_one
from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.accounts.staff_matching import OWNER_ROLES, on_staff
from apps.clusters.eligibility import (
    active_cluster_for_geography,
    active_cluster_for_school_geography,
    ineligibility_reason,
)
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
from apps.core.enums import ClusterRecordStatus
from apps.core.scoping import (
    assert_may_write_school,
    cluster_queryset,
    direct_portfolio_schools,
    resolve_user_scope,
    school_queryset,
)
from apps.frontend.view_models import SchoolDirectoryViewModel
from apps.core.fy import fy_options, get_operational_fy


def _may_upload_schools(request) -> bool:
    return has_permission(request.user, Permission.SCHOOL_UPLOAD.value)


def _may_create_single_school(request) -> bool:
    """Adding one school by hand is not the same as importing a spreadsheet.

    A field officer who meets an unlisted school at a cluster training has to
    be able to record it. The control on that is the Salesforce id the form
    demands, not the role — see Permission.SCHOOL_CREATE_SINGLE.
    """
    return has_permission(
        request.user, Permission.SCHOOL_CREATE_SINGLE.value
    ) or _may_upload_schools(request)


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

    # The Salesforce id is what makes this safe to open beyond IA: it proves
    # the school already exists in Salesforce, and because the column is
    # unique it is also the duplicate check — two people adding the same
    # school from the field collide here instead of minting two records.
    salesforce_account_id = normalize_salesforce_id(
        request.POST.get("salesforce_account_id", "")
    )
    if not salesforce_account_id:
        raise BadRequest(
            "Enter the school's Salesforce ID. Add the school in Salesforce "
            "first, then record it here with that ID."
        )
    existing = School.objects.filter(
        salesforce_account_id=salesforce_account_id, deleted_at__isnull=True
    ).first()
    if existing is not None:
        raise BadRequest(
            f"That Salesforce ID already belongs to {existing.name} "
            f"({existing.school_id}). Use that school rather than adding it twice."
        )

    with transaction.atomic():
        school = create_school(
            {
                "schoolId": request.POST.get("school_id", ""),
                "name": request.POST.get("name", ""),
                "salesforceAccountId": salesforce_account_id,
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
            # Narrowed by the school's own district, because a cluster belongs
            # to one and `set_school_cluster_membership` refuses the mismatch.
            # Reaching it produced "A school can only be assigned within its
            # own district" — accurate, but raised from the membership service
            # about a choice this form had offered, so it read as the save
            # breaking rather than as the picker being wrong.
            from apps.clusters.catchment import clusters_serving_district_q

            cluster = Cluster.objects.filter(
                clusters_serving_district_q(school.district_id),
                id=cluster_id,
                deleted_at__isnull=True,
                status="active",
            ).first()
            if cluster is None:
                raise BadRequest(
                    "Select an active cluster that serves the school's district: "
                    "one in the district, or one approved to serve it as a "
                    "neighbouring district. The list changes with the district."
                )
            set_school_cluster_membership(
                school,
                cluster,
                request.user.user_id,
                reason="Chosen when the school was added.",
                actor_role=getattr(request.user, "active_role", "") or "",
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
@require_export_permission
def school_directory_view(request):
    user = request.user
    scope = resolve_user_scope(user)

    # Directly-assigned schools only. A supervising Program Lead's `school_ids`
    # unions in their CCEOs' schools, which put 1030 schools this PL does not
    # own into their directory alongside their own 1141 — with the same edit,
    # cluster, project and staff-match controls on every one of them.
    # Supervision is not ownership.
    base_qs = school_queryset(scope, direct_only=True).filter(deleted_at__isnull=True)

    # Input parameters
    q = request.GET.get("q", "").strip()
    # The operational year unless a year the platform offers is chosen; the
    # literal "2026" default froze the directory's SSA progress on one year
    # (Programme Lead alignment, 2026-09-13).
    requested_fy = request.GET.get("fy", "").strip()
    fy = requested_fy if requested_fy in fy_options() else get_operational_fy()
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

    # One conditional aggregate describes the population behind the tabs and
    # KPI strip. These used to be fourteen near-identical COUNT round trips;
    # at country scale the SQL itself was cheap but their serial network waits
    # consumed most of the directory's service time under concurrency.
    summary = filtered_qs.aggregate(
        all=Count("id", distinct=True),
        unclustered=Count("id", filter=Q(cluster_status="unclustered"), distinct=True),
        clustered=Count("id", filter=Q(cluster_status="clustered"), distinct=True),
        not_assigned=Count(
            "id", filter=Q(project_assignments__isnull=True), distinct=True
        ),
        assigned=Count(
            "id", filter=Q(project_assignments__isnull=False), distinct=True
        ),
        client=Count("id", filter=Q(school_type="client"), distinct=True),
        core=Count("id", filter=Q(school_type="core"), distinct=True),
        no_ssa=Count("id", filter=Q(current_fy_ssa_status="not_done"), distinct=True),
        staff_setup=Count(
            "id",
            filter=(
                Q(account_owner_id__isnull=True)
                | Q(account_owner_id="")
                | Q(account_owner_status="pending")
            ),
            distinct=True,
        ),
        planning_ready=Count(
            "id",
            filter=Q(planning_readiness__in=PlanningReadiness.planning_ready_values()),
            distinct=True,
        ),
        duplicates=Count("id", filter=Q(duplicate_status="duplicate"), distinct=True),
        districts=Count(
            "district_id", filter=Q(district_id__isnull=False), distinct=True
        ),
    )
    all_count = summary["all"]
    unclustered_count = summary["unclustered"]
    clustered_count = summary["clustered"]
    not_assigned_count = summary["not_assigned"]
    assigned_count = summary["assigned"]

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
            # No cap. This used to be [:5000], which silently truncated: a
            # country-scope export of 16,274 schools returned 5,000 rows with
            # no warning anywhere, and a truncated file that looks complete is
            # worse than a refused one — it gets used as a reconciliation
            # source. Scoped roles never hit the limit, so it only ever
            # misinformed the people looking at the whole country.
            #
            # iterator() rather than a plain queryset so the rows stream from a
            # server-side cursor instead of materialising every School with its
            # three joined rows before the first byte is written. export_rows is
            # already a generator and the xlsx writer is write-only, so the
            # whole path stays constant-memory.
            for school in schools_qs.select_related(
                "district", "sub_county", "region"
            ).iterator(chunk_size=1000)
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
    total_schools = summary["all"]
    client_schools = summary["client"]
    core_schools = summary["core"]
    unclustered_schools = summary["unclustered"]
    no_ssa_schools = summary["no_ssa"]
    staff_setup_schools = summary["staff_setup"]
    planning_ready_schools = summary["planning_ready"]
    duplicate_schools = summary["duplicates"]
    district_count = summary["districts"]

    needs_setup = staff_setup_schools
    needs_ssa = no_ssa_schools
    ready_for_planning = planning_ready_schools

    # Construct unified KPI strip items
    kpi_strip_items = [
        render_precomputed_metric_item(
            "frontend_views_school_views_total_schools",
            str(total_schools),
            raw_value=total_schools,
            helper=f"Across {district_count} district{'' if district_count == 1 else 's'}",
            icon="school",
            variant="primary",
        ),
        render_precomputed_metric_item(
            "frontend_views_school_views_client_schools",
            str(client_schools),
            raw_value=client_schools,
            helper=f"{round(client_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            icon="school",
            variant="success",
        ),
        render_precomputed_metric_item(
            "frontend_views_school_views_core_schools",
            str(core_schools),
            raw_value=core_schools,
            helper=f"{round(core_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            icon="school",
            variant="purple",
        ),
        render_precomputed_metric_item(
            "frontend_views_school_views_unclustered",
            str(unclustered_schools),
            raw_value=unclustered_schools,
            helper=f"{round(unclustered_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            icon="school",
            variant="warning",
        ),
        render_precomputed_metric_item(
            "frontend_views_school_views_no_ssa",
            str(no_ssa_schools),
            raw_value=no_ssa_schools,
            helper=f"{round(no_ssa_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            icon="warning",
            variant="danger",
        ),
        render_precomputed_metric_item(
            "frontend_views_school_views_staff_required",
            str(staff_setup_schools),
            raw_value=staff_setup_schools,
            helper=f"{round(staff_setup_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            icon="users",
            variant="warning",
        ),
        render_precomputed_metric_item(
            "frontend_views_school_views_planning_ready",
            str(planning_ready_schools),
            raw_value=planning_ready_schools,
            helper=f"{round(planning_ready_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            icon="check",
            variant="success",
        ),
        render_precomputed_metric_item(
            "frontend_views_school_views_duplicates",
            str(duplicate_schools),
            raw_value=duplicate_schools,
            helper=f"{round(duplicate_schools * 100 / total_schools) if total_schools > 0 else 0}% of total",
            icon="warning",
            variant="neutral",
        ),
    ]

    # Paginate list
    schools_qs = schools_qs.select_related(
        "district", "sub_county", "parish"
    ).prefetch_related("project_assignments__project")
    schools_qs = schools_qs.annotate(
        _project_count=Count("project_assignments", distinct=True)
    )
    # Grouped by the people responsible — Program Lead, then the CCEO who
    # holds the school — for a country role who reads the whole portfolio
    # (owner, 2026-09-11 for Planning, 2026-09-12 for this directory: "IA
    # should have access to schools and planning and my plan but grouped by
    # PL"). Sorted by name for someone whose portfolio IS their list. An
    # explicit ?group= is the reader's choice either way.
    _group = request.GET.get("group")
    if _group is None:
        _group = "owner" if (scope.country_scope or scope.region_scope) else "name"
    group_by_owner = _group == "owner"
    owner_group_directory: dict = {}
    owner_group_counts: dict = {}
    if group_by_owner:
        from apps.planning.owner_groups import owner_order

        schools_qs, owner_group_directory = owner_order(schools_qs)
        owner_group_counts = {
            (row["account_owner_id"] or ""): row["n"]
            for row in schools_qs.values("account_owner_id").annotate(n=Count("id"))
        }
    paginator = Paginator(schools_qs, per_page)
    page_obj = paginator.get_page(page_number)
    from apps.core.pagination import elided_page_numbers

    pages_list = elided_page_numbers(page_obj)

    clusters_dict = {
        c.id: c.name for c in Cluster.objects.filter(deleted_at__isnull=True)
    }
    active_projects_exist = Project.objects.filter(deleted_at__isnull=True).exists()

    # Batch-compute SSA/visit/training progress for this page of schools in
    # a handful of queries instead of ~5-7 per-row queries inside from_school
    # (was a confirmed N+1 on the school directory list).
    page_school_ids = [s.id for s in page_obj]
    progress_by_school = SchoolDirectoryViewModel.bulk_progress(page_school_ids, fy=fy)
    # Derived from the canonical activities, never a stored flag (owner,
    # 2026-09-15): Scheduled for Visit, and whether a cluster training or
    # meeting is planned for the school this year.
    from apps.schools.school_status import cluster_training_coverage, visit_statuses

    visit_by_school = visit_statuses(page_school_ids, fy=fy)
    training_by_school = cluster_training_coverage(list(page_obj), fy=fy)
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

    view_models = []
    for s in page_obj:
        row = SchoolDirectoryViewModel.from_school(
            s,
            user,
            clusters_dict,
            active_projects_exist,
            progress=progress_by_school.get(s.id),
            staff_names_by_owner_id=staff_names_by_owner_id,
            visit_status=visit_by_school.get(s.id),
            training_coverage=training_by_school.get(s.id),
        )
        if group_by_owner:
            # Group headers, drawn where the owner changes.
            from apps.planning.owner_groups import group_label as _group_label

            key = s.account_owner_id or ""
            row["group_key"] = key
            row["group_label"] = _group_label(owner_group_directory.get(key))
            row["group_count"] = owner_group_counts.get(key, 0)
        view_models.append(row)

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
    from apps.core.scoping import cluster_owner_ids

    if scope.country_scope or scope.can_view_summary_only:
        clusters = Cluster.objects.filter(
            deleted_at__isnull=True, status=ClusterRecordStatus.ACTIVE
        ).order_by("name")
    else:
        owner_ids = cluster_owner_ids(scope, direct_only=True)
        clusters = (
            Cluster.objects.filter(
                deleted_at__isnull=True,
                status=ClusterRecordStatus.ACTIVE,
            )
            .filter(
                Q(responsible_staff_id__in=owner_ids) | Q(id__in=scope.own_cluster_ids)
            )
            .order_by("name")
        )
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

    # An empty table says why it is empty (controls audit F-03, 2026-09-14):
    # a filter with no matches used to tell the reader no schools had ever
    # been uploaded. Only asked when there is nothing to show.
    directory_empty_state = ""
    if not page_obj.object_list:
        if not School.objects.filter(deleted_at__isnull=True).exists():
            directory_empty_state = "registry_empty"
        elif not base_qs.exists():
            directory_empty_state = "scope_empty"
        else:
            directory_empty_state = "no_matches"

    context = {
        "directory_empty_state": directory_empty_state,
        "page_obj": page_obj,
        "pages_list": pages_list,
        "per_page": per_page,
        "view_models": view_models,
        "group_by_owner": group_by_owner,
        "selected_group": "owner" if group_by_owner else "name",
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
        "fy_options": fy_options(),
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
        # The upload doors lead to the Upload Center, which a Programme Lead
        # cannot open (Programme Lead walk, 2026-09-14).
        "can_open_upload_center": RolePermissionService.can_view_page(
            request.user, "uploads"
        ),
        "can_add_ssa": _may_upload_ssa(request),
        # The Regional Programme Lead reads the directory and works none of it,
        # so the row selection, bulk bar and per-row assign buttons are not
        # drawn for them: a control that can only answer "not you" is noise.
        "directory_read_only": scope.region_scope,
    }

    if request.headers.get("HX-Request") == "true":
        if request.headers.get("X-Edify-Update-Scope") == "table":
            return render(request, "partials/schools/table.html", context)
        return render(request, "partials/schools/htmx_response.html", context)

    return render(request, "pages/schools/index.html", context)


@require_page_permission("school_directory")
def school_sub_county_options_view(request):
    """Return native select options for a district-dependent school form.

    With ``with_clusters=1`` the response also carries the cluster options for
    the same district, swapped out-of-band. A cluster belongs to one district,
    so a cluster picker that does not follow the district field offers choices
    the assignment service must then refuse — "A school can only be assigned
    within its own district", raised after the form was filled in and
    submitted. Both selects depend on the same answer, so both are refreshed
    by the same request.
    """
    district_id = request.GET.get("district_id", "").strip()
    sub_counties = (
        SubCounty.objects.filter(district_id=district_id).order_by("name")
        if district_id
        else SubCounty.objects.none()
    )
    context = {"sub_counties": sub_counties}

    if request.GET.get("with_clusters"):
        clusters = Cluster.objects.none()
        if district_id:
            base = Cluster.objects.filter(
                district_id=district_id,
                deleted_at__isnull=True,
                status=ClusterRecordStatus.ACTIVE,
            )
            # Scoped as well as filtered: the picker listed every active
            # cluster in the country to anyone who could add a school.
            writable = cluster_queryset(resolve_user_scope(request.user), base=base)
            clusters = (writable if writable is not None else base).order_by("name")
        context["clusters"] = clusters
        context["include_cluster_options"] = True

    return render(
        request,
        "partials/schools/sub_county_options.html",
        context,
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
    """Add a school to one of its owner's clusters, or change its cluster.

    Owner, 2026-09-15 (twice):

    * The drawer lists the clusters that belong to the school's owner — never
      another staff member's, never an unowned one.
    * A cluster may be chosen when it serves the school's district: its own
      district, or a neighbouring district the Country Director or Admin
      approved for it (apps.clusters.catchment). Clusters that do not serve
      the district are listed, marked, and cannot be chosen.
    * A school already in a cluster is offered Change Cluster, which needs a
      reason and a confirmation. The canonical service closes the old
      membership in the history, opens the new one and keeps one active
      cluster — the school's own geography never changes.
    """
    from apps.clusters.catchment import (
        CatchmentRelationship,
        NOT_IN_CATCHMENT,
        service_districts_by_cluster,
    )
    from apps.clusters.eligibility import owner_clusters_for_school
    from apps.core.permissions import has_permission
    from apps.core.scoping import OVERSIGHT_ONLY_MESSAGE

    school = get_scoped_object_or_404(
        School.objects.select_related("district", "sub_county", "region"),
        request.user,
        id=school_id,
        deleted_at__isnull=True,
    )
    user = request.user

    if not has_permission(user, "cluster.assign"):
        return render(
            request,
            "partials/schools/drawer_error.html",
            {"error": "You do not have permission to assign clusters."},
        )
    # Reading a school is not operating on it. The drawer used to open for a
    # supervisor and then fail on save with "outside your scope"; say so first.
    writable = direct_portfolio_schools(resolve_user_scope(user))
    if writable is None or not writable.filter(id=school.id).exists():
        return render(
            request,
            "partials/schools/drawer_error.html",
            {"error": OVERSIGHT_ONLY_MESSAGE},
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

    current_cluster = (
        Cluster.objects.select_related("district")
        .filter(id=school.cluster_id, deleted_at__isnull=True)
        .first()
        if school.cluster_id
        else None
    )
    is_change = current_cluster is not None or school.cluster_status == "clustered"
    responsible_staff = get_responsible_staff(school)
    owner_clusters = list(
        owner_clusters_for_school(school)
        .select_related("district", "sub_county")
        .annotate(schools_count=Count("assignments", distinct=True))
        .order_by("name")
    )
    served = service_districts_by_cluster(
        [c.id for c in owner_clusters]
        + ([current_cluster.id] if current_cluster else [])
    )

    def relationship_for(cluster):
        if cluster is None or not school.district_id:
            return None
        if cluster.district_id == school.district_id:
            return CatchmentRelationship.PRIMARY
        for row in served.get(cluster.id, []):
            if row.district_id == school.district_id:
                return row.relationship_type
        return None

    for cluster in owner_clusters:
        cluster.catchment_relationship = relationship_for(cluster)
        cluster.serves_school = cluster.catchment_relationship is not None
        cluster.is_cross_district = (
            cluster.catchment_relationship == CatchmentRelationship.NEIGHBOURING
        )
        cluster.is_current = bool(current_cluster and cluster.id == current_cluster.id)
    # Served first, the school's own district first among those.
    owner_clusters.sort(
        key=lambda c: (
            not c.serves_school,
            c.is_cross_district,
            c.is_current,
            c.name.lower(),
        )
    )
    selectable = [c for c in owner_clusters if c.serves_school and not c.is_current]
    selectable_ids = {c.id for c in selectable}
    covering = (
        active_cluster_for_school_geography(school) if school.sub_county_id else None
    )
    preselected_id = (
        covering.id
        if covering and covering.id in selectable_ids
        else (selectable[0].id if len(selectable) == 1 else "")
    )
    current_relationship = relationship_for(current_cluster)

    def drawer_context(validation_error=None, posted=None):
        posted = posted or {}
        return {
            "school": school,
            "responsible_staff": responsible_staff,
            "owner_clusters": owner_clusters,
            "has_selectable_cluster": bool(selectable),
            "preselected_cluster_id": posted.get("cluster_id") or preselected_id,
            "posted_reason": posted.get("reason", ""),
            "validation_error": validation_error,
            "ineligibility_reason": ineligibility_reason(school),
            "current_cluster": current_cluster,
            "current_relationship": current_relationship,
            "current_is_cross_district": current_relationship
            == CatchmentRelationship.NEIGHBOURING,
            "is_change": is_change,
            "cross_district_ids": json.dumps(
                [c.id for c in owner_clusters if c.is_cross_district]
            ),
            "drawer_type": "center",
            "drawer_size": "md",
        }

    if not school.school_id or not school.name or not school.district_id:
        return render(
            request,
            "partials/schools/add_to_cluster_drawer.html",
            drawer_context(
                "This school needs a School ID, Name, and District before it can "
                "be clustered."
            ),
        )

    if request.method == "POST":
        action_type = request.POST.get("cluster_action_type", "existing")
        reason = (request.POST.get("reason") or "").strip()
        posted = {
            "cluster_id": request.POST.get("existing_cluster_id", "").strip(),
            "reason": reason,
        }

        if is_change:
            if request.POST.get("confirm_change") != "yes":
                return render(
                    request,
                    "partials/schools/add_to_cluster_drawer.html",
                    drawer_context(
                        f"Confirm that {school.name} should leave "
                        f"{current_cluster.name if current_cluster else 'its cluster'}.",
                        posted,
                    ),
                )
            if len(reason) < 5:
                return render(
                    request,
                    "partials/schools/add_to_cluster_drawer.html",
                    drawer_context("Give the reason for changing the cluster.", posted),
                )

        if action_type == "existing":
            cluster_id = posted["cluster_id"]
            # The same rule on submit: the id arrives in a POST body, and a
            # crafted one must not land this school in another owner's cluster
            # or a cluster that does not serve its district. The service checks
            # owner and catchment again.
            cluster = next(
                (c for c in owner_clusters if c.id == cluster_id and c.serves_school),
                None,
            )
            if cluster is None:
                listed = next((c for c in owner_clusters if c.id == cluster_id), None)
                message = (
                    NOT_IN_CATCHMENT.format(
                        cluster=listed.name, district=school.district.name
                    )
                    if listed is not None
                    else "Select one of the clusters belonging to this school's owner."
                )
                return render(
                    request,
                    "partials/schools/add_to_cluster_drawer.html",
                    drawer_context(message, posted),
                )
            if cluster.is_current:
                return render(
                    request,
                    "partials/schools/add_to_cluster_drawer.html",
                    drawer_context(
                        f"{school.name} is already in {cluster.name}.", posted
                    ),
                )
            if cluster.is_cross_district and len(reason) < 5:
                return render(
                    request,
                    "partials/schools/add_to_cluster_drawer.html",
                    drawer_context(
                        f"{cluster.name} is in {cluster.district.name}. Give the reason "
                        "this school joins a cluster across the district border.",
                        posted,
                    ),
                )
        else:
            cluster_name = request.POST.get("new_cluster_name", "").strip()
            if not cluster_name:
                return render(
                    request,
                    "partials/schools/add_to_cluster_drawer.html",
                    drawer_context("Enter a cluster name to continue.", posted),
                )
            try:
                cluster_data = create_cluster_service(
                    {
                        "name": cluster_name,
                        "regionId": school.region_id,
                        "districtId": school.district_id,
                        "subCountyIds": (
                            [str(school.sub_county_id)] if school.sub_county_id else []
                        ),
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
                    drawer_context(str(e), posted),
                )
            cluster = get_object_or_404(
                Cluster, id=cluster_data["id"], deleted_at__isnull=True
            )

        # Audited, historied and notified inside set_school_cluster_membership()
        # (the canonical service assign_school_to_cluster delegates to). Its
        # refusals — a district outside the catchment, a cluster retired since
        # the drawer opened, scope — come back as the sentence, never a 500.
        try:
            assign_school_to_cluster(
                school.school_id,
                {"clusterId": cluster.id, "reason": reason},
                user,
            )
        except (BadRequest, Forbidden, NotFoundError) as exc:
            return render(
                request,
                "partials/schools/add_to_cluster_drawer.html",
                drawer_context(str(getattr(exc, "detail", exc)), posted),
            )

        verb = "moved to" if is_change else "added to"
        message = f"{school.name} {verb} {cluster.name}."
        if request.headers.get("HX-Request") != "true":
            # The full-page fallback: a plain form post lands back on the
            # directory with the outcome, not on a bare toast fragment.
            from django.contrib import messages as flash

            flash.success(request, message)
            return redirect("/schools")
        response = render(
            request,
            "partials/schools/toast_success.html",
            {"message": message},
        )
        response["HX-Trigger"] = (
            f"schools-updated, cluster-schools-updated-{cluster.id}"
            + (
                f", cluster-schools-updated-{current_cluster.id}"
                if current_cluster
                else ""
            )
        )
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
    # The SSA panel (IA review, owner, 2026-09-13). The headline is the newest
    # CONFIRMED assessment — a pending or returned upload used to stand as the
    # school's "Average SSA" — and change is read between confirmed
    # assessments by the one rule (apps.ssa.change_rules), once per pair of
    # readings rather than once per activity delivered around them.
    from apps.analytics.ia_workflow import school_progress

    ssa_progress = school_progress(school)
    latest_ssa = ssa_progress["latest"]
    activities = school.activities.filter(deleted_at__isnull=True).order_by(
        "-planned_date"
    )

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
    from apps.planning import partner_oversight_service

    # Partner-delivered work at this school. Read-only, and read from the same
    # service the Partner Oversight page uses, so the CCEO's school view and
    # the Program Lead's partner view cannot tell different stories about the
    # same handover.
    partner_support = partner_oversight_service.build_items_for_school(school.id)

    from apps.business_transformation.services import school_profile_context

    business_transformation = school_profile_context(request.user, school)

    # Visit feedback stays on the activity that produced it. School 360 reads
    # that same record and adds the existing follow-up/pair lineage so the
    # finding is never detached from the visit or training it describes.
    from apps.activities.models import Activity, SchoolVisitFeedback

    visit_feedback = list(
        SchoolVisitFeedback.objects.filter(
            activity__school=school, activity__deleted_at__isnull=True
        )
        .select_related("activity", "activity__follow_up_of_activity")
        .order_by("-created_at")[:20]
    )
    paired_trainings = {
        training.paired_school_visit_id: training
        for training in Activity.objects.filter(
            paired_school_visit_id__in=[item.activity_id for item in visit_feedback],
            deleted_at__isnull=True,
        )
    }
    for feedback in visit_feedback:
        activity = feedback.activity
        paired_training = paired_trainings.get(activity.id)
        feedback.related_activity = paired_training or activity.follow_up_of_activity
        feedback.activity_date = (
            activity.actual_delivery_date
            or activity.planned_date
            or (activity.scheduled_date.date() if activity.scheduled_date else None)
        )

    # Current cluster and every membership before it (owner, 2026-09-15):
    # joins, changes and removals with who, why and when, and whether the
    # cluster serves the school across a district border.
    from apps.clusters.catchment import serving_match
    from apps.clusters.membership_history import membership_history

    current_cluster = (
        Cluster.objects.select_related("district")
        .filter(id=school.cluster_id, deleted_at__isnull=True)
        .first()
        if school.cluster_id
        else None
    )
    current_match = (
        serving_match(current_cluster, school.district_id) if current_cluster else None
    )

    from apps.schools.school_status import cluster_training_coverage, visit_statuses

    fy_now = get_operational_fy()
    visit_state = visit_statuses([school.id], fy=fy_now)[school.id]
    training_state = cluster_training_coverage([school], fy=fy_now)[school.id]

    context = {
        "school": school,
        "visit_status": visit_state,
        "training_coverage": training_state,
        "status_fy": fy_now,
        "current_cluster": current_cluster,
        "current_cluster_cross_district": bool(
            current_match and current_match.is_cross_district
        ),
        "current_cluster_outside_catchment": bool(current_cluster)
        and current_match is None,
        "cluster_history": membership_history(school.id),
        "partner_support": partner_support,
        "business_transformation": business_transformation,
        "latest_ssa": latest_ssa,
        "ssa_progress": ssa_progress,
        "activities": activities,
        "visit_feedback": visit_feedback,
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
            schools = school_queryset(scope, direct_only=True).filter(
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
            schools = school_queryset(scope, direct_only=True).filter(
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
            schools = school_queryset(scope, direct_only=True).filter(
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
    if not _may_create_single_school(request):
        return render_access_denied(
            request,
            "You do not have permission to add a school.",
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
        # `get_scoped_object_or_404` above is the READ gate — a Programme Lead
        # passes it for a supervised CCEO's school, which is correct and is what
        # oversight is for. It is not an ownership answer, and this branch
        # rewrites ownership: it sets account_owner_id and then deletes and
        # recreates StaffSchoolAssignment, the row resolve_user_scope reads to
        # build own_school_ids. Gating the write on the read helper let a
        # supervisor move a supervised school's planning, target and budget
        # scope onto themselves. The write asks the direct-portfolio question
        # every other school-row write asks.
        assert_may_write_school(request.user, school, action="edit")
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

            # Cluster membership is derived from the newly selected canonical
            # sub-county, never from a second manual field. This fixes the old
            # two-source race where School.save() found the right cluster and
            # the blank cluster dropdown immediately cleared it again.
            new_cluster = active_cluster_for_geography(
                district_id=district.id,
                sub_county_id=sub_county.id if sub_county else None,
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
    if not _may_create_single_school(request):
        return render_access_denied(
            request,
            "You do not have permission to add a school.",
        )

    districts = District.objects.select_related("region").order_by("name")
    from apps.core.scoping import cluster_owner_ids

    onboard_scope = resolve_user_scope(request.user)
    if onboard_scope.country_scope or onboard_scope.can_view_summary_only:
        clusters = Cluster.objects.filter(
            deleted_at__isnull=True, status=ClusterRecordStatus.ACTIVE
        ).order_by("name")
    else:
        owner_ids = cluster_owner_ids(onboard_scope, direct_only=True)
        clusters = (
            Cluster.objects.filter(
                deleted_at__isnull=True,
                status=ClusterRecordStatus.ACTIVE,
            )
            .filter(
                Q(responsible_staff_id__in=owner_ids)
                | Q(id__in=onboard_scope.own_cluster_ids)
            )
            .order_by("name")
        )
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


# ── School lifecycle: closing, and the archive ───────────────────────────────
@require_page_permission("school_profile")
def school_close_drawer(request, school_id: str):
    """What closing this school would do, before anybody confirms it.

    Server-computed from the same functions the service uses, so the numbers
    shown are the numbers that will move. Closing a school changes a country's
    active enrolment and somebody's target denominator — nobody should confirm
    that without having seen it.
    """
    from apps.core.exceptions import Forbidden, NotFoundError
    from apps.schools import lifecycle_service
    from apps.schools.lifecycle_models import ClosureReason, ClosureType

    try:
        preview = lifecycle_service.preview(school_id)
    except NotFoundError:
        return render(
            request, "partials/schools/close_drawer.html", {"preview": None}, status=404
        )

    # Asked here so the drawer can explain the refusal rather than letting
    # somebody fill the form and be rejected at submit.
    denial = ""
    try:
        from apps.schools.models import School

        school = School.objects.filter(
            lifecycle_service.models_Q_id_or_ref(school_id)
        ).first()
        lifecycle_service.assert_may_close(request.user, school)
    except Forbidden as exc:
        denial = str(exc)

    return render(
        request,
        "partials/schools/close_drawer.html",
        {
            "preview": preview,
            "denial": denial,
            "closure_types": ClosureType.choices,
            "reasons": ClosureReason.choices,
            "drawer_size": "md",
            "drawer_type": "center",
        },
    )


@require_page_permission("school_profile")
@require_POST
def school_close_action(request, school_id: str):
    """Close the school, or say why it cannot be closed."""
    from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
    from apps.schools import lifecycle_service

    try:
        closure = lifecycle_service.close_school(
            school_id,
            {
                "closure_type": request.POST.get("closure_type"),
                "reason_category": request.POST.get("reason_category"),
                "reason": request.POST.get("reason"),
                "effective_date": request.POST.get("effective_date"),
            },
            request.user,
        )
    except (BadRequest, ConflictError, Forbidden, NotFoundError) as exc:
        return _lifecycle_response(request, str(exc), ok=False)

    return _lifecycle_response(
        request,
        f"{closure.school.name} is closed. "
        f"{closure.activities_cancelled} future activity(s) cancelled.",
    )


@require_page_permission("school_profile")
@require_POST
def school_reopen_action(request, school_id: str):
    """Bring a school back, without resurrecting the work that was stopped."""
    from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
    from apps.schools import lifecycle_service

    try:
        lifecycle_service.reopen_school(
            school_id,
            {
                "reason": request.POST.get("reason"),
                "enrollment": request.POST.get("enrollment"),
            },
            request.user,
        )
    except (BadRequest, ConflictError, Forbidden, NotFoundError) as exc:
        return _lifecycle_response(request, str(exc), ok=False)

    return _lifecycle_response(request, "School reopened.")


def _lifecycle_response(request, message: str, *, ok: bool = True):
    """A confirmation for the HTMX swap, or a redirect for a plain post."""
    from urllib.parse import urlsplit

    from django.contrib import messages
    from django.http import HttpResponse
    from django.utils.html import escape

    from apps.core.redirects import local_redirect

    if request.headers.get("HX-Request") == "true":
        tone = "success" if ok else "danger"
        response = HttpResponse(
            f'<p class="pill pill-{tone}" role="status">{escape(message)}</p>'
        )
        if ok:
            # The directory, the KPI strip and the profile banner all change.
            # Reloading is cheaper to reason about than patching four fragments.
            response["HX-Refresh"] = "true"
        return response

    messages.success(request, message) if ok else messages.error(request, message)
    came_from = urlsplit(request.META.get("HTTP_REFERER") or "").path
    return local_redirect(came_from, fallback="/schools")


def _closed_archive_scope(user) -> Q:
    """The closures this reader may see, as a filter on SchoolClosure.

    The archive listed every closure in the deployment to anyone holding the
    page — a CCEO read another country's closed schools, their enrolment and
    who owned them (Programme Lead alignment, 2026-09-13). It now follows the
    reader's school scope, in the analytics form that keeps closed schools:

      • country roles → their country; Admin → the deployment;
      • everyone else → the schools assigned to them (and, for a Programme
        Lead, to their officers), plus any closure recorded against them or
        their officers as the school's owner — closing a school leaves its
        assignment in place, but an older closure may predate one.
    """
    from apps.core.scoping import owner_ids, scoped_school_queryset
    from apps.planning.oversight_service import _both_id_spaces

    scope = resolve_user_scope(user)
    schools = scoped_school_queryset(scope)
    if schools is None:  # pragma: no cover - schools app not ready
        return Q(pk__in=[])
    in_scope = Q(school_id__in=schools.values("id"))
    if scope.country_scope or scope.region_scope or scope.can_view_summary_only:
        return in_scope
    owners = _both_id_spaces(
        set(owner_ids(user)) | set(scope.supervised_staff_ids or [])
    )
    return in_scope | Q(owner_at_closure__in=owners) if owners else in_scope


@require_page_permission("closed_schools")
def closed_schools_view(request):
    """The archive. Closed schools stay reachable — just not operationally.

    Deliberately its own page rather than a filter on the directory. The
    requirement is that closed schools do not appear there, and a hidden
    filter default is a promise that breaks the first time somebody clears it.
    """
    from apps.schools import lifecycle_service
    from apps.schools.lifecycle_models import SchoolClosure

    closures = (
        SchoolClosure.objects.filter(
            _closed_archive_scope(request.user), reopened_at__isnull=True
        )
        .select_related("school", "school__district")
        .order_by("-effective_date")
    )
    query = (request.GET.get("q") or "").strip()
    if query:
        closures = closures.filter(school__name__icontains=query)

    # The KPIs aggregate in the database over every matching closure. Summing
    # the rendered page instead would report a number that shrinks as somebody
    # pages through the archive, and understate the enrolment lost the moment
    # there are more closures than fit on one screen.
    summary = closures.aggregate(
        closed=Count("id"),
        enrollment_removed=Sum("enrollment_at_closure"),
    )

    rows = [
        {
            "closure": c,
            "school": c.school,
            "district": getattr(c.school.district, "name", "") if c.school_id else "",
            "enrollment": c.enrollment_at_closure,
            "owner": c.owner_name_at_closure,
        }
        for c in closures[:500]
    ]

    # "Active" beside the archive means the same reader's schools, not the
    # deployment's.
    from apps.core.scoping import scoped_school_queryset

    totals = lifecycle_service.active_enrollment(
        scoped_school_queryset(resolve_user_scope(request.user))
    )
    return render(
        request,
        "pages/schools/closed.html",
        {
            "rows": rows,
            "q": query,
            "closed_count": summary["closed"] or 0,
            "active_count": totals["schools_active"],
            "enrollment_removed": summary["enrollment_removed"] or 0,
            # The one search is the top bar's. Binding it here keeps the
            # archive searchable without growing a second search box.
            "topbar_search": {
                "placeholder": "Search closed schools…",
                "value": query,
                "action": "/schools/closed",
            },
        },
    )
