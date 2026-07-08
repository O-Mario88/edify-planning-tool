import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.db import transaction
from django.db.models import Avg, F
from django.db.models.functions import TruncMonth
from django.views.decorators.http import require_POST
from datetime import date

from apps.core.permissions import require_page_permission, get_scoped_object_or_404
from apps.core.fy import get_operational_fy
from apps.core.enums import SsaIntervention
from apps.schools.models import School
from apps.geography.models import Region, District
from apps.accounts.models import StaffProfile
from apps.partners.models import Partner, PartnerAssignment
from apps.activities.models import Activity
from apps.ssa.models import SsaScore, SsaRecord
from apps.core_schools.models import (
    CorePlan,
    CoreActivitySlot,
    cslot_id,
    CoreSchoolProfile,
)
from apps.audit.services import log as audit_log
from apps.notifications.models import Notification

from apps.core_schools.core_planning_services import (
    CoreSchoolsService,
    CorePackageProgressService,
    CorePlanningService,
    CoreAssessmentService,
    CoreInterventionImpactService,
    CoreStaffPartnerPerformanceService,
    CoreRecommendationService,
)

logger = logging.getLogger(__name__)


@require_page_permission("core_schools")
def core_schools_view(request):
    """Core Schools planning main dashboard view."""
    fy = request.GET.get("fy", "2026")

    # 1. Filters
    filters = {
        "fy": fy,
        "region": request.GET.get("region", "All"),
        "district": request.GET.get("district", "All"),
        "staff": request.GET.get("staff", "All"),
        "partner": request.GET.get("partner", "All"),
        "school_type_filter": request.GET.get("school_type_filter", "All"),
        "ssa_status": request.GET.get("ssa_status", "All"),
        "partner_assigned": request.GET.get("partner_assigned", "All"),
    }

    # 2. Scoped core schools list
    core_schools_qs = CoreSchoolsService.get_core_schools(request.user, filters)

    # 3. Paginate planning core schools dataset to 10 schools per page
    from django.core.paginator import Paginator

    page_num = request.GET.get("page", 1)
    paginator = Paginator(core_schools_qs, 10)
    page_obj = paginator.get_page(page_num)
    pages_list = list(
        page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=2, on_ends=1
        )
    )

    # 4. Retrieve service-processed context
    matrix_rows = CorePackageProgressService.get_matrix_data(page_obj.object_list, fy)
    planning_queue = CorePlanningService.get_planning_queue(page_obj.object_list, fy)
    intervention_impact = CoreInterventionImpactService.get_intervention_impact(
        core_schools_qs, fy
    )
    perf_insights = CoreStaffPartnerPerformanceService.get_staff_vs_partner_performance(
        core_schools_qs, fy
    )
    reco_data = CoreRecommendationService.get_recommendation_card(core_schools_qs)

    # ── Real-data Card D/E computation (design contract: zero mock data) ──
    # Card D: Staff vs Partner average score by intervention, from CONFIRMED SSA
    # scores whose parent record was collected by staff or by a partner. No
    # fabricated fallback numbers — an intervention with no confirmed records
    # on one side simply omits that side (rendered as "—" in the template).
    interv_map = dict(SsaIntervention.choices)
    comparison_rows = (
        SsaScore.objects.filter(
            ssa_record__school__in=core_schools_qs,
            ssa_record__deleted_at__isnull=True,
            ssa_record__verification_status="confirmed",
            ssa_record__collector_type__in=["staff", "partner"],
        )
        .values("intervention", "ssa_record__collector_type")
        .annotate(avg_val=Avg("score"))
    )
    comparison_map = {}
    for row in comparison_rows:
        code = row["intervention"]
        entry = comparison_map.setdefault(
            code,
            {
                "code": code,
                "label": interv_map.get(code, code),
                "staff_pct": None,
                "partner_pct": None,
            },
        )
        pct = round(row["avg_val"] * 10)
        if row["ssa_record__collector_type"] == "staff":
            entry["staff_pct"] = pct
        else:
            entry["partner_pct"] = pct
    intervention_comparison = [
        comparison_map[code]
        for code, _ in SsaIntervention.choices
        if code in comparison_map
    ]
    perf_insights["intervention_comparison"] = intervention_comparison
    perf_insights["has_intervention_comparison"] = bool(intervention_comparison)

    # Card E: Intervention Impact Tracker — monthly average SSA score trend from
    # confirmed records for core schools in scope. Real ApexCharts line series
    # computed server-side; empty when no confirmed records exist yet.
    trend_rows = list(
        SsaRecord.objects.filter(
            school__in=core_schools_qs,
            deleted_at__isnull=True,
            verification_status="confirmed",
            average_score__isnull=False,
        )
        .annotate(month=TruncMonth("date_of_ssa"))
        .values("month")
        .annotate(avg_val=Avg("average_score"))
        .order_by("month")
    )
    has_impact_trend = bool(trend_rows)
    perf_insights["has_impact_trend"] = has_impact_trend
    perf_insights["impact_trend_chart"] = {
        "chart": {"type": "line", "toolbar": {"show": False}},
        "series": [
            {
                "name": "Avg Assessment Score",
                "data": [round(r["avg_val"] * 10) for r in trend_rows],
            }
        ],
        "xaxis": {
            "categories": [r["month"].strftime("%b %Y") for r in trend_rows],
            "labels": {
                "style": {"colors": "#94a3b8", "fontSize": "10px", "fontWeight": 500}
            },
            "axisBorder": {"show": False},
            "axisTicks": {"show": False},
        },
        "yaxis": {
            "max": 100,
            "labels": {"style": {"colors": "#94a3b8", "fontSize": "10px"}},
        },
        "colors": ["#3b82f6"],
        "stroke": {"curve": "smooth", "width": 2.5},
        "markers": {
            "size": 3,
            "colors": ["#3b82f6"],
            "strokeColors": "#ffffff",
            "strokeWidth": 2,
        },
        "grid": {"borderColor": "#f1f5f9"},
        "dataLabels": {"enabled": False},
        "tooltip": {"theme": "light"},
    }

    # 4. KPI Strip Metrics
    total_core = core_schools_qs.count()
    ready_core = core_schools_qs.filter(current_fy_ssa_status="done").count()
    avg_score = CoreAssessmentService.get_average_score(core_schools_qs)

    # Real improvement trend for the KPI strip: avg(follow_up - baseline) across
    # core plans that have both values recorded (no fabricated "vs last month").
    avg_delta_raw = CorePlan.objects.filter(
        school_id__in=core_schools_qs.values_list("school_id", flat=True),
        fy=fy,
        baseline_average__isnull=False,
        follow_up_average__isnull=False,
    ).aggregate(v=Avg(F("follow_up_average") - F("baseline_average")))["v"]
    if avg_delta_raw is None:
        avg_score_helper = "No baseline vs follow-up data yet"
    else:
        avg_delta_pp = round(avg_delta_raw * 10)
        sign = "▲" if avg_delta_pp > 0 else ("▼" if avg_delta_pp < 0 else "→")
        avg_score_helper = f"{sign} {abs(avg_delta_pp)}pp vs baseline"

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

    kpi_strip_items = [
        {
            "label": "Total Core Schools",
            "value": f"{total_core}",
            "helper": "100% of core",
            "icon": "school",
            "variant": "primary",
        },
        {
            "label": "Core Schools Ready for Planning",
            "value": f"{ready_core}",
            "helper": f"{int((ready_core/total_core)*100) if total_core else 0}% of core",
            "icon": "check",
            "variant": "warning",
        },
        {
            "label": "Avg. Core Assessment Score",
            "value": f"{int(avg_score * 10)}%",
            "helper": avg_score_helper,
            "icon": "trending-up",
            "variant": "success",
        },
        {
            "label": "Visits Scheduled",
            "value": f"{visits_scheduled} / {total_target}",
            "helper": f"{int((visits_scheduled/total_target)*100) if total_target else 0}% complete",
            "icon": "calendar",
            "variant": "info",
        },
        {
            "label": "Trainings Scheduled",
            "value": f"{trainings_scheduled} / {total_target}",
            "helper": f"{int((trainings_scheduled/total_target)*100) if total_target else 0}% complete",
            "icon": "calendar",
            "variant": "info",
        },
        {
            "label": "Staff vs Partner Performance Delta",
            "value": (
                f"{'+' if perf_insights['delta_pp'] > 0 else ''}{perf_insights['delta_pp']}pp"
                if perf_insights["has_delta_data"]
                else "—"
            ),
            "helper": (
                (
                    "Staff ahead"
                    if perf_insights["delta_pp"] > 0
                    else "Partner ahead"
                    if perf_insights["delta_pp"] < 0
                    else "Even"
                )
                if perf_insights["has_delta_data"]
                else "No baseline vs follow-up data yet"
            ),
            "icon": "chart",
            "variant": "primary",
        },
    ]

    # Role scope notice — one honest line, backend-driven from the same scoped
    # queryset the page renders (never hidden/derived by CSS).
    role = getattr(request.user, "active_role", None)
    if role in ("CountryDirector", "RegionalVicePresident", "Admin"):
        scope_text = f"Showing all {total_core} core school(s) nationwide."
    else:
        scope_text = (
            f"Showing {total_core} core school(s) scoped to your role and assignments."
        )

    # Dropdowns Options
    regions = Region.objects.all().order_by("name")
    if filters["region"] != "All":
        districts = District.objects.filter(region_id=filters["region"]).order_by(
            "name"
        )
    else:
        districts = District.objects.all().order_by("name")

    staff_members = (
        StaffProfile.objects.all().select_related("user").order_by("user__name")
    )
    partners = Partner.objects.all().order_by("name")

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
        "scope_text": scope_text,
        "matrix_rows": matrix_rows,
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
    }

    if request.headers.get("HX-Target") == "core-schools-table-container":
        return render(request, "partials/core_schools/matrix_table.html", context)

    return render(request, "pages/core_schools/index.html", context)


@require_page_permission("core_schools")
def core_schedule_visit_drawer(request):
    """Renders schedule core visit drawer."""
    school_id = request.GET.get("school_id")
    school = get_scoped_object_or_404(School, request.user, school_id=school_id)

    latest_ssa = (
        school.ssa_records.filter(deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )
    recommendations = []
    if latest_ssa:
        scores = sorted(
            list(latest_ssa.scores.all().values("intervention", "score")),
            key=lambda s: s["score"],
        )
        for s in scores[:2]:
            code = s["intervention"]
            label = dict(SsaIntervention.choices).get(code, code)
            recommendations.append({"code": code, "label": label, "score": s["score"]})

    staff_members = (
        StaffProfile.objects.all().select_related("user").order_by("user__name")
    )
    partners = Partner.objects.all().order_by("name")

    # Determine next visit sequence number
    fy = get_operational_fy()
    plan = CorePlan.objects.filter(school_id=school_id, fy=fy).first()
    next_visit_seq = 1
    if plan:
        completed_visits = plan.slots.filter(
            activity_type="visit",
            status__in=[
                "Completed",
                "Accountant Confirmed",
                "iaVerify",
                "ia_verified",
                "accountant_confirmed",
                "Scheduled",
            ],
        ).count()
        next_visit_seq = min(4, completed_visits + 1)

    context = {
        "school": school,
        "recommendations": recommendations,
        "staff_members": staff_members,
        "partners": partners,
        "next_visit_seq": next_visit_seq,
        "interventions": SsaIntervention.choices,
    }
    return render(request, "partials/core_schools/schedule_visit_drawer.html", context)


@require_POST
@require_page_permission("core_schools")
def core_schedule_visit_action(request):
    """Handles schedule visit submission."""
    school_id = request.POST.get("school_id")
    get_scoped_object_or_404(School, request.user, school_id=school_id)
    visit_seq = request.POST.get("visit_number", "1")
    scheduled_date = request.POST.get("scheduled_date")
    focus_intervention = request.POST.get("focus_intervention")
    purpose_text = request.POST.get("visit_purpose", "").strip()
    expected_outcome = request.POST.get("expected_outcome", "").strip()
    responsible_staff_id = request.POST.get("responsible_staff_id")
    partner_id = request.POST.get("assigned_partner_id")

    payload = {
        "schoolId": school_id,
        "activityType": "core_visit",
        "scheduledDate": scheduled_date,
        "focusIntervention": focus_intervention,
        "activityPurposeText": purpose_text,
        "expectedOutcome": expected_outcome,
        "responsibleStaffId": responsible_staff_id,
        "deliveryType": "partner" if partner_id else "staff",
        "assignedPartnerId": partner_id if partner_id else "",
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
            # 1. Create standard Activity in DB
            act_data = create_activity(payload, request.user)

            # 2. Find and update CoreActivitySlot
            slot_id = cslot_id(school_id, "v", int(visit_seq))
            slot = CoreActivitySlot.objects.filter(id=slot_id).first()
            if slot:
                slot.status = "Scheduled"
                slot.activity_id = act_data["id"]
                slot.scheduled_for = scheduled_date
                slot.scheduled_month = str(payload.get("plannedMonth"))
                slot.scheduled_week = payload.get("plannedWeek")
                slot.assigned_staff_id = responsible_staff_id
                if partner_id:
                    slot.assigned_partner_id = partner_id
                    slot.owner = "partner"
                slot.save()

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
                request, f"Core Visit V{visit_seq} scheduled successfully."
            )
            response = HttpResponse(
                '<script>window.location.href = "/my-plan";</script>'
            )
            response["HX-Trigger"] = "close-drawer"
            return response
    except Exception as e:
        return HttpResponse(
            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>',
            status=400,
        )


@require_page_permission("core_schools")
def core_schedule_training_drawer(request):
    """Renders schedule core training drawer."""
    school_id = request.GET.get("school_id")
    school = get_scoped_object_or_404(School, request.user, school_id=school_id)

    latest_ssa = (
        school.ssa_records.filter(deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )
    recommendations = []
    if latest_ssa:
        scores = sorted(
            list(latest_ssa.scores.all().values("intervention", "score")),
            key=lambda s: s["score"],
        )
        for s in scores[:2]:
            code = s["intervention"]
            label = dict(SsaIntervention.choices).get(code, code)
            recommendations.append({"code": code, "label": label, "score": s["score"]})

    staff_members = (
        StaffProfile.objects.all().select_related("user").order_by("user__name")
    )
    partners = Partner.objects.all().order_by("name")

    # Determine next training sequence number
    fy = get_operational_fy()
    plan = CorePlan.objects.filter(school_id=school_id, fy=fy).first()
    next_train_seq = 1
    if plan:
        completed_trainings = plan.slots.filter(
            activity_type="training",
            status__in=[
                "Completed",
                "Accountant Confirmed",
                "iaVerify",
                "ia_verified",
                "accountant_confirmed",
                "Scheduled",
            ],
        ).count()
        next_train_seq = min(4, completed_trainings + 1)

    context = {
        "school": school,
        "recommendations": recommendations,
        "staff_members": staff_members,
        "partners": partners,
        "next_train_seq": next_train_seq,
        "interventions": SsaIntervention.choices,
    }
    return render(
        request, "partials/core_schools/schedule_training_drawer.html", context
    )


@require_POST
@require_page_permission("core_schools")
def core_schedule_training_action(request):
    """Handles schedule training submission."""
    school_id = request.POST.get("school_id")
    get_scoped_object_or_404(School, request.user, school_id=school_id)
    train_seq = request.POST.get("training_number", "1")
    scheduled_date = request.POST.get("scheduled_date")
    focus_intervention = request.POST.get("focus_intervention")
    purpose_text = request.POST.get("training_purpose", "").strip()
    expected_participants = request.POST.get("expected_participants", "10")
    responsible_staff_id = request.POST.get("responsible_staff_id")
    partner_id = request.POST.get("assigned_partner_id")

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
        "assignedPartnerId": partner_id if partner_id else "",
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
            # 1. Create standard Activity in DB
            act_data = create_activity(payload, request.user)

            # 2. Find and update CoreActivitySlot
            slot_id = cslot_id(school_id, "t", int(train_seq))
            slot = CoreActivitySlot.objects.filter(id=slot_id).first()
            if slot:
                slot.status = "Scheduled"
                slot.activity_id = act_data["id"]
                slot.scheduled_for = scheduled_date
                slot.scheduled_month = str(payload.get("plannedMonth"))
                slot.scheduled_week = payload.get("plannedWeek")
                slot.assigned_staff_id = responsible_staff_id
                if partner_id:
                    slot.assigned_partner_id = partner_id
                    slot.owner = "partner"
                slot.save()

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
                request, f"Core Training T{train_seq} scheduled successfully."
            )
            response = HttpResponse(
                '<script>window.location.href = "/my-plan";</script>'
            )
            response["HX-Trigger"] = "close-drawer"
            return response
    except Exception as e:
        return HttpResponse(
            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>',
            status=400,
        )


@require_page_permission("core_schools")
def core_assign_partner_drawer(request):
    """Renders partner assignment drawer."""
    school_id = request.GET.get("school_id")
    school = get_scoped_object_or_404(School, request.user, school_id=school_id)

    partners = Partner.objects.all().order_by("name")
    interventions = SsaIntervention.choices

    context = {
        "school": school,
        "partners": partners,
        "interventions": interventions,
    }
    return render(request, "partials/core_schools/assign_partner_drawer.html", context)


@require_POST
@require_page_permission("core_schools")
def core_assign_partner_action(request):
    """Handles partner assignment submission."""
    school_id = request.POST.get("school_id")
    school = get_scoped_object_or_404(School, request.user, school_id=school_id)
    support_type = request.POST.get("support_type", "Visit")  # Visit | Training
    visit_training_number = request.POST.get("visit_training_number", "1")
    partner_id = request.POST.get("partner_id")
    focus_intervention = request.POST.get("focus_intervention")
    notes = request.POST.get("notes", "").strip()

    partner = get_object_or_404(Partner, id=partner_id)

    try:
        with transaction.atomic():
            # 1. Create PartnerAssignment in DB
            pa = PartnerAssignment.objects.create(
                school=school,
                partner=partner,
                assigning_staff_id=request.user.staff_profile_id,
                focus_intervention=focus_intervention,
                expected_activity_type="core_visit"
                if support_type == "Visit"
                else "core_training",
                notes=notes,
                status="assigned",
                visit_number=visit_training_number if support_type == "Visit" else "",
                training_number=visit_training_number
                if support_type == "Training"
                else "",
                support_type=support_type,
            )

            # 2. Update CoreActivitySlot
            kind_prefix = "v" if support_type == "Visit" else "t"
            slot_id = cslot_id(school_id, kind_prefix, int(visit_training_number))
            slot = CoreActivitySlot.objects.filter(id=slot_id).first()
            if slot:
                slot.status = "Assigned"
                slot.assigned_partner_id = partner_id
                slot.assigned_partner_name = partner.name
                slot.owner = "partner"
                slot.save()

            # Audit log
            audit_log(
                action="assign_core_partner",
                subject_kind="PartnerAssignment",
                subject_id=pa.id,
                actor_id=str(request.user.id),
                actor_role=getattr(request.user, "active_role", None),
                success=True,
            )

            # Notify Partner
            Notification.objects.create(
                recipient_id=partner_id,
                title="New Core School Support Assignment",
                body=f"Your organization has been assigned to support {school.name} with {support_type} {visit_training_number} focusing on {focus_intervention}.",
                priority="normal",
            )

            messages.success(
                request, f"Core support assigned to {partner.name} successfully."
            )
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response
    except Exception as e:
        return HttpResponse(
            f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>',
            status=400,
        )


@require_page_permission("core_schools")
def core_assessment_drawer(request):
    """Renders core assessment details drawer."""
    school_id = request.GET.get("school_id")
    school = get_scoped_object_or_404(School, request.user, school_id=school_id)
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


from apps.core_schools.champion_services import ChampionEligibilityService  # noqa: E402 — deliberate late import (see module layout)


@require_page_permission("core_schools")
def champion_candidates_view(request):
    """View to list Proposed Champion Candidates."""
    candidates = ChampionEligibilityService.evaluate_all()
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
    school = get_scoped_object_or_404(School, request.user, school_id=school_id)
    metrics = ChampionEligibilityService.calculate_score(school)

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

    context = {
        "school": school,
        "metrics": metrics,
        "latest_ssa": latest_ssa,
        "scores": scores,
    }
    return render(request, "partials/core_schools/champion_review_drawer.html", context)


@require_POST
@require_page_permission("core_schools")
def champion_approve_action(request, school_id):
    """Approve a core school to become champion."""
    success = ChampionEligibilityService.approve(school_id, request.user.user_id)
    if success:
        messages.success(request, "School successfully graduated to Champion Status!")
    else:
        messages.error(request, "Failed to graduate school.")
    return redirect("core_schools")


@require_POST
@require_page_permission("core_schools")
def champion_reject_action(request, school_id):
    """Reject a champion candidacy proposal."""
    success = ChampionEligibilityService.reject(school_id)
    if success:
        messages.warning(request, "Candidacy proposal rejected.")
    else:
        messages.error(request, "Failed to reject candidacy.")
    return redirect("core_schools")


@require_page_permission("core_schools")
def champions_list_view(request):
    """View to list official graduated Champions."""
    champions = School.objects.filter(
        school_type="champion", deleted_at__isnull=True
    ).order_by("name")
    formatted_champions = []
    for s in champions:
        profile = CoreSchoolProfile.objects.filter(school_id=s.school_id).first()
        latest_ssa = (
            s.ssa_records.filter(deleted_at__isnull=True)
            .order_by("-date_of_ssa")
            .first()
        )
        formatted_champions.append(
            {
                "school_id": s.school_id,
                "name": s.name,
                "district": s.district.name if s.district else "Unknown",
                "region": s.region.name if s.region else "Unknown",
                "onboard_fy": profile.core_start_fy if profile else "Unknown",
                "latest_avg": latest_ssa.average_score if latest_ssa else 0.0,
            }
        )
    context = {
        "champions": formatted_champions,
    }
    return render(request, "pages/core_schools/champions.html", context)
