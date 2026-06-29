from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.contrib import messages

from apps.schools.models import School
from apps.geography.models import District
from apps.core.enums import SchoolType, PlanningReadiness
from apps.schools.upload_service import upload_school_file
from apps.ssa.upload_service import upload_ssa_file
from apps.schools.services import get_one as get_school_one
from apps.analytics.services import school_impact

@login_required(login_url="/login")
def school_directory_view(request):
    q = request.GET.get("q", "").strip()
    district_id = request.GET.get("district", "").strip()
    school_type = request.GET.get("school_type", "").strip()
    readiness = request.GET.get("readiness", "").strip()
    page_number = request.GET.get("page", 1)

    schools_qs = School.objects.filter(deleted_at__isnull=True).order_by("name")

    if q:
        schools_qs = schools_qs.filter(Q(name__icontains=q) | Q(school_id__icontains=q))
    if district_id:
        schools_qs = schools_qs.filter(district_id=district_id)
    if school_type:
        schools_qs = schools_qs.filter(school_type=school_type)
    if readiness:
        schools_qs = schools_qs.filter(planning_readiness=readiness)

    schools_qs = schools_qs.select_related("district", "sub_county", "parish")

    paginator = Paginator(schools_qs, 15)
    page_obj = paginator.get_page(page_number)

    districts = District.objects.all().order_by("name")
    
    for school in page_obj:
        school.assigned_staff = school.account_owner_name_raw or school.account_owner_id or "Unassigned"

    context = {
        "page_obj": page_obj,
        "districts": districts,
        "school_types": SchoolType.choices,
        "readiness_choices": PlanningReadiness.choices,
        "q": q,
        "selected_district": district_id,
        "selected_type": school_type,
        "selected_readiness": readiness,
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/schools_table.html", context)

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
    
    # Resolve assigned staff name
    school.assigned_staff = school.account_owner_name_raw or school.account_owner_id or "Unassigned"
    
    # 1. Fetch latest SSA score details
    latest_ssa = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
    ssa_scores_list = []
    if latest_ssa:
        ssa_scores_list = list(latest_ssa.scores.all().order_by("-score"))

    # 2. Historical SSA list
    historical_ssas = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa")[1:]

    # 3. Scheduled visits and completed activities
    activities = school.activities.filter(deleted_at__isnull=True).order_by("-planned_date")
    
    # 4. Fetch structured SSA impact records
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
