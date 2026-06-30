from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count
from django.http import HttpResponse
import csv
from datetime import datetime, timedelta

from apps.clusters.models import Cluster, SchoolClusterAssignment, ClusterSubCounty
from apps.schools.models import School
from apps.geography.models import Region, District, SubCounty
from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.core.scoping import resolve_user_scope
from apps.core.fy import get_operational_fy, get_quarter_for_date

from apps.clusters.services import (
    list_clusters,
    cluster_schools,
    cluster_detail,
    cluster_weakest_interventions,
    cluster_intervention_summary,
    cluster_activity_impact,
    cluster_planning,
    create_cluster as create_cluster_service
)
from apps.activities.services import create as create_activity_service

def get_cluster_risk(cluster, planning_info, avg_ssa) -> str:
    if avg_ssa is not None and avg_ssa < 5.0:
        return "critical"
    
    schools_count = planning_info.get("schoolsCount", 0)
    ssa_done = planning_info.get("schoolsWithSsa", 0)
    if schools_count > 0 and (ssa_done / schools_count) < 0.5:
        return "critical"
        
    gap_cat = planning_info.get("gapCategory")
    if gap_cat == "no_meetings_this_fy":
        return "critical"
        
    if avg_ssa is not None and avg_ssa < 6.0:
        return "needs_attention"
        
    if gap_cat == "not_met_this_quarter":
        return "needs_attention"
        
    if planning_info.get("schoolsNotVisited", 0) > 0 or planning_info.get("schoolsNotTrained", 0) > 0:
        return "needs_attention"
        
    return "healthy"

def _get_cost_preview_data(activity_type, participants, cluster_id):
    from apps.budget.costing_service import active_catalogue, _rate_card
    catalogue = active_catalogue("2026")
    rates, _ = _rate_card(catalogue)
    
    meals_unit = rates.get("group_training_participant_meal_cost_per_head", 12000)
    venue_unit = rates.get("group_training_venue_cost", 50000)
    facilitation_unit = rates.get("group_training_facilitation_fee", 200000)
    meeting_meals_unit = rates.get("cluster_meeting_participant_meal_cost_per_head", 8000)
    
    cost_lines = []
    total_cost = 0
    if activity_type == "training":
        meals_total = participants * meals_unit
        cost_lines.append({
            "label": "Participant meals",
            "formula": f"{participants} x UGX {meals_unit:,.0f}",
            "amount": meals_total
        })
        cost_lines.append({
            "label": "Venue",
            "formula": f"UGX {venue_unit:,.0f}",
            "amount": venue_unit
        })
        cost_lines.append({
            "label": "Facilitation",
            "formula": f"UGX {facilitation_unit:,.0f}",
            "amount": facilitation_unit
        })
        total_cost = meals_total + venue_unit + facilitation_unit
    else:
        meals_total = participants * meeting_meals_unit
        cost_lines.append({
            "label": "Participant meals",
            "formula": f"{participants} x UGX {meeting_meals_unit:,.0f}",
            "amount": meals_total
        })
        total_cost = meals_total
        
    return {
        "catalogue_version": catalogue.version if catalogue else "None active",
        "lines": cost_lines,
        "amount": total_cost,
        "can_schedule": catalogue is not None,
    }

def get_cluster_impact_data(cluster_id, focus_intervention, principal):
    from apps.clusters.services import cluster_activity_impact
    impacts = cluster_activity_impact(cluster_id, principal)
    focus_impacts = [imp for imp in impacts if imp.get("focusIntervention") == focus_intervention]
    
    if not focus_impacts:
        return None
        
    latest_impact = focus_impacts[0]["impact"]
    return {
        "focus_intervention": focus_intervention.replace("_", " ").title(),
        "before_avg": latest_impact.get("beforeAvg", 0.0),
        "after_avg": latest_impact.get("afterAvg", 0.0),
        "delta": latest_impact.get("delta", 0.0),
        "improved": latest_impact.get("improvedCount", 0),
        "declined": latest_impact.get("declinedCount", 0),
    }

@login_required(login_url="/login")
def cluster_list_view(request):
    user = request.user
    scope = resolve_user_scope(user)
    
    # 1. Base scoped query
    base_qs = Cluster.objects.filter(deleted_at__isnull=True, status="active")
    if not scope.country_scope and scope.district_ids:
        base_qs = base_qs.filter(district_id__in=scope.district_ids)
        
    # 2. Filters from request
    q = request.GET.get("q", "").strip()
    fy = request.GET.get("fy", "2026").strip()
    quarter = request.GET.get("quarter", "").strip()
    district_id = request.GET.get("district", "").strip()
    sub_county_id = request.GET.get("sub_county", "").strip()
    staff_id = request.GET.get("staff", "").strip()
    ssa_status = request.GET.get("ssa_status", "").strip()
    cluster_risk = request.GET.get("cluster_risk", "").strip()
    activity_status = request.GET.get("activity_status", "").strip()
    
    # Apply filters to queryset
    filtered_qs = base_qs
    if q:
        filtered_qs = filtered_qs.filter(Q(name__icontains=q) | Q(district__name__icontains=q))
    if district_id:
        filtered_qs = filtered_qs.filter(district_id=district_id)
    if sub_county_id:
        filtered_qs = filtered_qs.filter(sub_county_id=sub_county_id)
    if staff_id:
        filtered_qs = filtered_qs.filter(Q(responsible_staff_id=staff_id) | Q(assignments__school__account_owner_id=staff_id)).distinct()

    # Get all planning info
    planning_list = cluster_planning(user)
    planning_map = {p["id"]: p for p in planning_list}
    
    # Build Card viewmodels for filtered list
    cards = []
    for c in filtered_qs.select_related("district", "sub_county"):
        schools = School.objects.filter(cluster_assignments__cluster=c, deleted_at__isnull=True)
        schools_count = schools.count()
        
        assigned_staff_ids = schools.exclude(account_owner_id__isnull=True).exclude(account_owner_id="").values_list("account_owner_id", flat=True).distinct()
        staff_count = len(assigned_staff_ids)
        
        latest_ssas = []
        for s in schools:
            latest = s.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
            if latest and latest.average_score is not None:
                latest_ssas.append(latest.average_score)
        avg_ssa = round(sum(latest_ssas) / len(latest_ssas), 1) if latest_ssas else None
        
        acts = Activity.objects.filter(cluster=c, deleted_at__isnull=True)
        
        last_meeting = acts.filter(activity_type="cluster_meeting", status="completed").order_by("-planned_date").first()
        last_meeting_date = last_meeting.planned_date.strftime("%d %b %Y") if last_meeting and last_meeting.planned_date else "Never"
        
        last_training = acts.filter(activity_type__in=["training", "school_improvement_training", "cluster_training"], status="completed").order_by("-planned_date").first()
        last_training_date = last_training.planned_date.strftime("%d %b %Y") if last_training and last_training.planned_date else "Never"
        
        weakest = cluster_weakest_interventions(c.id, user)
        planning_info = planning_map.get(c.id, {})
        risk = get_cluster_risk(c, planning_info, avg_ssa)
        
        if risk == "critical":
            next_action = "Schedule training"
        elif risk == "needs_attention":
            next_action = "Monitor progress"
        else:
            next_action = "Continue support"
            
        cards.append({
            "id": c.id,
            "name": c.name,
            "district": c.district.name if c.district else "Unknown",
            "sub_county": c.sub_county.name if c.sub_county else c.sub_county_name or "Unknown",
            "schools_count": schools_count,
            "staff_count": staff_count,
            "avg_ssa": avg_ssa,
            "last_meeting_date": last_meeting_date,
            "last_training_date": last_training_date,
            "weakest_interventions": weakest,
            "risk": risk,
            "next_action": next_action,
            "planning": planning_info,
        })
        
    # Apply calculated filters in Python
    if ssa_status:
        if ssa_status == "done":
            cards = [c for c in cards if c["planning"].get("schoolsWithSsa", 0) == c["schools_count"]]
        elif ssa_status == "not_done":
            cards = [c for c in cards if c["planning"].get("schoolsWithSsa", 0) < c["schools_count"]]
            
    if cluster_risk:
        cards = [c for c in cards if c["risk"] == cluster_risk]
        
    if activity_status:
        if activity_status == "pending":
            cards = [c for c in cards if c["planning"].get("meetingsScheduledThisFy", 0) > 0]
        elif activity_status == "completed":
            cards = [c for c in cards if c["planning"].get("meetingsThisFy", 0) > 0]

    # Calculate KPIs
    total_clusters = len(cards)
    schools_in_clusters = sum(c["schools_count"] for c in cards)
    without_ssa = sum(1 for c in cards if c["planning"].get("schoolsWithSsa", 0) < c["schools_count"])
    needing_training = sum(1 for c in cards if c["risk"] == "critical" or (c["avg_ssa"] is not None and c["avg_ssa"] < 5.5))
    not_met_this_quarter = sum(1 for c in cards if not c["planning"].get("metThisQuarter", True))
    
    ssas = [c["avg_ssa"] for c in cards if c["avg_ssa"] is not None]
    avg_cluster_ssa = round(sum(ssas) / len(ssas), 1) if ssas else 0.0
    
    from apps.core.enums import SsaIntervention
    interv_totals = {key.value: [] for key in SsaIntervention}
    for c in cards:
        for item in c["weakest_interventions"]:
            if item["avg"] is not None:
                interv_totals[item["intervention"]].append(item["avg"])
    
    weakest_name = "None"
    weakest_avg = 0.0
    lowest_val = 99.0
    for key in SsaIntervention:
        vals = interv_totals[key.value]
        if vals:
            avg = sum(vals) / len(vals)
            if avg < lowest_val:
                lowest_val = avg
                weakest_name = key.label
                weakest_avg = round(avg, 1)
                
    pending_activities = sum(c["planning"].get("meetingsScheduledThisFy", 0) for c in cards)
    
    kpis = {
        "total_clusters": total_clusters,
        "schools_in_clusters": schools_in_clusters,
        "without_ssa": without_ssa,
        "needing_training": needing_training,
        "not_met_this_quarter": not_met_this_quarter,
        "avg_ssa": avg_cluster_ssa,
        "weakest_intervention": weakest_name,
        "weakest_avg": weakest_avg,
        "pending_activities": pending_activities,
    }

    # Risk counts
    critical_count = sum(1 for c in cards if c["risk"] == "critical")
    attention_count = sum(1 for c in cards if c["risk"] == "needs_attention")
    healthy_count = sum(1 for c in cards if c["risk"] == "healthy")
    
    risk_counts = {
        "critical": critical_count,
        "needs_attention": attention_count,
        "healthy": healthy_count,
    }

    # Selected cluster
    selected_cluster = None
    selected_cluster_id = request.GET.get("selected_cluster_id", "").strip()
    if not selected_cluster_id and cards:
        selected_cluster_id = cards[0]["id"]
        
    if selected_cluster_id:
        selected_cluster = next((c for c in cards if c["id"] == selected_cluster_id), None)
        if not selected_cluster and cards:
            selected_cluster = cards[0]
            
    # Planner Cost Preview
    cost_preview = None
    if selected_cluster:
        cost_preview = _get_cost_preview_data("training", 50, selected_cluster["id"])

    # Impact data
    impact_data = None
    if selected_cluster:
        impact_data = get_cluster_impact_data(selected_cluster["id"], "leadership", user)

    # Export handling
    export_format = request.GET.get("export", "").strip()
    if export_format in ["csv", "xlsx"]:
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="clusters_export.csv"'
        writer = csv.writer(response)
        writer.writerow(["Cluster Name", "District", "Sub-county", "Schools", "Avg SSA", "Risk", "Last Meeting", "Last Training"])
        for c in cards:
            writer.writerow([c["name"], c["district"], c["sub_county"], c["schools_count"], c["avg_ssa"], c["risk"], c["last_meeting_date"], c["last_training_date"]])
        return response

    districts = District.objects.all().order_by("name")
    sub_counties = SubCounty.objects.all().order_by("name")
    staff_profiles = StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user").order_by("user__name")

    context = {
        "clusters": cards,
        "kpis": kpis,
        "risk_counts": risk_counts,
        "selected_cluster": selected_cluster,
        "cost_preview": cost_preview,
        "impact_data": impact_data,
        
        "districts": districts,
        "sub_counties": sub_counties,
        "staff_profiles": staff_profiles,
        
        # Selected states
        "q": q,
        "selected_fy": fy,
        "selected_quarter": quarter,
        "selected_district": district_id,
        "selected_sub_county": sub_county_id,
        "selected_staff": staff_id,
        "selected_ssa_status": ssa_status,
        "selected_cluster_risk": cluster_risk,
        "selected_activity_status": activity_status,
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/clusters/htmx_response.html", context)

    return render(request, "pages/clusters/index.html", context)

@login_required(login_url="/login")
def cluster_schools_partial(request, cluster_id):
    schools = cluster_schools(cluster_id, request.user)
    context = {
        "schools": schools,
        "cluster_id": cluster_id,
    }
    return render(request, "partials/clusters/expanded_schools.html", context)

@login_required(login_url="/login")
def cluster_cost_preview_partial(request):
    activity_type = request.GET.get("activity_type", "training").strip()
    participants_str = request.GET.get("expected_participants", "50").strip()
    participants = int(participants_str) if participants_str.isdigit() else 50
    cluster_id = request.GET.get("cluster_id", "").strip()
    
    try:
        preview = _get_cost_preview_data(activity_type, participants, cluster_id)
        context = {
            "success": True,
            "preview": preview,
            "activity_type": activity_type,
            "participants": participants,
        }
    except Exception as e:
        context = {
            "success": False,
            "error_msg": str(e),
        }
    return render(request, "partials/cost_preview.html", context)

@login_required(login_url="/login")
def cluster_schedule_activity_view(request):
    if request.method == "POST":
        cluster_id = request.POST.get("cluster_id", "").strip()
        activity_type = request.POST.get("activity_type", "training").strip()
        participants_str = request.POST.get("expected_participants", "50").strip()
        purpose = request.POST.get("purpose", "").strip()
        focus_intervention = request.POST.get("focus_intervention", "").strip()
        scheduled_date_str = request.POST.get("scheduled_date", "").strip()
        
        if not scheduled_date_str:
            # Fallback default date: 7 days from now
            scheduled_date_str = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT09:00:00Z")
            
        participants = int(participants_str) if participants_str.isdigit() else 50
        
        act_type = "cluster_training" if activity_type == "training" else "cluster_meeting"
        
        data = {
            "activityType": act_type,
            "clusterId": cluster_id,
            "expectedParticipants": participants,
            "activityPurposeText": purpose,
            "focusIntervention": focus_intervention,
            "scheduledDate": scheduled_date_str,
            "deliveryType": "staff",
        }
        
        try:
            create_activity_service(data, request.user)
            messages.success(request, f"Successfully scheduled {activity_type.replace('_', ' ')} for cluster.")
        except Exception as e:
            messages.error(request, f"Failed to schedule activity: {e}")
            
    return redirect("/clusters")

@login_required(login_url="/login")
def cluster_impact_partial(request, cluster_id):
    focus_intervention = request.GET.get("focus_intervention", "leadership").strip()
    impact_data = get_cluster_impact_data(cluster_id, focus_intervention, request.user)
    context = {
        "cluster_id": cluster_id,
        "focus_intervention": focus_intervention,
        "impact_data": impact_data,
    }
    return render(request, "partials/clusters/impact_panel.html", context)

@login_required(login_url="/login")
def create_cluster_view(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        region_id = request.POST.get("region_id", "").strip()
        district_id = request.POST.get("district_id", "").strip()
        sub_county_id = request.POST.get("sub_county_id", "").strip()
        cluster_type = request.POST.get("cluster_type", "mixed").strip()
        
        if name and district_id and sub_county_id:
            # Fetch region from district if not provided
            district = get_object_or_404(District, id=district_id)
            if not region_id:
                region_id = district.region_id
                
            payload = {
                "name": name,
                "regionId": region_id,
                "districtId": district_id,
                "subCountyId": sub_county_id,
                "clusterType": cluster_type,
            }
            try:
                create_cluster_service(payload, request.user)
                messages.success(request, f"Successfully created cluster '{name}'.")
            except Exception as e:
                messages.error(request, f"Failed to create cluster: {e}")
        else:
            messages.error(request, "Failed to create cluster: missing fields.")
            
    return redirect("/clusters")

@login_required(login_url="/login")
def cluster_detail_view(request, cluster_id):
    try:
        detail = cluster_detail(cluster_id, request.user)
        weakest = cluster_weakest_interventions(cluster_id, request.user)
        summary = cluster_intervention_summary(cluster_id, request.user)
        impact = cluster_activity_impact(cluster_id, request.user)
        schools = cluster_schools(cluster_id, request.user)
    except Exception as e:
        messages.error(request, f"Error loading cluster details: {e}")
        return redirect("/clusters")

    context = {
        "cluster": detail,
        "weakest_interventions": weakest,
        "intervention_summary": summary,
        "activity_impact": impact,
        "schools": schools,
    }
    return render(request, "pages/clusters/detail.html", context)


@login_required(login_url="/login")
def create_cluster_drawer_view(request):
    districts = District.objects.all().order_by("name")
    sub_counties = SubCounty.objects.all().order_by("name")
    context = {
        "districts": districts,
        "sub_counties": sub_counties,
        "drawer_size": "md",
    }
    return render(request, "partials/clusters/create_cluster_drawer.html", context)
