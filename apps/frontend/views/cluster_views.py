from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import (
    require_page_permission,
    RolePermissionService,
    get_scoped_object_or_404,
)
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
import csv
from datetime import datetime, timedelta

from apps.clusters.models import Cluster, SchoolClusterAssignment, ClusterSubCounty
from apps.schools.models import School
from apps.geography.models import District, SubCounty
from apps.accounts.models import StaffProfile
from apps.core.scoping import resolve_user_scope
from apps.core.enums import SsaIntervention

from apps.clusters.services import (
    cluster_schools,
    cluster_detail,
    cluster_weakest_interventions,
    cluster_intervention_summary,
    cluster_activity_impact,
    create_cluster as create_cluster_service,
    ClusterDashboardService,
    ClusterPlanningService,
    ClusterActionPlannerService,
    ClusterImpactService,
    ClusterRecommendationService,
    ClusterCostPreviewService,
)


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

    if (
        planning_info.get("schoolsNotVisited", 0) > 0
        or planning_info.get("schoolsNotTrained", 0) > 0
    ):
        return "needs_attention"

    return "healthy"


def _get_cost_preview_data(activity_type, participants, cluster_id):
    from apps.budget.costing_service import active_catalogue, _rate_card

    catalogue = active_catalogue("2026")
    rates, _ = _rate_card(catalogue)

    meals_unit = rates.get("group_training_participant_meal_cost_per_head", 12000)
    venue_unit = rates.get("group_training_venue_cost", 50000)
    facilitation_unit = rates.get("group_training_facilitation_fee", 200000)
    meeting_meals_unit = rates.get(
        "cluster_meeting_participant_meal_cost_per_head", 8000
    )

    cost_lines = []
    total_cost = 0
    if activity_type == "training":
        meals_total = participants * meals_unit
        cost_lines.append(
            {
                "label": "Participant meals",
                "formula": f"{participants} x UGX {meals_unit:,.0f}",
                "amount": meals_total,
            }
        )
        cost_lines.append(
            {
                "label": "Venue",
                "formula": f"UGX {venue_unit:,.0f}",
                "amount": venue_unit,
            }
        )
        cost_lines.append(
            {
                "label": "Facilitation",
                "formula": f"UGX {facilitation_unit:,.0f}",
                "amount": facilitation_unit,
            }
        )
        total_cost = meals_total + venue_unit + facilitation_unit
    else:
        meals_total = participants * meeting_meals_unit
        cost_lines.append(
            {
                "label": "Participant meals",
                "formula": f"{participants} x UGX {meeting_meals_unit:,.0f}",
                "amount": meals_total,
            }
        )
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
    focus_impacts = [
        imp for imp in impacts if imp.get("focusIntervention") == focus_intervention
    ]

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


@require_page_permission("planning")
@require_page_permission("planning")
def cluster_list_view(request):
    user = request.user

    # Use the dashboard service
    data = ClusterDashboardService.get_dashboard_data(request, user)
    cards = data["cards"]
    kpis = data["kpis"]
    kpi_strip_items = data["kpi_strip_items"]
    risk_counts = data["risk_counts"]

    # Pagination
    from django.core.paginator import Paginator

    paginator = Paginator(cards, 5)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    pages_list = list(
        page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=2, on_ends=1
        )
    )

    # Selected cluster
    selected_cluster = None
    selected_cluster_id = request.GET.get("selected_cluster_id", "").strip()
    if not selected_cluster_id and page_obj.object_list:
        selected_cluster_id = page_obj.object_list[0]["id"]

    if selected_cluster_id:
        selected_cluster = next(
            (c for c in cards if c["id"] == selected_cluster_id), None
        )
        if not selected_cluster and page_obj.object_list:
            selected_cluster = page_obj.object_list[0]

    # Planner Cost Preview
    cost_preview = None
    if selected_cluster:
        cost_preview = ClusterCostPreviewService.preview_cost(
            "training", 50, selected_cluster["id"]
        )

    # Cluster progress
    cluster_progress = []
    if selected_cluster:
        from apps.schools.models import School
        from apps.ssa.services import get_ssa_progress_by_fy

        schools = School.objects.filter(
            cluster_id=selected_cluster["id"], deleted_at__isnull=True
        )
        cluster_progress = get_ssa_progress_by_fy(schools)

    # Impact data
    impact_data = None
    if selected_cluster:
        impact_data = ClusterImpactService.get_impact_data(
            selected_cluster["id"], "leadership", user
        )

    # Export handling
    export_format = request.GET.get("export", "").strip()
    if export_format in ["csv", "xlsx"]:
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="clusters_export.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Cluster Name",
                "District",
                "Sub-county",
                "Schools",
                "Avg SSA",
                "Risk",
                "Last Meeting",
                "Last Training",
            ]
        )
        for c in cards:
            writer.writerow(
                [
                    c["name"],
                    c["district"],
                    c["sub_county"],
                    c["schools_count"],
                    c["avg_ssa"],
                    c["risk"],
                    c["last_meeting_date"],
                    c["last_training_date"],
                ]
            )
        return response

    districts = District.objects.all().order_by("name")
    sub_counties = SubCounty.objects.all().order_by("name")
    staff_profiles = (
        StaffProfile.objects.filter(deleted_at__isnull=True)
        .select_related("user")
        .order_by("user__name")
    )

    context = {
        "page_obj": page_obj,
        "pages_list": pages_list,
        "clusters": page_obj.object_list,
        "kpis": kpis,
        "kpi_strip_items": kpi_strip_items,
        "risk_counts": risk_counts,
        "selected_cluster": selected_cluster,
        "cost_preview": cost_preview,
        "impact_data": impact_data,
        "cluster_progress": cluster_progress,
        "districts": districts,
        "sub_counties": sub_counties,
        "staff_profiles": staff_profiles,
        # Selected states
        "q": request.GET.get("q", "").strip(),
        "selected_fy": request.GET.get("fy", "2026").strip(),
        "selected_quarter": request.GET.get("quarter", "").strip(),
        "selected_district": request.GET.get("district", "").strip(),
        "selected_sub_county": request.GET.get("sub_county", "").strip(),
        "selected_staff": request.GET.get("staff", "").strip(),
        "selected_ssa_status": request.GET.get("ssa_status", "").strip(),
        "selected_cluster_risk": request.GET.get("cluster_risk", "").strip(),
        "selected_activity_status": request.GET.get("activity_status", "").strip(),
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/clusters/htmx_response.html", context)

    return render(request, "pages/clusters/index.html", context)


@require_page_permission("planning")
def cluster_schools_partial(request, cluster_id):
    schools = ClusterPlanningService.get_cluster_schools(cluster_id, request.user)
    context = {
        "schools": schools,
        "cluster_id": cluster_id,
    }
    return render(request, "partials/clusters/cluster_schools_table.html", context)


@require_page_permission("planning")
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


@require_page_permission("planning")
def cluster_schedule_activity_view(request):
    if not RolePermissionService.can_schedule_activity(request.user):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to schedule cluster activities."
        )
    if request.method == "POST":
        cluster_id = request.POST.get("cluster_id", "").strip()
        activity_type = request.POST.get("activity_type", "training").strip()
        participants_str = request.POST.get("expected_participants", "50").strip()
        purpose = request.POST.get("purpose", "").strip()
        focus_intervention = request.POST.get("focus_intervention", "").strip()
        scheduled_date_str = request.POST.get("scheduled_date", "").strip()
        assigned_partner_id = request.POST.get("assigned_partner_id", "").strip()

        if not scheduled_date_str:
            scheduled_date_str = (datetime.now() + timedelta(days=7)).strftime(
                "%Y-%m-%dT09:00:00Z"
            )

        participants = int(participants_str) if participants_str.isdigit() else 50

        act_type = (
            "cluster_training" if activity_type == "training" else "cluster_meeting"
        )

        data = {
            "activityType": act_type,
            "clusterId": cluster_id,
            "expectedParticipants": participants,
            "activityPurposeText": purpose,
            "focusIntervention": focus_intervention,
            "scheduledDate": scheduled_date_str,
            "assignedPartnerId": assigned_partner_id or None,
            "deliveryType": "partner" if assigned_partner_id else "staff",
        }

        try:
            ClusterActionPlannerService.schedule_activity(data, request.user)
            messages.success(
                request,
                f"Successfully scheduled {activity_type.replace('_', ' ')} for cluster.",
            )
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse("")
                response["HX-Trigger"] = "close-drawer, refresh-clusters"
                return response
        except Exception as e:
            messages.error(request, f"Failed to schedule activity: {e}")
            if request.headers.get("HX-Request") == "true":
                scope = resolve_user_scope(request.user)
                clusters = Cluster.objects.filter(
                    deleted_at__isnull=True, status="active"
                )
                if not scope.country_scope and scope.district_ids:
                    clusters = clusters.filter(district_id__in=scope.district_ids)

                selected_cluster = clusters.filter(id=cluster_id).first()
                rec = None
                if selected_cluster:
                    rec = ClusterRecommendationService.get_recommendation(
                        selected_cluster.id, request.user
                    )

                staff_profiles = (
                    StaffProfile.objects.filter(deleted_at__isnull=True)
                    .select_related("user")
                    .order_by("user__name")
                )
                from apps.partners.models import Partner

                partners = Partner.objects.filter(deleted_at__isnull=True)
                from apps.core.enums import SsaIntervention

                interventions = [
                    {"value": key.value, "label": key.label} for key in SsaIntervention
                ]

                cost_preview = None
                if selected_cluster:
                    try:
                        cost_preview = ClusterCostPreviewService.preview_cost(
                            activity_type, participants, selected_cluster.id
                        )
                    except Exception:
                        pass

                context = {
                    "clusters": clusters,
                    "selected_cluster": selected_cluster,
                    "activity_type": activity_type,
                    "recommendation": rec,
                    "staff_profiles": staff_profiles,
                    "partners": partners,
                    "interventions": interventions,
                    "expected_participants": participants,
                    "cost_preview": cost_preview,
                    "error_msg": str(e),
                }
                return render(
                    request,
                    "partials/clusters/cluster_action_planner_drawer.html",
                    context,
                )

    return redirect("/clusters")


@require_page_permission("planning")
def cluster_impact_partial(request, cluster_id):
    focus_intervention = request.GET.get("focus_intervention", "leadership").strip()
    impact_data = get_cluster_impact_data(cluster_id, focus_intervention, request.user)
    context = {
        "cluster_id": cluster_id,
        "focus_intervention": focus_intervention,
        "impact_data": impact_data,
    }
    return render(request, "partials/clusters/impact_panel.html", context)


@require_page_permission("planning")
def create_cluster_view(request):
    if not RolePermissionService.can_schedule_activity(request.user):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to create clusters."
        )
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        region_id = request.POST.get("region_id", "").strip()
        district_id = request.POST.get("district_id", "").strip()

        # Accept multiple sub-counties from checklist
        sub_county_ids = request.POST.getlist("sub_county_ids")
        if not sub_county_ids and request.POST.get("sub_county_id"):
            sub_county_ids = [request.POST.get("sub_county_id")]

        cluster_type = request.POST.get("cluster_type", "mixed").strip()
        cluster_leader_name = request.POST.get("cluster_leader_name", "").strip()
        cluster_leader_phone = request.POST.get("cluster_leader_phone", "").strip()

        if name and district_id:
            district = get_object_or_404(District, id=district_id)
            if not region_id:
                region_id = district.region_id

            payload = {
                "name": name,
                "regionId": region_id,
                "districtId": district_id,
                "subCountyIds": sub_county_ids,
                "clusterType": cluster_type,
                "clusterLeaderName": cluster_leader_name or None,
                "clusterLeaderPhone": cluster_leader_phone or None,
            }
            try:
                cluster_data = create_cluster_service(payload, request.user)
                cluster_id = cluster_data.get("id")
                messages.success(request, f"Successfully created cluster '{name}'.")

                # Automatically assign the school if assign_school_id is provided
                assign_school_id = request.POST.get("assign_school_id", "").strip()
                if assign_school_id and cluster_id:
                    from apps.schools.models import School
                    from apps.clusters.models import SchoolClusterAssignment

                    school = get_scoped_object_or_404(
                        School,
                        request.user,
                        id=assign_school_id,
                        deleted_at__isnull=True,
                    )
                    cluster = get_scoped_object_or_404(
                        Cluster, request.user, id=cluster_id, deleted_at__isnull=True
                    )
                    school.cluster_id = cluster.id
                    school.cluster_status = "clustered"
                    school.planning_readiness = "ready"
                    school.save()

                    SchoolClusterAssignment.objects.get_or_create(
                        school=school,
                        cluster=cluster,
                        defaults={"assigned_by": request.user.user_id},
                    )

                    # Log audit event
                    from apps.audit.services import log as audit_log

                    audit_log(
                        action="school.assign_cluster",
                        subject_kind="School",
                        subject_id=school.id,
                        actor_id=request.user.user_id,
                        actor_role=request.user.active_role,
                        success=True,
                        payload={
                            "cluster_id": cluster.id,
                            "cluster_name": cluster.name,
                        },
                    )
                    messages.success(
                        request,
                        f"School '{school.name}' has been assigned to the new cluster '{cluster.name}'.",
                    )
                    return redirect("/schools")
            except Exception as e:
                messages.error(request, f"Failed to create cluster: {e}")
        else:
            messages.error(request, "Failed to create cluster: missing fields.")

    return redirect("/clusters")


@require_page_permission("planning")
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


@require_page_permission("planning")
def create_cluster_drawer_view(request):
    import json

    districts = District.objects.all().order_by("name")
    sub_counties = SubCounty.objects.all().order_by("name")

    sub_counties_list = [
        {"id": sc.id, "name": sc.name, "district_id": sc.district_id}
        for sc in sub_counties
    ]

    context = {
        "districts": districts,
        "sub_counties_json": json.dumps(sub_counties_list),
        "drawer_size": "md",
        "drawer_type": "center",
        "assign_school_id": request.GET.get("assign_school_id", "").strip(),
    }
    return render(request, "partials/clusters/create_cluster_drawer.html", context)


@require_page_permission("planning")
def planner_drawer_view(request):
    cluster_id = request.GET.get("cluster_id", "").strip()
    activity_type = request.GET.get("activity_type", "training").strip()
    fixed_cluster = request.GET.get("fixed_cluster", "false").strip().lower() == "true"

    scope = resolve_user_scope(request.user)
    clusters = Cluster.objects.filter(deleted_at__isnull=True, status="active")
    if not scope.country_scope and scope.district_ids:
        clusters = clusters.filter(district_id__in=scope.district_ids)

    selected_cluster = None
    if cluster_id:
        selected_cluster = clusters.filter(id=cluster_id).first()
    elif clusters.exists():
        selected_cluster = clusters.first()

    rec = None
    weakest_interventions = []
    if selected_cluster:
        rec = ClusterRecommendationService.get_recommendation(
            selected_cluster.id, request.user
        )
        from apps.clusters.services import cluster_weakest_interventions

        try:
            weakest_interventions = cluster_weakest_interventions(
                selected_cluster.id, request.user
            )
        except Exception:
            pass

    staff_profiles = (
        StaffProfile.objects.filter(deleted_at__isnull=True)
        .select_related("user")
        .order_by("user__name")
    )

    from apps.partners.models import Partner

    partners = Partner.objects.filter(deleted_at__isnull=True)

    from apps.core.enums import SsaIntervention

    interventions = [
        {"value": key.value, "label": key.label} for key in SsaIntervention
    ]

    raw_participants = request.GET.get("expected_participants", "").strip()
    if raw_participants.isdigit():
        participants = int(raw_participants)
    else:
        participants = 25 if activity_type == "training" else 10

    import datetime
    from django.utils import timezone

    tomorrow = (timezone.now() + datetime.timedelta(days=1)).date()
    default_date = tomorrow.strftime("%Y-%m-%d")

    cost_preview = None
    if selected_cluster:
        cost_preview = ClusterCostPreviewService.preview_cost(
            activity_type, participants, selected_cluster.id
        )

    context = {
        "clusters": clusters,
        "selected_cluster": selected_cluster,
        "fixed_cluster": fixed_cluster,
        "activity_type": activity_type,
        "recommendation": rec,
        "weakest_interventions": weakest_interventions,
        "staff_profiles": staff_profiles,
        "partners": partners,
        "interventions": interventions,
        "expected_participants": participants,
        "cost_preview": cost_preview,
        "default_date": default_date,
        "drawer_type": "center",
    }

    return render(
        request, "partials/clusters/cluster_action_planner_drawer.html", context
    )


@require_page_permission("planning")
def schedule_training_drawer_view(request):
    return planner_drawer_view(request)


@require_page_permission("planning")
def schedule_meeting_drawer_view(request):
    request.GET = request.GET.copy()
    request.GET["activity_type"] = "meeting"
    return planner_drawer_view(request)


@require_page_permission("planning")
def cluster_detail_drawer_view(request, cluster_id):
    try:
        detail = cluster_detail(cluster_id, request.user)
        context = {
            "cluster": detail,
            "drawer_size": "lg",
        }
        return render(request, "partials/clusters/cluster_detail_drawer.html", context)
    except Exception as e:
        return HttpResponse(f"<div class='p-4 text-red-500'>Error: {e}</div>")


@require_page_permission("planning")
def intervention_impact_drawer_view(request, cluster_id):
    focus_intervention = request.GET.get("focus_intervention", "leadership").strip()
    impact_data = ClusterImpactService.get_impact_data(
        cluster_id, focus_intervention, request.user
    )
    context = {
        "cluster_id": cluster_id,
        "focus_intervention": focus_intervention,
        "impact_data": impact_data,
        "interventions": SsaIntervention.choices,
        "drawer_size": "lg",
    }
    return render(request, "partials/clusters/intervention_impact_drawer.html", context)


@require_page_permission("planning")
def cluster_bulk_assign_drawer_view(request, cluster_id):
    from apps.audit.services import log as audit_log

    cluster = get_scoped_object_or_404(
        Cluster, request.user, id=cluster_id, deleted_at__isnull=True
    )
    covered_sub_counties = ClusterSubCounty.objects.filter(cluster=cluster).values_list(
        "sub_county_id", flat=True
    )

    if request.method == "POST":
        school_ids = request.POST.getlist("school_ids")
        user = request.user

        assigned_schools = []
        for sid in school_ids:
            # Allow assignment if school is in a covered sub-county OR (for
            # district-level clusters with no covered sub-counties) in the
            # cluster's district.
            if covered_sub_counties:
                school = School.objects.filter(
                    id=sid,
                    sub_county_id__in=covered_sub_counties,
                    deleted_at__isnull=True,
                ).first()
            else:
                school = School.objects.filter(
                    id=sid, district_id=cluster.district_id, deleted_at__isnull=True
                ).first()
            if school:
                school.cluster_id = cluster.id
                school.cluster_status = "clustered"
                school.recompute_quality_and_readiness()
                school.save()

                SchoolClusterAssignment.objects.get_or_create(
                    school=school,
                    cluster=cluster,
                    defaults={"assigned_by": user.user_id},
                )
                assigned_schools.append(school.name)

                audit_log(
                    action="school.assign_cluster",
                    subject_kind="School",
                    subject_id=school.id,
                    actor_id=user.user_id,
                    actor_role=user.active_role,
                    success=True,
                    payload={
                        "cluster_id": cluster.id,
                        "cluster_name": cluster.name,
                        "bulk": True,
                    },
                )

        msg = (
            f"Successfully assigned {len(assigned_schools)} schools to {cluster.name}."
        )
        response = render(
            request, "partials/schools/toast_success.html", {"message": msg}
        )
        response["HX-Trigger"] = (
            f"cluster-schools-updated-{cluster.id}, schools-updated"
        )
        return response

    # GET method — if cluster has covered sub-counties, filter by them.
    # If no covered sub-counties (district-level cluster), show all unclustered
    # schools in the cluster's district.
    if covered_sub_counties:
        unassigned_schools = (
            School.objects.filter(
                sub_county_id__in=covered_sub_counties,
                cluster_status="unclustered",
                deleted_at__isnull=True,
            )
            .select_related("sub_county")
            .order_by("sub_county__name", "name")
        )
    else:
        unassigned_schools = (
            School.objects.filter(
                district_id=cluster.district_id,
                cluster_status="unclustered",
                deleted_at__isnull=True,
            )
            .select_related("sub_county")
            .order_by("name")
        )

    context = {
        "cluster": cluster,
        "schools": unassigned_schools,
        "drawer_type": "right",
        "drawer_size": "md",
    }
    return render(request, "partials/clusters/bulk_assign_drawer.html", context)
