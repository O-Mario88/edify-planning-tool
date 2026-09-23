from django.utils.html import format_html
from django.utils.html import escape
from django.shortcuts import render, redirect, get_object_or_404
from apps.core.htmx_errors import error_fragment
from apps.core.permissions import (
    has_permission,
    require_export_permission,
    require_page_permission,
    RolePermissionService,
    get_operational_cluster_or_404,
    get_scoped_object_or_404,
)
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
import csv
import json
from datetime import datetime, timedelta

from apps.clusters.models import Cluster, ClusterSubCounty
from apps.frontend.views.planning_views import _no_scheduling_permission_message
from apps.partners.support_responsibility import (
    visibility_enabled as support_visibility_enabled,
)
from apps.schools.models import School
from apps.geography.models import District, SubCounty
from apps.accounts.models import StaffProfile
from apps.core.scoping import (
    cluster_queryset,
    direct_portfolio_schools,
    or_empty,
    resolve_user_scope,
)
from apps.core.enums import SsaIntervention
from apps.core.rbac import Permission

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


#: Form field -> costing key for the training materials a cluster session
#: plans (owner, 2026-09-15): printing by the page, photocopying by the page
#: and the copy. Read from the drawer's GET (preview, re-render) and POST
#: (schedule) alike, so the two cannot price different handouts.
MATERIALS_FIELDS = (
    ("printing_pages", "printingPages"),
    ("photocopy_pages", "photocopyPages"),
    ("photocopy_copies", "photocopyCopies"),
)


def _materials_from(source) -> dict:
    """The materials inputs as typed, keyed for costing; blank stays blank.

    Blank means "none planned" everywhere downstream — the engine prices a
    blank or zero page count as no materials line — so nothing is defaulted
    here; the service refuses anything that is not a whole number."""
    return {
        payload_key: str(source.get(form_key, "") or "").strip()
        for form_key, payload_key in MATERIALS_FIELDS
    }


def _get_cost_preview_data(
    activity_type,
    participants,
    cluster_id,
    *,
    planned_date=None,
    responsible_user_id=None,
    materials=None,
):
    """Cost preview via the central CostingService — no fallback/fabricated rates.

    Missing rates surface as blockers instead of fake prices."""
    from apps.budget.costing import _nonnegative_count
    from apps.budget.costing_service import preview

    act_type = "cluster_training" if activity_type == "training" else "cluster_meeting"
    materials = materials or {}
    result = preview(
        {
            "activityType": act_type,
            "expectedParticipants": participants,
            "clusterId": cluster_id,
            "plannedDate": planned_date,
            **materials,
        },
        minimum=True,
        responsible_user_id=responsible_user_id,
    )
    printing_pages = _nonnegative_count(materials.get("printingPages"))
    photocopy_pages = _nonnegative_count(materials.get("photocopyPages"))
    photocopy_copies = _nonnegative_count(materials.get("photocopyCopies"))

    cost_lines = []
    for line in result["lines"]:
        if line["missing"]:
            formula = "Rate not set"
        elif line["key"] == "printing_training_materials":
            formula = f"{printing_pages} pages x UGX {line['unit']:,.0f}"
        elif line["key"] == "photocopying_training_materials":
            formula = (
                f"{photocopy_pages} pages x {photocopy_copies} copies "
                f"x UGX {line['unit']:,.0f}"
            )
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
        "can_schedule": not result["costMissing"],
        "costMissing": result["costMissing"],
        "blockers": result["blockers"],
        "allocationNote": result["allocationNote"],
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

    raw_total = request.GET.get("expected_participants", "").strip()
    fallback = int(raw_total) if raw_total.isdigit() else 0

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
    from apps.core.pagination import elided_page_numbers

    pages_list = elided_page_numbers(page_obj)

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
        # The service validated the year; showing the raw query value let the
        # selector and the figures disagree (2026-09-13).
        "selected_fy": data["fy"],
        "fy_options": data["fy_options"],
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
    # The page permission alone was not enough: the Country Director holds
    # `planning` for non-school work, so the buttons appeared for them and
    # answered 403 — cluster meetings and trainings are the cluster owner's
    # programme, and `can_schedule_activity` is what the drawer POST checks.
    # Creating a cluster is registry work behind CLUSTER_ASSIGN, a different
    # question, so it gets its own flag.
    context["can_plan_clusters"] = RolePermissionService.can_view_page(
        request.user, "planning"
    ) and RolePermissionService.can_schedule_activity(request.user)
    context["can_create_clusters"] = (
        Permission.CLUSTER_ASSIGN.value in resolve_user_scope(request.user).permissions
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


def _attach_planning_badges(request, schools) -> str:
    """The Visit and Training badges on a Cluster School List (owner,
    2026-09-22), from the one calculation the Planning page reads, for the
    same financial year Planning defaults to. Returns that year.

    With the Partner-supported school rule on, Next Activity (owner,
    2026-09-23) is read from the same pass, as it is on Planning."""
    from apps.core.fy import get_operational_fy
    from apps.planning.school_planning_badges import (
        SchoolPlanningBadges,
        SchoolPlanningBadgeService,
    )

    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    rows = list(schools)
    details = [] if any(row.get("supportRule") for row in rows) else None
    badges = SchoolPlanningBadgeService.get_for_schools(
        [row["id"] for row in rows], financial_year=fy, details=details
    )
    upcoming = {}
    if details is not None:
        from apps.planning.planning_support import next_activities

        upcoming = next_activities(details)
    for row in rows:
        row["planningBadges"] = badges.get(row["id"]) or SchoolPlanningBadges(
            school_id=row["id"]
        )
        if details is not None:
            row["nextActivity"] = upcoming.get(row["id"])
    return fy


@require_page_permission("planning")
def cluster_schools_partial(request, cluster_id):
    schools = ClusterPlanningService.get_cluster_schools(cluster_id, request.user)
    _attach_planning_badges(request, schools)
    context = {
        "schools": schools,
        "cluster_id": cluster_id,
        # Whoever the drawer opens for: planners for their programme, the
        # visit roles for any school (owner, 2026-09-21), the Accountant to
        # ask — see RolePermissionService.can_open_schedule_drawer.
        "can_schedule": RolePermissionService.can_open_schedule_drawer(request.user),
        "can_assign_partner": RolePermissionService.can_assign_to_partner(request.user),
        # The same check the edit drawer and the remove endpoint enforce.
        "can_edit_cluster": RolePermissionService.can_view_page(
            request.user, "planning"
        ),
        # Bulk scheduling is a planner's act, not a requester's: the drawer
        # writes activities for several schools at once and the request flow
        # decides them one at a time (owner, 2026-09-21).
        "can_bulk_schedule": RolePermissionService.can_schedule_activity(request.user),
        # Cluster Meetings and Group Training are the cluster owner's
        # programme; a Partner-supported school joins one by name from its row.
        "can_plan_clusters": RolePermissionService.can_schedule_activity(request.user),
        "can_monitor_partners": has_permission(
            request.user, Permission.PARTNER_MONITORING_VIEW.value
        ),
    }
    return render(request, "partials/clusters/cluster_schools_table.html", context)


@require_page_permission("planning")
def cluster_cost_preview_partial(request):
    # Both spellings, because one drawer now serves both entry points and the
    # two arrived here with different vocabularies: the Clusters drawer sent
    # the short "training"/"meeting" its own radios use, the Planning drawer
    # sends the canonical activity type it posts to the scheduler. Normalising
    # here keeps a single preview endpoint rather than a second one.
    activity_type = request.GET.get("activity_type", "training").strip()
    if activity_type.startswith("cluster_"):
        activity_type = activity_type[len("cluster_") :]
    participants = _cost_preview_participants(request, activity_type)
    cluster_id = request.GET.get("cluster_id", "").strip()

    try:
        from apps.budget.costing_service import planning_preview_owner

        preview = _get_cost_preview_data(
            activity_type,
            participants,
            cluster_id,
            planned_date=request.GET.get("scheduled_date") or request.GET.get("date"),
            responsible_user_id=planning_preview_owner(
                request.user, request.GET.get("responsible_staff_id")
            ),
            materials=_materials_from(request.GET),
        )
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
            _no_scheduling_permission_message(request.user, cluster=True)
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
        else:
            # A cluster meeting is costed, evidenced and counted through its
            # catalogue item like every other activity. This path used to
            # create meetings with no catalogue item at all (2026-09-15), so
            # they carried no version snapshot or costing profile.
            from apps.activity_catalogue.services import (
                resolve_item_for_workflow_kind,
            )

            meeting_item = resolve_item_for_workflow_kind("cluster_meeting")
            if meeting_item is not None:
                data["catalogueItemId"] = meeting_item.id
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
        # Pages to print, pages to photocopy and copies — validated and
        # stored by the service; a blank one is no materials.
        data.update(_materials_from(request.POST))
        # Ticked by name. The count the budget multiplies by is derived from
        # the list rather than typed beside it, so the two cannot disagree.
        invited_school_ids = [
            s.strip() for s in request.POST.getlist("invited_school_ids") if s.strip()
        ]
        if invited_school_ids:
            data["invitedSchoolIds"] = invited_school_ids
            data["schoolsInvited"] = str(len(invited_school_ids))
        try:
            if activity_type == "training":
                from apps.activity_catalogue.availability import (
                    CLUSTER,
                    validate_priority_training_selection,
                )

                selected_training = validate_priority_training_selection(
                    catalogue_item_id,
                    planning_context=CLUSTER,
                )
                # Catalogue authority wins over any stale or crafted hidden
                # input. "Other" courses deliberately save no SSA dimension.
                data["focusIntervention"] = selected_training["ssaIntervention"] or None
            created = ClusterActionPlannerService.schedule_activity(data, request.user)
            from apps.frontend.views.planning_views import (
                _calendar_url_for_scheduled_date,
                _my_plan_url_for_scheduled_date,
                _scheduled_into_own_plan,
            )

            lands_here, owner_name = _scheduled_into_own_plan(created, request.user)
            noun = (
                "Cluster training" if activity_type == "training" else "Cluster meeting"
            )
            if lands_here:
                messages.success(
                    request, f"{noun} scheduled. It is on your My Plan for that week."
                )
                plan_url = _my_plan_url_for_scheduled_date(scheduled_date_str)
            else:
                messages.success(
                    request,
                    f"{noun} scheduled. It is on {owner_name}'s My Plan; you will "
                    "find it on the Calendar.",
                )
                plan_url = _calendar_url_for_scheduled_date(scheduled_date_str)
            if request.headers.get("HX-Request") == "true":
                from apps.frontend.views.planning_views import _saved_without_leaving

                msg = (
                    f"{noun} scheduled successfully."
                    if lands_here
                    else f"{noun} scheduled. It is on {owner_name}'s My Plan; you will find it on the Calendar."
                )
                response = _saved_without_leaving(
                    msg,
                    plan_url=plan_url,
                    plan_link_label="Open in My Plan"
                    if lands_here
                    else "Open in Calendar",
                )
                response["HX-Trigger"] = json.dumps(
                    {"close-drawer": True, "refresh-clusters": True}
                )
                return response
            return redirect(plan_url)
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
                retry_invited = set(invited_school_ids) or {s.id for s in retry_members}
                training_options = (
                    training_activity_options(
                        planning_context=CLUSTER,
                        cluster=selected_cluster,
                    )
                    if activity_type == "training"
                    else []
                )

                cost_preview = None
                if selected_cluster:
                    try:
                        cost_preview = ClusterCostPreviewService.preview_cost(
                            activity_type,
                            participants,
                            selected_cluster.id,
                            materials=_materials_from(request.POST),
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
                    **{
                        form_key: request.POST.get(form_key, "").strip()
                        for form_key, _payload_key in MATERIALS_FIELDS
                    },
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
    # CLUSTER_ASSIGN, not "can this person schedule". Defining a cluster is
    # registry work — the same question `cluster_overview`'s `canCreate` flag
    # already answers with this permission — while scheduling its meetings is
    # execution. Borrowing the scheduling predicate tied the two together, so
    # narrowing who may plan field work silently removed cluster creation from
    # the Admin who owns the registry.
    if (
        Permission.CLUSTER_ASSIGN.value
        not in resolve_user_scope(request.user).permissions
    ):
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

    from apps.clusters.models import Cluster as _Cluster
    from apps.clusters.services import cluster_delete_block, may_edit_cluster_profile

    _cluster_row = _Cluster.objects.filter(
        id=cluster_id, deleted_at__isnull=True
    ).first()
    _attach_planning_badges(request, schools)
    context = {
        "cluster": detail,
        # The reason the Delete control is inert, shown beside it — a cluster
        # that has hosted work is kept, and the page says so before a press.
        "delete_block": cluster_delete_block(_cluster_row) if _cluster_row else None,
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
        )
        and bool(_cluster_row and may_edit_cluster_profile(_cluster_row, request.user)),
        # Cluster-level planning and school-level scheduling use the same
        # permission checks as the destinations behind their controls. This
        # keeps the profile useful as a planning launch point without showing
        # actions that will answer 403 for oversight-only roles.
        # Cluster meetings and trainings are the cluster owner's programme;
        # the page permission alone let the Country Director see buttons the
        # drawer then refused (apps.planning.visit_requests).
        "can_plan_clusters": RolePermissionService.can_view_page(
            request.user, "planning"
        )
        and RolePermissionService.can_schedule_activity(request.user),
        # Whoever the drawer opens for: planners for their programme, the
        # visit roles for any school (owner, 2026-09-21), the Accountant to
        # ask — see RolePermissionService.can_open_schedule_drawer.
        "can_schedule": RolePermissionService.can_open_schedule_drawer(request.user),
        # Bulk scheduling is a planner's act, not a requester's (owner,
        # 2026-09-21): one press writes activities at five or more schools,
        # and a visit request is decided one school at a time.
        "can_bulk_schedule": RolePermissionService.can_schedule_activity(request.user),
        # Responsible, Visit, Training / Cluster and Partner Workflow columns
        # (owner, 2026-09-23), from the rows cluster_schools() already carries.
        "support_rule": support_visibility_enabled(request.user),
    }
    context.update(_catchment_context(request.user, _cluster_row))
    return render(request, "pages/clusters/detail.html", context)


def _catchment_context(user, cluster) -> dict:
    """The districts a cluster serves, and its members outside them."""
    if cluster is None:
        return {}
    from apps.clusters.catchment import active_on, may_manage_catchments
    from apps.clusters.models import ClusterServiceDistrict

    rows = list(
        ClusterServiceDistrict.objects.filter(cluster=cluster)
        .select_related("district")
        .order_by("-active", "relationship_type", "district__name")
    )
    in_force = {
        r.district_id
        for r in ClusterServiceDistrict.objects.filter(active_on(), cluster=cluster)
    } | {cluster.district_id}
    outside = list(
        School.objects.filter(cluster_id=cluster.id, deleted_at__isnull=True)
        .exclude(district_id__in=in_force)
        .select_related("district")
        .order_by("name")[:50]
    )
    return {
        "catchment_rows": rows,
        "catchment_outside_members": outside,
        "can_manage_catchments": may_manage_catchments(user),
    }


@require_page_permission("cluster_detail")
def cluster_catchment_drawer_view(request, cluster_id):
    """Approve a neighbouring district for a cluster (CD, Admin)."""
    from datetime import date as _date

    from apps.clusters.catchment import (
        approve_neighbouring_district,
        country_of_district,
        may_manage_catchments,
    )
    from apps.clusters.models import ClusterServiceDistrict
    from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

    if not may_manage_catchments(request.user):
        return HttpResponseForbidden(
            "Only a Country Director or Admin approves the districts a cluster serves."
        )
    cluster = get_scoped_object_or_404(
        Cluster.objects.select_related("district__region"),
        request.user,
        id=cluster_id,
        deleted_at__isnull=True,
    )
    served = set(
        ClusterServiceDistrict.objects.filter(cluster=cluster, active=True).values_list(
            "district_id", flat=True
        )
    ) | {cluster.district_id}
    country = country_of_district(cluster.district)
    districts = (
        District.objects.filter(region__country=country)
        .exclude(id__in=served)
        .select_related("region")
        .order_by("name")
    )

    def drawer(error=None, posted=None):
        return render(
            request,
            "partials/clusters/catchment_drawer.html",
            {
                "cluster": cluster,
                "districts": districts,
                "validation_error": error,
                "posted": posted or {},
                "today": _date.today().isoformat(),
                "drawer_size": "md",
            },
        )

    if request.method == "POST":
        posted = {
            "district_id": request.POST.get("district_id", "").strip(),
            "reason": request.POST.get("reason", "").strip(),
            "effective_from": request.POST.get("effective_from", "").strip(),
            "effective_to": request.POST.get("effective_to", "").strip(),
        }
        try:
            start = (
                _date.fromisoformat(posted["effective_from"])
                if posted["effective_from"]
                else None
            )
            end = (
                _date.fromisoformat(posted["effective_to"])
                if posted["effective_to"]
                else None
            )
        except ValueError:
            return drawer("Enter the dates as calendar dates.", posted)
        try:
            row = approve_neighbouring_district(
                cluster.id,
                posted["district_id"],
                request.user,
                reason=posted["reason"],
                effective_from=start,
                effective_to=end,
            )
        except (BadRequest, Forbidden, NotFoundError) as exc:
            return drawer(str(getattr(exc, "detail", exc)), posted)
        messages.success(
            request,
            f"{cluster.name} now serves {row.district.name} as a neighbouring district.",
        )
        response = HttpResponse(
            f'<script>window.location.href = "/clusters/{cluster.id}";</script>'
        )
        response["HX-Trigger"] = "close-drawer"
        return response
    return drawer()


@require_page_permission("cluster_detail")
def cluster_catchment_end_view(request, cluster_id, catchment_id):
    """End an approved neighbouring district (CD, Admin)."""
    from apps.clusters.catchment import end_catchment, may_manage_catchments
    from apps.clusters.models import ClusterServiceDistrict
    from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

    if not may_manage_catchments(request.user):
        return HttpResponseForbidden(
            "Only a Country Director or Admin changes the districts a cluster serves."
        )
    cluster = get_scoped_object_or_404(
        Cluster, request.user, id=cluster_id, deleted_at__isnull=True
    )
    row = get_object_or_404(
        ClusterServiceDistrict.objects.select_related("district"),
        id=catchment_id,
        cluster=cluster,
    )
    if request.method == "POST":
        try:
            end_catchment(row.id, request.user, reason=request.POST.get("reason", ""))
        except (BadRequest, Forbidden, NotFoundError) as exc:
            return render(
                request,
                "partials/clusters/catchment_end_drawer.html",
                {
                    "cluster": cluster,
                    "row": row,
                    "validation_error": str(getattr(exc, "detail", exc)),
                    "drawer_size": "sm",
                },
            )
        messages.success(
            request,
            f"{cluster.name} no longer serves {row.district.name}. Schools already "
            "in the cluster from there are listed for review.",
        )
        response = HttpResponse(
            f'<script>window.location.href = "/clusters/{cluster.id}";</script>'
        )
        response["HX-Trigger"] = "close-drawer"
        return response
    return render(
        request,
        "partials/clusters/catchment_end_drawer.html",
        {"cluster": cluster, "row": row, "drawer_size": "sm"},
    )


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
    member_schools = (
        list(active_schools(selected_cluster.id)) if selected_cluster else []
    )
    raw_invited = [
        s.strip() for s in request.GET.getlist("invited_school_ids") if s.strip()
    ]
    member_ids = {s.id for s in member_schools}
    invited_ids = [s for s in raw_invited if s in member_ids]
    # First open, and any re-render that has not been through the list yet,
    # invites the whole cluster — which is what the old number defaulted to —
    # except its Partner-supported schools, which are invited by name only
    # (owner, 2026-09-23); a school_id on the request pre-ticks that one.
    from apps.planning.partner_school_policy import partner_supported_members

    supported = partner_supported_members([s.id for s in member_schools], request.user)
    if not raw_invited:
        chosen_school = request.GET.get("school_id", "").strip()
        invited_ids = [
            s.id
            for s in member_schools
            if s.id not in supported or chosen_school in (s.id, s.school_id)
        ]
    invited_id_set = set(invited_ids)
    # Who the planner is inviting from each school. The drawer re-renders on
    # every cluster / activity-type change, so these come back from the form
    # rather than resetting to the defaults each time.
    per_school_defaults = (
        ("teachers_per_school", 2 if activity_type == "training" else 0),
        ("leaders_per_school", 0 if activity_type == "training" else 2),
        ("other_per_school", 0),
    )
    # The defaults are for a first open only. Once the form has been through
    # a re-render (a cluster or activity-type change), a field the planner
    # cleared is zero — not the default quietly put back (owner, 2026-09-15:
    # "leaving a field blank should automatically translate to zero").
    per_school_submitted = any(
        key in request.GET for key, _default in per_school_defaults
    )
    per_school_categories = {}
    for key, default in per_school_defaults:
        raw = request.GET.get(key, "").strip()
        if raw.isdigit():
            per_school_categories[key] = int(raw)
        else:
            per_school_categories[key] = 0 if per_school_submitted else default
    participants_per_school = sum(per_school_categories.values())
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
            activity_type,
            participants,
            selected_cluster.id,
            materials=_materials_from(request.GET),
        )

    from apps.activity_catalogue.availability import (
        CLUSTER,
        training_activity_options,
    )

    training_options = (
        training_activity_options(
            planning_context=CLUSTER,
            cluster=selected_cluster,
        )
        if activity_type == "training"
        else []
    )
    selectable_training_ids = {option["id"] for option in training_options}
    selected_training_activity_id = request.GET.get("catalogue_item_id", "").strip()
    if selected_training_activity_id not in selectable_training_ids:
        selected_training_activity_id = ""

    selected_focus_intervention = request.GET.get("focus_intervention", "").strip()
    if selected_focus_intervention not in SsaIntervention.values:
        selected_focus_intervention = (
            weakest_interventions[0]["intervention"] if weakest_interventions else ""
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
        # Materials as typed, so a re-render keeps them.
        **{
            form_key: request.GET.get(form_key, "").strip()
            for form_key, _payload_key in MATERIALS_FIELDS
        },
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
                "partner_name": supported.get(s.id, ""),
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
    # The districts this cluster serves: its own, and any approved
    # neighbouring district (owner, 2026-09-15).
    from django.db.models import Q

    from apps.clusters.catchment import active_on
    from apps.clusters.models import ClusterServiceDistrict

    served_ids = {cluster.district_id} | set(
        ClusterServiceDistrict.objects.filter(
            active_on(), cluster_id=cluster.id
        ).values_list("district_id", flat=True)
    )
    served_district_q = Q(district_id__in=served_ids)
    from apps.core.scoping import owner_ids

    scope = resolve_user_scope(request.user)
    if (
        not scope.country_scope
        and not scope.can_view_summary_only
        and cluster.responsible_staff_id in owner_ids(request.user)
    ):
        # Owners may group their own schools across districts; the membership
        # service still enforces portfolio ownership and country boundaries.
        # Only for a field owner, whose pool below is their direct portfolio:
        # a country-scope pool is every unclustered school, and the served
        # districts are what keep it to this cluster's area (and country).
        served_district_q = Q()
    if request.method == "POST":
        school_ids = request.POST.getlist("school_ids")
        user = request.user

        assigned_schools = []
        skipped_schools = []
        for sid in school_ids:
            # Allow assignment if school is in a covered sub-county OR (for
            # district-level clusters with no covered sub-counties) in the
            # cluster's district.
            # Direct portfolio only. Adding a school to a cluster edits the
            # school record, so a supervisor may not do it for a CCEO's school
            # — the same rule `assign_school` and the picker apply.
            writable = or_empty(
                direct_portfolio_schools(resolve_user_scope(user)), School
            )
            school = writable.filter(
                served_district_q, id=sid, deleted_at__isnull=True
            ).first()
            if not school:
                continue
            # The drawer lists unclustered schools only; a school clustered
            # since it was rendered is skipped rather than moved, so the
            # bulk path can never double-cluster (owner, 2026-09-15).
            if school.cluster_id or school.cluster_status == "clustered":
                skipped_schools.append(school.name)
                continue
            # Audited inside set_school_cluster_membership() (the
            # canonical service assign_school_to_cluster delegates to)
            # — not duplicated here.
            assign_school_to_cluster(school.school_id, {"clusterId": cluster.id}, user)
            assigned_schools.append(school.name)

        msg = (
            f"Successfully assigned {len(assigned_schools)} schools to {cluster.name}."
        )
        if skipped_schools:
            msg += (
                f" Skipped {len(skipped_schools)} already-clustered: "
                f"{', '.join(skipped_schools)}."
            )
        response = render(
            request, "partials/schools/toast_success.html", {"message": msg}
        )
        response["HX-Trigger"] = (
            f"cluster-schools-updated-{cluster.id}, schools-updated"
        )
        return response

    # GET method — bring out all unclustered schools in the district where the cluster is.
    if scope.country_scope or scope.can_view_summary_only:
        unassigned_schools = School.objects.filter(
            served_district_q,
            cluster_status="unclustered",
            deleted_at__isnull=True,
        )
    else:
        writable = or_empty(direct_portfolio_schools(scope), School)
        unassigned_schools = writable.filter(
            served_district_q,
            cluster_status="unclustered",
            deleted_at__isnull=True,
        )
    unassigned_schools = unassigned_schools.select_related("sub_county").order_by(
        "sub_county__name", "name"
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

    # 3. Ultimate fallback: all active CCEOs and PLs. A QuerySet like the
    # branches above: the edit drawer unions it with the recorded owner as a
    # `.values("id")` subquery, which a filtered Python list cannot answer.
    return (
        StaffProfile.objects.filter(
            user__is_active=True,
            user__roles__overlap=["CCEO", "Program Lead", "ProgramLead"],
        )
        .select_related("user")
        .order_by("user__name")
    )


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
    from django.db.models import Q

    cluster = get_object_or_404(
        cluster_queryset(resolve_user_scope(request.user)), id=cluster_id
    )
    from apps.clusters.services import may_edit_cluster_profile

    if not may_edit_cluster_profile(cluster, request.user):
        return HttpResponseForbidden("Only the cluster owner can edit this profile.")
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
    # Keep a recorded owner selectable even when they have no school or
    # geography assignment in the cluster's district.
    staff = (
        StaffProfile.objects.filter(
            Q(id__in=staff.values("id"))
            | Q(id=cluster.responsible_staff_id)
            | Q(user_id=cluster.responsible_staff_id)
        )
        .select_related("user")
        .order_by("user__name")
    )
    # The schools in the cluster, each ticked (owner, 2026-09-15): untick a
    # school added by mistake and save, and it goes back to unclustered.
    from apps.clusters.services import active_schools

    context = {
        "cluster": cluster,
        "districts": districts,
        "sub_counties_json": json.dumps(sub_counties_list),
        "covered_ids": covered_ids,
        "staff": staff,
        "member_schools": list(active_schools(cluster.id)),
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
                removed = _remove_unticked_members(request, cluster_id)
                messages.success(
                    request,
                    f"Successfully updated cluster '{name}'."
                    + (
                        f" Removed {len(removed)} school"
                        f"{'' if len(removed) == 1 else 's'}: {', '.join(removed)}."
                        if removed
                        else ""
                    ),
                )
            except Exception as e:
                messages.error(request, f"Failed to update cluster: {e}")
        else:
            messages.error(request, "Failed to update cluster: missing fields.")

    return redirect("/clusters")


def _remove_unticked_members(request, cluster_id: str) -> list[str]:
    """Take out every member school the edit drawer left unticked.

    Only when the drawer sent its member list (``manage_members``): an API
    client or an older form that never showed the schools must not empty
    the cluster by omission. Each removal goes through the canonical
    service, so the ownership rule and the audit trail are the roster's.
    """
    if not request.POST.get("manage_members"):
        return []
    from apps.clusters.services import active_schools, remove_school_from_cluster

    kept = {s.strip() for s in request.POST.getlist("member_school_ids") if s.strip()}
    removed = []
    for school in list(active_schools(cluster_id)):
        if school.id in kept:
            continue
        remove_school_from_cluster(school.id, cluster_id, request.user)
        removed.append(school.name)
    return removed


@require_page_permission("planning")
def remove_school_from_cluster_view(request, cluster_id, school_id):
    """Take one school out of a cluster from its roster (owner, 2026-09-15).

    The service decides who may: the school and the cluster must both be in
    the caller's direct portfolio. On success the cluster cards re-fetch
    their rosters (the same trigger the add-schools drawer fires) and the
    profile page reloads itself.
    """
    from django.http import HttpResponse, HttpResponseNotAllowed

    from apps.clusters.services import remove_school_from_cluster
    from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    is_htmx = bool(request.headers.get("HX-Request"))
    try:
        result = remove_school_from_cluster(school_id, cluster_id, request.user)
    except (BadRequest, Forbidden, NotFoundError) as exc:
        if is_htmx:
            return HttpResponse(
                f'<div class="edify-note" data-tone="danger" role="alert">'
                f'<p class="edify-note__body">{escape(str(exc))}</p></div>',
                status=400,
            )
        messages.error(request, str(exc))
        # A fixed destination: the id in the path is the caller's, and a
        # redirect built from it is an open-redirect finding (CodeQL, PR
        # #104). The list page shows the message either way.
        return redirect("/clusters")
    message = f"Removed {result['schoolId']} from the cluster; it is unclustered again."
    if is_htmx:
        response = render(
            request, "partials/schools/toast_success.html", {"message": message}
        )
        response["HX-Trigger"] = (
            f"cluster-schools-updated-{cluster_id}, schools-updated"
        )
        return response
    messages.success(request, message)
    # Back to the profile of the cluster the service resolved -- its own id
    # from the database, reversed through the route, never the path value.
    return redirect("frontend:cluster_detail", cluster_id=result["clusterId"])


@require_page_permission("planning")
def delete_cluster_view(request, cluster_id):
    """Delete a cluster from its profile (owner, 2026-09-11).

    The service decides: a cluster that has hosted a meeting or training is
    refused with the reason, and the page shows that reason before the button
    is ever pressed (see ``delete_block`` on the profile). A deleted cluster's
    schools are released to ``unclustered``, ready for a new cluster.
    """
    from django.http import HttpResponse, HttpResponseNotAllowed

    from apps.clusters.services import delete_cluster
    from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    is_htmx = bool(request.headers.get("HX-Request"))
    try:
        result = delete_cluster(cluster_id, request.user)
    except (BadRequest, Forbidden, NotFoundError) as exc:
        if is_htmx:
            return HttpResponse(
                f'<div class="edify-note" data-tone="danger" role="alert">'
                f'<p class="edify-note__body">{escape(str(exc))}</p></div>',
                status=400,
            )
        messages.error(request, str(exc))
        return redirect(f"/clusters/{cluster_id}")
    released = result["schoolsReleased"]
    messages.success(
        request,
        f"Deleted cluster '{result['name']}'. {released} school"
        f"{'s' if released != 1 else ''} released and ready for a new cluster.",
    )
    if is_htmx:
        response = HttpResponse(status=200)
        response["HX-Redirect"] = "/clusters"
        return response
    return redirect("/clusters")


@require_page_permission("cluster_detail")
def cluster_bulk_schedule_drawer_view(request, cluster_id):
    """A day of visits across one to five of a cluster's schools.

    Bulk scheduling happens from a cluster and nowhere else (owner,
    2026-09-21), and takes at most five schools for a day — five was first
    read as a floor, and a floor left a planner with four schools no door at
    all (owner, 2026-09-22). It offers only the four purposes that are the
    same errand at every school on the route. Every rule lives in
    apps.planning.cluster_bulk_scheduling; this view opens the drawer and
    hands the selection to it.
    """
    from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
    from apps.planning.cluster_bulk_scheduling import (
        CLUSTER_BULK_MAXIMUM_SCHOOLS,
        CLUSTER_BULK_VISIT_PURPOSES,
        bulk_schedule_cluster_visits,
        schedulable_members,
    )
    from apps.frontend.views.planning_views import _saved_without_leaving

    if not RolePermissionService.can_schedule_activity(request.user):
        return HttpResponseForbidden(_no_scheduling_permission_message(request.user))

    cluster = get_operational_cluster_or_404(
        request.user, id=cluster_id, deleted_at__isnull=True
    )
    selection = schedulable_members(cluster, request.user)

    def drawer(error=None, posted=None, status=200):
        return render(
            request,
            "partials/clusters/bulk_schedule_drawer.html",
            {
                "cluster": cluster,
                "selection": selection,
                "members": [member.as_dict() for member in selection.members],
                "maximum_schools": CLUSTER_BULK_MAXIMUM_SCHOOLS,
                "bulk_visit_purposes": CLUSTER_BULK_VISIT_PURPOSES,
                "validation_error": error,
                "posted": posted or {},
                "drawer_size": "md",
            },
            status=status,
        )

    if request.method != "POST":
        return drawer()

    posted = {
        "purposeOfVisit": request.POST.get("purpose_of_visit", "").strip(),
        "scheduledDate": request.POST.get("scheduled_date", "").strip(),
        "activityPurposeText": request.POST.get("activity_goal", "").strip(),
        "schoolIds": request.POST.getlist("school_ids"),
    }
    try:
        result = bulk_schedule_cluster_visits(cluster.id, posted, request.user)
    except (BadRequest, Forbidden, NotFoundError) as exc:
        return drawer(str(getattr(exc, "detail", exc)), posted, status=400)
    except Exception as exc:  # noqa: BLE001 — the service's sentence, shown as is
        return error_fragment(exc, action="Could not schedule the day", status=400)
    from apps.frontend.views.planning_views import _my_plan_url_for_scheduled_date

    return _saved_without_leaving(
        f"{result['purposeLabel']} scheduled at {result['schools']} "
        f"{result['clusterName']} schools for {result['scheduledDate']}.",
        plan_url=_my_plan_url_for_scheduled_date(result["scheduledDate"]),
        plan_link_label="Open My Plan",
    )
