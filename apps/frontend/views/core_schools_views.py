from apps.core.metrics import render_precomputed_metric_item
import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseForbidden
from django.contrib import messages
from django.utils.html import escape
from django.db import transaction
from django.views.decorators.http import require_POST
from datetime import date

from apps.core.htmx_errors import error_fragment
from apps.core.donut import build_gauge
from apps.core.permissions import (
    RolePermissionService,
    require_page_permission,
    get_operational_school_or_404,
    get_visit_target_school_or_404,
)
from apps.core.exceptions import BadRequest
from apps.core.fy import fy_options, get_operational_fy
from apps.core.enums import SsaIntervention
from apps.schools.models import School
from apps.geography.models import Region, District
from apps.accounts.models import StaffProfile
from apps.partners.models import Partner, PartnerAssignment
from apps.partners import services as partner_services
from apps.partners.purposes import PARTNER_VISIT_PURPOSES
from apps.activities.models import Activity
from apps.core_schools.models import (
    CoreActivitySlot,
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


_CORE_CHART_KEYS = (
    ("scheduled_visits", "scheduled_visit_count"),
    ("visits_target", "visits_target"),
    ("scheduled_trainings", "scheduled_training_count"),
    ("trainings_target", "trainings_target"),
)


def _core_totals(name: str, rows) -> dict:
    """One person's package scheduling, summed over their school rows."""
    totals = {"name": name, **{key: 0 for key, _ in _CORE_CHART_KEYS}}
    for row in rows:
        for key, source in _CORE_CHART_KEYS:
            totals[key] += int(row.get(source) or 0)
    return totals


def _core_rows_by_person(oversight_rows, *, roster=(), person_of) -> list[dict]:
    """The team oversight rows folded per person, for the chart that reads
    each person as a series.

    ``person_of(row)`` names the person a school row belongs to as an
    ``(id, name)`` pair — its responsible CCEO for a Programme Lead, the
    supervising Programme Lead for a country or regional reader — and
    ``roster`` lists, in display order, everyone who must appear whether or
    not they hold a core school, so a person with nothing to show is a zero
    row rather than a missing one. Anyone the rows name who is not on the
    roster follows in name order; schools nobody owns fold under Unassigned
    at the end. Summed from the rows, so a person's bars and their school
    rows agree by construction.
    """
    by_person: dict[str, list] = {}
    names: dict[str, str] = {}
    for row in oversight_rows:
        key, name = person_of(row)
        key = str(key or "")
        by_person.setdefault(key, []).append(row)
        names.setdefault(key, name or "Unassigned")
    order = [(str(key), name) for key, name in roster]
    listed = {key for key, _ in order}
    extra = sorted(
        ((key, names[key]) for key in by_person if key and key not in listed),
        key=lambda pair: pair[1].casefold(),
    )
    folded = [_core_totals(name, by_person.get(key, ())) for key, name in order + extra]
    if by_person.get(""):
        folded.append(_core_totals("Unassigned", by_person[""]))
    return folded


def _core_oversight_chart(user, scope, fy, oversight_qs) -> dict:
    """The Team Core Oversight chart: every core school the reader watches,
    folded per person.

    A Programme Lead reads their own core schools first, then each officer on
    their roster; a country or regional reader reads one series per
    Programme Lead. Folded over the whole oversight set rather than the page
    on show, so the bars do not change when the table is paged.
    """
    from apps.clusters.oversight_service import (
        _label,
        _staff_directory,
        _supervisor_of,
    )
    from apps.core.rbac import EdifyRole
    from apps.hr.team_roster import team_members
    from apps.planning.oversight_service import system_program_leads

    rows = CoreTeamOversightService.build_rows(
        CorePackageProgressService.get_matrix_data(oversight_qs, fy), fy
    )
    if scope.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        own_qs, _ = CoreSchoolsService.base_queryset(user, lens="direct")
        own_rows = CoreTeamOversightService.build_rows(
            CorePackageProgressService.get_matrix_data(own_qs, fy), fy
        )
        own_label = f"{getattr(user, 'name', '') or 'My work'} (you)"
        roster = [(member.id, _label(member)) for member in team_members(user)]
        return {
            "rows": [_core_totals(own_label, own_rows)]
            + _core_rows_by_person(
                rows,
                roster=roster,
                person_of=lambda row: (
                    row.get("account_owner_id"),
                    row.get("responsible_cceo"),
                ),
            ),
            "title": "Core package scheduling by person",
            "subtitle": "You and each officer you supervise, summed over every "
            "core school your team holds",
        }
    directory = _staff_directory(
        {row.get("account_owner_id") for row in rows if row.get("account_owner_id")}
    )

    def lead_of(row):
        lead = _supervisor_of(directory.get(row.get("account_owner_id")))
        return (getattr(lead, "id", None), _label(lead) if lead else "Unassigned")

    return {
        "rows": _core_rows_by_person(
            rows,
            roster=[(pl["id"], pl["name"]) for pl in system_program_leads()],
            person_of=lead_of,
        ),
        "title": "Core package scheduling by Programme Lead",
        "subtitle": "Each Lead's team, summed over every core school in your oversight",
    }


def _core_page_size(request) -> int:
    raw = str(request.GET.get("per_page", "")).strip()
    if raw.isdigit() and int(raw) in CORE_PAGE_SIZES:
        return int(raw)
    return CORE_PAGE_SIZE_DEFAULT


@require_page_permission("core_schools")
def core_schools_view(request):
    """Core Schools planning main dashboard view."""
    # The operational year unless a year the platform offers is chosen
    # (Programme Lead alignment, 2026-09-13): "2026" was a literal default.
    requested_fy = (request.GET.get("fy") or "").strip()
    fy = requested_fy if requested_fy in fy_options() else get_operational_fy()

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
    from apps.core.pagination import elided_page_numbers

    pages_list = elided_page_numbers(page_obj)

    # 4. Retrieve service-processed context
    matrix_rows = CorePackageProgressService.get_matrix_data(page_obj.object_list, fy)
    oversight_rows = (
        CoreTeamOversightService.build_rows(matrix_rows, fy)
        if lens == "oversight"
        else []
    )
    oversight_chart = (
        _core_oversight_chart(request.user, scope, fy, core_schools_qs)
        if lens == "oversight"
        else None
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

    # What is scheduled against the package is the SLOT, not an Activity of a
    # particular type, and these two counters are "how many of the 4 + 4
    # package slots are taken" — the same question available_options and
    # assert_can_schedule answer. Counting activities by type answered a
    # different one and got trainings wrong: a Core training is delivered by
    # the standard In-school Training workflow (activity_type
    # "in_school_training", the course naming it), so "core_training" matched
    # nothing ever written and the tile read 0 / 412 however many were
    # scheduled — which is what scheduling one and seeing nothing looks like
    # (owner, 2026-09-17: "Core school training scheduling ... is not
    # saving"). It saved; only the count could not see it.
    #
    # Read through the slots and the two paths that book a training — this
    # drawer and the In-school Training option on the visit drawer — are both
    # counted, because both commit a slot. is_allocated, rather than a status
    # filter, because slot status is stored in mixed case and carries the
    # workflow's later states as well as "Scheduled".
    # "Scheduled" here means committed: dated, or handed to a partner who has
    # not dated it yet. See status_is_taken.
    slot_states = CoreActivitySlot.objects.filter(
        core_plan__school_id__in=core_schools_qs.values_list("school_id", flat=True),
        core_plan__fy=fy,
    ).values_list("activity_type", "status")
    visits_scheduled = 0
    trainings_scheduled = 0
    for slot_kind, slot_status in slot_states:
        if not CorePackageSchedulingService.status_is_taken(slot_status):
            continue
        if slot_kind == "visit":
            visits_scheduled += 1
        elif slot_kind == "training":
            trainings_scheduled += 1

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
            helper=f"{int((ready_core / total_core) * 100) if total_core else 0}% of core",
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
            helper=f"{int((visits_scheduled / total_target) * 100) if total_target else 0}% complete",
            icon="calendar",
            variant="info",
        ),
        render_precomputed_metric_item(
            "frontend_views_core_schools_views_trainings_scheduled",
            f"{trainings_scheduled} / {total_target}",
            helper=f"{int((trainings_scheduled / total_target) * 100) if total_target else 0}% complete",
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
            helper=f"{int((regions_covered / total_regions) * 100) if total_regions else 0}% coverage",
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

    from apps.core.permissions import has_permission

    context = {
        "fy": fy,
        "selected_fy": fy,
        "fy_options": fy_options(),
        # Add to Project, the same one the School Directory offers (owner,
        # 2026-09-17: "core schools should be able to be added to project as
        # well ... replicate the exact add to project functionality on client
        # schools"). The drawer and the enrolment service already handle a core
        # school — projects_open_for_enrolment excludes client-only projects
        # for one — so the whole of what was missing was the way in.
        "can_assign_project": has_permission(request.user, "project.assignSchool"),
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
        "oversight_chart": oversight_chart,
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


def _core_visit_request_context(school, user) -> dict:
    """The request-only country roles ask for a core visit, not plan it.

    Same rule as the ordinary school drawer (apps.planning.visit_requests):
    at a school somebody owns the visit waits for the owner's approval, and
    the requester — not the owner — is the one going.
    """
    from apps.planning.visit_requests import approval_owner_for, staff_name

    owner_id = approval_owner_for(school, user)
    if not owner_id:
        return {"visit_request_owner_id": None, "visit_request_owner_name": ""}
    return {
        "visit_request_owner_id": owner_id,
        "visit_request_owner_name": staff_name(owner_id) or "the school's owner",
    }


def _requester_identity(user) -> str | None:
    return (
        getattr(user, "staff_profile_id", None)
        or getattr(user, "user_id", None)
        or getattr(user, "id", None)
    )


CORE_TRAINING_REFUSED = (
    "Core trainings are planned by the CCEO or Program Lead responsible for "
    "the school. Your role schedules school visits only."
)


def _refuse_core_training_for_requesters(user):
    """Core trainings are the owner's; these roles schedule visits only.

    Reads `schedules_visits_only` rather than `can_request_school_visit`: the
    Country Director and Impact Assessment stopped filing requests on
    2026-09-21 and schedule their visits outright, and the core package's
    trainings did not move with them.
    """
    if RolePermissionService.schedules_visits_only(user):
        return HttpResponseForbidden(CORE_TRAINING_REFUSED)
    return None


def _core_training_courses() -> list[dict]:
    """Every governed training course, whatever intervention it serves.

    Owner, 2026-09-15: Core trainings are chosen from the whole Training
    Catalogue, not only the courses keyed to a school-level delivery or a
    focus intervention. The standard In-school Training workflow delivers the
    course, exactly as it does at a client school.
    """
    from apps.activity_catalogue.availability import (
        in_school_training_course_options,
    )

    return in_school_training_course_options()


def _follow_up_requires_training() -> bool:
    from apps.frontend.views.planning_views import _follow_up_requires_training as rule

    return rule()


def _core_ranked_focus(school) -> tuple[str, str]:
    """The SSA's first-ranked need, as (code, label), or blanks."""
    from apps.ssa.plan_alignment import school_need

    need = school_need(school)
    code = need.priorities[0] if need.priorities else ""
    return code, dict(SsaIntervention.choices).get(code, "")


def _core_visit_payload_base(request, school_id, scheduled_date, partner_id):
    payload = {
        "schoolId": school_id,
        "scheduledDate": scheduled_date,
        "activityPurposeText": (
            request.POST.get("activity_goal", "")
            or request.POST.get("visit_purpose", "")
        ).strip(),
        "expectedOutcome": request.POST.get("expected_outcome", "").strip(),
        "deliveryType": "partner" if partner_id else "staff",
        "requireCatalogue": True,
        "recommendationReason": request.POST.get("recommendation_reason", ""),
        # Omit the key entirely for staff delivery — an empty string would be
        # stamped into the budget line's partner FK and violate the constraint.
        **({"assignedPartnerId": partner_id} if partner_id else {}),
    }
    try:
        dt = date.fromisoformat(scheduled_date)
        payload["plannedMonth"] = dt.month
        payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
    except (TypeError, ValueError):
        pass
    return payload


def _core_scheduled_response(request, created, scheduled_date, message):
    """Confirm the save and keep the planner on Core Schools without leaving.

    Owner, 2026-09-19: scheduling should NOT navigate straight to My Plan.
    The work lands on My Plan and the planner can manually navigate to My Plan
    when they are done rather than being interrupted after every activity.
    """
    from apps.frontend.views.planning_views import (
        _calendar_url_for_scheduled_date,
        _my_plan_url_for_scheduled_date,
        _saved_without_leaving,
        _scheduled_into_own_plan,
    )

    lands_here, owner_name = _scheduled_into_own_plan(created, request.user)
    if lands_here:
        url = _my_plan_url_for_scheduled_date(scheduled_date)
        link_label = "Open My Plan"
    else:
        message = (
            f"{message} It is on {owner_name}'s My Plan, because they are the "
            "responsible staff member — you will find it on the Calendar."
        )
        url = _calendar_url_for_scheduled_date(scheduled_date)
        link_label = "Open in Calendar"
    return _saved_without_leaving(message, plan_url=url, plan_link_label=link_label)


@require_page_permission("core_schools")
def core_schedule_visit_drawer(request):
    """Renders schedule core visit drawer.

    The visit is chosen by its Purpose of Visit, as at a client school, not by
    an SSA focus intervention. The first Core visit of the fiscal year is SSA
    Support: it collects the year's SSA data before any other support.
    """
    import json

    from apps.partners.purposes import STAFF_VISIT_PURPOSES

    school_id = request.GET.get("school_id")
    school = get_visit_target_school_or_404(request.user, school_id=school_id)

    # §17 — four weakest verified interventions, 2 → Partner, 2 → Staff.
    from apps.core_schools.core_planning_services import (
        CoreInterventionRecommendationService,
    )

    reco = CoreInterventionRecommendationService.recommend(school)
    recommendations = reco["rows"]

    staff_members = (
        StaffProfile.objects.all().select_related("user").order_by("user__name")
    )
    partners = Partner.objects.all().order_by("name")

    fy = get_operational_fy()
    plan = CorePlan.objects.filter(school_id=school_id, fy=fy).first()
    available_visit_slots = (
        CorePackageSchedulingService.available_options(plan, "visit") if plan else []
    )
    available_training_slots = (
        CorePackageSchedulingService.available_options(plan, "training") if plan else []
    )
    # The package's first visit no longer has to be SSA Support, so every
    # purpose is offered from the start (owner, 2026-09-17).
    first_visit = False
    # Trainings are the owner's; the portfolio-less country roles do visits.
    # The same question `_refuse_core_training_for_requesters` asks at POST,
    # so the drawer never offers a purpose the action then refuses.
    visits_only = RolePermissionService.schedules_visits_only(request.user)
    purposes = [
        (value, label)
        for value, label in STAFF_VISIT_PURPOSES
        if not (visits_only and value == "in_school_training")
    ]

    from apps.frontend.views.planning_views import _school_training_follow_up_options

    focus_code, focus_label = _core_ranked_focus(school)
    context = {
        "school": school,
        "recommendations": recommendations,
        "staff_members": staff_members,
        "partners": partners,
        "next_visit_seq": available_visit_slots[0]["sequence"]
        if available_visit_slots
        else None,
        "available_visit_slots": available_visit_slots,
        "available_training_slots": available_training_slots,
        "first_visit": first_visit,
        "visit_purposes": purposes,
        "recommended_visit_purpose": "ssa_support" if first_visit else "",
        "partner_visit_purpose_values_json": json.dumps(
            [value for value, _label in PARTNER_VISIT_PURPOSES]
        ),
        "interventions": SsaIntervention.choices,
        "recommended_focus_intervention": focus_code,
        "ssa_top_label": focus_label,
        "training_courses_json": json.dumps(_core_training_courses()),
        "follow_up_options_json": json.dumps(
            _school_training_follow_up_options(school)
        ),
        "follow_up_fy": fy,
        "follow_up_requires_training": _follow_up_requires_training(),
        "requester_name": getattr(request.user, "name", "") or "You",
        **_core_visit_request_context(school, request.user),
    }
    return render(request, "partials/core_schools/schedule_visit_drawer.html", context)


@require_POST
@require_page_permission("core_schools")
def core_schedule_visit_action(request):
    """Handles schedule visit submission."""
    from apps.activity_catalogue.services import resolve_item_for_workflow_kind
    from apps.partners.purposes import normalise_visit_purpose, visit_purpose_label

    school_id = request.POST.get("school_id")
    school = get_visit_target_school_or_404(request.user, school_id=school_id)
    visit_seq = request.POST.get("visit_number", "1")
    scheduled_date = request.POST.get("scheduled_date")
    focus_intervention = request.POST.get("focus_intervention", "").strip() or None
    purpose_of_visit = request.POST.get("purpose_of_visit", "").strip()
    responsible_staff_id = request.POST.get("responsible_staff_id")
    partner_id = request.POST.get("assigned_partner_id", "").strip() or None
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    source_activity_id = request.POST.get("source_activity_id", "").strip()
    # Whose visit this is, resolved here and never from the form, so a posted
    # responsible person cannot reassign the work. The Programme Accountant at
    # somebody else's school asks and goes themselves
    # (apps.planning.visit_requests); anyone scheduling at a school outside
    # their own portfolio is likewise the one going, rather than filing a core
    # visit onto the holder's My Plan and fund request.
    visit_request = _core_visit_request_context(school, request.user)
    visit_request_owner_id = visit_request["visit_request_owner_id"]
    visit_justification = request.POST.get("visit_justification", "").strip()
    if visit_request_owner_id:
        responsible_staff_id = _requester_identity(request.user)
        partner_id = None
    elif not partner_id and not responsible_staff_id:
        # This drawer offers a Responsible Staff Owner picker, so a named
        # person is a deliberate handover and stands. Only when nobody was
        # named does the visit fall to whoever is going — the scheduler at a
        # school outside their portfolio, the school's owner inside it.
        from apps.frontend.views.planning_views import visit_owner_for

        responsible_staff_id, _name = visit_owner_for(school, request.user)

    try:
        scheduled_for = date.fromisoformat(scheduled_date)
    except (TypeError, ValueError):
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Please choose a valid planned date and visit slot.</div>',
            status=400,
        )

    try:
        if purpose_of_visit:
            purpose_of_visit = normalise_visit_purpose(
                purpose_of_visit, for_partner=bool(partner_id)
            )
        if purpose_of_visit == "in_school_training":
            if visit_request_owner_id:
                raise BadRequest(CORE_TRAINING_REFUSED)
            return _schedule_core_in_school_training(
                request,
                school=school,
                scheduled_for=scheduled_for,
                responsible_staff_id=responsible_staff_id,
                partner_id=partner_id,
            )
        visit_sequence = int(visit_seq)
    except (TypeError, ValueError):
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Please choose a valid planned date and visit slot.</div>',
            status=400,
        )
    except Exception as exc:
        return error_fragment(exc, status=400)

    payload = {
        **_core_visit_payload_base(request, school_id, scheduled_date, partner_id),
        "activityType": "core_visit",
        "responsibleStaffId": responsible_staff_id,
        **(
            {"visitJustification": visit_justification}
            if visit_request_owner_id
            else {}
        ),
    }

    from apps.activities.services import create as create_activity

    try:
        if not catalogue_item_id:
            item = resolve_item_for_workflow_kind("core_visit", on_date=scheduled_for)
            if item is None:
                raise BadRequest(
                    "No approved Catalogue Activity costs a Core School visit. "
                    "Ask the Country Director to configure one."
                )
            catalogue_item_id = item.id
        payload["catalogueItemId"] = catalogue_item_id

        with transaction.atomic():
            plan = (
                CorePlan.objects.select_for_update()
                .filter(school_id=school_id, fy=get_operational_fy())
                .first()
            )
            if not plan:
                raise BadRequest("This school does not have an active core package.")
            # SSA Support remains the DEFAULT when a caller names no purpose —
            # a core package opens by collecting the year's SSA data, and that
            # is still the sensible reading of an unspecified visit. What is
            # gone (2026-09-17) is the refusal that used to follow: the first
            # visit of a package no longer HAS to be SSA Support, and the
            # drawer offers every purpose from the start.
            if not purpose_of_visit:
                purpose_of_visit = "ssa_support"
            if purpose_of_visit:
                payload["purposeType"] = purpose_of_visit
            if purpose_of_visit == "ssa_support":
                # Linked to data collection: completion asks for the scores (or
                # why none were collected), and IA reads it as an SSA visit.
                payload["ssaCollectionExpected"] = True
                focus_intervention = None
            elif purpose_of_visit == "training_follow_up":
                from apps.frontend.views.planning_views import (
                    _school_training_follow_up_options,
                )

                from apps.planning.fy_policy import (
                    follow_up_requires_prior_training,
                )

                eligible = {
                    option["id"]
                    for option in _school_training_follow_up_options(school)
                }
                if source_activity_id:
                    if source_activity_id not in eligible:
                        raise BadRequest(
                            "Choose a completed current-FY training this School did."
                        )
                    payload["sourceActivityId"] = source_activity_id
                    # The training followed up owns the intervention.
                    focus_intervention = None
                elif follow_up_requires_prior_training(get_operational_fy()):
                    raise BadRequest(
                        "Select the completed training this visit follows up."
                    )
                elif not focus_intervention:
                    # No prior training is recorded and the policy allows the
                    # visit (owner, 2026-09-15): the SSA names what it moves.
                    focus_intervention = _core_ranked_focus(school)[0] or None
            elif purpose_of_visit == "in_school_coaching" and not focus_intervention:
                focus_intervention = _core_ranked_focus(school)[0] or None
            if focus_intervention:
                payload["focusIntervention"] = focus_intervention

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

            purpose_note = (
                f" ({visit_purpose_label(purpose_of_visit)})"
                if purpose_of_visit
                else ""
            )
            if visit_request_owner_id:
                from apps.planning.visit_requests import QUEUE_URL

                messages.success(
                    request,
                    f"Core Visit V{visit_sequence}{purpose_note} scheduled, pending "
                    f"{visit_request['visit_request_owner_name']}'s approval. It "
                    "takes effect on your plan and enters your budget once approved.",
                )
                response = HttpResponse(
                    f'<script>window.location.href = "{QUEUE_URL}";</script>'
                )
                response["HX-Trigger"] = "close-drawer"
                return response
            return _core_scheduled_response(
                request,
                act_data,
                scheduled_date,
                f"Core Visit V{visit_sequence}{purpose_note} scheduled successfully.",
            )
    except Exception as e:
        return error_fragment(e, status=400)


def _schedule_core_in_school_training(
    request, *, school, scheduled_for, responsible_staff_id, partner_id
):
    """In-school Training chosen from the Core visit drawer.

    Same outcome as at a client school: the governed Training and its
    companion School Visit are created together
    (apps.planning.services.schedule_in_school_training_pair). The Training
    fills the package's next open training slot — it is the Core training —
    while the companion visit is the uncosted Salesforce/evidence record of
    the same mission and leaves the visit slots untouched.
    """
    from apps.activity_catalogue.availability import (
        validate_in_school_training_course_selection,
    )
    from apps.planning.services import schedule_in_school_training_pair

    school_id = school.school_id
    scheduled_date = scheduled_for.isoformat()
    course_id = request.POST.get("training_course_id", "").strip()
    if not course_id:
        raise BadRequest("Select the Training to deliver.")
    validate_in_school_training_course_selection(course_id, on_date=scheduled_for)

    payload = {
        **_core_visit_payload_base(request, school_id, scheduled_date, partner_id),
        "catalogueItemId": course_id,
        "responsibleStaffId": responsible_staff_id,
    }
    with transaction.atomic():
        plan = (
            CorePlan.objects.select_for_update()
            .filter(school_id=school_id, fy=get_operational_fy())
            .first()
        )
        if not plan:
            raise BadRequest("This school does not have an active core package.")
        # No first-visit gate here any more: a TRAINING slot is not a visit
        # slot, and refusing one on the state of the other is how a core
        # school with an unstarted package could be given no training at all
        # (owner, 2026-09-17).
        requested = request.POST.get("training_number", "").strip()
        options = CorePackageSchedulingService.available_options(plan, "training")
        if not options:
            raise BadRequest("All 4 core trainings are already scheduled or completed.")
        training_sequence = int(requested) if requested else options[0]["sequence"]
        slot = CorePackageSchedulingService.assert_can_schedule(
            plan=plan,
            school=school,
            activity_type="training",
            sequence_number=training_sequence,
            scheduled_for=scheduled_for,
            is_partner_delivery=bool(partner_id),
        )
        created = schedule_in_school_training_pair(payload, request.user)
        CorePackageSchedulingService.commit_schedule(
            slot,
            activity_id=created["id"],
            scheduled_for=scheduled_date,
            scheduled_month=str(payload.get("plannedMonth")),
            scheduled_week=payload.get("plannedWeek"),
            assigned_staff_id=responsible_staff_id,
            partner_id=partner_id,
        )
        audit_log(
            action="schedule_core_training",
            subject_kind="Activity",
            subject_id=created["id"],
            actor_id=str(request.user.id),
            actor_role=getattr(request.user, "active_role", None),
            success=True,
        )
    return _core_scheduled_response(
        request,
        created,
        scheduled_date,
        f"Core Training T{training_sequence} ({created['trainingCourseLabel']}) and "
        "its school visit scheduled successfully.",
    )


@require_page_permission("core_schools")
def core_schedule_training_drawer(request):
    """Renders schedule core training drawer."""
    refused = _refuse_core_training_for_requesters(request.user)
    if refused is not None:
        return refused
    school_id = request.GET.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)

    # §17 — four weakest verified interventions, 2 → Partner, 2 → Staff.
    from apps.core_schools.core_planning_services import (
        CoreInterventionRecommendationService,
    )

    reco = CoreInterventionRecommendationService.recommend(school)
    recommendations = reco["rows"]

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
        "catalogue_items": _core_training_courses(),
    }
    return render(
        request, "partials/core_schools/schedule_training_drawer.html", context
    )


@require_POST
@require_page_permission("core_schools")
def core_schedule_training_action(request):
    """Handles schedule training submission."""
    refused = _refuse_core_training_for_requesters(request.user)
    if refused is not None:
        return refused
    school_id = request.POST.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)
    train_seq = request.POST.get("training_number", "1")
    scheduled_date = request.POST.get("scheduled_date")
    purpose_text = request.POST.get("training_purpose", "").strip()
    expected_participants = request.POST.get("expected_participants", "10")
    responsible_staff_id = request.POST.get("responsible_staff_id")
    partner_id = request.POST.get("assigned_partner_id")
    catalogue_item_id = request.POST.get("catalogue_item_id", "").strip()
    if not catalogue_item_id:
        return error_fragment(
            BadRequest("Select a training from the Training Catalogue."),
            status=400,
        )
    try:
        from apps.activity_catalogue.availability import (
            validate_in_school_training_course_selection,
        )
        from apps.activity_catalogue.services import (
            get_selectable_item,
            resolve_item_for_workflow_kind,
        )
        from apps.core.activity_types import ActivityType

        # Any governed course: the course names the training, the standard
        # In-school Training workflow delivers and costs it — the same split a
        # client school's in-school training uses. Posting the course itself
        # as the catalogue item made the Activity take the course's own kind,
        # which for the cluster-delivered courses is not a school workflow.
        validate_in_school_training_course_selection(catalogue_item_id)
        course = get_selectable_item(catalogue_item_id)
        training_profile = resolve_item_for_workflow_kind(
            ActivityType.IN_SCHOOL_TRAINING
        )
        if training_profile is None:
            raise BadRequest(
                "The standard In-school Training profile must be active before "
                "a Core training can be scheduled."
            )
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
        "activityType": ActivityType.IN_SCHOOL_TRAINING,
        "purposeType": "in_school_training",
        "scheduledDate": scheduled_date,
        "activityPurposeText": purpose_text,
        "expectedParticipants": int(expected_participants)
        if expected_participants.isdigit()
        else 10,
        "responsibleStaffId": responsible_staff_id,
        "deliveryType": "partner" if partner_id else "staff",
        "catalogueItemId": training_profile.id,
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
            act_data = create_activity(
                payload,
                request.user,
                core_slot_verified=True,
                training_course=course,
            )

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

            return _core_scheduled_response(
                request,
                act_data,
                scheduled_date,
                f"Core Training T{training_sequence} scheduled successfully.",
            )
    except Exception as e:
        return error_fragment(e, status=400)


@require_page_permission("core_schools")
def core_assign_partner_drawer(request):
    """Renders partner assignment drawer.

    Owner, 2026-09-15: the support is chosen by Purpose of Visit, as for a
    client school — In-school Training, Training Follow Up or SSA Support —
    not by a Visit/Training switch. For In-school Training staff choose the
    course here and the partner only sets the date.
    """
    import json

    school_id = request.GET.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)

    partners = Partner.objects.all().order_by("name")
    plan = CorePlan.objects.filter(school_id=school_id, fy=get_operational_fy()).first()
    available_visit_slots = (
        CorePackageSchedulingService.available_options(plan, "visit") if plan else []
    )
    available_training_slots = (
        CorePackageSchedulingService.available_options(plan, "training") if plan else []
    )
    # The same three purposes the client school's assign drawer offers, from
    # the same tuple (owner, 2026-09-17: "the purpose options are the same as
    # the options on the client school assign to partner"). They used to be
    # filtered down to SSA Support alone until the package's first visit was
    # taken; that rule is lifted, so the filter is gone rather than left here
    # as a no-op that could quietly come back to life.
    first_visit = False
    purposes = PARTNER_VISIT_PURPOSES
    from apps.frontend.views.planning_views import _school_training_follow_up_options

    context = {
        "school": school,
        "partners": partners,
        "available_visit_slots": available_visit_slots,
        "available_training_slots": available_training_slots,
        "first_visit": first_visit,
        "partner_visit_purposes": purposes,
        "recommended_visit_purpose": "ssa_support" if first_visit else "",
        "training_courses_json": json.dumps(
            [
                course
                for course in _core_training_courses()
                if course["partnerDeliveryAllowed"]
            ]
        ),
        "follow_up_options_json": json.dumps(
            _school_training_follow_up_options(school)
        ),
        "follow_up_fy": get_operational_fy(),
        "follow_up_requires_training": _follow_up_requires_training(),
    }
    return render(request, "partials/core_schools/assign_partner_drawer.html", context)


@require_page_permission("core_schools")
def core_schedule_activity_drawer(request):
    """Choose Core package support or an unrestricted general activity."""
    school_id = request.GET.get("school_id")
    school = get_visit_target_school_or_404(request.user, school_id=school_id)
    plan = CorePlan.objects.filter(school_id=school_id, fy=get_operational_fy()).first()
    summary = CorePackageSchedulingService.summary(plan) if plan else None
    from apps.planning.visit_gate import visit_gate

    gate = visit_gate(school, get_operational_fy())

    context = {
        "school": school,
        # Staff's two visits (owner, 2026-09-15): the core-visit option greys
        # out once they are used, whatever the package still has left for
        # the partner.
        "staff_can_schedule_visit": gate.staff_can_schedule,
        "staff_visit_reason": gate.staff_reason,
        "staff_visit_count": gate.staff_visits,
        "staff_visits_cap": gate.staff_cap,
        # Core trainings are the owner's programme; the portfolio-less country
        # roles schedule visits only (`schedules_visits_only`).
        "can_plan_core_training": RolePermissionService.can_schedule_activity(
            request.user
        ),
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
    from apps.activity_catalogue.availability import (
        validate_in_school_training_course_selection,
    )
    from apps.activity_catalogue.services import (
        get_selectable_item,
        resolve_item_for_workflow_kind,
        validate_context,
    )
    from apps.core.activity_types import ActivityType
    from apps.partners.purposes import normalise_visit_purpose, visit_purpose_label
    from apps.ssa.services import latest_applicable_record

    school_id = request.POST.get("school_id")
    school = get_operational_school_or_404(request.user, school_id=school_id)
    partner_id = request.POST.get("partner_id")
    purpose_of_visit = request.POST.get("purpose_of_visit", "").strip()
    notes = request.POST.get("notes", "").strip()
    source_activity_id = request.POST.get("source_activity_id", "").strip() or None
    course_id = request.POST.get("training_course_id", "").strip()

    partner = get_object_or_404(Partner, id=partner_id)

    try:
        with transaction.atomic():
            if not purpose_of_visit:
                raise BadRequest("Select the purpose of this support.")
            purpose_of_visit = normalise_visit_purpose(
                purpose_of_visit, for_partner=True
            )
            is_training = purpose_of_visit == "in_school_training"
            support_type = "Training" if is_training else "Visit"
            activity_type = "training" if is_training else "visit"

            plan = (
                CorePlan.objects.select_for_update()
                .filter(school_id=school_id, fy=get_operational_fy())
                .first()
            )
            if not plan:
                raise BadRequest("This school does not have an active core package.")
            # A handoff may be any of the three partner purposes from the
            # start; the first-visit-is-SSA rule is lifted (owner, 2026-09-17).
            training_course = None
            source_activity = None
            focus_intervention = None
            if is_training:
                if not course_id:
                    raise BadRequest("Select the Training the partner delivers.")
                selected = validate_in_school_training_course_selection(course_id)
                training_course = get_selectable_item(course_id)
                if not training_course.partner_delivery_allowed:
                    raise BadRequest(
                        "The selected Training is not approved for Partner delivery."
                    )
                catalogue_item = resolve_item_for_workflow_kind(
                    ActivityType.IN_SCHOOL_TRAINING
                )
                focus_intervention = selected["ssaIntervention"] or None
                linked = ", ".join(selected["priorityTitles"])
                recommendation_reason = (
                    f"Priority activity: {linked}"
                    if linked
                    else f"Governed {selected['category']} training."
                )
            else:
                catalogue_item = resolve_item_for_workflow_kind("core_visit")
                recommendation_reason = (
                    f"{visit_purpose_label(purpose_of_visit)} selected by the "
                    "assigning staff member."
                )
                if purpose_of_visit == "training_follow_up":
                    from apps.frontend.views.planning_views import (
                        _school_training_follow_up_options,
                    )

                    from apps.planning.fy_policy import (
                        follow_up_requires_prior_training,
                    )

                    if not source_activity_id:
                        if follow_up_requires_prior_training(get_operational_fy()):
                            raise BadRequest(
                                "Select the completed training this support follows up."
                            )
                        focus_intervention = (
                            focus_intervention or _core_ranked_focus(school)[0] or None
                        )
                    else:
                        eligible = {
                            option["id"]
                            for option in _school_training_follow_up_options(school)
                        }
                        if source_activity_id not in eligible:
                            raise BadRequest(
                                "Choose a completed current-FY training this School did."
                            )
                        source_activity = Activity.objects.get(id=source_activity_id)
                        focus_intervention = (
                            source_activity.focus_intervention
                            or source_activity.purpose_intervention
                            or None
                        )
            if catalogue_item is None:
                raise BadRequest(
                    "No approved Catalogue Activity is configured for this support. "
                    "Ask the Country Director to configure one."
                )
            validate_context(
                catalogue_item,
                school=school,
                cluster=None,
                project=None,
                executor_type="partner",
            )

            options = CorePackageSchedulingService.available_options(
                plan, activity_type
            )
            requested = request.POST.get("visit_training_number", "").strip()
            try:
                sequence_number = (
                    int(requested) if requested else options[0]["sequence"]
                )
            except (TypeError, ValueError, IndexError) as error:
                raise BadRequest("Choose an available support slot.") from error
            slot = CorePackageSchedulingService.assert_can_assign(
                plan=plan,
                activity_type=activity_type,
                sequence_number=sequence_number,
            )
            if activity_type == "visit":
                # The partner side of a core package is two visits (owner,
                # 2026-09-15): scheduled partner visits plus visit slots
                # already assigned and waiting on the partner.
                from apps.planning.visit_gate import assert_may_assign_partner_visit

                assert_may_assign_partner_visit(school)

            # 1. Create PartnerAssignment in DB
            pa = partner_services.create_assignment(
                school=school,
                partner=partner,
                assigning_staff_id=request.user.staff_profile_id,
                assignment_mode="specific_activity",
                catalogue_item=catalogue_item,
                training_course=training_course,
                source_ssa=latest_applicable_record(school),
                source_activity=source_activity,
                recommendation_reason=recommendation_reason,
                catalogue_snapshot=catalogue_item.snapshot(),
                focus_intervention=focus_intervention,
                purpose_of_visit=purpose_of_visit,
                expected_activity_type=catalogue_item.workflow_kind,
                notes=notes,
                visit_number="" if is_training else str(sequence_number),
                training_number=str(sequence_number) if is_training else "",
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
            what = visit_purpose_label(purpose_of_visit)
            if training_course is not None:
                what = f"{what}: {training_course.display_name}"
            WorkflowNotificationService.trigger(
                event_type="core_school_assigned",
                category="partner",
                priority="normal",
                title="New Core School Support Assignment",
                body=f"Your organization has been assigned to support {school.name} with {what}. Choose the date to deliver it.",
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
