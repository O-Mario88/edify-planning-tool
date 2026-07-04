from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import require_page_permission, get_scoped_object_or_404
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.contrib import messages
from django.http import HttpResponseForbidden

from apps.schools.models import School
from apps.geography.models import Region, District, SubCounty
from apps.core.enums import SchoolType, PlanningReadiness
from apps.schools.upload_service import upload_school_file
from apps.ssa.upload_service import upload_ssa_file
from apps.schools.services import get_one as get_school_one
from apps.analytics.services import school_impact
from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.clusters.models import Cluster, SchoolClusterAssignment
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.core.scoping import resolve_user_scope, school_queryset
from apps.frontend.view_models import SchoolDirectoryViewModel

def _get_school_intelligence_data(school):
    cluster_name = "Unassigned"
    if school.cluster_id:
        cluster = Cluster.objects.filter(id=school.cluster_id, deleted_at__isnull=True).first()
        if cluster:
            cluster_name = cluster.name
            
    project_assignments = school.project_assignments.all() if hasattr(school, "project_assignments") else ProjectSchoolAssignment.objects.filter(school=school)
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
            next_step_text = "Assign to project if needed, or continue planning through cluster."
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
    school = get_scoped_object_or_404(School, request.user, id=school_id, deleted_at__isnull=True)
    intel_data = _get_school_intelligence_data(school)
    can_toggle_core = request.user.active_role in ("Admin", "CountryDirector", "ImpactAssessment")
    return render(request, "partials/schools/directory_intelligence.html", {
        "intelligence": intel_data,
        "can_toggle_core": can_toggle_core
    })

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
    school_type = request.GET.get("school_type", "").strip()
    cluster_status = request.GET.get("cluster_status", "").strip()
    project_status = request.GET.get("project_status", "").strip()
    active_tab = request.GET.get("tab", "all").strip()
    page_number = request.GET.get("page", 1)

    # Apply dropdown filters
    filtered_qs = base_qs.order_by("name")
    if q:
        filtered_qs = filtered_qs.filter(Q(name__icontains=q) | Q(school_id__icontains=q))
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
            filtered_qs = filtered_qs.filter(project_assignments__isnull=False).distinct()
        elif project_status == "unassigned":
            filtered_qs = filtered_qs.exclude(project_assignments__isnull=False).distinct()

    # Compute Tab Counts on the filtered list (before active tab filtering)
    all_count = filtered_qs.count()
    unclustered_count = filtered_qs.filter(cluster_status="unclustered").count()
    clustered_count = filtered_qs.filter(cluster_status="clustered").count()
    not_assigned_count = filtered_qs.exclude(project_assignments__isnull=False).distinct().count()
    assigned_count = filtered_qs.filter(project_assignments__isnull=False).distinct().count()

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

    # Compute scoped base KPIs for the KPI Row
    total_schools = base_qs.count()
    client_schools = base_qs.filter(school_type="client").count()
    core_schools = base_qs.filter(school_type="core").count()
    unclustered_schools = base_qs.filter(cluster_status="unclustered").count()
    no_ssa_schools = base_qs.filter(current_fy_ssa_status="not_done").count()
    staff_setup_schools = base_qs.filter(Q(account_owner_id__isnull=True) | Q(account_owner_id="") | Q(account_owner_status="pending")).count()
    planning_ready_schools = base_qs.filter(planning_readiness="ready").count()
    duplicate_schools = base_qs.filter(duplicate_status="duplicate").count()

    needs_setup = staff_setup_schools
    needs_ssa = no_ssa_schools
    ready_for_planning = planning_ready_schools

    # Construct unified KPI strip items
    kpi_strip_items = [
        {
            "label": "Total Schools",
            "value": str(total_schools),
            "raw_value": total_schools,
            "helper": "Across 5 districts",
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
        }
    ]

    # Paginate list
    schools_qs = schools_qs.select_related("district", "sub_county", "parish").prefetch_related("project_assignments__project")
    schools_qs = schools_qs.annotate(_project_count=Count("project_assignments", distinct=True))
    paginator = Paginator(schools_qs, 15)
    page_obj = paginator.get_page(page_number)
    pages_list = list(page_obj.paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1))

    clusters_dict = {c.id: c.name for c in Cluster.objects.filter(deleted_at__isnull=True)}
    active_projects_exist = Project.objects.filter(deleted_at__isnull=True).exists()

    view_models = [SchoolDirectoryViewModel.from_school(s, user, clusters_dict, active_projects_exist) for s in page_obj]

    # Default Selected School Intelligence
    selected_school_data = None
    if page_obj.object_list:
        default_school = page_obj.object_list[0]
        selected_school_data = _get_school_intelligence_data(default_school)

    # Populating filter options
    regions = Region.objects.all().order_by("name")
    districts = District.objects.all().order_by("name")
    sub_counties = SubCounty.objects.all().order_by("name")
    staff_profiles = StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user").order_by("user__name")
    clusters = Cluster.objects.filter(deleted_at__isnull=True).order_by("name")
    projects = Project.objects.filter(deleted_at__isnull=True).order_by("name")

    context = {
        "page_obj": page_obj,
        "pages_list": pages_list,
        "view_models": view_models,
        "kpi_strip_items": kpi_strip_items,
        "regions": regions,
        "districts": districts,
        "sub_counties": sub_counties,
        "staff_profiles": staff_profiles,
        "clusters": clusters,
        "projects": projects,
        
        "school_types": SchoolType.choices,
        "readiness_choices": PlanningReadiness.choices,
        
        # Selected states
        "q": q,
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
        "can_toggle_core": user.active_role in ("Admin", "CountryDirector", "ImpactAssessment"),
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/schools/htmx_response.html", context)

    return render(request, "pages/schools/index.html", context)

@require_page_permission("school_directory")
def add_to_cluster_drawer_view(request, school_id):
    school = get_scoped_object_or_404(School, request.user, id=school_id, deleted_at__isnull=True)
    user = request.user
    
    from apps.core.permissions import has_permission
    if not has_permission(user, "cluster.assign"):
        return render(request, "partials/schools/drawer_error.html", {"error": "You do not have permission to assign clusters."})
        
    from apps.accounts.models import StaffProfile
    from apps.geography.models import District, SubCounty
    from apps.clusters.models import Cluster, ClusterSubCounty, SchoolClusterAssignment
    
    # Helper to fetch sub-counties scoped to the school's district with unclustered school counts & covering cluster claims
    def get_scoped_sub_counties(sch):
        if not sch.district_id:
            return SubCounty.objects.none()
        scs = list(SubCounty.objects.filter(district_id=sch.district_id).order_by("name"))
        for sc in scs:
            sc.unclustered_schools_count = School.objects.filter(
                sub_county=sc,
                cluster_status="unclustered",
                deleted_at__isnull=True
            ).count()
            
            # Find if this sub-county is already claimed by any active cluster
            claim = ClusterSubCounty.objects.filter(sub_county=sc, cluster__deleted_at__isnull=True).select_related("cluster").first()
            if claim:
                sc.covering_cluster_name = claim.cluster.name
                sc.covering_cluster_id = claim.cluster.id
            else:
                sc.covering_cluster_name = None
                sc.covering_cluster_id = None
        return scs

    # Helper to check if school's sub-county is already covered
    def get_existing_covering_cluster(sch):
        if not sch.sub_county_id:
            return None
        claim = ClusterSubCounty.objects.filter(sub_county_id=sch.sub_county_id, cluster__deleted_at__isnull=True).select_related("cluster").first()
        return claim.cluster if claim else None

    # 1. Enforce Minimum Data Needed for Clustering
    if not school.school_id or not school.name or not school.district_id or not school.sub_county_id:
        districts = District.objects.all().order_by("name")
        sub_counties = get_scoped_sub_counties(school)
        recommended_clusters = Cluster.objects.filter(
            district_id=school.district_id,
            sub_county_id=school.sub_county_id,
            deleted_at__isnull=True
        ).order_by("name")
        for rc in recommended_clusters:
            rc.schools_count = rc.assignments.count()
        all_clusters = Cluster.objects.filter(deleted_at__isnull=True).order_by("name")
        for ac in all_clusters:
            ac.schools_count = ac.assignments.count()
        staff_list = StaffProfile.objects.filter(user__is_active=True).select_related("user").order_by("user__name")
        return render(request, "partials/schools/add_to_cluster_drawer.html", {
            "school": school,
            "school_contact": school.primary_contact_name or "—",
            "recommended_clusters": recommended_clusters,
            "all_clusters": all_clusters,
            "districts": districts,
            "sub_counties": sub_counties,
            "staff_list": staff_list,
            "existing_covering_cluster": get_existing_covering_cluster(school),
            "validation_error": "This school does not have the minimum required data for clustering (School ID, School Name, District, and Sub-county location are required). Please click 'Fix Data' to resolve this first.",
            "drawer_type": "center",
            "drawer_size": "md",
        })

    if request.method == "POST":
        action_type = request.POST.get("cluster_action_type", "existing")
        cluster_id = None
        
        responsible_staff_id = request.POST.get("responsible_staff_id")
        notes = request.POST.get("notes", "").strip()

        # Check if the school's sub-county is already covered
        existing_covering_cluster = get_existing_covering_cluster(school)

        if action_type == "existing" or existing_covering_cluster:
            cluster_id = request.POST.get("existing_cluster_id")
            if existing_covering_cluster:
                # Force existing covering cluster ID
                cluster_id = existing_covering_cluster.id
                
            if not cluster_id:
                districts = District.objects.all().order_by("name")
                sub_counties = get_scoped_sub_counties(school)
                recommended_clusters = Cluster.objects.filter(
                    district_id=school.district_id,
                    sub_county_id=school.sub_county_id,
                    deleted_at__isnull=True
                ).order_by("name")
                for rc in recommended_clusters:
                    rc.schools_count = rc.assignments.count()
                all_clusters = Cluster.objects.filter(deleted_at__isnull=True).order_by("name")
                for ac in all_clusters:
                    ac.schools_count = ac.assignments.count()
                staff_list = StaffProfile.objects.filter(user__is_active=True).select_related("user").order_by("user__name")
                return render(request, "partials/schools/add_to_cluster_drawer.html", {
                    "school": school,
                    "school_contact": school.primary_contact_name or "—",
                    "recommended_clusters": recommended_clusters,
                    "all_clusters": all_clusters,
                    "districts": districts,
                    "sub_counties": sub_counties,
                    "staff_list": staff_list,
                    "existing_covering_cluster": existing_covering_cluster,
                    "validation_error": "Please select an existing cluster.",
                    "drawer_type": "center",
                    "drawer_size": "md",
                })
            cluster = get_object_or_404(Cluster, id=cluster_id, deleted_at__isnull=True)
            if responsible_staff_id:
                cluster.responsible_staff_id = responsible_staff_id
            if notes:
                cluster.override_reason = notes
            cluster.save()
        else:
            # Create new cluster
            cluster_name = request.POST.get("new_cluster_name", "").strip()
            district_id = request.POST.get("new_district_id")
            new_sub_county_ids = request.POST.getlist("new_sub_county_ids")
            
            # Enforce that the school's own sub-county is always included in the cluster coverage
            school_sub_county_id_str = str(school.sub_county_id)
            if school_sub_county_id_str not in new_sub_county_ids:
                new_sub_county_ids.append(school_sub_county_id_str)
                
            if not cluster_name or not district_id or not new_sub_county_ids:
                districts = District.objects.all().order_by("name")
                sub_counties = get_scoped_sub_counties(school)
                recommended_clusters = Cluster.objects.filter(
                    district_id=school.district_id,
                    sub_county_id=school.sub_county_id,
                    deleted_at__isnull=True
                ).order_by("name")
                for rc in recommended_clusters:
                    rc.schools_count = rc.assignments.count()
                all_clusters = Cluster.objects.filter(deleted_at__isnull=True).order_by("name")
                for ac in all_clusters:
                    ac.schools_count = ac.assignments.count()
                staff_list = StaffProfile.objects.filter(user__is_active=True).select_related("user").order_by("user__name")
                return render(request, "partials/schools/add_to_cluster_drawer.html", {
                    "school": school,
                    "school_contact": school.primary_contact_name or "—",
                    "recommended_clusters": recommended_clusters,
                    "all_clusters": all_clusters,
                    "districts": districts,
                    "sub_counties": sub_counties,
                    "staff_list": staff_list,
                    "existing_covering_cluster": existing_covering_cluster,
                    "validation_error": "Please fill in all fields for the new cluster.",
                    "drawer_type": "center",
                    "drawer_size": "md",
                })
                
            district = get_object_or_404(District, id=district_id)
            sub_county = get_object_or_404(SubCounty, id=school.sub_county_id)
            cluster = Cluster.objects.create(
                name=cluster_name,
                district=district,
                region=district.region,
                sub_county=sub_county,
                status="active",
                override_reason=notes,
                responsible_staff_id=responsible_staff_id
            )
            
            # Associate all checked sub-counties
            for sc_id in new_sub_county_ids:
                sc_obj = SubCounty.objects.filter(id=sc_id).first()
                if sc_obj:
                    ClusterSubCounty.objects.get_or_create(cluster=cluster, sub_county=sc_obj)
            cluster_id = cluster.id
            
        cluster = get_object_or_404(Cluster, id=cluster_id, deleted_at__isnull=True)
        school.cluster_id = cluster.id
        school.cluster_status = "clustered"
        school.recompute_quality_and_readiness()
        school.save()
        
        SchoolClusterAssignment.objects.get_or_create(
            school=school,
            cluster=cluster,
            defaults={"assigned_by": user.user_id}
        )
        
        from apps.audit.services import log as audit_log
        audit_log(
            action="school.assign_cluster",
            subject_kind="School",
            subject_id=school.id,
            actor_id=user.user_id,
            actor_role=user.active_role,
            success=True,
            payload={"cluster_id": cluster.id, "cluster_name": cluster.name}
        )
        
        response = render(request, "partials/schools/toast_success.html", {"message": "School added to cluster successfully."})
        response["HX-Trigger"] = "schools-updated"
        return response
        
    districts = District.objects.all().order_by("name")
    sub_counties = get_scoped_sub_counties(school)
    
    # Update recommended clusters query to search both primary sub-county and covers
    recommended_clusters = Cluster.objects.filter(
        district_id=school.district_id,
        deleted_at__isnull=True
    ).filter(
        Q(sub_county_id=school.sub_county_id) | Q(covered_sub_counties__sub_county_id=school.sub_county_id)
    ).distinct().order_by("name")
    
    for rc in recommended_clusters:
        rc.schools_count = rc.assignments.count()
        
    all_clusters = Cluster.objects.filter(deleted_at__isnull=True).order_by("name")
    for ac in all_clusters:
        ac.schools_count = ac.assignments.count()
        
    staff_list = StaffProfile.objects.filter(user__is_active=True).select_related("user").order_by("user__name")
    school_contact = school.primary_contact_name or "—"
    
    return render(request, "partials/schools/add_to_cluster_drawer.html", {
        "school": school,
        "school_contact": school_contact,
        "recommended_clusters": recommended_clusters,
        "all_clusters": all_clusters,
        "districts": districts,
        "sub_counties": sub_counties,
        "staff_list": staff_list,
        "existing_covering_cluster": get_existing_covering_cluster(school),
        "drawer_type": "center",
        "drawer_size": "md",
    })

@require_page_permission("school_directory")
def assign_to_project_drawer_view(request, school_id):
    school = get_scoped_object_or_404(School, request.user, id=school_id, deleted_at__isnull=True)
    user = request.user
    
    from apps.core.permissions import has_permission
    if not has_permission(user, "project.manage"):
        return render(request, "partials/schools/drawer_error.html", {"error": "You do not have permission to assign projects."})
        
    if request.method == "POST":
        project_id = request.POST.get("project_id")
        project_type = request.POST.get("project_type", "").strip()
        participation_type = request.POST.get("participation_type", "").strip()
        start_date_str = request.POST.get("start_date", "").strip()
        support_area = request.POST.get("support_area", "").strip()
        notes = request.POST.get("notes", "").strip()
        
        if not project_id:
            projects = Project.objects.filter(deleted_at__isnull=True).order_by("name")
            return render(request, "partials/schools/assign_to_project_drawer.html", {
                "school": school,
                "projects": projects,
                "validation_error": "Please select a project."
            })
            
        project = get_object_or_404(Project, id=project_id, deleted_at__isnull=True)
        
        already_assigned = ProjectSchoolAssignment.objects.filter(project=project, school=school).exists()
        if already_assigned:
            projects = Project.objects.filter(deleted_at__isnull=True).order_by("name")
            return render(request, "partials/schools/assign_to_project_drawer.html", {
                "school": school,
                "projects": projects,
                "validation_error": "School is already assigned to this project."
            })
            
        start_date = None
        if start_date_str:
            import datetime
            try:
                start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
            except ValueError:
                pass
                
        ProjectSchoolAssignment.objects.create(
            project=project,
            school=school,
            assigned_by=user.user_id,
            project_type=project_type,
            participation_type=participation_type,
            start_date=start_date,
            support_area=support_area,
            notes=notes
        )
        
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
                "participation_type": participation_type
            }
        )
        
        response = render(request, "partials/schools/toast_success.html", {"message": "School assigned to project successfully."})
        response["HX-Trigger"] = "schools-updated"
        return response
        
    projects = Project.objects.filter(deleted_at__isnull=True).order_by("name")
    school_contact = school.primary_contact_name or "—"
    
    return render(request, "partials/schools/assign_to_project_drawer.html", {
        "school": school,
        "school_contact": school_contact,
        "projects": projects
    })

@require_page_permission("school_upload")
def school_upload_view(request):
    if request.user.active_role not in ["Admin", "ImpactAssessment"]:
        messages.error(request, "Access restricted: Insufficient permissions for data upload.")
        return redirect("/dashboard")

    if request.method == "POST":
        schools_file = request.FILES.get("schools_file")
        ssa_file = request.FILES.get("ssa_file")
        
        if schools_file:
            update_existing = request.POST.get("update_existing") == "on"
            try:
                result = upload_school_file(schools_file, request.user, update_existing=update_existing)
                result["type"] = "schools"
                return render(request, "partials/upload_result.html", {"result": result})
            except Exception as e:
                return render(request, "partials/upload_result.html", {"error": str(e)})

        elif ssa_file:
            try:
                result = upload_ssa_file(ssa_file, request.user)
                result["type"] = "ssa"
                return render(request, "partials/upload_result.html", {"result": result})
            except Exception as e:
                return render(request, "partials/upload_result.html", {"error": str(e)})

        return render(request, "partials/upload_result.html", {"error": "No file uploaded."})

    return render(request, "pages/schools/upload.html")

@require_page_permission("school_profile")
def school_detail_view(request, school_id):
    school = get_school_one(school_id, request.user)
    school.assigned_staff = school.account_owner_name_raw or school.account_owner_id or "Unassigned"
    latest_ssa = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
    ssa_scores_list = []
    if latest_ssa:
        ssa_scores_list = list(latest_ssa.scores.all().order_by("-score"))

    historical_ssas = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa")[1:]
    activities = school.activities.filter(deleted_at__isnull=True).order_by("-planned_date")
    impact_data = school_impact(school_id, request.user)

    from apps.ssa.services import get_ssa_progress_by_fy
    from apps.schools.models import School
    ssa_progress_history = get_ssa_progress_by_fy(School.objects.filter(id=school.id))

    stroke_dashoffset = 175.9 * (100 - school.data_quality_score) / 100

    context = {
        "school": school,
        "latest_ssa": latest_ssa,
        "ssa_scores": ssa_scores_list,
        "historical_ssas": historical_ssas,
        "ssa_progress_history": ssa_progress_history,
        "activities": activities,
        "impact_data": impact_data,
        "stroke_dashoffset": stroke_dashoffset,
    }
    return render(request, "pages/schools/detail.html", context)

@require_page_permission("school_directory")
def bulk_assign_cluster_view(request):
    if request.method == "POST":
        school_ids = request.POST.get("school_ids", "").split(",")
        cluster_id = request.POST.get("cluster_id", "").strip()
        if school_ids and cluster_id:
            cluster = get_object_or_404(Cluster, id=cluster_id, deleted_at__isnull=True)
            schools = School.objects.filter(id__in=school_ids, deleted_at__isnull=True)
            already_clustered = schools.filter(cluster_status="clustered")
            if already_clustered.exists():
                skipped_names = ", ".join([s.name for s in already_clustered])
                messages.warning(request, f"Skipped already-clustered schools: {skipped_names}.")
                schools = schools.exclude(cluster_status="clustered")
            
            count = 0
            for s in schools:
                s.cluster_id = cluster.id
                s.cluster_status = "clustered"
                s.planning_readiness = "ready"
                s.save()
                SchoolClusterAssignment.objects.get_or_create(
                    school=s,
                    cluster=cluster,
                    defaults={"assigned_by": request.user.user_id}
                )
                count += 1
            if count > 0:
                messages.success(request, f"Successfully assigned {count} schools to cluster '{cluster.name}'.")
            else:
                messages.error(request, "No unclustered schools were selected.")
        else:
            messages.error(request, "Failed to perform assignment: missing fields.")
    return redirect("/schools")

@require_page_permission("school_directory")
def bulk_assign_project_view(request):
    if request.method == "POST":
        school_ids = request.POST.get("school_ids", "").split(",")
        project_id = request.POST.get("project_id", "").strip()
        if school_ids and project_id:
            project = get_object_or_404(Project, id=project_id, deleted_at__isnull=True)
            schools = School.objects.filter(id__in=school_ids, deleted_at__isnull=True)
            
            count = 0
            duplicates = 0
            for s in schools:
                already_assigned = ProjectSchoolAssignment.objects.filter(project=project, school=s).exists()
                if already_assigned:
                    duplicates += 1
                    continue
                    
                ProjectSchoolAssignment.objects.create(
                    project=project,
                    school=s,
                    assigned_by=request.user.user_id
                )
                count += 1
                
            if duplicates > 0:
                messages.warning(request, f"Skipped {duplicates} school(s) already assigned to this project.")
            if count > 0:
                messages.success(request, f"Successfully assigned {count} school(s) to project '{project.name}'.")
            else:
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
            staff = get_object_or_404(StaffProfile, id=staff_id, deleted_at__isnull=True)
            schools = School.objects.filter(id__in=school_ids, deleted_at__isnull=True)
            for s in schools:
                s.account_owner_id = staff.id
                s.account_owner_name_raw = staff.user.name
                s.account_owner_status = "active"
                s.save()
                StaffSchoolAssignment.objects.get_or_create(
                    school_id=s.id,
                    staff=staff
                )
            messages.success(request, f"Successfully matched {schools.count()} schools to CCEO '{staff.user.name}'.")
        else:
            messages.error(request, "Failed to match staff: missing fields.")
    return redirect("/schools")

@require_page_permission("school_directory")
def add_school_view(request):
    if request.method == "POST":
        school_id = request.POST.get("school_id", "").strip()
        name = request.POST.get("name", "").strip()
        district_id = request.POST.get("district_id", "").strip()
        school_type = request.POST.get("school_type", "client").strip()
        enrollment_str = request.POST.get("enrollment", "").strip()
        
        if school_id and name and district_id:
            district = get_object_or_404(District, id=district_id)
            enrollment = int(enrollment_str) if enrollment_str.isdigit() else 0
            
            school = School.objects.create(
                school_id=school_id,
                name=name,
                district=district,
                region=district.region,
                school_type=school_type,
                enrollment=enrollment,
                planning_readiness="blocked"
            )
            messages.success(request, f"Successfully created school '{school.name}' ({school.school_id}).")
        else:
            messages.error(request, "Failed to create school: missing required fields.")
            
    return redirect("/schools")

from django.http import HttpResponse

@require_page_permission("school_directory")
def school_change_type_view(request, school_id):
    if request.method != "POST":
        return HttpResponseForbidden("Method not allowed")
    
    # Check permissions (CD, IA, Admin)
    user = request.user
    if user.active_role not in ("Admin", "CountryDirector", "ImpactAssessment"):
        return HttpResponseForbidden("You do not have permission to change school type.")
        
    school = get_scoped_object_or_404(School, request.user, id=school_id, deleted_at__isnull=True)
    new_type = request.POST.get("school_type")
    
    from apps.schools.services import set_type
    try:
        set_type(user, school.id, new_type)
        messages.success(request, f"School type changed to {new_type.title()} successfully.")
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        
    return HttpResponse(f'<script>window.location.reload();</script>')


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
            return redirect(f"/schools/uploads/{batch.id}/result")
        elif action == "cancel":
            batch.status = "cancelled"
            batch.save()
            messages.info(request, "Import cancelled.")
            return redirect("/schools/upload")

    context = {
        "batch": batch,
        "rows": rows,
        "tab": tab,
        "stats": stats
    }
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
    
    context = {
        "batch": batch,
        "stats": stats
    }
    return render(request, "pages/schools/import_result.html", context)


@require_page_permission("school_directory")
def school_edit_drawer_view(request, school_id):
    from apps.schools.models import School
    from apps.clusters.models import Cluster
    from apps.accounts.models import StaffProfile
    from django.shortcuts import render
    from django.contrib import messages
    from django.http import HttpResponse
    
    school = get_scoped_object_or_404(School, request.user, id=school_id, deleted_at__isnull=True)
    clusters = Cluster.objects.filter(deleted_at__isnull=True, status="active")
    staff = StaffProfile.objects.filter(user__is_active=True).select_related("user")
    
    if request.method == "POST":
        school.name = request.POST.get("name", school.name).strip()
        school.school_phone = request.POST.get("school_phone", school.school_phone).strip()
        school.primary_contact_name = request.POST.get("primary_contact_name", school.primary_contact_name).strip()
        school.director_name = request.POST.get("director_name", school.director_name).strip()
        school.headteacher_name = request.POST.get("headteacher_name", school.headteacher_name).strip()
        school.shipping_address = request.POST.get("shipping_address", school.shipping_address).strip()
        
        enroll_raw = request.POST.get("enrollment")
        if enroll_raw:
            try:
                school.enrollment = int(enroll_raw)
            except ValueError:
                pass
                
        cluster_id = request.POST.get("cluster_id")
        if cluster_id:
            school.cluster_id = cluster_id
            school.cluster_status = "clustered"
        else:
            school.cluster_id = None
            school.cluster_status = "unclustered"
            
        owner_id = request.POST.get("account_owner_id")
        if owner_id:
            school.account_owner_id = owner_id
            staff_owner = StaffProfile.objects.filter(id=owner_id).first()
            if staff_owner:
                school.account_owner_name_raw = staff_owner.user.name
                school.account_owner_status = "matched"
                from apps.accounts.models import StaffSchoolAssignment
                StaffSchoolAssignment.objects.get_or_create(school_id=school.id, staff_id=owner_id)
        else:
            school.account_owner_id = None
            school.account_owner_status = "pending"
            
        school.save()
        messages.success(request, f"School '{school.name}' successfully updated and quality score recalculated!")
        return HttpResponse('<script>window.location.reload();</script>')
        
    context = {
        "school": school,
        "clusters": clusters,
        "staff": staff
    }
    return render(request, "partials/schools/edit_drawer.html", context)


@require_page_permission("school_directory")
def school_onboard_drawer_view(request):
    from apps.geography.models import District
    from apps.clusters.models import Cluster
    from django.shortcuts import render, get_object_or_404
    from django.http import HttpResponse
    from django.contrib import messages
    from apps.schools.models import School
    from apps.clusters.models import SchoolClusterAssignment

    districts = District.objects.all().order_by("name")
    clusters = Cluster.objects.filter(deleted_at__isnull=True, status="active")
    
    # Pre-populated cluster if any
    cluster_id = request.GET.get("cluster_id", "").strip()

    if request.method == "POST":
        school_id = request.POST.get("school_id", "").strip()
        name = request.POST.get("name", "").strip()
        district_id = request.POST.get("district_id", "").strip()
        school_type = request.POST.get("school_type", "client").strip()
        enrollment_str = request.POST.get("enrollment", "").strip()
        target_cluster_id = request.POST.get("cluster_id", "").strip()

        if school_id and name and district_id:
            district = get_object_or_404(District, id=district_id)
            enrollment = int(enrollment_str) if enrollment_str.isdigit() else 0
            
            # Create school
            school = School.objects.create(
                school_id=school_id,
                name=name,
                district=district,
                region=district.region,
                school_type=school_type,
                enrollment=enrollment,
                planning_readiness="blocked"
            )
            
            # If cluster assignment was selected, assign it
            if target_cluster_id:
                cluster = get_object_or_404(Cluster, id=target_cluster_id)
                SchoolClusterAssignment.objects.create(
                    school=school,
                    cluster=cluster,
                    assigned_by=str(request.user.id)
                )
                school.cluster_status = "clustered"
                school.save(update_fields=["cluster_status"])
                
            messages.success(request, f"Successfully created and onboarded school '{school.name}' ({school.school_id}).")
            
            # Reload page to refresh the checklist/directory
            return HttpResponse('<script>window.location.reload();</script>')
        else:
            return HttpResponse('<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Failed to create school: missing required fields.</div>', status=400)

    context = {
        "districts": districts,
        "clusters": clusters,
        "pre_cluster_id": cluster_id,
    }
    return render(request, "partials/schools/onboard_drawer.html", context)
