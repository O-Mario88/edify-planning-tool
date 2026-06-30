from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone

from apps.planning.services import setup as planning_setup
from apps.planning.services import (
    schedule_school_visit,
    schedule_cluster_activity
)
from apps.budget.costing_service import preview as cost_preview
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.partners.models import Partner, PartnerAssignment
from apps.core.enums import SsaIntervention, PlanningReadiness, SsaStatus, SchoolType, ClusterStatus
from apps.core.fy import get_operational_fy
from apps.core.exceptions import BadRequest
from apps.geography.models import District, SubCounty
from apps.accounts.models import StaffProfile, User
from apps.planning.planning_service import PlanningDashboardService

@login_required(login_url="/login")
def planning_dashboard_view(request):
    fy = get_operational_fy()
    
    # 1. Gather all filters from GET
    filters = {
        "fy": request.GET.get("fy", "2026"),
        "quarter": request.GET.get("quarter", "Q2"),
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

    # 2. Query Dashboard data from Service
    data = PlanningDashboardService.get_dashboard_data(request.user, filters)

    # 3. Dropdowns options
    districts = District.objects.all().order_by("name")
    
    # Filter sub-counties by district if a district is selected
    if filters["district"] and filters["district"] != "All":
        sub_counties = SubCounty.objects.filter(district_id=filters["district"]).order_by("name")
    else:
        sub_counties = SubCounty.objects.all().order_by("name")
        
    staff_members = StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user").order_by("user__name")
    partners = Partner.objects.filter(deleted_at__isnull=True, active_status=True).order_by("name")

    # Pagination pages list
    total_pages = data["total_pages"]
    pages_list = list(range(1, total_pages + 1))
    
    showing_start = (int(filters["page"]) - 1) * int(filters["per_page"]) + 1 if data["total_count"] > 0 else 0
    showing_end = min(int(filters["page"]) * int(filters["per_page"]), data["total_count"])

    # 4. Construct context
    context = {
        "schools": data["schools"],
        "kpis": data["kpis"],
        "cluster_planning": data["cluster_planning"],
        "core_summary": data["core_summary"],
        "total_count": data["total_count"],
        
        # Options
        "districts": districts,
        "sub_counties": sub_counties,
        "staff_members": staff_members,
        "partners": partners,
        "fy_options": ["2026", "2025", "2024"],
        "quarter_options": ["Q1", "Q2", "Q3", "Q4"],
        "school_types": SchoolType.choices,
        "readiness_choices": PlanningReadiness.choices,
        "ssa_statuses": SsaStatus.choices,
        "cluster_statuses": ClusterStatus.choices,

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
        "base_template": "layouts/blank.html" if request.headers.get("HX-Request") == "true" and not request.headers.get("HX-Target") else "layouts/shell.html",
        "use_dark_sidebar": False,
    }

    # If the target is only the school table
    if request.headers.get("HX-Target") == "schools-table-container":
        return render(request, "partials/planning/school_table.html", context)

    return render(request, "pages/planning/index.html", context)


@login_required(login_url="/login")
def schedule_modal_view(request):
    school_id = request.GET.get("school_id")
    school = get_object_or_404(School, Q(id=school_id) | Q(school_id=school_id))

    # Resolve focus recommendations
    recommendations = []
    latest_ssa = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
    if latest_ssa:
        scores = sorted(list(latest_ssa.scores.all().values("intervention", "score")), key=lambda s: s["score"])
        for s in scores[:2]:
            code = s["intervention"]
            label = dict(SsaIntervention.choices).get(code, code)
            recommendations.append({
                "code": code,
                "label": label,
                "score": s["score"]
            })

    partners = Partner.objects.filter(deleted_at__isnull=True, active_status=True).order_by("name")

    context = {
        "school": school,
        "recommendations": recommendations,
        "interventions": SsaIntervention.choices,
        "partners": partners,
    }
    return render(request, "partials/planning/schedule_modal.html", context)


@login_required(login_url="/login")
def schedule_action_view(request):
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    activity_type = request.POST.get("activity_type", "school_visit")
    school_id = request.POST.get("school_id")
    scheduled_date = request.POST.get("scheduled_date")
    focus_intervention = request.POST.get("focus_intervention")
    purpose_text = request.POST.get("activity_purpose_text", "").strip()
    expected_outcome = request.POST.get("expected_outcome", "").strip()
    delivery_type = request.POST.get("delivery_type", "staff")
    partner_id = request.POST.get("assigned_partner_id")

    from datetime import date
    fy = get_operational_fy()

    payload = {
        "activityType": activity_type,
        "scheduledDate": scheduled_date,
        "activityPurposeText": purpose_text,
        "expectedOutcome": expected_outcome,
        "deliveryType": delivery_type,
        "fy": fy,
    }

    if scheduled_date:
        try:
            dt = date.fromisoformat(scheduled_date)
            payload["plannedMonth"] = dt.month
            payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
        except ValueError:
            pass

    if school_id:
        sch = School.objects.filter(Q(id=school_id) | Q(school_id=school_id)).first()
        if sch:
            payload["schoolId"] = sch.school_id
    if focus_intervention:
        payload["focusIntervention"] = focus_intervention
        payload["purposeIntervention"] = focus_intervention
    if partner_id:
        payload["assignedPartnerId"] = partner_id

    try:
        schedule_school_visit(payload, request.user)
        # Trigger page refresh and close modal via client headers
        response = HttpResponse('<script>window.location.reload();</script>')
        response["HX-Trigger"] = "close-modal"
        return response
    except Exception as e:
        return HttpResponse(f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>', status=400)


@login_required(login_url="/login")
def assign_partner_modal_view(request):
    school_id = request.GET.get("school_id")
    school = get_object_or_404(School, Q(id=school_id) | Q(school_id=school_id))

    partners = Partner.objects.filter(deleted_at__isnull=True, active_status=True).order_by("name")
    
    context = {
        "school": school,
        "partners": partners,
        "interventions": SsaIntervention.choices,
    }
    return render(request, "partials/planning/assign_partner_modal.html", context)


@login_required(login_url="/login")
def assign_partner_action_view(request):
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    school_id = request.POST.get("school_id")
    partner_id = request.POST.get("partner_id")
    purpose = request.POST.get("purpose", "").strip()
    focus_intervention = request.POST.get("focus_intervention")
    notes = request.POST.get("notes", "").strip()

    school = get_object_or_404(School, Q(id=school_id) | Q(school_id=school_id))
    partner = get_object_or_404(Partner, id=partner_id)

    try:
        # Create PartnerAssignment record
        PartnerAssignment.objects.create(
            school=school,
            partner=partner,
            assigning_staff_id=request.user.user_id,
            purpose=purpose,
            focus_intervention=focus_intervention,
            notes=notes
        )

        # Update school status
        school.current_fy_ssa_status = "partner_assigned"
        school.planning_readiness = "limited"
        school.save(update_fields=["current_fy_ssa_status", "planning_readiness", "updated_at"])

        # Return refresh trigger and close modal
        response = HttpResponse('<script>window.location.reload();</script>')
        response["HX-Trigger"] = "close-modal"
        return response
    except Exception as e:
        return HttpResponse(f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>', status=400)


@login_required(login_url="/login")
def planning_intelligence_view(request):
    school_id = request.GET.get("school_id")
    if not school_id:
        return HttpResponse('<p class="text-slate-400 text-[11.5px] font-bold py-6 text-center">Select a school to view planning intelligence.</p>')

    school = School.objects.filter(Q(id=school_id) | Q(school_id=school_id)).first()
    if not school:
        return HttpResponse('<p class="text-rose-500 text-[11.5px] font-bold py-6 text-center">School not found.</p>')

    # Fetch latest SSA date
    latest_ssa = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
    last_ssa_date = latest_ssa.date_of_ssa.strftime("%d %b %Y") if latest_ssa else "—"

    # Weakest area
    weakest_area = "—"
    if latest_ssa:
        scores = sorted(list(latest_ssa.scores.all().values("intervention", "score")), key=lambda s: s["score"])
        if scores:
            weakest_area = dict(SsaIntervention.choices).get(scores[0]["intervention"], scores[0]["intervention"])

    # Assigned staff
    assigned_staff = "—"
    if school.account_owner_id:
        owner_profile = StaffProfile.objects.filter(user_id=school.account_owner_id).select_related("user").first()
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


@login_required(login_url="/login")
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
        response["Content-Disposition"] = 'attachment; filename="bulk_planning_export.csv"'
        writer = csv.writer(response)
        writer.writerow(["School ID", "Name", "District", "Cluster", "Planning Readiness"])
        for s in schools:
            writer.writerow([s.school_id, s.name, s.district.name, s.cluster_id or "—", s.planning_readiness])
        return response

    elif action == "partner":
        # Bulk Assign Partner
        partner_id = request.POST.get("partner_id")
        partner = get_object_or_404(Partner, id=partner_id)
        
        for s in schools:
            PartnerAssignment.objects.create(
                school=s,
                partner=partner,
                assigning_staff_id=request.user.user_id,
                purpose="Bulk Partner Assignment"
            )
            s.current_fy_ssa_status = "partner_assigned"
            s.planning_readiness = "limited"
            s.save(update_fields=["current_fy_ssa_status", "planning_readiness", "updated_at"])

        return HttpResponse('<script>window.location.reload();</script>')

    return HttpResponse("Action processed", status=200)


@login_required(login_url="/login")
def schedule_activity_form_view(request):
    action = request.GET.get("action", "visit") # visit, training, meeting
    school_id = request.GET.get("school", "")
    cluster_id = request.GET.get("cluster", "")

    # Populate lookups
    schools = School.objects.filter(deleted_at__isnull=True).order_by("name")
    clusters = Cluster.objects.filter(deleted_at__isnull=True).order_by("name")
    partners = Partner.objects.filter(deleted_at__isnull=True, active_status=True).order_by("name")

    selected_school = School.objects.filter(Q(id=school_id) | Q(school_id=school_id)).first() if school_id else None
    selected_cluster = Cluster.objects.filter(id=cluster_id).first() if cluster_id else None

    # Resolve focus recommendations if school chosen
    recommendations = []
    if selected_school:
        latest_ssa = selected_school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
        if latest_ssa:
            scores = sorted(list(latest_ssa.scores.all().values("intervention", "score")), key=lambda s: s["score"])
            for s in scores[:2]:
                code = s["intervention"]
                label = dict(SsaIntervention.choices).get(code, code)
                recommendations.append({
                    "code": code,
                    "label": label,
                    "score": s["score"]
                })

    if request.method == "POST":
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
                messages.success(request, f"School visit scheduled successfully.")
            else:
                schedule_cluster_activity(payload, request.user)
                messages.success(request, f"Cluster activity scheduled successfully.")
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


@login_required(login_url="/login")
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


