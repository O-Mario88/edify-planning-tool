from apps.core.metrics import render_precomputed_metric_item
import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.utils.html import escape
from django.db import transaction
from django.views.decorators.http import require_POST
from datetime import date

from apps.core.htmx_errors import error_fragment
from apps.core.donut import build_gauge
from apps.core.permissions import (
    require_page_permission,
    get_operational_school_or_404,
)
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.core.enums import SsaIntervention
from apps.schools.models import School
from apps.geography.models import Region, District
from apps.accounts.models import StaffProfile
from apps.partners.models import Partner, PartnerAssignment
from apps.partners import services as partner_services
from apps.partners.purposes import PARTNER_VISIT_PURPOSES
from apps.activities.models import Activity
from apps.core_schools.models import (
    CorePlan,
    CoreSchoolProfile,
)
from apps.audit.services import log as audit_log
from apps.core_schools.champion_services import ChampionEligibilityService
from apps.notifications.services import WorkflowNotificationService

from apps.core_schools.core_planning_services import (
    CoreSchoolsService,
    CorePackageProgressService,
    CorePlanningService,
    CoreAssessmentService,
    CoreInterventionImpactService,
    CoreStaffPartnerPerformanceService,
    CoreRecommendationService,
    CorePackageSchedulingService,
    CoreTeamOversightService,
    build_sparkline_path,
)
from apps.core.scoping import resolve_user_scope

logger = logging.getLogger(__name__)


# How many core schools one page shows, and what a reader may choose. The
# default was 20; fifteen keeps the page easier to scan while still showing a
# useful working set on phone, tablet and desktop. Existing explicit 10/20/50
# links remain valid. Both the default and the option set are server-side: an
# unrecognised `per_page` falls back rather than becoming an unbounded query.
CORE_PAGE_SIZES = (10, 15, 20, 50)
CORE_PAGE_SIZE_DEFAULT = 15


def _core_page_size(request) -> int:
    raw = str(request.GET.get("per_page", "")).strip()
    if raw.isdigit() and int(raw) in CORE_PAGE_SIZES:
        return int(raw)
    return CORE_PAGE_SIZE_DEFAULT


@require_page_permission("core_schools")
def core_schools_view(request):
    """Core Schools planning main dashboard view."""
    fy = request.GET.get("fy", "2026")

    # 1. Filters
    filters = {
        "fy": fy,
        "q": request.GET.get("q", "").strip(),
        "region": request.GET.get("region", "All"),
        "district": request.GET.get("district", "All"),
        "staff": request.GET.get("staff", "All"),
        "partner": request.GET.get("partner", "All"),
        "school_type_filter": request.GET.get("school_type_filter", "All"),
        "ssa_status": request.GET.get("ssa_status", "All"),
        "partner_assigned": request.GET.get("partner_assigned", "All"),
    }

    # 2. Scoped core schools list.
    #
    # Two lenses, never mixed. `direct` is the operational list and carries
    # every write control on the page; `oversight` is a supervisor's
    # supervisees' core schools, read-only, and reachable only when they have
    # some. A lens the user cannot hold falls back rather than 404s, so a
    # bookmarked ?lens=oversight from a former supervisor is harmless.
    scope = resolve_user_scope(request.user)
    has_team_core = bool(
        CoreSchoolsService.base_queryset(request.user, lens="oversight")[0].exists()
    )
    lens = "oversight" if request.GET.get("lens") == "oversight" else "direct"
    if lens == "oversight" and not has_team_core:
        lens = "direct"

    core_schools_qs = CoreSchoolsService.get_core_schools(
        request.user, filters, lens=lens
    )

    # 3. Paginate the core schools dataset — server-side, bounded.
    from django.core.paginator import Paginator

    page_num = request.GET.get("page", 1)
    per_page = _core_page_size(request)
    paginator = Paginator(core_schools_qs, per_page)
    page_obj = paginator.get_page(page_num)
    pages_list = list(
        page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=1, on_ends=1
        )
    )

    # 4. Retrieve service-processed context
    matrix_rows = CorePackageProgressService.get_matrix_data(page_obj.object_list, fy)
    oversight_rows = (
        CoreTeamOversightService.build_rows(matrix_rows, fy)
        if lens == "oversight"
        else []
    )
    planning_queue = CorePlanningService.get_planning_queue(page_obj.object_list, fy)
    intervention_impact = CoreInterventionImpactService.get_intervention_impact(
        core_schools_qs, fy
    )
    perf_insights = CoreStaffPartnerPerformanceService.get_staff_vs_partner_performance(
        core_schools_qs, fy
    )
    perf_insights["intervention_comparison"] = (
        CoreStaffPartnerPerformanceService.get_intervention_comparison_rows(
            core_schools_qs, fy
        )
    )
    reco_data = CoreRecommendationService.get_recommendation_card(core_schools_qs)

    # 4. KPI Strip Metrics
    total_core = core_schools_qs.count()
    ready_core = core_schools_qs.filter(current_fy_ssa_status="done").count()
    avg_score = CoreAssessmentService.get_average_score(core_schools_qs)
    overall_trend = CoreAssessmentService.get_monthly_trend(core_schools_qs)
    trend_values = [t["avg"] for t in overall_trend]
    perf_insights["overall_trend"] = overall_trend
    perf_insights["overall_trend_path"] = (
        build_sparkline_path(trend_values, width=100, height=50, padding=3)
        if trend_values
        else ""
    )
    # Latest-period summary panel for the full-width tracker: real verified
    # assessment periods only — no fabricated progression.
    if overall_trend:
        first, latest = overall_trend[0], overall_trend[-1]
        change = round(latest["avg"] - first["avg"], 1)
        perf_insights["trend_summary"] = {
            "latest_label": latest["label"],
            "latest_avg": latest["avg"],
            "baseline_label": first["label"],
            "change": change,
            "direction": "Improving"
            if change > 0
            else ("Declining" if change < 0 else "Stable"),
            "assessments": latest["n"],
            "periods": len(overall_trend),
        }
    else:
        perf_insights["trend_summary"] = None

    delta_points = perf_insights["delta_points"]

    visits_scheduled = (
        Activity.objects.filter(
            school__in=core_schools_qs,
            activity_type="core_visit",
            fy=fy,
            deleted_at__isnull=True,
        )
        .exclude(status="cancelled")
        .count()
    )

    trainings_scheduled = (
        Activity.objects.filter(
            school__in=core_schools_qs,
            activity_type="core_training",
            fy=fy,
            deleted_at__isnull=True,
        )
        .exclude(status="cancelled")
        .count()
    )

    total_target = total_core * 4
    regions_covered = core_schools_qs.values("region").distinct().count()
    total_regions = Region.objects.count()

    kpi_strip_items = [
        render_precomputed_metric_item(
            "frontend_views_core_schools_views_total_core_schools",
            f"{total_core}",
            icon="school",
            variant="primary",
        ),
        render_precomputed_metric_item(
            "frontend_views_core_schools_views_core_schools_ready_for_planning",
            f"{ready_core}",
            helper=f"{int((ready_core/total_core)*100) if total_core else 0}% of core",
            icon="check",
            variant="warning",
        ),
        render_precomputed_metric_item(
            "frontend_views_core_schools_views_avg_core_assessment_score",
            f"{round(avg_score, 1)}/10",
            icon="trending-up",
            variant="success",
        ),
        render_precomputed_metric_item(
            "frontend_views_core_schools_views_visits_scheduled",
            f"{visits_scheduled} / {total_target}",
            helper=f"{int((visits_scheduled/total_target)*100) if total_target else 0}% complete",
            icon="calendar",
            variant="info",
        ),
        render_precomputed_metric_item(
            "frontend_views_core_schools_views_trainings_scheduled",
            f"{trainings_scheduled} / {total_target}",
            helper=f"{int((trainings_scheduled/total_target)*100) if total_target else 0}% complete",
            icon="calendar",
            variant="info",
        ),
        render_precomputed_metric_item(
            "frontend_views_core_schools_views_staff_vs_partner_performance_delta",
            f"{'+' if delta_points >= 0 else ''}{delta_points}"
            if delta_points is not None
            else "—",
            helper=f"score points · {'Staff' if delta_points >= 0 else 'Partner'} ahead"
            if delta_points is not None
            else "No paired SSA cycles yet",
            icon="chart",
            variant="primary",
        ),
        render_precomputed_metric_item(
            "frontend_views_core_schools_views_regions_covered",
            f"{regions_covered} / {total_regions}",
            helper=f"{int((regions_covered/total_regions)*100) if total_regions else 0}% coverage",
            icon="target",
            variant="success",
        ),
    ]

    # Dropdowns Options
    #
    # Scoped to the core schools this page is actually showing. The district
    # list used to be narrowed by the Region control; with Region gone, the
    # narrowing comes from the schools themselves, which is stricter — an
    # option only exists if results can come from it — and needs no second
    # control to stay correct per role.
    _core_district_ids = core_schools_qs.values("district_id")
    regions = Region.objects.all().order_by("name")
    districts = (
        District.objects.filter(id__in=_core_district_ids).distinct().order_by("name")
    )
    # Owners of the core schools in view, not every staff record in the system.
    staff_members = (
        StaffProfile.objects.filter(
            user_id__in=core_schools_qs.exclude(account_owner_id__isnull=True).values(
                "account_owner_id"
            )
        )
        .select_related("user")
        .order_by("user__name")
    )
    partners = (
        Partner.objects.filter(
            id__in=PartnerAssignment.objects.filter(school__school_type="core").values(
                "partner_id"
            )
        )
        .distinct()
        .order_by("name")
    )

    context = {
        "fy": fy,
        "selected_fy": fy,
        "selected_region": filters["region"],
        "selected_district": filters["district"],
        "selected_staff": filters["staff"],
        "selected_partner": filters["partner"],
        "selected_school_type": filters["school_type_filter"],
        "selected_ssa_status": filters["ssa_status"],
        "selected_partner_assigned": filters["partner_assigned"],
        "regions": regions,
        "districts": districts,
        "staff_members": staff_members,
        "partners": partners,
        "kpi_strip_items": kpi_strip_items,
        "matrix_rows": matrix_rows,
        "oversight_rows": oversight_rows,
        "lens": lens,
        "is_oversight_lens": lens == "oversight",
        "has_team_core": has_team_core,
        "per_page": per_page,
        "page_size_options": CORE_PAGE_SIZES,
        "supervised_count": len(scope.supervised_staff_ids or []),
        "planning_queue": planning_queue,
        "intervention_impact": intervention_impact,
        "perf_insights": perf_insights,
        "reco_data": reco_data,
        "page_obj": page_obj,
        "is_paginated": page_obj.has_other_pages(),
        "pages_list": pages_list,
        "base_template": "layouts/blank.html"
        if request.headers.get("HX-Request") == "true"
        else "layouts/shell.html",
        # The page had no search control of any kind, so the top bar showed the
        # generic global form that searches somewhere else entirely. It now
        # drives this matrix, and carries the filter row along so a query
        # narrows the current view rather than resetting it.
        "topbar_search": {
            "placeholder": "Search Core Schools…",
            "label": "Search Core Schools by name, ID, district or owner",
            "name": "q",
            "value": filters["q"],
            "hx_get": "/core-schools",
            # The oversight lens has no `#core-schools-table-container` — that
            # id belongs to the operational matrix. Searching there swapped a
            # matrix partial into an element that was not on the page, so the
            # query appeared to do nothing. Whole-container swap instead, which
            # is what the filter row already does.
            "hx_target": (
                "#core-schools-main-container"
                if lens == "oversight"
                else "#core-schools-table-container"
            ),
            "hx_swap": "outerHTML" if lens == "oversight" else "innerHTML",
            "hx_trigger": "keyup changed delay:250ms, search",
            "hx_include": "#core-filters-form",
        },
    }

    if (
        request.headers.get("HX-Target") == "core-schools-table-container"
        and lens != "oversight"
    ):
        return render(request, "partials/core_schools/matrix_table.html", context)

    return render(request, "pages/core_schools/index.html", context)


@require_page_permission("core_schools")
def core_schedule_visit_drawer(request):
    """Renders schedule core visit drawer."""
    school_id = request.GET.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)

    (
        school.ssa_records.filter(deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )
    # §17 — four weakest verified interventions, 2 → Partner, 2 → Staff.
    from apps.core_schools.core_planning_services import (
        CoreInterventionRecommendationService,
    )

    reco = CoreInterventionRecommendationService.recommend(school)
    recommendations = reco["rows"]
    from apps.activity_catalogue.services import recommend_activities

    catalogue_result = recommend_activities(
        school=school,
        principal=request.user,
        executor_type="staff",
        limit=3,
    )
    visit_catalogue_items = [
        row
        for row in [
            *catalogue_result["primary"],
            *catalogue_result["otherEligible"],
        ]
        if row["stableCode"] == "CORE_SCHOOL_FOLLOWUP_VISIT"
    ]

    staff_members = (
        StaffProfile.objects.all().select_related("user").order_by("user__name")
    )
    partners = Partner.objects.all().order_by("name")

    fy = get_operational_fy()
    plan = CorePlan.objects.filter(school_id=school_id, fy=fy).first()
    available_visit_slots = (
        CorePackageSchedulingService.available_options(plan, "visit") if plan else []
    )

    context = {
        "school": school,
        "recommendations": recommendations,
        "staff_members": staff_members,
        "partners": partners,
        "next_visit_seq": available_visit_slots[0]["sequence"]
        if available_visit_slots
        else None,
        "available_visit_slots": available_visit_slots,
        "interventions": SsaIntervention.choices,
        "catalogue_items": visit_catalogue_items,
    }
    return render(request, "partials/core_schools/schedule_visit_drawer.html", context)


@require_POST
@require_page_permission("core_schools")
def core_schedule_visit_action(request):
    """Handles schedule visit submission."""
    school_id = request.POST.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)
    visit_seq = request.POST.get("visit_number", "1")
    scheduled_date = request.POST.get("scheduled_date")
    focus_intervention = request.POST.get("focus_intervention")
    purpose_text = request.POST.get("visit_purpose", "").strip()
    expected_outcome = request.POST.get("expected_outcome", "").strip()
    responsible_staff_id = request.POST.get("responsible_staff_id")
    partner_id = request.POST.get("assigned_partner_id")
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    source_activity_id = request.POST.get("source_activity_id", "").strip()
    if not catalogue_item_id:
        return error_fragment(
            BadRequest("Select an eligible approved Catalogue visit."),
            status=400,
        )

    try:
        visit_sequence = int(visit_seq)
        scheduled_for = date.fromisoformat(scheduled_date)
    except (TypeError, ValueError):
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Please choose a valid planned date and visit slot.</div>',
            status=400,
        )

    payload = {
        "schoolId": school_id,
        "activityType": "core_visit",
        "scheduledDate": scheduled_date,
        "focusIntervention": focus_intervention,
        "activityPurposeText": purpose_text,
        "expectedOutcome": expected_outcome,
        "responsibleStaffId": responsible_staff_id,
        "deliveryType": "partner" if partner_id else "staff",
        "catalogueItemId": catalogue_item_id,
        "requireCatalogue": True,
        "sourceActivityId": source_activity_id,
        "recommendationReason": request.POST.get("recommendation_reason", ""),
        # Omit the key entirely for staff delivery — an empty string would be
        # stamped into the budget line's partner FK and violate the constraint.
        **({"assignedPartnerId": partner_id} if partner_id else {}),
    }

    if scheduled_date:
        try:
            dt = date.fromisoformat(scheduled_date)
            payload["plannedMonth"] = dt.month
            payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
        except ValueError:
            pass

    from apps.activities.services import create as create_activity

    try:
        with transaction.atomic():
            plan = (
                CorePlan.objects.select_for_update()
                .filter(school_id=school_id, fy=get_operational_fy())
                .first()
            )
            if not plan:
                raise BadRequest("This school does not have an active core package.")
            slot = CorePackageSchedulingService.assert_can_schedule(
                plan=plan,
                school=school,
                activity_type="visit",
                sequence_number=visit_sequence,
                scheduled_for=scheduled_for,
                is_partner_delivery=bool(partner_id),
            )

            # 1. Create standard Activity in DB. The flag records that a
            # package slot was locked above — create() refuses core types
            # without it, closing the raw-POST bypass around the slot cap.
            act_data = create_activity(payload, request.user, core_slot_verified=True)

            # 2. Commit the policy-checked slot through the same service that
            # locked it, so the 4 + 4 guard and the state it protects share an
            # owner.
            CorePackageSchedulingService.commit_schedule(
                slot,
                activity_id=act_data["id"],
                scheduled_for=scheduled_date,
                scheduled_month=str(payload.get("plannedMonth")),
                scheduled_week=payload.get("plannedWeek"),
                assigned_staff_id=responsible_staff_id,
                partner_id=partner_id,
            )

            # Audit log
            audit_log(
                action="schedule_core_visit",
                subject_kind="Activity",
                subject_id=act_data["id"],
                actor_id=str(request.user.id),
                actor_role=getattr(request.user, "active_role", None),
                success=True,
            )

            # Success message & direct redirect to My Plan
            messages.success(
                request, f"Core Visit V{visit_sequence} scheduled successfully."
            )
            response = HttpResponse(
                '<script>window.location.href = "/my-plan";</script>'
            )
            response["HX-Trigger"] = "close-drawer"
            return response
    except Exception as e:
        return error_fragment(e, status=400)


@require_page_permission("core_schools")
def core_schedule_training_drawer(request):
    """Renders schedule core training drawer."""
    school_id = request.GET.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)

    (
        school.ssa_records.filter(deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )
    # §17 — four weakest verified interventions, 2 → Partner, 2 → Staff.
    from apps.core_schools.core_planning_services import (
        CoreInterventionRecommendationService,
    )

    reco = CoreInterventionRecommendationService.recommend(school)
    recommendations = reco["rows"]
    from apps.activity_catalogue.availability import (
        SCHOOL,
        training_activity_options,
    )

    # Course choice is governed by the 21-row Training Catalogue.  SSA
    # recommendations remain visible as advice, but they no longer replace
    # the user's training decision or ask them to restate its association.
    training_catalogue_items = training_activity_options(
        planning_context=SCHOOL,
        school=school,
    )

    staff_members = (
        StaffProfile.objects.all().select_related("user").order_by("user__name")
    )
    partners = Partner.objects.all().order_by("name")

    fy = get_operational_fy()
    plan = CorePlan.objects.filter(school_id=school_id, fy=fy).first()
    available_training_slots = (
        CorePackageSchedulingService.available_options(plan, "training") if plan else []
    )

    context = {
        "school": school,
        "recommendations": recommendations,
        "staff_members": staff_members,
        "partners": partners,
        "next_train_seq": available_training_slots[0]["sequence"]
        if available_training_slots
        else None,
        "available_training_slots": available_training_slots,
        "partner_visit_purposes": PARTNER_VISIT_PURPOSES,
        "interventions": SsaIntervention.choices,
        "catalogue_items": training_catalogue_items,
    }
    return render(
        request, "partials/core_schools/schedule_training_drawer.html", context
    )


@require_POST
@require_page_permission("core_schools")
def core_schedule_training_action(request):
    """Handles schedule training submission."""
    school_id = request.POST.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)
    train_seq = request.POST.get("training_number", "1")
    scheduled_date = request.POST.get("scheduled_date")
    focus_intervention = request.POST.get("focus_intervention")
    purpose_text = request.POST.get("training_purpose", "").strip()
    expected_participants = request.POST.get("expected_participants", "10")
    responsible_staff_id = request.POST.get("responsible_staff_id")
    partner_id = request.POST.get("assigned_partner_id")
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    if not catalogue_item_id:
        return error_fragment(
            BadRequest("Select an eligible approved Catalogue Training."),
            status=400,
        )
    try:
        from apps.activity_catalogue.availability import (
            SCHOOL,
            validate_priority_training_selection,
        )

        selected_training = validate_priority_training_selection(
            catalogue_item_id,
            planning_context=SCHOOL,
        )
        focus_intervention = selected_training["ssaIntervention"] or None
    except BadRequest as exc:
        return error_fragment(exc, status=400)

    try:
        training_sequence = int(train_seq)
        scheduled_for = date.fromisoformat(scheduled_date)
    except (TypeError, ValueError):
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Please choose a valid planned date and training slot.</div>',
            status=400,
        )

    payload = {
        "schoolId": school_id,
        "activityType": "core_training",
        "scheduledDate": scheduled_date,
        "focusIntervention": focus_intervention,
        "activityPurposeText": purpose_text,
        "expectedParticipants": int(expected_participants)
        if expected_participants.isdigit()
        else 10,
        "responsibleStaffId": responsible_staff_id,
        "deliveryType": "partner" if partner_id else "staff",
        "catalogueItemId": catalogue_item_id,
        "requireCatalogue": True,
        "recommendationReason": request.POST.get("recommendation_reason", ""),
        # Omit the key entirely for staff delivery — an empty string would be
        # stamped into the budget line's partner FK and violate the constraint.
        **({"assignedPartnerId": partner_id} if partner_id else {}),
    }

    if scheduled_date:
        try:
            dt = date.fromisoformat(scheduled_date)
            payload["plannedMonth"] = dt.month
            payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
        except ValueError:
            pass

    from apps.activities.services import create as create_activity

    try:
        with transaction.atomic():
            plan = (
                CorePlan.objects.select_for_update()
                .filter(school_id=school_id, fy=get_operational_fy())
                .first()
            )
            if not plan:
                raise BadRequest("This school does not have an active core package.")
            slot = CorePackageSchedulingService.assert_can_schedule(
                plan=plan,
                school=school,
                activity_type="training",
                sequence_number=training_sequence,
                scheduled_for=scheduled_for,
                is_partner_delivery=bool(partner_id),
            )

            # 1. Create standard Activity in DB. The flag records that a
            # package slot was locked above — create() refuses core types
            # without it, closing the raw-POST bypass around the slot cap.
            act_data = create_activity(payload, request.user, core_slot_verified=True)

            # 2. Commit the policy-checked slot through the same service that
            # locked it, so the 4 + 4 guard and the state it protects share an
            # owner.
            CorePackageSchedulingService.commit_schedule(
                slot,
                activity_id=act_data["id"],
                scheduled_for=scheduled_date,
                scheduled_month=str(payload.get("plannedMonth")),
                scheduled_week=payload.get("plannedWeek"),
                assigned_staff_id=responsible_staff_id,
                partner_id=partner_id,
            )

            # Audit log
            audit_log(
                action="schedule_core_training",
                subject_kind="Activity",
                subject_id=act_data["id"],
                actor_id=str(request.user.id),
                actor_role=getattr(request.user, "active_role", None),
                success=True,
            )

            # Success message & redirect to My Plan
            messages.success(
                request,
                f"Core Training T{training_sequence} scheduled successfully.",
            )
            response = HttpResponse(
                '<script>window.location.href = "/my-plan";</script>'
            )
            response["HX-Trigger"] = "close-drawer"
            return response
    except Exception as e:
        return error_fragment(e, status=400)


@require_page_permission("core_schools")
def core_assign_partner_drawer(request):
    """Renders partner assignment drawer."""
    school_id = request.GET.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)

    partners = Partner.objects.all().order_by("name")
    interventions = SsaIntervention.choices
    plan = CorePlan.objects.filter(school_id=school_id, fy=get_operational_fy()).first()
    available_visit_slots = (
        CorePackageSchedulingService.available_options(plan, "visit") if plan else []
    )
    available_training_slots = (
        CorePackageSchedulingService.available_options(plan, "training") if plan else []
    )
    from apps.activity_catalogue.services import recommend_activities

    catalogue_result = recommend_activities(
        school=school,
        principal=request.user,
        executor_type="partner",
        limit=3,
    )
    catalogue_items = [
        row
        for row in [
            *catalogue_result["primary"],
            *catalogue_result["otherEligible"],
        ]
        if row["stableCode"] == "CORE_SCHOOL_FOLLOWUP_VISIT"
    ]
    from apps.activity_catalogue.availability import (
        SCHOOL,
        training_activity_options,
    )

    training_options = training_activity_options(
        planning_context=SCHOOL,
        school=school,
        executor_type="partner",
    )

    context = {
        "school": school,
        "partners": partners,
        "interventions": interventions,
        "available_visit_slots": available_visit_slots,
        "available_training_slots": available_training_slots,
        "partner_visit_purposes": PARTNER_VISIT_PURPOSES,
        "catalogue_items": catalogue_items,
        "training_options": training_options,
    }
    return render(request, "partials/core_schools/assign_partner_drawer.html", context)


@require_page_permission("core_schools")
def core_schedule_activity_drawer(request):
    """Choose Core package support or an unrestricted general activity."""
    school_id = request.GET.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)
    plan = CorePlan.objects.filter(school_id=school_id, fy=get_operational_fy()).first()
    summary = CorePackageSchedulingService.summary(plan) if plan else None

    context = {
        "school": school,
        "package_available": bool(plan),
        "package_complete": bool(summary and summary["package_complete"]),
        "visits_remaining": max(0, (summary["visits_target"] - summary["visits"]))
        if summary
        else 0,
        "trainings_remaining": max(
            0, (summary["trainings_target"] - summary["trainings"])
        )
        if summary
        else 0,
    }
    return render(
        request, "partials/core_schools/schedule_activity_drawer.html", context
    )


@require_POST
@require_page_permission("core_schools")
def core_assign_partner_action(request):
    """Handles partner assignment submission."""
    school_id = request.POST.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)
    support_type = request.POST.get("support_type", "Visit")  # Visit | Training
    visit_training_number = request.POST.get("visit_training_number", "1")
    partner_id = request.POST.get("partner_id")
    purpose_of_visit = request.POST.get("purpose_of_visit", "").strip()
    focus_intervention = request.POST.get("focus_intervention")
    notes = request.POST.get("notes", "").strip()
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    source_activity_id = request.POST.get("source_activity_id", "").strip() or None

    partner = get_object_or_404(Partner, id=partner_id)

    try:
        with transaction.atomic():
            from apps.activity_catalogue.services import (
                get_selectable_item,
                recommend_activities,
                resolve_activity_intervention,
                validate_context,
            )
            from apps.ssa.services import latest_applicable_record

            if not catalogue_item_id:
                raise BadRequest("Select an eligible approved Catalogue Activity.")
            catalogue_item = get_selectable_item(catalogue_item_id)
            override_reason = (request.POST.get("override_reason") or "").strip()
            recommendation = None
            if support_type == "Training":
                from apps.activity_catalogue.availability import (
                    SCHOOL,
                    validate_priority_training_selection,
                )

                selected_training = validate_priority_training_selection(
                    catalogue_item_id,
                    planning_context=SCHOOL,
                )
                focus_intervention = selected_training["ssaIntervention"] or None
            else:
                recommendation_result = recommend_activities(
                    school=school,
                    principal=request.user,
                    executor_type="partner",
                    limit=3,
                )
                recommendation_rows = [
                    *recommendation_result["primary"],
                    *recommendation_result["otherEligible"],
                ]
                recommendation = next(
                    (
                        row
                        for row in recommendation_rows
                        if row["catalogueItemId"] == catalogue_item.id
                    ),
                    None,
                )
                if recommendation is None and not override_reason:
                    raise BadRequest(
                        "The selected Partner Activity is not eligible in the "
                        "current Core School SSA context."
                    )
                if (
                    recommendation
                    and focus_intervention != recommendation["targetIntervention"]
                    and not override_reason
                ):
                    raise BadRequest(
                        "The selected intervention does not match this Catalogue "
                        "recommendation."
                    )
            source_activity = (
                Activity.objects.filter(
                    id=source_activity_id,
                    school=school,
                    deleted_at__isnull=True,
                ).first()
                if source_activity_id
                else None
            )
            validate_context(
                catalogue_item,
                school=school,
                cluster=None,
                project=None,
                executor_type="partner",
            )
            focus_intervention = resolve_activity_intervention(
                catalogue_item,
                requested_intervention=focus_intervention,
                source_activity=source_activity,
            )
            if support_type == "Visit" and catalogue_item.core_slot_type != "VISIT":
                raise BadRequest("Choose the approved Core Visit Catalogue item.")
            if (
                support_type == "Training"
                and catalogue_item.activity_type != "training"
            ):
                raise BadRequest("Choose an approved Training Catalogue item.")
            if support_type not in {"Visit", "Training"}:
                raise BadRequest("Choose either a visit or training support slot.")
            from apps.partners.purposes import normalise_visit_purpose

            purpose_of_visit = normalise_visit_purpose(
                purpose_of_visit,
                for_partner=True,
                fallback_activity_type=(
                    "in_school_training"
                    if support_type == "Training"
                    else "school_visit"
                ),
            )
            activity_type = "visit" if support_type == "Visit" else "training"
            try:
                sequence_number = int(visit_training_number)
            except (TypeError, ValueError) as error:
                raise BadRequest("Choose an available support slot.") from error
            plan = (
                CorePlan.objects.select_for_update()
                .filter(school_id=school_id, fy=get_operational_fy())
                .first()
            )
            if not plan:
                raise BadRequest("This school does not have an active core package.")
            slot = CorePackageSchedulingService.assert_can_assign(
                plan=plan,
                activity_type=activity_type,
                sequence_number=sequence_number,
            )

            # 1. Create PartnerAssignment in DB
            pa = partner_services.create_assignment(
                school=school,
                partner=partner,
                assigning_staff_id=request.user.staff_profile_id,
                assignment_mode="specific_activity",
                catalogue_item=catalogue_item,
                source_ssa=latest_applicable_record(school),
                source_activity=source_activity,
                recommendation_reason=request.POST.get("recommendation_reason", "")
                or (
                    recommendation["recommendationReason"]
                    if recommendation
                    else "Authorized Core School alternative."
                ),
                override_reason=override_reason,
                catalogue_snapshot=catalogue_item.snapshot(),
                focus_intervention=focus_intervention,
                purpose_of_visit=purpose_of_visit,
                expected_activity_type=catalogue_item.workflow_kind,
                notes=notes,
                visit_number=visit_training_number if support_type == "Visit" else "",
                training_number=visit_training_number
                if support_type == "Training"
                else "",
                support_type=support_type,
            )

            # 2. Reserve the slot through the service that locked it.
            CorePackageSchedulingService.commit_assign(
                slot, partner_id=partner_id, partner_name=partner.name
            )

            # Audit log
            audit_log(
                action="assign_core_partner",
                subject_kind="PartnerAssignment",
                subject_id=pa.id,
                actor_id=str(request.user.id),
                actor_role=getattr(request.user, "active_role", None),
                success=True,
            )

            # Notify the partner's USERS. `partner_id` is a Partner
            # organisation id — it resolves to neither a User nor a
            # StaffProfile, so the service skipped it and this notification was
            # silently dropped 100% of the time. The correct lookup already
            # exists in apps/partners/signals.py.
            partner_user_ids = [
                uid
                for uid in Partner.objects.filter(id=partner_id).values_list(
                    "user_id", flat=True
                )
                if uid
            ]
            WorkflowNotificationService.trigger(
                event_type="core_school_assigned",
                category="partner",
                priority="normal",
                title="New Core School Support Assignment",
                body=f"Your organization has been assigned to support {school.name} with {support_type} {visit_training_number} focusing on {focus_intervention}.",
                context_type="School",
                context_id=school.id,
                recipients=partner_user_ids,
            )

            messages.success(
                request, f"Core support assigned to {partner.name} successfully."
            )
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response
    except Exception as e:
        return error_fragment(e, status=400)


@require_page_permission("core_schools")
def core_assessment_drawer(request):
    """Renders core assessment details drawer."""
    school_id = request.GET.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)
    latest_ssa = (
        school.ssa_records.filter(deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )

    scores = []
    if latest_ssa:
        for s in latest_ssa.scores.all().order_by("intervention"):
            label = dict(SsaIntervention.choices).get(s.intervention, s.intervention)
            scores.append(
                {
                    "label": label,
                    "score": s.score,
                    "score_pct": int(s.score * 10),
                }
            )

    context = {
        "school": school,
        "latest_ssa": latest_ssa,
        "scores": scores,
    }
    return render(request, "partials/core_schools/core_assessment_drawer.html", context)


@require_page_permission("core_schools")
def core_strategy_playbook_drawer(request):
    """Renders recommended strategy playbook drawer."""
    context = {
        "interventions": SsaIntervention.choices,
    }
    return render(
        request, "partials/core_schools/strategy_playbook_drawer.html", context
    )


@require_page_permission("core_schools")
def champion_candidates_view(request):
    """View to list Proposed Champion Candidates."""
    from apps.core.scoping import resolve_user_scope

    candidates = ChampionEligibilityService.evaluate_all()
    # Evaluation is a system-wide sweep — it must stay system-wide so a school's
    # candidacy does not depend on who happened to open this page — but the
    # *list* is a read, and reads follow the ordinary portfolio scope. It was
    # showing every candidate in the country to every CCEO.
    scope = resolve_user_scope(request.user)
    visible = set(scope.school_ids or [])
    if not scope.country_scope:
        candidates = [c for c in candidates if c["school"].id in visible]
    # Format candidates list
    formatted_candidates = []
    for c in candidates:
        formatted_candidates.append(
            {
                "school_id": c["school"].school_id,
                "name": c["school"].name,
                "district": c["school"].district.name
                if c["school"].district
                else "Unknown",
                "score": c["metrics"]["score"],
                "latest_avg": c["metrics"]["latest_avg"],
                "delta": c["metrics"]["delta"],
                "completed_slots": c["metrics"]["completed_slots"],
                "total_slots": c["metrics"]["total_slots"],
                "lowest_score": c["metrics"]["lowest_score"],
                "lowest_intervention": c["metrics"]["lowest_intervention"],
            }
        )
    context = {
        "candidates": formatted_candidates,
    }
    return render(request, "pages/core_schools/champion_candidates.html", context)


@require_page_permission("core_schools")
def champion_review_drawer(request, school_id):
    """Drawer to review details of a Potential Champion candidate."""
    school = get_operational_school_or_404(request.user, school_id=school_id)
    metrics = ChampionEligibilityService.calculate_score(school)
    metrics["gauge"] = build_gauge(
        metrics["score"], label="Graduation score", color="var(--edify-chart-blue)"
    )

    # Fetch recent SSA record
    latest_ssa = (
        school.ssa_records.filter(deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )
    scores = []
    if latest_ssa:
        for s in latest_ssa.scores.all().order_by("intervention"):
            label = dict(SsaIntervention.choices).get(s.intervention, s.intervention)
            scores.append(
                {
                    "label": label,
                    "score": s.score,
                    "score_pct": int(s.score * 10),
                }
            )

    from apps.core.scoping import may_write_school, resolve_user_scope

    context = {
        "school": school,
        "metrics": metrics,
        "latest_ssa": latest_ssa,
        "scores": scores,
        # A Programme Lead may open this drawer for a CCEO's candidate and
        # read the score; graduating the school is the owner's write.
        "may_review": may_write_school(resolve_user_scope(request.user), school),
    }
    return render(request, "partials/core_schools/champion_review_drawer.html", context)


@require_POST
@require_page_permission("core_schools")
def champion_approve_action(request, school_id):
    """Approve a core school to become champion."""
    success = ChampionEligibilityService.approve(school_id, request.user)
    if success:
        messages.success(request, "School successfully graduated to Champion Status!")
    else:
        messages.error(request, "Failed to graduate school.")
    return redirect("/core-schools")


@require_POST
@require_page_permission("core_schools")
def champion_reject_action(request, school_id):
    """Reject a champion candidacy proposal."""
    success = ChampionEligibilityService.reject(school_id, request.user)
    if success:
        messages.warning(request, "Candidacy proposal rejected.")
    else:
        messages.error(request, "Failed to reject candidacy.")
    return redirect("/core-schools")


@require_page_permission("core_schools")
def champions_list_view(request):
    """View to list official graduated Champions."""
    from apps.ssa.models import SsaRecord

    champions = (
        School.objects.filter(school_type="champion", deleted_at__isnull=True)
        .select_related("district", "region")
        .order_by("name")
    )
    champions = list(champions)

    # Was N+1: one CoreSchoolProfile query + one SsaRecord query per champion
    # school, plus unfetched district/region FKs. Batch both lookups once for
    # the whole (naturally small — graduated schools only) list instead.
    school_ids = [s.school_id for s in champions]
    profile_by_school_id = dict(
        CoreSchoolProfile.objects.filter(school_id__in=school_ids).values_list(
            "school_id", "core_start_fy"
        )
    )
    latest_ssa_by_school_id = {
        row["school_id"]: row["average_score"]
        for row in SsaRecord.objects.filter(
            school_id__in=[s.id for s in champions], deleted_at__isnull=True
        )
        .order_by("school_id", "-date_of_ssa")
        .distinct("school_id")
        .values("school_id", "average_score")
    }

    formatted_champions = [
        {
            "school_id": s.school_id,
            "name": s.name,
            "district": s.district.name if s.district else "Unknown",
            "region": s.region.name if s.region else "Unknown",
            "onboard_fy": profile_by_school_id.get(s.school_id, "Unknown"),
            "latest_avg": latest_ssa_by_school_id.get(s.id) or 0.0,
        }
        for s in champions
    ]
    context = {
        "champions": formatted_champions,
    }
    return render(request, "pages/core_schools/champions.html", context)


@require_POST
@require_page_permission("core_schools")
def core_oversight_send_action(request):
    """ "Send to <CCEO>" from Team Core Oversight.

    The only write this lens produces, and it writes an *ask*, not work. It
    creates the TeamAction, notification, to-do and audit event through the
    same `send_action` every other oversight page uses, so a core ask is
    tracked, deduplicated and auto-resolved exactly like a planning one.

    Everything is re-derived server-side. The school is re-checked against the
    sender's oversight set and the blocker is recomputed from the plan, so a
    sender who edits the form cannot address a school outside their team or
    raise a condition that is not true.
    """
    from apps.core.exceptions import Forbidden
    from apps.frontend.views.oversight_views import may_delegate
    from apps.planning.action_service import ActionError, send_action

    if not may_delegate(request.user, country=False):
        return error_fragment(
            Forbidden(
                "Sending an action here belongs to the supervisor of the team. "
                "You can read this page but not send from it."
            ),
            status=403,
        )

    school_ref = (request.POST.get("school_id") or "").strip()
    note = (request.POST.get("note") or "").strip()
    fy = (request.POST.get("fy") or get_operational_fy()).strip()

    scope = resolve_user_scope(request.user)
    oversight_qs, _ = CoreSchoolsService.base_queryset(request.user, lens="oversight")
    school = oversight_qs.filter(school_id=school_ref).first()
    if school is None:
        return error_fragment(
            Forbidden(
                "That core school is not in your team, so there is nobody here "
                "to send it to."
            ),
            status=403,
        )

    plan = CorePlan.objects.filter(school_id=school.school_id, fy=fy).first()
    if plan is None:
        return error_fragment(
            BadRequest("This school has no core plan for the selected year."),
            status=400,
        )
    # Ordered most- to least-blocking, and filtered to what the recipient can
    # actually do. CORE-01: `core_assessment_missing` is the more severe
    # blocker, but while no catalogue item can schedule a core assessment it is
    # an ask nobody can close — so it is skipped rather than sent, and the
    # supervisor still gets the package ask, which IS resolvable. Falling
    # through rather than refusing is the point: a Programme Lead must not lose
    # the ability to send an action because the platform has a configuration
    # gap in an unrelated slot.
    from apps.planning.action_service import sendable_issue_keys

    sendable = sendable_issue_keys()
    candidates = []
    if not plan.assessment_completed:
        candidates.append(
            (
                "core_assessment_missing",
                "The core assessment for this year is not on file.",
            )
        )
    if not CorePackageSchedulingService.summary(plan)["package_complete"]:
        candidates.append(
            (
                "core_package_behind",
                "The 4 visits + 4 trainings core package is not fully allocated.",
            )
        )
    actionable = [(k, d) for k, d in candidates if k in sendable]
    if not actionable:
        if candidates:
            return error_fragment(
                BadRequest(
                    "The only thing outstanding on this core package is the "
                    "core assessment, and no Activity Catalogue item can "
                    "schedule one — so there is nothing the recipient could "
                    "do with this ask. This is a Country Director "
                    "configuration gap; see Scheduling Health."
                ),
                status=400,
            )
        return error_fragment(
            BadRequest("This core package is complete, so there is nothing to send."),
            status=400,
        )
    key, detail = actionable[0]

    try:
        action = send_action(
            sender=request.user,
            school=school,
            issue={
                "key": key,
                "condition_key": f"core|{key}|school|{school.id}|{fy}",
                "severity": "critical"
                if key == "core_assessment_missing"
                else "warning",
                "detail": detail,
            },
            fy=fy,
            note=note,
            within_staff_ids=scope.supervised_staff_ids or None,
        )
    except ActionError as exc:
        return error_fragment(BadRequest(str(exc)), status=400)

    from apps.frontend.views.oversight_views import _recipient_name

    name = _recipient_name(action)
    response = HttpResponse(
        f'<p class="pill pill-success" role="status">Sent to {escape(name.rstrip("."))}. '
        "Tracked under Actions Sent.</p>"
    )
    response["HX-Trigger"] = "core-oversight-action-sent"
    return response
