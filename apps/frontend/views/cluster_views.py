from django.utils.html import format_html
from django.shortcuts import render, redirect, get_object_or_404
from apps.core.htmx_errors import error_fragment
from apps.core.permissions import (
    require_export_permission,
    require_page_permission,
    RolePermissionService,
    get_scoped_object_or_404,
)
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
import csv
import json
from datetime import datetime, timedelta

from apps.clusters.models import Cluster, ClusterSubCounty
from apps.schools.models import School
from apps.geography.models import District, SubCounty
from apps.accounts.models import StaffProfile
from apps.core.scoping import (
    cluster_queryset,
    direct_portfolio_schools,
    resolve_user_scope,
)
from apps.core.enums import SsaIntervention

from apps.clusters.services import (
    cluster_schools,
    cluster_detail,
    cluster_intervention_overview,
    cluster_activity_impact,
    assign_school as assign_school_to_cluster,
    cluster_creation_district_ids,
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
    """Cost preview via the central CostingService — no fallback/fabricated rates.

    Missing rates surface as blockers instead of fake prices."""
    from apps.budget.costing_service import preview

    act_type = "cluster_training" if activity_type == "training" else "cluster_meeting"
    result = preview(
        {
            "activityType": act_type,
            "expectedParticipants": participants,
            "clusterId": cluster_id,
        }
    )

    cost_lines = []
    for line in result["lines"]:
        if line["missing"]:
            formula = "Rate not set"
        elif line["qty"] and line["qty"] > 1:
            formula = f"{line['qty']} x UGX {line['unit']:,.0f}"
        else:
            formula = f"UGX {line['unit']:,.0f}"
        cost_lines.append(
            {
                "label": line["label"],
                "formula": formula,
                "amount": line["amount"],
                "missing": line["missing"],
            }
        )

    return {
        "catalogue_version": result["catalogueVersion"] or "None active",
        "lines": cost_lines,
        "amount": result["amount"],
        "can_schedule": result["canSchedule"],
        "blockers": result["blockers"],
    }


def _per_school_from_categories(source) -> int:
    """Teachers + school leaders + other, per school, or 0 when none stated.

    The drawer asks who is invited from each school and never asks for the
    per-school total, so every consumer of that figure — preview and scheduler
    alike — adds the same three numbers up rather than trusting a rendered one.
    """
    total = 0
    for key in ("teachers_per_school", "leaders_per_school", "other_per_school"):
        raw = str(source.get(key, "") or "").strip()
        if raw.isdigit():
            total += int(raw)
    return total


def _cost_preview_participants(request, activity_type):
    """Return the participant count the cost preview must price.

    Cluster totals are derived from the values the planner actually chooses.
    The hidden total is only an Alpine-rendered convenience and can be one
    event behind when HTMX serializes the form.
    """

    raw_total = request.GET.get("expected_participants", "50").strip()
    fallback = int(raw_total) if raw_total.isdigit() else 50

    per_school = _per_school_from_categories(request.GET)
    if per_school < 1:
        raw_per_school = request.GET.get("participants_per_school", "").strip()
        if not raw_per_school.isdigit() or int(raw_per_school) < 1:
            return fallback
        per_school = int(raw_per_school)

    # The ticked schools are the multiplier, for meetings as well as
    # trainings. A meeting used to be priced against live membership on the
    # assumption that it always invites everyone, which stopped being true the
    # moment the planner could untick a school.
    ticked = [s for s in request.GET.getlist("invited_school_ids") if s.strip()]
    if ticked:
        return per_school * len(ticked)

    if activity_type != "training":
        from apps.clusters.services import active_school_count

        schools = active_school_count(request.GET.get("cluster_id", "").strip())
        return per_school * schools if schools else fallback

    # Older callers still send a count rather than a list.
    raw_schools_invited = request.GET.get("schools_invited", "").strip()
    if not raw_schools_invited.isdigit():
        return fallback

    schools_invited = int(raw_schools_invited)
    if schools_invited < 1:
        return fallback

    return per_school * schools_invited


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


@require_page_permission("clusters")
@require_export_permission
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
            page_obj.number, on_each_side=1, on_ends=1
        )
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

    # Only places that hold a cluster. This directory lists clusters, so the
    # geography filters are derived from the clusters themselves rather than
    # from the national district table, where all but a handful of options
    # returned an empty list.
    # Options come from the service, which builds them from the same scoped
    # queryset it lists. Two earlier attempts to rebuild that predicate here
    # both drifted wider than the list — first by including soft-deleted and
    # non-active clusters, then by dropping the scope filter — and each time
    # the surplus showed up as an option that selected nothing.
    districts = data["district_options"]
    sub_counties = data["sub_county_options"]
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

    # Create Cluster, the two header schedule buttons and the per-card
    # "schedule training" all open drawers behind `planning`, which oversight
    # roles do not hold — a Country Director may read this page in full and may
    # not schedule field work on it. They were rendered unconditionally, so
    # those roles were offered controls that answered 403. Gated on the same
    # permission the drawers enforce, exactly as the cluster detail page
    # already does, so a control is present precisely when it works. The server
    # check stays where it is; this is the other half of it.
    #
    # Set BEFORE the HTMX branch: the cards are re-rendered by every filter and
    # search keystroke through that path, so a flag added after it would make
    # the per-card button vanish on the first refresh for the people who are
    # entitled to it.
    context["can_plan_clusters"] = RolePermissionService.can_view_page(
        request.user, "planning"
    )

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/clusters/htmx_response.html", context)

    context["topbar_search"] = {
        "placeholder": "Search clusters…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "hx_get": "/clusters",
        "hx_target": "#clusters-table-container",
        "hx_trigger": "keyup changed delay:250ms, search",
        "hx_include": "#filters-form",
    }
    return render(request, "pages/clusters/index.html", context)


@require_page_permission("planning")
def cluster_schools_partial(request, cluster_id):
    schools = ClusterPlanningService.get_cluster_schools(cluster_id, request.user)
    context = {
        "schools": schools,
        "cluster_id": cluster_id,
        "can_schedule": RolePermissionService.can_schedule_activity(request.user),
        "can_assign_partner": RolePermissionService.can_assign_to_partner(request.user),
    }
    return render(request, "partials/clusters/cluster_schools_table.html", context)


@require_page_permission("planning")
def cluster_cost_preview_partial(request):
    activity_type = request.GET.get("activity_type", "training").strip()
    participants = _cost_preview_participants(request, activity_type)
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
        catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
        scheduled_date_str = request.POST.get("scheduled_date", "").strip()
        assigned_partner_id = request.POST.get("assigned_partner_id", "").strip()
        responsible_staff_id = request.POST.get("responsible_staff_id", "").strip()

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
            "responsibleStaffId": responsible_staff_id or None,
            "assignedPartnerId": assigned_partner_id or None,
            "deliveryType": "partner" if assigned_partner_id else "staff",
        }
        if activity_type == "training":
            data["catalogueItemId"] = catalogue_item_id
            data["requireCatalogue"] = True
        # Cluster work plans people per school, by category, across the schools
        # actually invited. All of it is passed raw: the service validates the
        # categories, adds them into the per-school figure, recounts the
        # cluster and recomputes the total — the browser's arithmetic above is
        # a preview and never the number that gets costed.
        for post_key, payload_key in (
            ("teachers_per_school", "teachersPerSchool"),
            ("leaders_per_school", "leadersPerSchool"),
            ("other_per_school", "otherPerSchool"),
        ):
            raw = request.POST.get(post_key, "").strip()
            if raw:
                data[payload_key] = raw
        per_school = request.POST.get("participants_per_school", "").strip()
        if per_school:
            data["participantsPerSchool"] = per_school
        # Ticked by name. The count the budget multiplies by is derived from
        # the list rather than typed beside it, so the two cannot disagree.
        invited_school_ids = [
            s.strip() for s in request.POST.getlist("invited_school_ids") if s.strip()
        ]
        if invited_school_ids:
            data["invitedSchoolIds"] = invited_school_ids
            data["schoolsInvited"] = str(len(invited_school_ids))
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
                clusters = cluster_queryset(scope, direct_only=True).filter(
                    status="active"
                )

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
                from apps.clusters.services import active_school_count, active_schools
                from apps.activity_catalogue.availability import (
                    CLUSTER,
                    training_activity_options,
                )

                cluster_school_count = (
                    active_school_count(selected_cluster.id) if selected_cluster else 0
                )
                # A failed submission must come back with the same schools
                # ticked. Losing them would silently re-invite the whole
                # cluster and re-price the session on the way through.
                retry_members = (
                    list(active_schools(selected_cluster.id))
                    if selected_cluster
                    else []
                )
                retry_invited = set(invited_school_ids) or {
                    s.id for s in retry_members
                }
                training_options = (
                    training_activity_options(planning_context=CLUSTER)
                    if activity_type == "training"
                    else []
                )

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
                    # Give the planner back exactly what they typed; a failed
                    # submit must not silently reset the room they planned.
                    "teachers_per_school": request.POST.get(
                        "teachers_per_school", ""
                    ).strip()
                    or 0,
                    "leaders_per_school": request.POST.get(
                        "leaders_per_school", ""
                    ).strip()
                    or 0,
                    "other_per_school": request.POST.get("other_per_school", "").strip()
                    or 0,
                    "schools_invited": len(retry_invited),
                    "member_schools": [
                        {
                            "id": s.id,
                            "name": s.name,
                            "school_id": s.school_id,
                            "invited": s.id in retry_invited,
                        }
                        for s in retry_members
                    ],
                    "cluster_school_count": cluster_school_count,
                    "training_activity_options": training_options,
                    "training_activity_options_json": json.dumps(training_options),
                    "selected_training_activity_id": catalogue_item_id,
                    "selected_focus_intervention": focus_intervention,
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


def _default_cluster_owner(user):
    """Who owns a cluster when the creator did not name anybody.

    A field role gets themselves: a cluster is scoped to whoever is responsible
    for it, so a CCEO who created one and left the field blank would build a
    cluster that immediately vanished from their own pickers.

    An oversight role gets nobody. A Country Director creating a cluster is
    setting it up for a team, and quietly filing it under the CD would hide it
    from the field and make the CD the responsible party for work they do not
    do. It stays unowned and visible in `list_ownerless_clusters` until
    somebody assigns it.
    """
    from apps.core.scoping import resolve_user_scope

    scope = resolve_user_scope(user)
    if scope.country_scope or scope.can_view_summary_only:
        return None
    return getattr(user, "user_id", None) or getattr(user, "id", None)


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

        if name and district_id and sub_county_ids:
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
                # Neither this view nor the create form carried the cluster's
                # owner, so every cluster was created ownerless and
                # `responsible_staff_id` was null on every row in the table.
                # `create_cluster` has always accepted it — only the edit
                # drawer ever sent it, so an owner could be added afterwards
                # but never chosen at the point the cluster was made.
                #
                # Falling back to the creator matters now that a cluster is
                # scoped to whoever is responsible for it: a CCEO who made one
                # and left the field alone would otherwise build a cluster they
                # could not then see. An oversight role creating on somebody
                # else's behalf picks the owner explicitly.
                "responsibleStaffId": (
                    request.POST.get("responsible_staff_id", "").strip()
                    or _default_cluster_owner(request.user)
                ),
            }
            try:
                cluster_data = create_cluster_service(payload, request.user)
                cluster_id = cluster_data.get("id")
                messages.success(request, f"Successfully created cluster '{name}'.")

                # Automatically assign the school if assign_school_id is provided
                assign_school_id = request.POST.get("assign_school_id", "").strip()
                if assign_school_id and cluster_id:
                    from apps.schools.models import School

                    school = get_scoped_object_or_404(
                        School,
                        request.user,
                        id=assign_school_id,
                        deleted_at__isnull=True,
                    )
                    cluster = get_scoped_object_or_404(
                        Cluster, request.user, id=cluster_id, deleted_at__isnull=True
                    )
                    # Audited inside set_school_cluster_membership() (the
                    # canonical service assign_school_to_cluster delegates
                    # to) — not duplicated here.
                    assign_school_to_cluster(
                        school.school_id, {"clusterId": cluster.id}, request.user
                    )
                    messages.success(
                        request,
                        f"School '{school.name}' has been assigned to the new cluster '{cluster.name}'.",
                    )
                    return redirect("/schools")
            except Exception as e:
                messages.error(request, f"Failed to create cluster: {e}")
        elif not sub_county_ids:
            messages.error(
                request,
                "Failed to create cluster: select at least one sub-county.",
            )
        else:
            messages.error(request, "Failed to create cluster: missing fields.")

    return redirect("/clusters")


@require_page_permission("cluster_detail")
def cluster_detail_view(request, cluster_id):
    try:
        detail = cluster_detail(cluster_id, request.user)
        intervention_overview = cluster_intervention_overview(cluster_id, request.user)
        impact = cluster_activity_impact(cluster_id, request.user)
        schools = cluster_schools(cluster_id, request.user)
    except Exception as e:
        messages.error(request, f"Error loading cluster details: {e}")
        return redirect("/clusters")

    context = {
        "cluster": detail,
        "weakest_interventions": intervention_overview["weakest"],
        "intervention_summary": intervention_overview["summary"],
        "activity_impact": impact,
        "schools": schools,
        # The same check edit_cluster_drawer_view enforces. Asking the
        # permission service rather than comparing role strings means the
        # button appears exactly when the drawer behind it would open — a
        # template that guesses can offer a control the endpoint refuses, or
        # hide one the user is entitled to.
        "can_edit_cluster": RolePermissionService.can_view_page(
            request.user, "planning"
        ),
        # Cluster-level planning and school-level scheduling use the same
        # permission checks as the destinations behind their controls. This
        # keeps the profile useful as a planning launch point without showing
        # actions that will answer 403 for oversight-only roles.
        "can_plan_clusters": RolePermissionService.can_view_page(
            request.user, "planning"
        ),
        "can_schedule": RolePermissionService.can_schedule_activity(request.user),
    }
    return render(request, "pages/clusters/detail.html", context)


@require_page_permission("planning")
def create_cluster_drawer_view(request):
    import json

    districts = District.objects.all()
    allowed_district_ids = cluster_creation_district_ids(request.user)
    districts = districts.filter(id__in=allowed_district_ids)
    districts = districts.order_by("name")

    district_ids = list(districts.values_list("id", flat=True))
    district_id_strings = {str(district_id) for district_id in district_ids}
    sub_counties = SubCounty.objects.filter(district_id__in=district_ids).order_by(
        "name"
    )

    # A sub-county an active cluster already covers cannot be clustered again —
    # create_cluster refuses it. Send that occupancy alongside the options so
    # the drawer can disable it and name the holder, rather than letting
    # someone pick it and learn the rule from a 400 after submitting.
    from apps.clusters.services import covered_sub_counties

    covered = covered_sub_counties()
    sub_counties_list = [
        {
            "id": sc.id,
            "name": sc.name,
            "district_id": sc.district_id,
            "covered_by": covered.get(str(sc.id)),
        }
        for sc in sub_counties
    ]
    requested_district_id = request.GET.get("district_id", "").strip()
    selected_district_id = requested_district_id
    if selected_district_id not in district_id_strings:
        selected_district_id = str(district_ids[0]) if district_ids else ""

    context = {
        "districts": districts,
        "sub_counties_json": json.dumps(sub_counties_list),
        "selected_district_id": selected_district_id,
        # The create form reads responsible_staff_id on POST but never offered
        # it, so every cluster was created ownerless. Seeded for the district
        # the drawer opens on; the district select refills it from there.
        "staff": get_eligible_staff(selected_district_id),
        "drawer_size": "xl",
        "drawer_type": "center",
        "assign_school_id": request.GET.get("assign_school_id", "").strip(),
    }
    return render(request, "partials/clusters/create_cluster_drawer.html", context)


@require_page_permission("planning")
def planner_drawer_view(request):
    cluster_id = request.GET.get("cluster_id", "").strip()
    activity_type = request.GET.get("activity_type", "training").strip()
    fixed_cluster = request.GET.get("fixed_cluster", "false").strip().lower() == "true"

    # Was: skip the filter when `scope.district_ids` is empty — which handed
    # every cluster in the country to the one user who has no geography at all.
    # `cluster_queryset` fails closed instead, agreeing with `cluster_in_scope`.
    #
    # This is the cluster *planner*: everything it offers leads to a schedule,
    # so it asks the write question. A supervisor sees their CCEOs' clusters
    # on oversight instead.
    scope = resolve_user_scope(request.user)
    clusters = cluster_queryset(scope, direct_only=True).filter(status="active")

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

    from apps.core.enums import SsaIntervention

    interventions = [
        {"value": key.value, "label": key.label} for key in SsaIntervention
    ]

    from apps.clusters.services import active_school_count, active_schools

    cluster_school_count = (
        active_school_count(selected_cluster.id) if selected_cluster else 0
    )
    # The planner ticks schools by name rather than typing how many. The count
    # that multiplies into the budget is then derived from the ticks, so the
    # figure and the list can never disagree — and the completion form knows
    # who to expect instead of starting from a blank register.
    member_schools = list(active_schools(selected_cluster.id)) if selected_cluster else []
    raw_invited = [
        s.strip() for s in request.GET.getlist("invited_school_ids") if s.strip()
    ]
    member_ids = {s.id for s in member_schools}
    invited_ids = [s for s in raw_invited if s in member_ids]
    # First open, and any re-render that has not been through the list yet,
    # invites the whole cluster — which is what the old number defaulted to.
    if not raw_invited:
        invited_ids = [s.id for s in member_schools]
    invited_id_set = set(invited_ids)
    # Who the planner is inviting from each school. The drawer re-renders on
    # every cluster / activity-type change, so these come back from the form
    # rather than resetting to the defaults each time.
    per_school_categories = {
        key: (
            int(request.GET.get(key, "").strip())
            if request.GET.get(key, "").strip().isdigit()
            else default
        )
        for key, default in (
            ("teachers_per_school", 2 if activity_type == "training" else 0),
            ("leaders_per_school", 0 if activity_type == "training" else 2),
            ("other_per_school", 0),
        )
    }
    participants_per_school = sum(per_school_categories.values()) or 2
    schools_invited = len(invited_ids)

    raw_participants = request.GET.get("expected_participants", "").strip()
    if cluster_school_count:
        # Meetings pick their schools the same way trainings do now. A meeting
        # used to invite the whole cluster by definition, but schools miss
        # meetings for the same reasons they miss trainings, and the register
        # has to be able to say which ones were asked.
        participants = participants_per_school * schools_invited
    elif raw_participants.isdigit():
        participants = int(raw_participants)
    else:
        participants = 10

    import datetime
    from django.utils import timezone

    tomorrow = (timezone.now() + datetime.timedelta(days=1)).date()
    default_date = tomorrow.strftime("%Y-%m-%d")

    cost_preview = None
    if selected_cluster:
        cost_preview = ClusterCostPreviewService.preview_cost(
            activity_type, participants, selected_cluster.id
        )

    from apps.activity_catalogue.availability import (
        CLUSTER,
        training_activity_options,
    )

    training_options = (
        training_activity_options(planning_context=CLUSTER)
        if activity_type == "training"
        else []
    )
    selectable_training_ids = {option["id"] for option in training_options}
    selected_training_activity_id = request.GET.get(
        "catalogue_item_id", ""
    ).strip()
    if selected_training_activity_id not in selectable_training_ids:
        selected_training_activity_id = ""

    selected_focus_intervention = request.GET.get(
        "focus_intervention", ""
    ).strip()
    if selected_focus_intervention not in SsaIntervention.values:
        selected_focus_intervention = (
            weakest_interventions[0]["intervention"]
            if weakest_interventions
            else ""
        )

    context = {
        "clusters": clusters,
        "selected_cluster": selected_cluster,
        "fixed_cluster": fixed_cluster,
        "activity_type": activity_type,
        "recommendation": rec,
        "weakest_interventions": weakest_interventions,
        "staff_profiles": staff_profiles,
        "interventions": interventions,
        "expected_participants": participants,
        "cost_preview": cost_preview,
        "default_date": default_date,
        "drawer_type": "center",
        "training_activity_options": training_options,
        "training_activity_options_json": json.dumps(training_options),
        "selected_training_activity_id": selected_training_activity_id,
        "selected_focus_intervention": selected_focus_intervention,
        **per_school_categories,
        "schools_invited": schools_invited,
        "member_schools": [
            {
                "id": s.id,
                "name": s.name,
                "school_id": s.school_id,
                "invited": s.id in invited_id_set,
            }
            for s in member_schools
        ],
        # Read-only, from the canonical counter. It is the ceiling on schools
        # invited and the default when the planner invites everyone; the
        # backend recounts at submission so a stale drawer cannot price work.
        "cluster_school_count": cluster_school_count,
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
        # Was an f-string: unescaped, and it printed whatever the exception
        # said. This one had no `status=`, which is why the earlier sweep of
        # these fragments walked past it.
        return error_fragment(e, action="Could not open the cluster")


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
            # Direct portfolio only. Adding a school to a cluster edits the
            # school record, so a supervisor may not do it for a CCEO's school
            # — the same rule `assign_school` and the picker apply.
            writable = (
                direct_portfolio_schools(resolve_user_scope(user))
                or School.objects.none()
            )
            if covered_sub_counties:
                school = writable.filter(
                    id=sid,
                    sub_county_id__in=covered_sub_counties,
                    deleted_at__isnull=True,
                ).first()
            else:
                school = writable.filter(
                    id=sid, district_id=cluster.district_id, deleted_at__isnull=True
                ).first()
            if school:
                # Audited inside set_school_cluster_membership() (the
                # canonical service assign_school_to_cluster delegates to)
                # — not duplicated here.
                assign_school_to_cluster(
                    school.school_id, {"clusterId": cluster.id}, user
                )
                assigned_schools.append(school.name)

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
        "drawer_type": "center",
        "drawer_size": "md",
    }
    return render(request, "partials/clusters/bulk_assign_drawer.html", context)


def get_eligible_staff(district_id):
    from apps.accounts.models import StaffProfile, StaffSchoolAssignment
    from apps.schools.models import School
    from apps.geography.models import District

    if not district_id:
        return (
            StaffProfile.objects.all()
            .select_related("user")
            .order_by("user__name")[:50]
        )

    # 1. Staff assigned to schools in this district
    school_ids = School.objects.filter(district_id=district_id).values_list(
        "id", flat=True
    )
    staff_ids = StaffSchoolAssignment.objects.filter(
        school_id__in=school_ids
    ).values_list("staff_id", flat=True)
    profiles = (
        StaffProfile.objects.filter(id__in=staff_ids)
        .select_related("user")
        .order_by("user__name")
    )
    if profiles.exists():
        return profiles

    # 2. Fallback to staff assigned to schools in the same region
    district = District.objects.filter(id=district_id).select_related("region").first()
    if district:
        school_ids_in_region = School.objects.filter(
            region_id=district.region_id
        ).values_list("id", flat=True)
        staff_ids_in_region = StaffSchoolAssignment.objects.filter(
            school_id__in=school_ids_in_region
        ).values_list("staff_id", flat=True)
        profiles = (
            StaffProfile.objects.filter(id__in=staff_ids_in_region)
            .select_related("user")
            .order_by("user__name")
        )
        if profiles.exists():
            return profiles

    # 3. Ultimate fallback: all active CCEOs and PLs
    profiles = (
        StaffProfile.objects.filter(user__is_active=True)
        .select_related("user")
        .order_by("user__name")
    )
    return [
        p
        for p in profiles
        if any(r in ["CCEO", "Program Lead", "ProgramLead"] for r in p.user.roles)
    ]


@require_page_permission("planning")
def eligible_staff_options_view(request):
    district_id = request.GET.get("district_id", "").strip()
    selected_staff_id = request.GET.get("selected_staff_id", "").strip()

    staff = get_eligible_staff(district_id)

    # format_html rather than an f-string: these values reach the browser as
    # markup, and a staff name is free text. One apostrophe or angle bracket
    # in a name broke out of the attribute it was written into.
    #
    # Two whole templates rather than one with a `selected` fragment spliced
    # in: injecting an attribute means marking it safe, and a mark_safe() in
    # the middle of a loop over user data is the shape that makes the next
    # reader — and the next scanner — stop and check.
    SELECTED = '<option value="{}" selected>{} ({})</option>'
    UNSELECTED = '<option value="{}">{} ({})</option>'

    # The label goes through as an argument rather than being baked into the
    # format string: format_html() with no args is deprecated in Django 6, and
    # the escaping is identical either way.
    options_html = format_html(
        '<option value="">{}</option>', "-- No Assigned Staff --"
    )
    for sp in staff:
        chosen = (
            str(sp.user.user_id) == selected_staff_id or str(sp.id) == selected_staff_id
        )
        options_html += format_html(
            SELECTED if chosen else UNSELECTED,
            sp.user.user_id,
            sp.user.name,
            sp.user.active_role,
        )

    from django.http import HttpResponse

    return HttpResponse(options_html)


@require_page_permission("planning")
def edit_cluster_drawer_view(request, cluster_id):
    import json

    cluster = get_object_or_404(Cluster, id=cluster_id)
    districts = District.objects.all().order_by("name")
    sub_counties = SubCounty.objects.all().order_by("name")

    covered_ids = list(
        ClusterSubCounty.objects.filter(cluster=cluster).values_list(
            "sub_county_id", flat=True
        )
    )

    # Same occupancy rule as the create drawer, minus this cluster's own
    # coverage: a cluster editing itself must still be able to keep the
    # sub-counties it already holds.
    from apps.clusters.services import covered_sub_counties

    covered = covered_sub_counties()
    own = {str(cluster.sub_county_id)} | {str(i) for i in covered_ids}
    sub_counties_list = [
        {
            "id": sc.id,
            "name": sc.name,
            "district_id": sc.district_id,
            "covered_by": None if str(sc.id) in own else covered.get(str(sc.id)),
        }
        for sc in sub_counties
    ]

    staff = get_eligible_staff(cluster.district_id)

    context = {
        "cluster": cluster,
        "districts": districts,
        "sub_counties_json": json.dumps(sub_counties_list),
        "covered_ids": covered_ids,
        "staff": staff,
        "drawer_size": "md",
        "drawer_type": "center",
    }
    return render(request, "partials/clusters/edit_cluster_drawer.html", context)


@require_page_permission("planning")
def edit_cluster_view(request, cluster_id):
    from apps.clusters.services import update_cluster

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        district_id = request.POST.get("district_id", "").strip()
        sub_county_ids = request.POST.getlist("sub_county_ids")
        cluster_type = request.POST.get("cluster_type", "mixed").strip()
        cluster_leader_name = request.POST.get("cluster_leader_name", "").strip()
        cluster_leader_phone = request.POST.get("cluster_leader_phone", "").strip()
        responsible_staff_id = request.POST.get("responsible_staff_id", "").strip()

        if name and district_id:
            payload = {
                "name": name,
                "districtId": district_id,
                "subCountyIds": sub_county_ids,
                "clusterType": cluster_type,
                "clusterLeaderName": cluster_leader_name or None,
                "clusterLeaderPhone": cluster_leader_phone or None,
                "responsibleStaffId": responsible_staff_id or None,
            }
            try:
                update_cluster(cluster_id, payload, request.user)
                messages.success(request, f"Successfully updated cluster '{name}'.")
            except Exception as e:
                messages.error(request, f"Failed to update cluster: {e}")
        else:
            messages.error(request, "Failed to update cluster: missing fields.")

    return redirect("/clusters")
