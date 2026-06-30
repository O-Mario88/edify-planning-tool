from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.contrib import messages

from apps.schools.models import School
from apps.geography.models import Region, District, SubCounty
from apps.core.enums import SchoolType, PlanningReadiness
from apps.schools.upload_service import upload_school_file
from apps.ssa.upload_service import upload_ssa_file
from apps.schools.services import get_one as get_school_one
from apps.analytics.services import school_impact
from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.clusters.models import Cluster, SchoolClusterAssignment
from apps.core.scoping import resolve_user_scope, school_queryset

def _get_school_intelligence_data(school):
    latest_ssa = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
    weakest = "None"
    last_ssa_date = "No SSA Recorded"
    if latest_ssa:
        last_ssa_date = latest_ssa.date_of_ssa.strftime("%d %b %Y")
        lowest_score = latest_ssa.scores.filter(deleted_at__isnull=True).order_by("score").first()
        if lowest_score:
            weakest = f"{lowest_score.get_intervention_display()} ({lowest_score.score})"
    
    cluster_name = "Unassigned"
    if school.cluster_id:
        cluster = Cluster.objects.filter(id=school.cluster_id, deleted_at__isnull=True).first()
        if cluster:
            cluster_name = cluster.name
            
    assigned_staff_name = school.account_owner_name_raw or school.account_owner_id or "Unassigned"
    
    return {
        "school": school,
        "cluster_name": cluster_name,
        "weakest_intervention": weakest,
        "last_ssa_date": last_ssa_date,
        "assigned_staff_name": assigned_staff_name,
    }

@login_required(login_url="/login")
def school_intelligence_partial(request, school_id):
    school = get_object_or_404(School, id=school_id, deleted_at__isnull=True)
    intel_data = _get_school_intelligence_data(school)
    return render(request, "partials/schools/directory_intelligence.html", {"intelligence": intel_data})

@login_required(login_url="/login")
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
    staff_id = request.GET.get("staff", "").strip()
    staff_match = request.GET.get("staff_match", "").strip()
    cluster_status = request.GET.get("cluster_status", "").strip()
    ssa_status = request.GET.get("ssa_status", "").strip()
    readiness = request.GET.get("readiness", "").strip()
    partner_type = request.GET.get("partner_type", "").strip()
    active_tab = request.GET.get("tab", "all").strip()
    page_number = request.GET.get("page", 1)

    # Apply dropdown filters to calculate active KPIs and tab counts
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
    if staff_id:
        filtered_qs = filtered_qs.filter(account_owner_id=staff_id)
    if staff_match:
        if staff_match == "matched":
            filtered_qs = filtered_qs.exclude(account_owner_id__isnull=True).exclude(account_owner_id="")
        elif staff_match == "unmatched":
            filtered_qs = filtered_qs.filter(Q(account_owner_id__isnull=True) | Q(account_owner_id=""))
    if cluster_status:
        filtered_qs = filtered_qs.filter(cluster_status=cluster_status)
    if ssa_status:
        filtered_qs = filtered_qs.filter(current_fy_ssa_status=ssa_status)
    if readiness:
        filtered_qs = filtered_qs.filter(planning_readiness=readiness)
    if partner_type:
        if partner_type == "assigned":
            filtered_qs = filtered_qs.exclude(cluster_id__isnull=True).exclude(cluster_id="")
        elif partner_type == "none":
            filtered_qs = filtered_qs.filter(Q(cluster_id__isnull=True) | Q(cluster_id=""))

    # Compute Tab Counts on the filtered list (before active tab filtering)
    all_count = filtered_qs.count()
    unclustered_count = filtered_qs.filter(cluster_status="unclustered").count()
    needs_ssa_count = filtered_qs.filter(current_fy_ssa_status="not_done").count()
    staff_setup_count = filtered_qs.filter(Q(account_owner_id__isnull=True) | Q(account_owner_id="") | Q(account_owner_status="pending")).count()
    duplicates_count = filtered_qs.filter(duplicate_status="duplicate").count()

    # Apply Tab Filter
    schools_qs = filtered_qs
    if active_tab == "unclustered":
        schools_qs = schools_qs.filter(cluster_status="unclustered")
    elif active_tab == "needs_ssa":
        schools_qs = schools_qs.filter(current_fy_ssa_status="not_done")
    elif active_tab == "staff_setup":
        schools_qs = schools_qs.filter(Q(account_owner_id__isnull=True) | Q(account_owner_id="") | Q(account_owner_status="pending"))
    elif active_tab == "duplicates":
        schools_qs = schools_qs.filter(duplicate_status="duplicate")

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

    # Paginate list
    schools_qs = schools_qs.select_related("district", "sub_county", "parish")
    paginator = Paginator(schools_qs, 15)
    page_obj = paginator.get_page(page_number)

    for school in page_obj:
        school.assigned_staff = school.account_owner_name_raw or school.account_owner_id or "Unassigned"

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

    context = {
        "page_obj": page_obj,
        "regions": regions,
        "districts": districts,
        "sub_counties": sub_counties,
        "staff_profiles": staff_profiles,
        "clusters": clusters,
        
        "school_types": SchoolType.choices,
        "readiness_choices": PlanningReadiness.choices,
        
        # Selected states
        "q": q,
        "selected_fy": fy,
        "selected_region": region_id,
        "selected_district": district_id,
        "selected_sub_county": sub_county_id,
        "selected_type": school_type,
        "selected_staff": staff_id,
        "selected_staff_match": staff_match,
        "selected_cluster_status": cluster_status,
        "selected_ssa_status": ssa_status,
        "selected_readiness": readiness,
        "selected_partner_type": partner_type,
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
        "needs_ssa_count": needs_ssa_count,
        "staff_setup_count": staff_setup_count,
        "duplicates_count": duplicates_count,
        
        # Selected school intelligence
        "intelligence": selected_school_data,
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/schools/htmx_response.html", context)

    return render(request, "pages/schools/index.html", context)

@login_required(login_url="/login")
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

@login_required(login_url="/login")
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

    context = {
        "school": school,
        "latest_ssa": latest_ssa,
        "ssa_scores": ssa_scores_list,
        "historical_ssas": historical_ssas,
        "activities": activities,
        "impact_data": impact_data,
    }
    return render(request, "pages/schools/detail.html", context)

@login_required(login_url="/login")
def bulk_assign_cluster_view(request):
    if request.method == "POST":
        school_ids = request.POST.get("school_ids", "").split(",")
        cluster_id = request.POST.get("cluster_id", "").strip()
        if school_ids and cluster_id:
            cluster = get_object_or_404(Cluster, id=cluster_id, deleted_at__isnull=True)
            schools = School.objects.filter(id__in=school_ids, deleted_at__isnull=True)
            for s in schools:
                s.cluster_id = cluster.id
                s.cluster_status = "clustered"
                s.save()
                SchoolClusterAssignment.objects.get_or_create(
                    school=s,
                    cluster=cluster,
                    defaults={"assigned_by": request.user.user_id}
                )
            messages.success(request, f"Successfully assigned {schools.count()} schools to cluster '{cluster.name}'.")
        else:
            messages.error(request, "Failed to perform assignment: missing fields.")
    return redirect("/schools")

@login_required(login_url="/login")
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

@login_required(login_url="/login")
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
