from __future__ import annotations

from datetime import date

from apps.core.metrics import render_precomputed_metric_for_source


from django.utils.html import escape
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
)
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core.redirects import local_redirect
from apps.accounts.models import Leave, StaffProfile
from apps.core.permissions import render_access_denied, require_page_permission
from apps.hr.models import (
    Application,
    CompensationRecord,
    EmployeeComplianceRecord,
    OffboardingPlan,
    OnboardingPlan,
    PayrollReadinessRecord,
    PerformanceImprovementPlan,
    PerformanceReview,
    SuccessionCandidate,
    Vacancy,
)


SUCCESS_TERMS = (
    "active",
    "approved",
    "closed",
    "completed",
    "compliant",
    "hired",
    "open",
    "ready",
    "resolved",
    "verified",
)
DANGER_TERMS = (
    "critical",
    "escalated",
    "expired",
    "missing",
    "overdue",
    "rejected",
    "suspended",
)
WARNING_TERMS = (
    "draft",
    "pending",
    "review",
    "screen",
    "triage",
    "progress",
    "submitted",
)


def _status_tone(value) -> str:
    normalized = str(value or "").strip().lower()
    if any(term in normalized for term in DANGER_TERMS):
        return "danger"
    if any(term in normalized for term in SUCCESS_TERMS):
        return "success"
    if any(term in normalized for term in WARNING_TERMS):
        return "warning"
    return "info"


def _cell(label: str, value, *, primary=False, status=False) -> dict:
    display = "—" if value in (None, "") else str(value)
    return {
        "label": label,
        "value": display,
        "primary": primary,
        "status": status,
        "tone": _status_tone(display) if status else "",
    }


def _metric(label: str, value, helper: str, tone="info") -> dict:
    return render_precomputed_metric_for_source(
        "apps.frontend.views.hr_views:_metric", label, value, helper=helper, tone=tone
    )


def _profile_scope(request):
    """The People records the viewer may read — the one rule in apps.hr.reach.

    Admin reads the organisation, a Regional HR Director the countries of
    their region, a Programme Lead their team, every other role their own
    country.
    """
    from apps.hr.reach import people_reach, scope_profiles

    profiles = StaffProfile.objects.select_related("user").filter(
        user__deleted_at__isnull=True
    )
    return scope_profiles(profiles, people_reach(request.user))


def _hr_today_action(request):
    """The "HR Today" header button, for viewers who may open HR Today.

    Offered unconditionally, it sent anyone who reached these registers
    without HR Today access (the Programme Lead lost it on 2026-09-13) to a
    refusal.
    """
    from apps.core.permissions import RolePermissionService

    if RolePermissionService.can_view_page(request.user, "hr_today"):
        return {"label": "HR Today", "href": "/hr-today"}
    return None


def _search_profiles(profiles, query: str):
    if not query:
        return profiles
    return profiles.filter(
        Q(user__name__icontains=query)
        | Q(user__email__icontains=query)
        | Q(title__icontains=query)
        | Q(department__icontains=query)
        | Q(country__icontains=query)
    )


def _render_workspace(
    request,
    *,
    title,
    description,
    metrics,
    rows,
    primary_action,
    empty_title="No records in this scope",
    empty_body="New records will appear here as the connected workflow progresses.",
    header_actions=None,
    eyebrow="Human Capital Operations",
    notice=None,
    team_view=False,
):
    """Render an HR programme register.

    `header_actions` are drawer buttons for creating a record
    ({"label", "drawer"}); a row may carry its own `actions` the same way.
    Rules, permissions and audit stay in the services the drawers call
    (apps/frontend/views/hr_programme_views.py). `team_view` marks a
    Programme Lead's team register, which sits in Team Performance rather
    than under Human Capital.
    """
    paginator = Paginator(rows, 25)
    page = paginator.get_page(request.GET.get("page") or 1)
    context = {
        "title": title,
        "description": description,
        "metrics": metrics,
        "page_obj": page,
        "rows": page.object_list,
        "has_row_actions": any(row.get("actions") for row in page.object_list),
        "primary_action": primary_action,
        "header_actions": header_actions or [],
        "eyebrow": eyebrow,
        "notice": notice,
        "empty_title": empty_title,
        "empty_body": empty_body,
        "search": (request.GET.get("q") or "").strip(),
        "team_view": team_view,
    }
    return render(request, "pages/hr/module_workspace.html", context)


@require_page_permission("org_structure")
def org_structure_view(request):
    """Who reports to whom, by department and country.

    The page was titled for reporting lines and showed none: it listed name,
    role, department, country and lifecycle (HR audit, 2026-09-13). It now
    names each person's supervisor and direct reports from
    StaffSupervisorAssignment, and counts the people with no recorded line, the
    data gap that breaks leave approval, reviews and oversight downstream.
    """
    from apps.accounts.models import StaffSupervisorAssignment

    profiles = _search_profiles(
        _profile_scope(request), (request.GET.get("q") or "").strip()
    ).exclude(onboarding_state="exited")
    profile_ids = profiles.values("id")
    supervisors: dict[str, list[str]] = {}
    reports: dict[str, int] = {}
    for supervisee_id, supervisor_name, supervisor_id in (
        StaffSupervisorAssignment.objects.filter(supervisee_id__in=profile_ids)
        .select_related("supervisor__user")
        .values_list("supervisee_id", "supervisor__user__name", "supervisor_id")
    ):
        supervisors.setdefault(supervisee_id, []).append(supervisor_name)
    for supervisor_id, count in (
        StaffSupervisorAssignment.objects.filter(supervisor_id__in=profile_ids)
        .values_list("supervisor_id")
        .annotate(n=Count("id"))
    ):
        reports[supervisor_id] = count
    # The top of each country's structure reports outside the platform.
    top_roles = {"CountryDirector", "RegionalVicePresident", "Admin"}
    rows = []
    unlined = 0
    for profile in profiles.select_related("user").order_by("department", "user__name"):
        lines = supervisors.get(profile.id, [])
        if not lines and profile.user.active_role not in top_roles:
            unlined += 1
        rows.append(
            {
                "cells": [
                    _cell("Team member", profile.user.name, primary=True),
                    _cell("Role", profile.title or profile.user.active_role),
                    _cell("Reports to", ", ".join(sorted(lines)) or "No line recorded"),
                    _cell("Direct reports", reports.get(profile.id, 0)),
                    _cell("Department", profile.department),
                    _cell("Country", profile.country),
                    _cell(
                        "Lifecycle",
                        profile.get_onboarding_state_display(),
                        status=True,
                    ),
                ]
            }
        )
    return _render_workspace(
        request,
        title="Organization Structure",
        eyebrow="People and staffing",
        description=(
            "Reporting lines across the countries you oversee: who each person "
            "reports to, who reports to them, and where a line is missing."
        ),
        metrics=[
            _metric("People in scope", profiles.count(), "not exited", "info"),
            _metric(
                "Active",
                profiles.filter(onboarding_state="active").count(),
                "fully activated staff",
                "success",
            ),
            _metric(
                "Departments",
                profiles.exclude(department__isnull=True)
                .exclude(department="")
                .values("department")
                .distinct()
                .count(),
                "represented in this scope",
            ),
            _metric(
                "No reporting line",
                unlined,
                "leave, reviews and oversight need one",
                "warning" if unlined else "success",
            ),
        ],
        rows=rows,
        primary_action={"label": "Open People Directory", "href": "/staff"},
        empty_title="No people in this scope",
    )


@require_page_permission("workforce_planning")
def workforce_planning_view(request):
    """Staffing by country and department: who is here, who is leaving, and
    the roles open or awaiting approval to replace or grow.

    "Vacancies" counted "Approved", "Open" and "Screening" across the whole
    organisation, strings a vacancy never stores, so it read 0 (HR audit,
    2026-09-13). Everything is now bounded by the director's reach.
    """
    from datetime import timedelta

    from apps.core.fy import get_fy_date_range, get_operational_fy
    from apps.hr.models import OffboardingPlan, VacancyStatus
    from apps.hr.reach import people_reach, scope_by_country

    profiles = _search_profiles(
        _profile_scope(request), (request.GET.get("q") or "").strip()
    )
    today = date.today()
    fy = get_operational_fy()
    fy_start = get_fy_date_range(fy)[0].date()
    horizon = today + timedelta(days=90)
    grouped = {
        (item["country"], item["department"] or ""): item
        for item in profiles.exclude(onboarding_state="exited")
        .values("department", "country")
        .annotate(
            headcount=Count("id", filter=Q(user__is_active=True)),
            pending=Count("id", filter=Q(onboarding_state="pending")),
        )
    }
    leaving: dict[tuple, int] = {}
    left: dict[tuple, int] = {}
    for country, department, last_day, status in OffboardingPlan.objects.filter(
        staff_id__in=profiles.values("id"), last_working_day__isnull=False
    ).values_list("staff__country", "staff__department", "last_working_day", "status"):
        key = (country, department or "")
        if today <= last_day <= horizon and status != "Closed":
            leaving[key] = leaving.get(key, 0) + 1
        if fy_start <= last_day <= today:
            left[key] = left.get(key, 0) + 1
    vacancies = scope_by_country(Vacancy.objects.all(), people_reach(request.user))
    open_roles: dict[tuple, int] = {}
    awaiting: dict[tuple, int] = {}
    for country, department, status in vacancies.values_list(
        "country", "department", "status"
    ):
        key = (country, department or "")
        status = (status or "").lower()
        if status == VacancyStatus.OPEN:
            open_roles[key] = open_roles.get(key, 0) + 1
        elif status == VacancyStatus.PENDING_APPROVAL:
            awaiting[key] = awaiting.get(key, 0) + 1
    keys = sorted(set(grouped) | set(open_roles) | set(awaiting) | set(leaving))
    rows = [
        {
            "cells": [
                _cell("Department", key[1] or "Unassigned", primary=True),
                _cell("Country", key[0]),
                _cell("Headcount", grouped.get(key, {}).get("headcount", 0)),
                _cell("Pending activation", grouped.get(key, {}).get("pending", 0)),
                _cell("Left this FY", left.get(key, 0)),
                _cell("Leaving in 90 days", leaving.get(key, 0)),
                _cell("Open roles", open_roles.get(key, 0)),
                _cell("Awaiting approval", awaiting.get(key, 0)),
            ]
        }
        for key in keys
    ]
    headcount = sum(item["headcount"] for item in grouped.values())
    leavers = sum(left.values())
    population = headcount + leavers
    return _render_workspace(
        request,
        title="Workforce Planning",
        eyebrow="People and staffing",
        description=(
            "Staffing by country and department: headcount, who has left and "
            "who is leaving, and the roles open or awaiting approval to replace "
            "or grow."
        ),
        metrics=[
            _metric("Headcount", headcount, "active people in your countries"),
            _metric(
                "Open roles",
                sum(open_roles.values()),
                f"{sum(awaiting.values())} awaiting approval",
                "info",
            ),
            _metric(
                "Leaving in 90 days",
                sum(leaving.values()),
                "last working day ahead",
                "warning" if leaving else "success",
            ),
            _metric(
                "Turnover this FY",
                f"{round(leavers * 100 / population, 1):g}%" if population else "—",
                f"{leavers} left since {fy_start:%b %Y}",
                "info",
            ),
        ],
        rows=rows,
        header_actions=[{"label": "Request a vacancy", "drawer": "/recruitment/new"}],
        primary_action={"label": "Open Recruitment", "href": "/recruitment"},
        empty_title="No workforce profiles in this scope",
    )


@require_page_permission("recruitment")
def recruitment_view(request):
    """Staffing needs: vacancies for growth and replacements after turnover.

    The tiles counted "Open", "Pending Approval" and "Screening", none of which
    a vacancy stores (the codes are lowercase, and screening is an application
    stage), so every tile read 0; and nothing on the page could request,
    approve or close a vacancy although the service could (HR audit,
    2026-09-12).
    """
    from apps.hr.models import VacancyStatus
    from apps.hr.reach import people_reach, scope_by_country

    query = (request.GET.get("q") or "").strip()
    vacancies = scope_by_country(
        Vacancy.objects.select_related("reporting_manager").annotate(
            application_count=Count("applications")
        ),
        people_reach(request.user),
    )
    if query:
        vacancies = vacancies.filter(
            Q(role__icontains=query)
            | Q(department__icontains=query)
            | Q(country__icontains=query)
            | Q(status__icontains=query)
        )
    live = [VacancyStatus.PENDING_APPROVAL, VacancyStatus.APPROVED, VacancyStatus.OPEN]
    rows = []
    for vacancy in vacancies.order_by("-created_at"):
        actions = []
        if vacancy.status in live:
            actions.append({"label": "Review", "drawer": f"/recruitment/{vacancy.id}"})
        rows.append(
            {
                "cells": [
                    _cell(
                        "Vacancy",
                        f"{vacancy.role} · {vacancy.department}"
                        if vacancy.department
                        else vacancy.role,
                        primary=True,
                    ),
                    _cell("Country", vacancy.country),
                    _cell("Type", vacancy.get_replacement_or_new_role_display()),
                    _cell("Applications", vacancy.application_count),
                    _cell("Target start", vacancy.target_start_date),
                    _cell("Status", vacancy.get_status_display(), status=True),
                ],
                "actions": actions,
            }
        )
    open_or_pending = vacancies.filter(status__in=live)
    return _render_workspace(
        request,
        title="Recruitment & Vacancies",
        eyebrow="Staffing and recruiting",
        description=(
            "Staffing needs across the countries you oversee: new roles for growth "
            "and replacements after turnover, from request and approval to an open "
            "post."
        ),
        metrics=[
            _metric(
                "Open",
                vacancies.filter(status=VacancyStatus.OPEN).count(),
                "accepting candidates",
                "success",
            ),
            _metric(
                "Pending approval",
                vacancies.filter(status=VacancyStatus.PENDING_APPROVAL).count(),
                "awaiting a Country Director or the RVP",
                "warning",
            ),
            _metric(
                "Replacements",
                open_or_pending.filter(replacement_or_new_role="replacement").count(),
                "open posts replacing a leaver",
                "info",
            ),
            _metric(
                "Applications",
                Application.objects.filter(vacancy__in=vacancies).count(),
                "across visible vacancies",
            ),
        ],
        rows=rows,
        header_actions=[{"label": "Request a vacancy", "drawer": "/recruitment/new"}]
        if request.user.active_role in ("HumanResources", "Admin")
        else [],
        primary_action={
            "label": "Candidate Pipeline",
            "href": "/candidate-pipeline",
        }
        if request.user.active_role in ("HumanResources", "Admin")
        else None,
        empty_title="No vacancies yet",
        empty_body=(
            "Request a vacancy to start recruiting for a new role or to replace "
            "someone who is leaving."
        ),
    )


@require_page_permission("candidate_pipeline")
def candidate_pipeline_view(request):
    """Every application, by its real selection stage, with the next step."""
    from apps.hr.models import ApplicationStage
    from apps.hr.reach import people_reach, scope_by_country

    query = (request.GET.get("q") or "").strip()
    applications = scope_by_country(
        Application.objects.select_related("candidate", "vacancy"),
        people_reach(request.user),
        "vacancy__country",
    )
    if query:
        applications = applications.filter(
            Q(candidate__name__icontains=query)
            | Q(candidate__email__icontains=query)
            | Q(vacancy__role__icontains=query)
            | Q(stage__icontains=query)
        )
    finished = [
        ApplicationStage.HIRED,
        ApplicationStage.REJECTED,
        ApplicationStage.WITHDRAWN,
    ]
    rows = []
    for application in applications.order_by("-updated_at"):
        actions = []
        if application.stage not in finished:
            label = (
                "Hire"
                if application.stage == ApplicationStage.ACCEPTED
                else "Next step"
            )
            actions.append(
                {"label": label, "drawer": f"/candidate-pipeline/{application.id}"}
            )
        rows.append(
            {
                "cells": [
                    _cell("Candidate", application.candidate.name, primary=True),
                    _cell("Vacancy", application.vacancy.role),
                    _cell("Country", application.vacancy.country),
                    _cell("Stage", application.get_stage_display(), status=True),
                    _cell("Updated", application.updated_at.date()),
                ],
                "actions": actions,
            }
        )
    return _render_workspace(
        request,
        title="Candidate Pipeline",
        eyebrow="Staffing and recruiting",
        description=(
            "Every candidate against the vacancies you oversee, by selection stage, "
            "from application to hire."
        ),
        metrics=[
            _metric(
                "Applications",
                applications.exclude(stage__in=finished).count(),
                "still in selection",
            ),
            _metric(
                "Screening",
                applications.filter(stage=ApplicationStage.SCREENING).count(),
                "in early assessment",
                "info",
            ),
            _metric(
                "Interviews",
                applications.filter(
                    stage__in=[
                        ApplicationStage.INTERVIEW,
                        ApplicationStage.ASSESSMENT,
                        ApplicationStage.REFERENCE_CHECK,
                    ]
                ).count(),
                "interview, assessment or references",
                "warning",
            ),
            _metric(
                "Offers",
                applications.filter(
                    stage__in=[ApplicationStage.OFFER, ApplicationStage.ACCEPTED]
                ).count(),
                "made or accepted",
                "info",
            ),
            _metric(
                "Hired",
                applications.filter(stage=ApplicationStage.HIRED).count(),
                "provisioned employees",
                "success",
            ),
        ],
        rows=rows,
        header_actions=[
            {"label": "Record a candidate", "drawer": "/candidate-pipeline/new"}
        ],
        primary_action={"label": "Vacancies", "href": "/recruitment"},
        empty_title="No candidate applications yet",
        empty_body="Record a candidate against an open vacancy to start selection.",
    )


@require_page_permission("onboarding")
def onboarding_view(request):
    """New hires from invitation to activation, and their probation decision.

    "Active" and "Overdue" counted statuses an onboarding plan never stores,
    so both read 0 and "In progress" swallowed closed plans (HR audit,
    2026-09-12).
    """
    from apps.hr.models import OnboardingStatus
    from apps.hr.onboarding_service import overdue_onboarding

    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    plans = (
        OnboardingPlan.objects.filter(staff_id__in=visible_ids)
        .select_related("staff__user")
        .annotate(
            total_tasks=Count("tasks"),
            completed_tasks=Count("tasks", filter=Q(tasks__is_completed=True)),
        )
    )
    if query:
        plans = plans.filter(
            Q(staff__user__name__icontains=query)
            | Q(staff__country__icontains=query)
            | Q(status__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Team member", plan.staff.user.name, primary=True),
                _cell("Role", plan.staff.title or plan.staff.user.active_role),
                _cell("Country", plan.staff.country),
                _cell("Start date", plan.start_date),
                _cell("Checklist", f"{plan.completed_tasks} of {plan.total_tasks}"),
                _cell("Status", plan.get_status_display(), status=True),
            ],
            "actions": [{"label": "Manage", "drawer": f"/onboarding/{plan.id}"}],
        }
        for plan in plans.order_by("-created_at")
    ]
    open_plans = plans.exclude(status=OnboardingStatus.CLOSED)
    overdue = overdue_onboarding(visible_ids)
    return _render_workspace(
        request,
        title="Staff Onboarding",
        eyebrow="Staffing and recruiting",
        description=(
            "New hires from invitation to activation: checklist, supervisor "
            "confirmation, and the probation decision."
        ),
        metrics=[
            _metric("Plans", open_plans.count(), "onboarding in progress"),
            _metric(
                "Overdue",
                overdue.count(),
                "past their target completion",
                "danger",
            ),
            _metric(
                "Awaiting supervisor",
                plans.filter(status=OnboardingStatus.SUPERVISOR_REVIEW).count(),
                "readiness not yet confirmed",
                "warning",
            ),
            _metric(
                "Ready for activation",
                plans.filter(status=OnboardingStatus.READY_FOR_ACTIVATION).count(),
                "HR can close and activate",
                "success",
            ),
        ],
        rows=rows,
        primary_action={"label": "Candidate Pipeline", "href": "/candidate-pipeline"},
        empty_title="No onboarding plans in this scope",
        empty_body="Hiring a candidate opens their onboarding plan here.",
    )


@require_page_permission("cpd_learning")
def cpd_learning_view(request):
    """HR Professional Development Dashboard (§16) — the management
    command-center sitting beside the employee-owned My Professional
    Development page. Same underlying data, HR/CD/PL oversight scope."""
    from apps.professional_development.hr_dashboard_service import HRPDDashboardService

    if not getattr(request.user, "staff_profile_id", None):
        return HttpResponseForbidden("No staff profile on this account.")
    params = {
        "fy": request.GET.get("fy"),
        "country": request.GET.get("country"),
        "role": request.GET.get("role"),
        "status": request.GET.get("status"),
        "reminder": request.GET.get("reminder"),
        "q": request.GET.get("q"),
        "page": request.GET.get("page"),
    }
    try:
        context = HRPDDashboardService.get_dashboard(request.user, params)
    except ValueError:
        return HttpResponseBadRequest("Invalid filter value.")
    # A Programme Lead reads the page as their team's development: the
    # requests waiting on them first, then the courses to follow up. HR's
    # allocation settings, fund charts and sign-off snapshot are HR's work
    # (Program Lead alignment, 2026-09-13).
    context["pd_body_template"] = (
        "partials/hr/pd_dashboard/team_body.html"
        if context.get("team_view")
        else "partials/hr/pd_dashboard/body.html"
    )
    if (
        request.headers.get("HX-Request") == "true"
        and request.GET.get("partial") == "tracker"
    ):
        return render(request, "partials/hr/pd_dashboard/tracker_table.html", context)
    if request.headers.get("HX-Request") == "true":
        return render(request, context["pd_body_template"], context)
    context["topbar_search"] = {
        "placeholder": "Search PD requests…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "attach_to": "pd-filters",
        "autosubmit": True,
    }
    return render(request, "pages/hr/professional_development_dashboard.html", context)


@require_page_permission("cpd_learning")
def pd_dashboard_adjust_allocation_view(request):
    """GET: the "Adjust Allocation" drawer for one role. POST: save it,
    optionally bulk-applying to every current staff member in that role."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.core.fy import get_operational_fy
    from apps.professional_development.hr_dashboard_service import (
        ROLE_LABELS,
        HRPDDashboardService,
    )
    from apps.professional_development.models import PDRoleAllocation

    # PL / CD / RVP share the page read-only; setting the money is HR's
    # alone (Admin retains platform administration). Gated here as well as
    # in the service so the drawer never renders a form the server would
    # refuse.
    if getattr(request.user, "active_role", "") not in ("HumanResources", "Admin"):
        return HttpResponseForbidden(
            "Only HR may adjust Professional Development allocations."
        )

    role = request.GET.get("role") or request.POST.get("role") or ""
    fy = request.GET.get("fy") or request.POST.get("fy") or get_operational_fy()
    country = request.GET.get("country") or request.POST.get("country") or "Uganda"

    if request.method == "GET":
        existing = PDRoleAllocation.objects.filter(
            role=role, fy=fy, country=country
        ).first()
        from apps.accounts.models import StaffProfile

        staff_count = StaffProfile.objects.filter(
            user__active_role=role, country=country
        ).count()
        return render(
            request,
            "partials/hr/pd_dashboard/adjust_allocation_drawer.html",
            {
                "role": role,
                "role_label": ROLE_LABELS.get(role, role),
                "fy": fy,
                "country": country,
                "existing": existing,
                "staff_count": staff_count,
                "per_staff": (existing.annual_allocation_cents / 100)
                if existing
                else 0,
            },
        )

    try:
        amount = float(request.POST.get("annual_allocation") or 0)
    except ValueError:
        return HttpResponseBadRequest("Invalid amount.")
    try:
        HRPDDashboardService.adjust_role_allocation(
            request.user,
            role=role,
            fy=fy,
            country=country,
            amount_major=amount,
            currency=request.POST.get("currency") or "USD",
            apply_to_existing=request.POST.get("apply_to_existing") == "on",
        )
        messages.success(
            request, f"PD allocation updated for {ROLE_LABELS.get(role, role)}."
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return local_redirect(f"/cpd-learning?fy={fy}&country={country}")


_REMINDER_SENDER = {
    "HumanResources": "HR",
    "Program Lead": "your Programme Lead",
    "CountryDirector": "your Country Director",
    "RegionalVicePresident": "your Regional Vice President",
    "Admin": "a platform administrator",
}


def _reminder_sender(request) -> str:
    """Who a PD reminder says it is from. Every reminder read "Reminder from
    HR", including the ones a Programme Lead sent their own officers."""
    return _REMINDER_SENDER.get(getattr(request.user, "active_role", ""), "HR")


def _scoped_pd_request(request, request_id):
    """A PD request inside the viewer's Professional Development scope, or None.

    The single "Send Reminder" looked the request up by id alone, so anyone
    with the page could post any id and notify any requester in any country
    under HR's name (Program Lead alignment, 2026-09-13). The bulk reminder
    already used this scope; the single one now does too.
    """
    from apps.professional_development.hr_dashboard_service import _scoped_staff_ids
    from apps.professional_development.models import ProfessionalDevelopmentRequest

    if not request_id:
        return None
    scoped_ids, locked_country = _scoped_staff_ids(request.user)
    requests = ProfessionalDevelopmentRequest.objects.filter(id=request_id)
    if scoped_ids is not None:
        requests = requests.filter(staff_id__in=scoped_ids)
    if locked_country:
        requests = requests.filter(country=locked_country)
    return requests.first()


@require_page_permission("cpd_learning")
def pd_supervisor_return_drawer(request):
    """The Return drawer for a team request waiting at the supervisor stage."""
    from apps.frontend.views.hr_programme_views import _drawer, _field
    from apps.professional_development.approval_service import (
        PDApprovalRoutingService,
    )
    from apps.professional_development.models import (
        PDStatus,
        ProfessionalDevelopmentRequest,
    )

    req = (
        ProfessionalDevelopmentRequest.objects.filter(
            id=request.GET.get("request_id") or "",
            status=PDStatus.SUBMITTED_TO_SUPERVISOR,
        )
        .only("id", "staff_id", "status", "staff_name", "course_name", "fy")
        .first()
    )
    if req is None or not PDApprovalRoutingService.can_review(req, request.user):
        return _drawer(
            request,
            title="Return a development request",
            subtitle="Nothing to return",
            empty=(
                "This request is not waiting for your approval. It may already "
                "have been decided, or it is routed to someone else."
            ),
        )
    return _drawer(
        request,
        title=f"Return {req.staff_name}'s request",
        subtitle=f"{req.course_name} · FY {req.fy}",
        action="/cpd-learning/action",
        submit="Return to the officer",
        note=(
            "The request goes back to the officer with your reason. They can "
            "correct it and submit again."
        ),
        fields=[
            _field("action", "", type="hidden", value="supervisor_return"),
            _field("request_id", "", type="hidden", value=req.id),
            _field(
                "reason",
                "Why it is returned",
                type="textarea",
                required=True,
                rows=4,
                maxlength=512,
                placeholder="What needs to change before you can approve it",
            ),
        ],
    )


@require_page_permission("cpd_learning")
def pd_dashboard_action_view(request):
    """send_reminder / sign_off dispatched from the HR Action Center, and a
    supervisor's approve / return from the team's approval list."""
    from apps.core.exceptions import BadRequest, Forbidden

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    action = request.POST.get("action")
    request_id = request.POST.get("request_id")
    try:
        if action == "sign_off":
            from apps.professional_development.completion_service import (
                PDCourseTrackingService,
            )

            # Closing a course releases money; the page offers it to HR alone
            # and the service refuses anyone else, so say so plainly here.
            if not _require_hr(request):
                raise Forbidden("Only HR signs off a completed course.")
            PDCourseTrackingService.sign_off(request_id, request.user)
            messages.success(request, "Course signed off and closed.")
        elif action in ("supervisor_approve", "supervisor_return"):
            # The approval services decide: only the configured supervisor or
            # their active cover, never for their own request, and a return
            # needs its reason. The page only routes the decision.
            from apps.professional_development.approval_service import (
                PDApprovalRoutingService,
            )
            from apps.professional_development.models import (
                ProfessionalDevelopmentRequest,
            )

            if not ProfessionalDevelopmentRequest.objects.filter(
                id=request_id or ""
            ).exists():
                raise BadRequest("That development request no longer exists.")
            if action == "supervisor_approve":
                req = PDApprovalRoutingService.supervisor_approve(
                    request_id, request.user
                )
                messages.success(
                    request,
                    f"{req.staff_name}'s request for “{req.course_name}” is "
                    "approved and sent to HR.",
                )
            else:
                req = PDApprovalRoutingService.supervisor_return(
                    request_id,
                    request.user,
                    (request.POST.get("reason") or "").strip(),
                )
                messages.success(
                    request,
                    f"{req.staff_name}'s request was returned with your reason.",
                )
        elif action in ("send_apply_reminder", "bulk_apply_reminders"):
            # Chasing people who never applied is HR's job, and the bulk set
            # is recomputed server-side from the same definition the panel
            # shows — a posted list of ids is never trusted.
            from apps.notifications.services import WorkflowNotificationService
            from apps.professional_development.hr_dashboard_service import (
                HRPDDashboardService,
            )

            if getattr(request.user, "active_role", "") not in (
                "HumanResources",
                "Admin",
            ):
                raise Forbidden("Only HR may send apply reminders.")
            from apps.core.fy import get_operational_fy

            fy = request.POST.get("fy") or get_operational_fy()
            pending = HRPDDashboardService.staff_without_requests(
                request.user,
                fy,
                country=request.POST.get("country") or "",
                role_filter=request.POST.get("role") or "",
            )
            if action == "send_apply_reminder":
                target_user_id = request.POST.get("staff_user_id") or ""
                pending = [p for p in pending if p["user_id"] == target_user_id]
                if not pending:
                    raise BadRequest(
                        "That staff member has already applied, or is outside "
                        "your scope."
                    )
            sent = 0
            for person in pending:
                if not person["user_id"]:
                    continue
                WorkflowNotificationService.trigger(
                    event_type="pd_action_required",
                    category="professional_development",
                    priority="medium",
                    title="Apply for Professional Development",
                    body=(
                        f"HR reminder: your FY {fy} PD allocation is "
                        f"{person['allocation']} and you have not applied yet — "
                        "open My Professional Development to submit a request."
                    ),
                    context_type="pd_apply_reminder",
                    context_id=person["staff_id"],
                    recipients=[person["user_id"]],
                )
                sent += 1
            if action == "send_apply_reminder":
                messages.success(request, f"Reminder sent to {pending[0]['name']}.")
            else:
                messages.success(
                    request,
                    f"Apply reminders sent to {sent} staff member{'s' if sent != 1 else ''}.",
                )
        elif action == "send_reminder":
            from apps.professional_development.approval_service import (
                PDApprovalRoutingService,
            )

            req = _scoped_pd_request(request, request_id)
            if not req or not req.owner_user_id:
                raise BadRequest("Request not found.")
            sender = _reminder_sender(request)
            PDApprovalRoutingService._notify(
                req.owner_user_id,
                f"Reminder from {sender}",
                f"{request.user.name} ({sender}) sent you a reminder about "
                f"“{req.course_name}” — check My Professional Development for "
                "what's due.",
                req,
            )
            messages.success(request, f"Reminder sent to {req.staff_name}.")
        elif action == "bulk_send_reminders":
            from apps.professional_development.approval_service import (
                PDApprovalRoutingService,
            )
            from apps.professional_development.models import (
                ProfessionalDevelopmentRequest,
            )

            bucket = request.POST.get("bucket") or ""
            due_statuses = {
                "not_started": (
                    "submitted_to_supervisor",
                    "submitted_to_hr",
                    "pending_exception",
                    "approved_pending_funding",
                    "approved_unfunded",
                    "disbursed",
                    "enrollment_pending",
                ),
                "in_progress": ("enrollment_confirmed", "in_progress"),
                "pending_certificate": ("ended", "marked_complete"),
                "pending_accountability": (
                    "bamboohr_confirmed",
                    "accountability_submitted",
                ),
            }.get(bucket, ())
            # Scope the send to exactly what the dashboard was showing. This
            # filtered on status alone — no staff scope, no FY, no country —
            # while the button's own label came from the SCOPED count. A
            # Program Lead with four supervisees clicked "Remind All (4)" and
            # notified every PD requester in every country, in every financial
            # year. `cpd_learning` is granted to PL, CD and RVP as well as HR.
            from apps.professional_development.hr_dashboard_service import (
                _scoped_staff_ids,
            )

            scoped_ids, locked_country = _scoped_staff_ids(request.user)
            reminder_fy = (request.POST.get("fy") or "").strip()
            reminder_country = (
                locked_country or (request.POST.get("country") or "").strip()
            )

            due_qs = ProfessionalDevelopmentRequest.objects.filter(
                status__in=due_statuses
            )
            if scoped_ids is not None:
                due_qs = due_qs.filter(staff_id__in=scoped_ids)
            if reminder_fy:
                due_qs = due_qs.filter(fy=reminder_fy)
            if reminder_country:
                due_qs = due_qs.filter(country=reminder_country)

            sent = 0
            sender = _reminder_sender(request)
            for req in due_qs:
                if req.owner_user_id:
                    PDApprovalRoutingService._notify(
                        req.owner_user_id,
                        f"Reminder from {sender}",
                        f"{request.user.name} ({sender}) sent you a reminder "
                        f"about “{req.course_name}” — check My Professional "
                        "Development.",
                        req,
                    )
                    sent += 1
            messages.success(request, f"Sent {sent} reminder(s).")
        else:
            return HttpResponseBadRequest("Unknown action.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    fy = request.POST.get("fy") or ""
    country = request.POST.get("country") or ""
    return local_redirect(f"/cpd-learning?fy={fy}&country={country}")


@require_page_permission("succession_planning")
def succession_planning_view(request):
    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    candidates = SuccessionCandidate.objects.filter(
        staff_successor_id__in=visible_ids
    ).select_related("staff_successor__user")
    if query:
        candidates = candidates.filter(
            Q(position_name__icontains=query)
            | Q(staff_successor__user__name__icontains=query)
            | Q(readiness__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Critical position", candidate.position_name, primary=True),
                _cell("Successor", candidate.staff_successor.user.name),
                _cell("Current role", candidate.staff_successor.title),
                _cell("Country", candidate.staff_successor.country),
                _cell("Readiness", candidate.readiness, status=True),
                _cell("Updated", candidate.updated_at.date()),
            ]
        }
        for candidate in candidates.order_by(
            "position_name", "staff_successor__user__name"
        )
    ]
    return _render_workspace(
        request,
        title="Succession Planning",
        description="Critical-position continuity built from named successors and explicit readiness assessments—not inferred talent labels.",
        metrics=[
            _metric("Nominations", candidates.count(), "successor records in scope"),
            _metric(
                "Ready now",
                candidates.filter(readiness="Ready Now").count(),
                "immediate successors",
                "success",
            ),
            _metric(
                "6–12 months",
                candidates.filter(readiness="Ready in 6-12 Months").count(),
                "near-term pipeline",
                "info",
            ),
            _metric(
                "Development required",
                candidates.filter(readiness="Development Required").count(),
                "requires action",
                "warning",
            ),
        ],
        rows=rows,
        primary_action={
            "label": "Review Professional Development",
            "href": "/cpd-learning",
        },
        empty_title="No succession nominations in this scope",
    )


@require_page_permission("performance_reviews")
def performance_reviews_view(request):
    """This fiscal year's reviews by stage, with final ratings once calibrated.

    The register read the legacy ``status`` strings ("Completed", "Manager
    Review Pending") and a ``score`` nothing calibrates, while ``stage`` is the
    authority, so its tiles described records that no longer move that way
    (HR audit, 2026-09-13).
    """
    from apps.core.fy import get_operational_fy
    from apps.hr.models import PerformanceRating, ReviewStage

    if getattr(request.user, "active_role", "") == "Program Lead":
        return _team_performance_reviews(request)
    is_hr = _require_hr(request)
    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    reviews = (
        PerformanceReview.objects.filter(staff_id__in=visible_ids)
        .filter(Q(fy=fy) | Q(fy__isnull=True))
        .select_related("staff__user", "manager__user")
    )
    if query:
        reviews = reviews.filter(
            Q(staff__user__name__icontains=query)
            | Q(period__icontains=query)
            | Q(review_type__icontains=query)
            | Q(stage__icontains=query)
        )
    done = (
        ReviewStage.CLOSED,
        ReviewStage.EMPLOYEE_ACKNOWLEDGED,
        ReviewStage.SIGNED_AND_ARCHIVED,
    )
    calibrating = (
        ReviewStage.CALIBRATION,
        ReviewStage.HR_QUALITY_REVIEW,
        ReviewStage.READY_FOR_SLT_CALIBRATION,
    )
    ratings = dict(PerformanceRating.choices)
    today = date.today()
    rows = []
    for review in reviews.order_by("due_date", "staff__user__name"):
        overdue = (
            review.stage not in done and review.due_date and review.due_date < today
        )
        cells = [
            _cell("Team member", review.staff.user.name, primary=True),
            _cell(
                "Review",
                f"{review.get_review_type_display()} · {review.period}",
            ),
            _cell(
                "Manager",
                review.manager.user.name
                if review.manager_id and review.manager.user_id
                else "Not recorded",
            ),
            _cell("Due", review.due_date),
        ]
        # The review-level manager rating is written only by HR's legacy
        # assessment path, so outside HR the column was always blank (Program
        # Lead alignment, 2026-09-13). HR's register keeps it.
        if is_hr:
            cells.append(
                _cell(
                    "Manager rating",
                    ratings.get(review.manager_rating or "", review.manager_rating),
                )
            )
        cells += [
            _cell("Final rating", ratings.get(review.rating or "", review.rating)),
            _cell(
                "Stage",
                "Overdue" if overdue else review.get_stage_display(),
                status=True,
            ),
        ]
        rows.append({"cells": cells})
    return _render_workspace(
        request,
        title="Performance Reviews",
        eyebrow="Performance and talent",
        description=(
            f"FY {fy} reviews for the people you oversee: where each one is in "
            "the cycle, the manager's rating and the final rating once "
            "calibrated."
        ),
        metrics=[
            _metric("Reviews", reviews.count(), f"FY {fy}"),
            _metric(
                "Completed",
                reviews.filter(stage__in=done).count(),
                "acknowledged or archived",
                "success",
            ),
            _metric(
                "Overdue",
                reviews.exclude(stage__in=done).filter(due_date__lt=today).count(),
                "past due and not complete",
                "danger",
            ),
            _metric(
                "Awaiting calibration",
                reviews.filter(stage__in=calibrating).count(),
                "HR or SLT to calibrate",
                "warning",
            ),
        ],
        rows=rows,
        # The performance console is HR's; everyone else was offered a button
        # that refused them.
        primary_action={
            "label": "Open Performance Cycle",
            "href": f"/hr/performance-cycle?fy={fy}",
        }
        if is_hr
        else None,
        empty_title="No performance reviews in this scope",
    )


def _team_performance_reviews(request):
    """Performance Reviews for a Programme Lead: the officers they review.

    The lead participates in the performance reviews of the CCEOs assigned to
    them (the role description, owner 2026-09-13). The register they were
    given was HR's country list with HR's columns: a stale `review.manager`
    written once when the cycle opened, a review-level manager rating nothing
    outside HR ever wrote, and a button to a console that refused them. This
    is the reviewer's view instead: one row per person the lead reviews
    (`review_authority.reviewees_of`, never themself), where their agreement
    stands, the window HR has open, what is saved in that window's
    conversation, who the rule says reviews them, and a link into it. Rows
    are apps.hr.performance_engine.team_review_rows, which the reviewer
    To-Dos read too.
    """
    from apps.hr.performance_engine import REVIEW_DONE_STAGES, team_review_rows

    fy = _requested_fy(request)
    query = (request.GET.get("q") or "").strip().casefold()
    today = date.today()
    team = team_review_rows(request.user, fy=fy, today=today)
    window_open = bool(team and team[0]["window"] not in ("", "none"))

    rows = []
    for row in team:
        if query and query not in row["name"].casefold():
            continue
        review = row["review"]
        reviewer = row["reviewer"]
        if not review:
            columns, reflection, signed = "—", "—", "—"
        else:
            columns = f"{row['manager_saved']} of {row['priorities']}"
            reflection = "Saved" if row["reflection_saved"] else "Not yet"
            if row["signed_off_at"]:
                signed = f"{row['signed_off_at']:%-d %b %Y}"
            elif not window_open:
                signed = "No window open"
            elif not row["snapshot"]:
                # Agreed after HR froze this window's figures: there is no
                # record for this window to sign.
                signed = "Not in this window"
            else:
                signed = "Not yet"
        stage = row["stage_label"] if review else "No agreement"
        if row["overdue_reviews"]:
            stage = "Overdue"
        rows.append(
            {
                "cells": [
                    _cell("CCEO", row["name"], primary=True),
                    _cell("Agreement", stage, status=True),
                    _cell(
                        "Open window",
                        row["window_label"][:1].upper() + row["window_label"][1:]
                        if window_open
                        else "None open",
                    ),
                    _cell("Manager columns", columns),
                    _cell("Reflection", reflection),
                    _cell("Signed off", signed),
                    _cell(
                        "Reviewer",
                        reviewer.user.name
                        if reviewer is not None and reviewer.user_id
                        else "No reviewer recorded",
                    ),
                ],
                "actions": [
                    {
                        "label": "Open conversation",
                        "href": f"/performance-conversation?staff={row['profile'].id}",
                    }
                ],
            }
        )

    waiting = sum(1 for row in team if row["agreement_waiting"] or row["hold_needed"])
    overdue = sum(1 for row in team if row["overdue_reviews"])
    completed = sum(
        1 for row in team if row["review"] and row["review"].stage in REVIEW_DONE_STAGES
    )
    notice = None
    if team and not window_open:
        notice = {
            "tone": "info",
            "text": (
                "No conversation window is open. HR opens each quarter's "
                "window; until then the conversations are read-only."
            ),
        }
    return _render_workspace(
        request,
        title="Performance Reviews",
        eyebrow="Team performance",
        description=(
            f"FY {fy}: the officers you review — where each agreement stands, "
            "what is saved in the open window's conversation, and what is left "
            "before you sign it off."
        ),
        # The lead's own tiles (apps/core/metrics/hr_programme_metrics.py):
        # HR's "People" and "Manager pending" count HR's country register.
        metrics=[
            _metric("Officers you review", len(team), "on your team this FY"),
            _metric(
                "Waiting on you as reviewer",
                waiting,
                "priorities to agree or conversations to hold",
                "warning",
            ),
            _metric("Reviews past due", overdue, "past the review due date", "danger"),
            _metric(
                "Agreements completed", completed, "acknowledged or archived", "success"
            ),
        ],
        rows=rows,
        primary_action=None,
        notice=notice,
        team_view=True,
        empty_title="Nobody to review",
        empty_body=(
            "The officers you supervise appear here once they are assigned to "
            "you as their reporting manager."
        ),
    )


@require_page_permission("recovery_plans")
def recovery_plans_view(request):
    """Performance recovery plans: authorise, follow and close them.

    The tiles counted "Active", "Progress Review", "Escalated" and "Successfully
    Completed", but a plan stores lowercase codes, so every tile read 0; rows
    printed raw codes; and no screen could authorise a formal plan or record
    its outcome although the services could (HR audit, 2026-09-13).
    """
    from datetime import timedelta

    from apps.hr.models import RecoveryStatus

    is_hr = _require_hr(request)
    team_view = getattr(request.user, "active_role", "") == "Program Lead"
    if team_view:
        # A Programme Lead's reach includes their own People record, so a
        # draft plan recommended ABOUT the lead — which HR has not yet
        # authorised or shared — listed on their own team register. The lead
        # follows the plans of the people they review (Program Lead
        # alignment, 2026-09-13).
        from apps.hr.review_authority import reviewees_of

        visible_ids = (
            reviewees_of(request.user)
            .exclude(id=getattr(request.user, "staff_profile_id", None))
            .values("id")
        )
    else:
        visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    plans = PerformanceImprovementPlan.objects.filter(
        staff_id__in=visible_ids
    ).select_related("staff__user")
    if query:
        plans = plans.filter(
            Q(staff__user__name__icontains=query)
            | Q(cause__icontains=query)
            | Q(status__icontains=query)
        )
    today = date.today()
    live = (
        RecoveryStatus.ACTIVE,
        RecoveryStatus.PROGRESS_REVIEW,
        RecoveryStatus.EXTENDED,
    )
    rows = []
    for plan in plans.order_by("status", "end_date"):
        past_end = plan.status in live and plan.end_date and plan.end_date < today
        rows.append(
            {
                "cells": [
                    _cell("Team member", plan.staff.user.name, primary=True),
                    _cell("Plan", plan.get_plan_type_display()),
                    _cell("Cause", plan.get_cause_display()),
                    _cell("Start", plan.start_date),
                    _cell("Review by", plan.end_date),
                    _cell(
                        "Status",
                        "Past review date" if past_end else plan.get_status_display(),
                        status=True,
                    ),
                ],
                "actions": [{"label": "Open", "drawer": f"/recovery-plans/{plan.id}"}],
            }
        )
    return _render_workspace(
        request,
        title="Performance Recovery Plans",
        eyebrow="Performance and talent",
        description=(
            "Informal recovery plans and formal improvement plans: the cause, "
            "the support offered, the review date, and the decision at the end."
        ),
        metrics=[
            _metric(
                "Awaiting authorisation",
                plans.filter(status=RecoveryStatus.DRAFT).count(),
                "formal plans to authorise",
                "warning",
            ),
            _metric(
                "Active",
                plans.filter(status__in=live).count(),
                "under recovery",
                "info",
            ),
            _metric(
                "Ending in 30 days",
                plans.filter(
                    status__in=live,
                    end_date__gte=today,
                    end_date__lte=today + timedelta(days=30),
                ).count(),
                "outcome to decide",
                "warning",
            ),
            _metric(
                "Escalated",
                plans.filter(status=RecoveryStatus.ESCALATED).count(),
                "became conduct cases",
                "danger",
            ),
        ],
        rows=rows,
        header_actions=[
            {"label": "Recommend a formal plan", "drawer": "/recovery-plans/new"}
        ],
        primary_action={
            "label": "Open Performance Cycle",
            "href": "/hr/performance-cycle",
        }
        if is_hr
        else None,
        team_view=team_view,
        empty_title="No recovery plans in this scope",
        empty_body=(
            "A plan you recommend for someone you review appears here while HR "
            "authorises it, and stays while you record its check-ins."
            if team_view
            else "New records will appear here as the connected workflow progresses."
        ),
    )


@require_page_permission("culture_engagement")
def culture_engagement_view(request):
    profiles = _search_profiles(
        _profile_scope(request), (request.GET.get("q") or "").strip()
    )
    grouped = (
        profiles.values("department", "country")
        .annotate(
            people=Count("id"), active=Count("id", filter=Q(onboarding_state="active"))
        )
        .order_by("country", "department")
    )
    rows = [
        {
            "cells": [
                _cell("Team", item["department"] or "Unassigned", primary=True),
                _cell("Country", item["country"]),
                _cell("People", item["people"]),
                _cell("Active", item["active"]),
                _cell(
                    "Activation",
                    f"{round(item['active'] / item['people'] * 100) if item['people'] else 0}%",
                    status=True,
                ),
            ]
        }
        for item in grouped
    ]
    # Same scope as the register itself — the counts leaked what the list hid.
    relations = _employee_relations_scope(request.user)
    return _render_workspace(
        request,
        title="Culture & Engagement",
        description="A conservative workforce-experience view using real activation and employee-relations signals. Survey and eNPS values are intentionally absent until a survey workflow exists.",
        metrics=[
            _metric("People", profiles.count(), "in the visible workforce"),
            _metric(
                "Active",
                profiles.filter(onboarding_state="active").count(),
                "activated team members",
                "success",
            ),
            _metric(
                "Open relations cases",
                relations.exclude(status__in=["Resolved", "Closed"]).count(),
                "confidential follow-up",
                "warning",
            ),
            _metric(
                "Critical cases",
                relations.filter(severity="critical")
                .exclude(status__in=["Resolved", "Closed"])
                .count(),
                "leadership attention",
                "danger",
            ),
        ],
        rows=rows,
        primary_action={"label": "Open People Directory", "href": "/staff"},
        empty_title="No workforce experience data in this scope",
    )


def _employee_relations_scope(viewer_user):
    """Employee-relations cases the viewer may see.

    Now delegates to the canonical service, which scopes on the case's OWN
    country and subject rather than inferring it from the owner's profile —
    possible only since `EmployeeRelationsCase` gained a subject and a country.
    """
    from apps.hr.employee_relations_service import visible_cases

    return visible_cases(viewer_user)


@require_page_permission("employee_relations")
def employee_relations_view(request):
    """Disciplinary matters, grievances, disputes and investigations.

    The register counted title-case statuses ("Resolved", "Triage") while the
    model stores lowercase codes, so Triage and Resolved always read 0 and
    "Open" counted closed cases too; the table printed raw codes; and no
    screen could open or advance a case although the service could (HR
    audit, 2026-09-12).
    """
    from apps.hr import employee_relations_service
    from apps.hr.models import ERCaseStatus, ERCaseType

    query = (request.GET.get("q") or "").strip()
    cases = _employee_relations_scope(request.user).select_related(
        "complainant_staff__user"
    )
    # Reading a restricted people register is itself an accountable act.
    employee_relations_service.record_access(request.user, what="case_register")
    if query:
        cases = cases.filter(
            Q(case_type__icontains=query)
            | Q(status__icontains=query)
            | Q(severity__icontains=query)
            | Q(country__icontains=query)
            | Q(case_owner__name__icontains=query)
            | Q(subject_staff__user__name__icontains=query)
        )
    closed = [ERCaseStatus.RESOLVED, ERCaseStatus.CLOSED]
    in_investigation = [
        ERCaseStatus.INVESTIGATION,
        ERCaseStatus.FINDINGS,
        ERCaseStatus.ACTION,
        ERCaseStatus.APPEAL,
    ]
    rows = []
    for case in cases.order_by("-updated_at"):
        concerns = (
            case.subject_staff.user.name
            if case.subject_staff and case.subject_staff.user
            else "No named individual"
        )
        rows.append(
            {
                "cells": [
                    _cell(
                        "Case",
                        f"{case.get_case_type_display()} · {concerns}",
                        primary=True,
                    ),
                    _cell("Country", case.country),
                    _cell("Severity", case.get_severity_display(), status=True),
                    _cell(
                        "Investigator",
                        case.investigator.name if case.investigator else "Not named",
                    ),
                    _cell(
                        "Opened",
                        case.opened_at.date()
                        if case.opened_at
                        else case.created_at.date(),
                    ),
                    _cell("Status", case.get_status_display(), status=True),
                ],
                "actions": [
                    {"label": "Open case", "drawer": f"/employee-relations/{case.id}"}
                ],
            }
        )
    # Counts over every case in the director's countries, confidential ones
    # included: they know a confidential case exists without seeing whom it
    # concerns.
    from apps.hr.models import EmployeeRelationsCase
    from apps.hr.reach import people_reach, scope_by_country

    all_cases = scope_by_country(
        EmployeeRelationsCase.objects.all(), people_reach(request.user)
    )
    open_cases = all_cases.exclude(status__in=closed)
    return _render_workspace(
        request,
        title="Employee Relations",
        eyebrow="Employee relations",
        description=(
            "Disciplinary matters, grievances, disputes and investigations across "
            "the countries you oversee. Confidential cases show only to the people "
            "working them."
        ),
        metrics=[
            _metric("Open cases", open_cases.count(), "not yet resolved"),
            _metric(
                "Awaiting triage",
                open_cases.filter(
                    status__in=[ERCaseStatus.SUBMITTED, ERCaseStatus.TRIAGE]
                ).count(),
                "submitted or in restricted triage",
                "warning",
            ),
            _metric(
                "Under investigation",
                open_cases.filter(status__in=in_investigation).count(),
                "investigation to appeal",
                "info",
            ),
            _metric(
                "Disciplinary matters",
                open_cases.filter(case_type=ERCaseType.DISCIPLINARY).count(),
                "open",
                "warning",
            ),
            _metric(
                "Critical",
                open_cases.filter(severity="critical").count(),
                "open and critical",
                "danger",
            ),
            _metric(
                "Resolved",
                all_cases.filter(status__in=closed).count(),
                "resolved or closed",
                "success",
            ),
        ],
        rows=rows,
        header_actions=[{"label": "Open a case", "drawer": "/employee-relations/new"}],
        primary_action=_hr_today_action(request),
        empty_title="No employee-relations cases",
        empty_body=(
            "No case you may see is open. Open a case to record a disciplinary "
            "matter, grievance, dispute or investigation."
        ),
    )


@require_page_permission("wellness")
def wellness_view(request):
    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    leaves = Leave.objects.filter(staff_id__in=visible_ids).select_related(
        "staff__user", "covering_staff__user"
    )
    if query:
        leaves = leaves.filter(
            Q(staff__user__name__icontains=query)
            | Q(type__icontains=query)
            | Q(status__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Team member", leave.staff.user.name, primary=True),
                _cell("Leave type", leave.type.replace("_", " ").title()),
                _cell("Dates", f"{leave.start_date} – {leave.end_date}"),
                _cell(
                    "Days",
                    leave.days_charged
                    if leave.days_charged is not None
                    else leave.days,
                ),
                _cell(
                    "Coverage",
                    leave.covering_staff.user.name
                    if leave.covering_staff
                    else leave.coverage_status,
                    status=True,
                ),
                _cell("Status", leave.status.title(), status=True),
            ]
        }
        for leave in leaves.order_by("-created_at")
    ]
    return _render_workspace(
        request,
        title="Staff Wellness & Support",
        description="Real leave, workload-continuity, and coverage signals. Clinical or counseling data is not collected on this platform.",
        metrics=[
            _metric("Leave records", leaves.count(), "visible requests"),
            _metric(
                "Pending",
                leaves.filter(status="pending").count(),
                "awaiting a decision",
                "warning",
            ),
            _metric(
                "Approved",
                leaves.filter(status="approved").count(),
                "confirmed time away",
                "success",
            ),
            _metric(
                "Coverage gaps",
                leaves.filter(covering_staff__isnull=True)
                .exclude(status__in=["rejected", "cancelled"])
                .count(),
                "without a named cover",
                "danger",
            ),
        ],
        rows=rows,
        primary_action={
            "label": "Open Personal Time Off",
            "href": "/personal-time-off/",
        },
        empty_title="No leave or coverage records in this scope",
    )


@require_page_permission("compensation_benefits")
def compensation_benefits_view(request):
    """Pay bands, medical cover, pension and review dates, per employee.

    Salary amounts and bank details stay off the overview: they are in each
    record's drawer, which only HR opens.
    """
    from datetime import timedelta

    from apps.hr.models import CompensationStatus

    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    records = CompensationRecord.objects.filter(
        staff_id__in=visible_ids
    ).select_related("staff__user")
    if query:
        records = records.filter(
            Q(staff__user__name__icontains=query)
            | Q(salary_band__icontains=query)
            | Q(pension_scheme__icontains=query)
            | Q(status__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Team member", record.staff.user.name, primary=True),
                _cell("Country", record.staff.country),
                _cell("Salary band", record.salary_band),
                _cell("Medical cover", record.get_medical_cover_display()),
                _cell("Pension", record.pension_scheme or "None recorded"),
                _cell("Next review", record.next_review_date),
                _cell("Status", record.get_status_display(), status=True),
            ],
            "actions": [
                {
                    "label": "Update",
                    "drawer": f"/compensation-benefits/{record.staff_id}",
                }
            ],
        }
        for record in records.order_by("staff__user__name")
    ]
    profiles = _profile_scope(request).exclude(onboarding_state="exited")
    soon = date.today() + timedelta(days=30)
    return _render_workspace(
        request,
        title="Compensation & Benefits",
        eyebrow="Rewards and wellbeing",
        description=(
            "Salary bands, medical cover, pension and review dates for the people "
            "you oversee. Amounts and bank details stay inside each record."
        ),
        metrics=[
            _metric("Compensation profiles", records.count(), "configured records"),
            _metric(
                "Approved",
                records.filter(status=CompensationStatus.APPROVED).count(),
                "completed HR review",
                "success",
            ),
            _metric(
                "In review",
                records.filter(status=CompensationStatus.HR_REVIEW).count(),
                "requiring HR action",
                "warning",
            ),
            _metric(
                "Pay reviews due",
                records.filter(next_review_date__lte=soon).count(),
                "pay reviews due in 30 days",
                "info",
            ),
            _metric(
                "Missing profiles",
                profiles.exclude(compensation_details__isnull=False).count(),
                "current staff without a record",
                "warning",
            ),
        ],
        rows=rows,
        header_actions=[
            {"label": "Add a record", "drawer": "/compensation-benefits/new"}
        ],
        primary_action={"label": "People Directory", "href": "/staff"},
        empty_title="No compensation profiles in this scope",
        empty_body="Add a record to capture an employee's band, benefits and review date.",
    )


@require_page_permission("health_safety")
def health_safety_view(request):
    """Occupational health and safety: incidents, near misses and hazards."""
    from datetime import timedelta

    from apps.hr.models import SafetyIncident, SafetyIncidentStatus
    from apps.hr.reach import people_reach, scope_by_country

    query = (request.GET.get("q") or "").strip()
    incidents = scope_by_country(
        SafetyIncident.objects.select_related("affected_staff__user"),
        people_reach(request.user),
    )
    if query:
        incidents = incidents.filter(
            Q(category__icontains=query)
            | Q(location__icontains=query)
            | Q(country__icontains=query)
            | Q(affected_staff__user__name__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell(
                    "Incident",
                    f"{incident.get_category_display()} · "
                    + (
                        incident.affected_staff.user.name
                        if incident.affected_staff
                        else "No one injured"
                    ),
                    primary=True,
                ),
                _cell("Country", incident.country),
                _cell("Date", incident.incident_date),
                _cell("Severity", incident.get_severity_display(), status=True),
                _cell("Days lost", incident.days_lost),
                _cell("Status", incident.get_status_display(), status=True),
            ],
            "actions": [{"label": "Open", "drawer": f"/health-safety/{incident.id}"}],
        }
        for incident in incidents.order_by("-incident_date")
    ]
    open_incidents = incidents.exclude(status=SafetyIncidentStatus.CLOSED)
    year_ago = date.today() - timedelta(days=365)
    return _render_workspace(
        request,
        title="Health & Safety",
        eyebrow="Rewards and wellbeing",
        description=(
            "Occupational health and safety across the countries you oversee: "
            "incidents, near misses and hazards, and the corrective action taken."
        ),
        metrics=[
            _metric(
                "Open incidents", open_incidents.count(), "not yet closed", "warning"
            ),
            _metric(
                "Serious incidents",
                open_incidents.filter(severity__in=["high", "critical"]).count(),
                "high or critical, open",
                "danger",
            ),
            _metric(
                "Near misses",
                incidents.filter(
                    category="near_miss", incident_date__gte=year_ago
                ).count(),
                "reported in the last 12 months",
                "info",
            ),
            _metric(
                "Days lost",
                sum(
                    incidents.filter(incident_date__gte=year_ago).values_list(
                        "days_lost", flat=True
                    )
                ),
                "to incidents in the last 12 months",
                "warning",
            ),
        ],
        rows=rows,
        header_actions=[
            {"label": "Report an incident", "drawer": "/health-safety/new"}
        ],
        primary_action=_hr_today_action(request),
        empty_title="No incidents recorded",
        empty_body=(
            "Report injuries, road traffic incidents, near misses and hazards so "
            "their causes can be fixed."
        ),
    )


@require_page_permission("recognition")
def recognition_view(request):
    """Recognition given to staff: the productivity, recognition and morale
    programme in the role description."""
    from datetime import timedelta

    from apps.hr.models import StaffRecognition
    from apps.hr.reach import people_reach, scope_by_country

    query = (request.GET.get("q") or "").strip()
    recognitions = scope_by_country(
        StaffRecognition.objects.select_related("staff__user", "awarded_by"),
        people_reach(request.user),
    )
    if query:
        recognitions = recognitions.filter(
            Q(staff__user__name__icontains=query)
            | Q(category__icontains=query)
            | Q(citation__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Team member", item.staff.user.name, primary=True),
                _cell("Country", item.country),
                _cell("Recognised for", item.get_category_display()),
                _cell(
                    "Citation",
                    item.citation[:90] + ("…" if len(item.citation) > 90 else ""),
                ),
                _cell("Awarded", item.awarded_on),
            ]
        }
        for item in recognitions.order_by("-awarded_on")
    ]
    quarter_ago = date.today() - timedelta(days=91)
    recent = recognitions.filter(awarded_on__gte=quarter_ago)
    staff_in_scope = _profile_scope(request).exclude(onboarding_state="exited").count()
    recognised_people = recent.values("staff_id").distinct().count()
    return _render_workspace(
        request,
        title="Recognition",
        eyebrow="Rewards and wellbeing",
        description=(
            "Recognition given to staff across the countries you oversee, so good "
            "work is named and nobody goes a year unrecognised."
        ),
        metrics=[
            _metric(
                "Recognitions", recent.count(), "given in the last quarter", "success"
            ),
            _metric(
                "People recognised",
                recognised_people,
                f"of {staff_in_scope} staff, last quarter",
                "info",
            ),
        ],
        rows=rows,
        header_actions=[{"label": "Recognise someone", "drawer": "/recognition/new"}],
        primary_action={"label": "Staff Pulse Surveys", "href": "/pulse-surveys"},
        empty_title="No recognition recorded yet",
        empty_body="Recognise someone to record what they did and why it mattered.",
    )


@require_page_permission("pulse_surveys")
def pulse_surveys_view(request):
    """Anonymous staff pulse surveys and their results."""
    from apps.hr.models import PulseSurvey, PulseSurveyStatus
    from apps.hr.reach import people_reach
    from apps.hr.rewards_wellbeing_service import survey_results

    reach = people_reach(request.user)
    surveys = [
        survey
        for survey in PulseSurvey.objects.order_by("-opens_on")
        if all(reach.allows_country(c) for c in (survey.countries or []))
    ]
    rows = []
    latest_overall = None
    for survey in surveys:
        results = survey_results(survey)
        if latest_overall is None and results["shown"]:
            latest_overall = results["overall"]
        rows.append(
            {
                "cells": [
                    _cell("Survey", survey.title, primary=True),
                    _cell("Countries", ", ".join(survey.countries or [])),
                    _cell(
                        "Open",
                        f"{survey.opens_on:%d %b} to {survey.closes_on:%d %b %Y}",
                    ),
                    _cell("Responses", results["count"]),
                    _cell(
                        "Score",
                        f"{results['overall']} of 5"
                        if results["shown"]
                        else "Too few to show",
                    ),
                    _cell("Status", survey.get_status_display(), status=True),
                ],
                "actions": [
                    {"label": "Results", "drawer": f"/pulse-surveys/{survey.id}"}
                ],
            }
        )
    open_count = sum(1 for s in surveys if s.status == PulseSurveyStatus.OPEN)
    return _render_workspace(
        request,
        title="Staff Pulse Surveys",
        eyebrow="Rewards and wellbeing",
        description=(
            "Short anonymous surveys on purpose, support, workload, recognition "
            "and growth, to find what demotivates staff before it costs a "
            "resignation. Results show only once five people have answered."
        ),
        metrics=[
            _metric("Open surveys", open_count, "collecting answers", "info"),
            _metric(
                "Latest morale score",
                f"{latest_overall} of 5" if latest_overall is not None else "—",
                "average across the five statements",
                "success",
            ),
        ],
        rows=rows,
        header_actions=[{"label": "Open a survey", "drawer": "/pulse-surveys/new"}],
        primary_action={"label": "Recognition", "href": "/recognition"},
        empty_title="No pulse survey yet",
        empty_body="Open a survey to hear from staff anonymously.",
    )


@require_page_permission("payroll_readiness")
def payroll_readiness_view(request):
    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    records = PayrollReadinessRecord.objects.filter(
        staff_id__in=visible_ids
    ).select_related("staff__user")
    if query:
        records = records.filter(
            Q(staff__user__name__icontains=query)
            | Q(payroll_period__icontains=query)
            | Q(exception_notes__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Team member", record.staff.user.name, primary=True),
                _cell("Role", record.staff.title or record.staff.user.active_role),
                _cell("Country", record.staff.country),
                _cell("Payroll period", record.payroll_period),
                _cell(
                    "Exceptions",
                    "Yes" if record.has_exceptions else "None",
                    status=record.has_exceptions,
                ),
                _cell(
                    "Readiness",
                    "Ready" if record.is_payroll_ready else "Pending",
                    status=True,
                ),
            ]
        }
        for record in records.order_by("-payroll_period", "staff__user__name")
    ]
    latest_period = (
        records.order_by("-payroll_period")
        .values_list("payroll_period", flat=True)
        .first()
    )
    latest = (
        records.filter(payroll_period=latest_period)
        if latest_period
        else records.none()
    )
    return _render_workspace(
        request,
        title="Payroll Readiness",
        description="Period-specific payroll checks that expose exceptions and readiness without revealing banking or salary details.",
        metrics=[
            _metric(
                "Current period", latest_period or "—", "latest configured payroll run"
            ),
            _metric("Staff checked", latest.count(), "records in latest period"),
            _metric(
                "Ready",
                latest.filter(is_payroll_ready=True).count(),
                "cleared for payroll",
                "success",
            ),
            _metric(
                "Exceptions",
                latest.filter(has_exceptions=True).count(),
                "requiring resolution",
                "danger",
            ),
        ],
        rows=rows,
        primary_action={
            "label": "Open the People Directory",
            "href": "/staff",
        },
        empty_title="No payroll-readiness checks in this scope",
    )


@require_page_permission("compliance_register")
def compliance_register_view(request):
    """Compliance with country employment law, employee by employee.

    Mandatory requirements an employee has no record against are listed first
    as missing, so the register shows the gaps rather than only the evidence
    someone already filed.
    """
    from apps.hr.compliance_service import compliance_gaps, visible_requirements
    from apps.hr.models import ComplianceStatus

    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    records = EmployeeComplianceRecord.objects.filter(
        staff_id__in=visible_ids
    ).select_related("staff__user", "requirement", "verified_by")
    if query:
        records = records.filter(
            Q(staff__user__name__icontains=query)
            | Q(requirement__name__icontains=query)
            | Q(requirement__country__icontains=query)
            | Q(status__icontains=query)
        )
    gaps = compliance_gaps(request.user)
    if query:
        needle = query.lower()
        gaps = [
            (profile, requirement)
            for profile, requirement in gaps
            if needle in profile.user.name.lower()
            or needle in requirement.name.lower()
            or needle in (profile.country or "").lower()
            or needle in "missing"
        ]
    rows = [
        {
            "cells": [
                _cell("Team member", profile.user.name, primary=True),
                _cell("Requirement", requirement.name),
                _cell("Country", profile.country),
                _cell("Expiry", None),
                _cell("Verified by", "No evidence on file"),
                _cell("Status", ComplianceStatus.MISSING.label, status=True),
            ],
            "actions": [
                {
                    "label": "Record",
                    "drawer": (
                        f"/compliance-register/new?staff={profile.id}"
                        f"&requirement={requirement.id}"
                    ),
                }
            ],
        }
        for profile, requirement in gaps
    ]
    urgency = {
        ComplianceStatus.EXPIRED: 0,
        ComplianceStatus.MISSING: 1,
        ComplianceStatus.DUE_SOON: 2,
        ComplianceStatus.COMPLIANT: 3,
    }
    ordered = sorted(
        records.order_by("expiry_date", "staff__user__name"),
        key=lambda record: urgency.get(record.status, 4),
    )
    rows += [
        {
            "cells": [
                _cell("Team member", record.staff.user.name, primary=True),
                _cell("Requirement", record.requirement.name),
                _cell("Country", record.requirement.country),
                _cell("Expiry", record.expiry_date),
                _cell(
                    "Verified by",
                    record.verified_by.name if record.verified_by else "Not verified",
                ),
                _cell("Status", record.get_status_display(), status=True),
            ],
            "actions": [
                {"label": "Update", "drawer": f"/compliance-register/{record.id}"}
            ],
        }
        for record in ordered
    ]
    requirements = visible_requirements(request.user)
    return _render_workspace(
        request,
        title="Employment Compliance",
        eyebrow="Policy and compliance",
        description=(
            "Country employment-law requirements (contracts, work permits, "
            "statutory registrations) and the evidence each employee holds. A "
            "status follows its document and expiry date."
        ),
        metrics=[
            _metric(
                "Requirements", requirements.count(), "configured for your countries"
            ),
            _metric(
                "Compliant",
                records.filter(status=ComplianceStatus.COMPLIANT).count(),
                "evidence in date",
                "success",
            ),
            _metric(
                "Due soon",
                records.filter(status=ComplianceStatus.DUE_SOON).count(),
                "expiring within 30 days",
                "warning",
            ),
            _metric(
                "Missing or expired",
                records.filter(
                    status__in=[ComplianceStatus.MISSING, ComplianceStatus.EXPIRED]
                ).count()
                + len(gaps),
                "requiring remediation",
                "danger",
            ),
        ],
        rows=rows,
        header_actions=[
            {"label": "Record evidence", "drawer": "/compliance-register/new"},
            {
                "label": "Add a requirement",
                "drawer": "/compliance-register/requirement",
            },
        ],
        primary_action={"label": "Policies & Documents", "href": "/policies"},
        empty_title="No employee compliance records yet",
        empty_body=(
            "Add the employment-law requirements for your countries, then record "
            "each employee's evidence."
        ),
    )


@require_page_permission("policies")
def policies_view(request):
    """The policies and manuals the Regional HR Director owns, and who has
    acknowledged them.

    This page listed `hr.ComplianceRequirement` rows, which nothing writes, and
    said acknowledgements were not tracked "until a dedicated acknowledgement
    model exists" while `DocumentAcknowledgement` recorded every agreement
    behind the first-login gate (HR audit, 2026-09-12). It now lists the
    documents themselves, per country, with their review dates and the
    acknowledgement coverage of the people the director oversees.
    """
    from datetime import timedelta

    from apps.documents.models import (
        AcknowledgementState,
        DocumentAcknowledgement,
        DocumentAsset,
        DocumentStatus,
        DocumentType,
    )
    from apps.hr.reach import people_reach, scope_profiles

    reach = people_reach(request.user)
    query = (request.GET.get("q") or "").strip()
    documents = (
        DocumentAsset.objects.filter(
            document_type__in=[DocumentType.POLICY, DocumentType.MANUAL]
        )
        .exclude(status=DocumentStatus.ARCHIVED)
        .select_related("current_version")
    )
    if not reach.is_everything:
        documents = documents.filter(
            Q(country="") | Q(country__in=list(reach.countries))
        )
    if query:
        documents = documents.filter(
            Q(title__icontains=query)
            | Q(category__icontains=query)
            | Q(country__icontains=query)
        )
    documents = list(documents.order_by("title"))

    people = set(
        scope_profiles(StaffProfile.objects.all(), reach)
        .exclude(user_id=None)
        .values_list("user_id", flat=True)
    )
    version_ids = [d.current_version_id for d in documents if d.current_version_id]
    counts: dict[tuple[str, str], int] = {}
    acknowledgements = DocumentAcknowledgement.objects.filter(
        version_id__in=version_ids
    )
    if not reach.is_everything:
        acknowledgements = acknowledgements.filter(user_id__in=people)
    for row in acknowledgements.values("document_id", "state").annotate(n=Count("id")):
        counts[(row["document_id"], row["state"])] = row["n"]

    today = date.today()
    review_soon = today + timedelta(days=60)
    rows = []
    agreed_total = asked_total = disagreed_total = reviews_due = 0
    for document in documents:
        version = document.current_version
        agreed = counts.get((document.id, AcknowledgementState.AGREED), 0)
        pending = counts.get((document.id, AcknowledgementState.PENDING), 0)
        disagreed = counts.get((document.id, AcknowledgementState.DISAGREED), 0)
        asked = agreed + pending + disagreed
        agreed_total += agreed
        asked_total += asked
        disagreed_total += disagreed
        review_date = getattr(version, "review_date", None)
        if review_date and review_date <= review_soon:
            reviews_due += 1
        rows.append(
            {
                "cells": [
                    _cell("Document", document.title, primary=True),
                    _cell("Type", document.get_document_type_display()),
                    _cell("Country", document.country or "All countries"),
                    _cell(
                        "Version",
                        f"v{version.version_number}" if version else "No version yet",
                    ),
                    _cell("Review by", review_date),
                    _cell(
                        "Acknowledged",
                        f"{agreed} of {asked}"
                        if document.acknowledgement_required
                        else "Not required",
                    ),
                    _cell("Status", document.get_status_display(), status=True),
                ],
                "actions": [
                    {"label": "Manage", "href": f"/documents/{document.slug}/manage"}
                ],
            }
        )
    published = sum(
        1
        for d in documents
        if d.status in (DocumentStatus.PUBLISHED, DocumentStatus.EFFECTIVE)
    )
    awaiting = sum(
        1
        for d in documents
        if d.status
        in (DocumentStatus.DRAFT, DocumentStatus.UNDER_REVIEW, DocumentStatus.RETURNED)
    )
    return _render_workspace(
        request,
        title="Policies & Documents",
        eyebrow="Policy and compliance",
        description=(
            "The policies and manuals that apply to the countries you oversee: "
            "their current version, when each is due for review, and who has "
            "acknowledged it."
        ),
        metrics=[
            _metric("Published policies", published, "in force", "success"),
            _metric(
                "Policies in review",
                awaiting,
                "draft, in review or returned",
                "warning",
            ),
            _metric(
                "Acknowledgement rate",
                f"{round(agreed_total * 100 / asked_total)}%" if asked_total else "—",
                "of required acknowledgements agreed",
                "info",
            ),
            _metric(
                "Policy reviews due",
                reviews_due,
                "review date within 60 days",
                "warning",
            ),
            _metric(
                "Disagreements",
                disagreed_total,
                "staff who did not agree",
                "danger" if disagreed_total else "success",
            ),
        ],
        rows=rows,
        header_actions=[{"label": "Publish a policy", "href": "/uploads/new"}],
        primary_action={"label": "Policy Compliance", "href": "/policy-compliance"},
        empty_title="No policies yet",
        empty_body="Publish a policy or manual to track its review and acknowledgement here.",
    )


@require_page_permission("offboarding")
def offboarding_view(request):
    """Exits: why people leave, who takes over, and the account closed on time."""
    from apps.hr.models import VOLUNTARY_EXIT_REASONS
    from apps.hr.offboarding_service import accounts_past_last_working_day

    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    plans = OffboardingPlan.objects.filter(staff_id__in=visible_ids).select_related(
        "staff__user", "handover_owner__user"
    )
    if query:
        plans = plans.filter(
            Q(staff__user__name__icontains=query)
            | Q(status__icontains=query)
            | Q(exit_reason__icontains=query)
            | Q(handover_owner__user__name__icontains=query)
        )
    overdue_exits = (
        accounts_past_last_working_day().filter(staff_id__in=visible_ids).count()
    )
    rows = [
        {
            "cells": [
                _cell("Team member", plan.staff.user.name, primary=True),
                _cell("Country", plan.staff.country),
                _cell("Last working day", plan.last_working_day),
                _cell(
                    "Reason",
                    plan.get_exit_reason_display()
                    if plan.exit_reason
                    else "Not recorded",
                ),
                _cell(
                    "Handover owner",
                    plan.handover_owner.user.name
                    if plan.handover_owner
                    else "Unassigned",
                ),
                _cell("Status", plan.status, status=True),
            ],
            "actions": [{"label": "Open", "drawer": f"/offboarding/{plan.id}"}],
        }
        for plan in plans.order_by("last_working_day")
    ]
    open_plans = plans.exclude(status="Closed")
    return _render_workspace(
        request,
        title="Staff Offboarding",
        eyebrow="Staffing and recruiting",
        description=(
            "Exits across the countries you oversee: the reason for leaving, the "
            "handover, and the account closed on the last working day."
        ),
        metrics=[
            _metric("In progress", open_plans.count(), "exits being worked", "warning"),
            _metric(
                "Handover gaps",
                open_plans.filter(handover_owner__isnull=True).count(),
                "without a named owner",
                "danger",
            ),
            _metric(
                "Voluntary exits",
                plans.filter(exit_reason__in=list(VOLUNTARY_EXIT_REASONS)).count(),
                "resignations and retirements",
                "info",
            ),
            _metric(
                "Past exit date, still active",
                overdue_exits,
                "accounts to close now",
                "danger" if overdue_exits else "success",
            ),
        ],
        rows=rows,
        header_actions=[
            {"label": "Start an offboarding", "drawer": "/offboarding/new"}
        ],
        primary_action={"label": "Recruitment", "href": "/recruitment"},
        empty_title="No offboarding in this scope",
        empty_body="Start an offboarding when someone resigns, retires or is leaving.",
    )


def _hr_analytics_workspace(request) -> dict:
    """Everything the HR analytics register shows, for both of its homes.

    /hr-analytics is the HR module's own page with its breadcrumb and module
    chrome; the Analytics workspace reaches the same register at
    /analytics/people, so crossing into People does not change the page around
    the reader (owner, 2026-09-05).
    """

    profiles = _search_profiles(
        _profile_scope(request), (request.GET.get("q") or "").strip()
    )
    grouped = (
        profiles.values("country", "department")
        .annotate(
            headcount=Count("id"),
            active=Count("id", filter=Q(onboarding_state="active")),
            pending=Count("id", filter=Q(onboarding_state="pending")),
        )
        .order_by("country", "department")
    )
    rows = [
        {
            "cells": [
                _cell("Country", item["country"], primary=True),
                _cell("Department", item["department"] or "Unassigned"),
                _cell("Headcount", item["headcount"]),
                _cell("Active", item["active"]),
                _cell("Pending", item["pending"], status=item["pending"] > 0),
                _cell(
                    "Activation rate",
                    f"{round(item['active'] / item['headcount'] * 100) if item['headcount'] else 0}%",
                ),
            ]
        }
        for item in grouped
    ]
    reviews = PerformanceReview.objects.filter(staff_id__in=profiles.values("id"))
    compliance = EmployeeComplianceRecord.objects.filter(
        staff_id__in=profiles.values("id")
    )
    return dict(
        title="HR Analytics & Workforce Insights",
        description="Live workforce, review, and compliance signals computed from current operational records. Unsupported demographic and salary-correlation claims are intentionally excluded.",
        metrics=[
            _metric("Headcount", profiles.count(), "people in scope"),
            _metric(
                "Countries",
                profiles.values("country").distinct().count(),
                "operating footprint",
            ),
            _metric(
                "Reviews due",
                reviews.exclude(status__in=["Completed", "Closed"]).count(),
                "open review workload",
                "warning",
            ),
            _metric(
                "Compliance gaps",
                compliance.filter(status__in=["Missing", "Expired"]).count(),
                "missing or expired evidence",
                "danger",
            ),
        ],
        rows=rows,
        primary_action={"label": "Review HR Dashboard", "href": "/dashboard"},
        empty_title="No workforce analytics in this scope",
    )


@require_page_permission("hr_analytics")
def hr_analytics_view(request):
    return _render_workspace(request, **_hr_analytics_workspace(request))


@require_page_permission("hr_analytics")
def people_analytics_section_view(request):
    """People Analytics as a tab of the one Analytics page."""

    workspace = _hr_analytics_workspace(request)
    paginator = Paginator(workspace["rows"], 25)
    page = paginator.get_page(request.GET.get("page") or 1)
    from apps.frontend.views.analytics_render import render_analytics_section

    return render_analytics_section(
        request,
        "partials/analytics/panels/people_analytics.html",
        {
            **workspace,
            "page_obj": page,
            "rows": page.object_list,
            "search": (request.GET.get("q") or "").strip(),
        },
        section_key="people",
        panel_title=workspace["title"],
        frame={
            "question": (
                "Where are workforce capacity, review workload or compliance "
                "gaps most likely to constrain delivery?"
            ),
            "evidence": "Live workforce, review and compliance records",
            "freshness": "Current operational scope",
            "confidence": "No unsupported demographic inference",
        },
    )


def _audit_action_label(action: str) -> str:
    """ "hr.er_case_opened" reads "Er case opened" under its area, not as a code."""
    area, _, name = (action or "").partition(".")
    areas = {
        "hr": "HR",
        "pd": "Professional development",
        "leave": "Leave",
        "documents": "Policy",
        "admin": "Accounts",
    }
    words = (name or area).replace("_", " ").replace(".", " ").strip()
    if not words:
        return action or "—"
    return f"{areas.get(area, area.title())} · {words[0].upper()}{words[1:]}"


@require_page_permission("hr_audit_log")
def hr_audit_log_view(request):
    """The real HR trail, from the tamper-evident chain.

    This read `HRAuditEvent` — a second, hash-chain-less audit table with no
    writer anywhere in the codebase. The page therefore rendered zero rows
    while describing itself as the accountability view for sensitive HR
    actions, which reads as "nothing has happened" rather than "nothing can be
    recorded here". Meanwhile the actual trail — leave decisions, PD approvals,
    coverage grants, supervisor changes, account disablement, allocation
    changes — was accumulating in `apps.audit.AuditLog` all along.
    """
    from apps.audit.models import AuditLog

    query = (request.GET.get("q") or "").strip()
    # Policy events (published, agreed, disagreed, commented) belong on the
    # HR trail too: the director owns those policies (HR audit, 2026-09-12).
    events = AuditLog.objects.filter(
        Q(action__startswith="hr.")
        | Q(action__startswith="pd.")
        | Q(action__startswith="pd_")
        | Q(action__startswith="leave.")
        | Q(action__startswith="documents.")
        | Q(action__startswith="admin.user")
        | Q(action__startswith="admin.supervisor")
    )
    if query:
        events = events.filter(
            Q(action__icontains=query)
            | Q(actor_role__icontains=query)
            | Q(subject_id__icontains=query)
            | Q(subject_kind__icontains=query)
        )
    events = events.order_by("-created_at")

    actor_names = dict(
        StaffProfile.objects.filter(
            user_id__in=[e.actor_id for e in events[:200] if e.actor_id]
        )
        .select_related("user")
        .values_list("user_id", "user__name")
    )
    rows = [
        {
            "cells": [
                _cell("Action", _audit_action_label(event.action), primary=True),
                _cell(
                    "Actor",
                    actor_names.get(event.actor_id, event.actor_id or "System"),
                ),
                _cell("Role", event.actor_role),
                _cell(
                    "Record", f"{event.subject_kind or '—'} · {event.subject_id or '—'}"
                ),
                _cell(
                    "Outcome",
                    "Success" if event.success else "Refused",
                    status=True,
                ),
                _cell("Timestamp", event.created_at.strftime("%d %b %Y, %H:%M")),
            ]
        }
        for event in events[:200]
    ]
    total = events.count()
    return _render_workspace(
        request,
        title="HR System Audit Log",
        eyebrow="Policy and compliance",
        description="Sensitive people decisions as recorded on the platform's tamper-evident, hash-chained audit trail. Payload detail stays out of the list to limit incidental PII exposure.",
        metrics=[
            _metric("Events", total, "matching audit records"),
            _metric(
                "Refused actions",
                events.filter(success=False).count(),
                "denied or blocked attempts",
                "warning",
            ),
            _metric(
                "Acting roles",
                events.values("actor_role").distinct().count(),
                "roles represented",
            ),
            _metric(
                "Showing",
                min(total, 200),
                "most recent events",
                "info",
            ),
        ],
        rows=rows,
        # System Health is Admin-only; the button refused HR (HR audit,
        # 2026-09-12).
        primary_action=_hr_today_action(request),
        empty_title="No HR audit events recorded yet",
    )


@require_page_permission("my_performance")
def my_performance_view(request, tab=None):
    """My Performance — the employee's agreement, live progress, development
    and values. Progress is derived on read from the verified ledger; the
    page never shows a typed number."""
    from apps.hr.models import PerformanceCycle, PerformanceReview
    from apps.hr.performance_engine import development_rows

    sp = getattr(request.user, "staff_profile", None)
    if sp is None:
        return render_access_denied(request, "No staff profile is linked.")
    from apps.core.fy import get_operational_fy

    from apps.hr.accountability import allocation_priorities

    distributed = allocation_priorities(request.user, request.GET.get("fy"))
    fy = distributed["fy"]
    cycle = PerformanceCycle.objects.filter(fy=fy).first()
    review = PerformanceReview.objects.filter(
        staff=sp, fy=fy, review_type="annual_priorities"
    ).first()
    if cycle and review is None:
        from apps.hr.performance_engine import build_draft_agreement

        review = build_draft_agreement(
            sp, cycle, request.user, include_role_templates=False
        )

    overall_pct = distributed["pct"]

    WINDOW_LABELS = {
        "priority_setting": "Priority Setting",
        "q1": "Q1 Check-in",
        "q2_midyear": "Q2 Mid-Year",
        "q3": "Q3 Check-in",
        "q4_yearend": "Q4 Year-End",
    }
    amendments = []
    if review:
        from apps.hr.models import PriorityAmendment

        amendments = list(
            PriorityAmendment.objects.filter(priority__review=review)
            .select_related("priority", "requested_by")
            .order_by("-created_at")[:20]
        )
    snapshots = []
    if review:
        for snap in review.snapshots.order_by("created_at"):
            snapshots.append(
                {"snap": snap, "label": WINDOW_LABELS.get(snap.window, snap.window)}
            )

    user_role = getattr(request.user, "active_role", "")
    MANAGER_ROLES = {
        "Program Lead",
        "PL",
        "CountryDirector",
        "CD",
        "RegionalVicePresident",
        "RVP",
        "HumanResources",
        "HR",
        "Admin",
    }
    show_open_conversation = user_role in MANAGER_ROLES
    context = {
        "cycle": cycle,
        "review": review,
        "development": development_rows(review) if review else [],
        "values": list(review.value_commitments.filter(kind="value")) if review else [],
        "spiritual": list(review.value_commitments.filter(kind="spiritual"))
        if review
        else [],
        "distributed": distributed,
        "fy": fy,
        "caps": {"employee"}
        if review
        and fy == get_operational_fy()
        and cycle
        and cycle.active_window != "none"
        else set(),
        "signed": bool(review and review.stage in {"signed_off", "archived"}),
        "can_distribute": user_role in {"ImpactAssessment", "Admin"},
        "can_distribute_team": user_role in {"Program Lead", "Admin"},
        "can_configure": user_role
        in {"ImpactAssessment", "Admin", "CountryDirector", "RegionalVicePresident"},
        "amendments": amendments,
        "snapshots": snapshots,
        "overall_pct": overall_pct,
        "show_open_conversation": show_open_conversation,
        "active_window_label": (
            WINDOW_LABELS.get(cycle.active_window) if cycle else None
        ),
        "stage_label": (
            {
                "not_started": "Draft — not started",
                "draft": "Draft",
                "employee_input": "Employee input",
                "manager_review": "Manager review",
                "approved": "Approved",
                "returned": "Returned",
                "signed_off": "Signed off",
            }.get(review.stage, review.stage.replace("_", " ").capitalize())
            if review
            else None
        ),
        "tab_defs": [
            ("distributed", "Distributed Priorities"),
            ("values", "Core Values"),
            ("spiritual", "Spiritual Formation"),
            ("development", "Professional Development"),
        ],
        "tab": (tab or request.GET.get("tab"))
        if (tab or request.GET.get("tab")) in {"values", "spiritual", "development"}
        else "distributed",
    }
    return render(request, "pages/hr/my_performance.html", context)


# ── Performance conversation form (§9, §11, §12) ────────────────────────────
# The working conversation: employee reflection + self-rating, manager review
# and rating, functional-manager rating. HR-window-gated by the engine; every
# write goes through the engine's role-scoped save_* functions, never the ORM
# directly, so the §20 boundaries hold at the one write path.


def _resolve_conversation(request):
    """Return (review, target_staff, caps) for the conversation the viewer is
    entitled to open, or (None, target, caps) when there is no agreement.

    caps is the set of channels this viewer may write: any of 'employee',
    'manager', 'functional', 'hr'. Raises PermissionDenied-style responses via
    the caller when the viewer has no relationship at all.

    'manager' is the reviewer the reporting rule names, or their active cover
    (apps.hr.review_authority.is_reviewer_of). Any supervisor link used to
    grant it — including the oversight rows the model documents as not the
    reporting line — while the engine refused the save, so the form offered
    a column its owner could not write (Program Lead alignment, 2026-09-13).
    """
    from apps.core.fy import get_operational_fy
    from apps.hr.models import PerformanceReview
    from apps.hr.review_authority import is_reviewer_of

    viewer_sp = getattr(request.user, "staff_profile", None)
    staff_param = (request.GET.get("staff") or request.POST.get("staff") or "").strip()
    role = getattr(request.user, "active_role", "")
    is_hr = role in ("HumanResources", "Admin")

    if staff_param and staff_param != getattr(viewer_sp, "id", None):
        # The lookup was unscoped: any HR account could name any staff id in
        # any country and read that person's ratings, self-reflection and
        # manager assessment — then download them as a document. HR oversight
        # of the performance CYCLE does not require reading every country's
        # conversations (2026-08-20 HR audit).
        target = (
            _profile_scope(request)
            .filter(id=staff_param)
            .select_related("user")
            .first()
        )
        if target is None and viewer_sp:
            # Someone covering an absent reviewer holds the review for the
            # cover's window, although the people are not in their own reach.
            candidate = (
                StaffProfile.objects.filter(id=staff_param)
                .select_related("user")
                .first()
            )
            if candidate is not None and is_reviewer_of(candidate, request.user):
                target = candidate
    else:
        target = viewer_sp
    if target is None:
        return None, None, set()

    caps: set[str] = set()
    if viewer_sp and target.id == viewer_sp.id:
        caps.add("employee")
    if viewer_sp and target.id != viewer_sp.id and is_reviewer_of(target, request.user):
        caps.add("manager")
    fy = get_operational_fy()
    review = PerformanceReview.objects.filter(
        staff=target, fy=fy, review_type="annual_priorities"
    ).first()
    if review and review.functional_manager_id == request.user.id:
        caps.add("functional")
    if is_hr:
        caps.add("hr")
    if not caps:
        # No employee/manager/functional/HR relationship to this person at all.
        return None, None, set()
    return review, target, caps


@require_page_permission("performance_conversations")
def performance_conversation_view(request):
    """The conversation form for one employee's active window."""
    from apps.hr.models import PerformanceCycle, PerformanceRating
    from apps.hr.performance_engine import live_progress, milestone_metrics

    review, target, caps = _resolve_conversation(request)
    if target is None:
        return render_access_denied(request, "No staff profile is linked.")
    if not caps:
        return render_access_denied(
            request, "You are not part of this performance conversation."
        )

    cycle = PerformanceCycle.objects.filter(fy=review.fy).first() if review else None
    window = cycle.active_window if cycle else "none"
    window_open = bool(cycle and window != "none")

    snap = None
    if review:
        snap = review.snapshots.filter(window=window).first() if window_open else None
    snap_by_seq = {}
    if snap:
        snap_by_seq = {r["sequence"]: r for r in snap.data.get("priorities", [])}

    rows = []
    if review:
        # source_rule is read per row to say what an inherited commitment is
        # inherited AS; without the join that is one extra query per priority.
        for p in review.priorities.select_related("source_rule").order_by("sequence"):
            live = live_progress(p)
            frozen = snap_by_seq.get(p.sequence)
            rows.append(
                {
                    "p": p,
                    "live": live,
                    # The conversation is held against the FROZEN figure when a
                    # snapshot exists; live is shown only before activation.
                    "shown_actual": frozen["actual"] if frozen else live["actual"],
                    "shown_pct": frozen["pct"] if frozen else live["pct"],
                    "milestones": milestone_metrics(p),
                    "frozen": bool(frozen),
                }
            )

    WINDOW_LABELS = {
        "priority_setting": "FY Priority Setting",
        "q1": "Q1 Performance Conversation",
        "mid_year": "Mid-Year Performance Conversation",
        "q3": "Q3 Performance Conversation",
        "year_end": "End-of-Year Performance Conversation",
    }
    from apps.hr.accountability import allocation_priorities

    contract = (
        allocation_priorities(target.user, review.fy)
        if review
        else {"rows": [], "pct": None}
    )
    if snap:
        # An old snapshot without this projection remains historical; never
        # quietly substitute today's allocations into a signed conversation.
        from apps.hr.accountability import snapshot_contract

        contract = snapshot_contract(snap.data)

    signed = bool(snap and snap.signed_off_at)
    # What the reviewer needs to act on without leaving the page: priorities
    # the employee submitted for agreement (open in any window), and whether
    # the employee has spoken in this window yet — the reviewer's sign-off
    # waits for it (Program Lead alignment, 2026-09-13).
    agreement_waiting = bool(
        review and "manager" in caps and review.stage == "priorities_manager_review"
    )
    reflection_saved = True
    if review and snap and "manager" in caps and "employee" not in caps:
        from apps.hr.performance_engine import conversation_progress

        reflection_saved = (
            conversation_progress([review], window)
            .get(review.id, {})
            .get("reflection_saved", False)
        )
    context = {
        "distributed": contract,
        "review": review,
        "target": target,
        "caps": caps,
        "window": window,
        "window_label": WINDOW_LABELS.get(window, "No window open"),
        "window_open": window_open,
        "rows": rows,
        "ratings": PerformanceRating.choices,
        "values": list(review.value_commitments.filter(kind="value")) if review else [],
        "spiritual": list(review.value_commitments.filter(kind="spiritual"))
        if review
        else [],
        "snapshot": snap,
        "signed": signed,
        "staff_param": target.id if "employee" not in caps else "",
        "agreement_waiting": agreement_waiting,
        "priorities_to_agree": list(review.priorities.order_by("sequence"))
        if agreement_waiting
        else [],
        "reflection_saved": reflection_saved,
        "back_to_reviews": "manager" in caps
        and getattr(request.user, "active_role", "") == "Program Lead",
    }
    return render(request, "pages/hr/performance_conversation.html", context)


@require_page_permission("performance_conversations")
@require_POST
def performance_agree_priorities_view(request, review_id):
    """The reviewer agrees the priorities an employee submitted.

    `performance_service.agree_priorities` held the rule — the reviewer or
    HR, never the employee, only while the priorities wait on the manager —
    and no screen called it, so a submitted agreement waited on a manager who
    had no way to agree it (Program Lead alignment, 2026-09-13). Refusals are
    the service's words.
    """
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.hr.models import PerformanceReview
    from apps.hr.performance_service import agree_priorities

    review = (
        PerformanceReview.objects.filter(id=review_id)
        .select_related("staff__user")
        .first()
    )
    if review is None:
        return HttpResponseBadRequest("Unknown review.")
    try:
        agree_priorities(
            review.id, request.user, note=(request.POST.get("note") or "").strip()
        )
    except Forbidden as exc:
        return HttpResponseForbidden(escape(str(exc)))
    except BadRequest as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{review.staff.user.name}'s priorities are agreed.")
    return redirect(f"/performance-conversation?staff={review.staff_id}")


def _conversation_redirect(request, target_id, caps):
    staff = "" if "employee" in caps else target_id
    url = "/performance-conversation"
    if staff:
        url += f"?staff={staff}"
    return redirect(url)


# Declared here as well as enforced in apps.hr.performance_engine. The
# engine owns the real rules -- ownership, the review window, who may sign
# off -- and keeps them. This decorator states the audience where the route
# is, so a page-permission audit can see it; §9 treats an undeclared route
# as authorization drift even when the view behind it is safe.
@require_page_permission("performance_conversations")
def performance_input_save_view(request, priority_id):
    """One POST per channel. The engine enforces window + role; we only route
    the fields to the matching save_* function."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.hr.models import PerformancePriority
    from apps.hr.performance_engine import (
        save_employee_input,
        save_functional_manager_input,
        save_manager_input,
    )

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    priority = (
        PerformancePriority.objects.filter(id=priority_id)
        .select_related("review__staff")
        .first()
    )
    if priority is None:
        return HttpResponseBadRequest("Unknown priority.")
    channel = request.POST.get("channel", "")
    data = {
        k: v
        for k, v in request.POST.items()
        if k not in ("csrfmiddlewaretoken", "channel", "staff")
    }
    try:
        if channel == "employee":
            save_employee_input(priority, data, request.user)
        elif channel == "manager":
            save_manager_input(priority, data, request.user)
        elif channel == "functional":
            save_functional_manager_input(priority, data, request.user)
        else:
            return HttpResponseBadRequest("Unknown channel.")
    except Forbidden as e:
        return HttpResponseForbidden(escape(str(e)))
    except BadRequest as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Saved.")
    _, target, caps = _resolve_conversation(request)
    return _conversation_redirect(request, priority.review.staff_id, caps)


# Declared here as well as enforced in apps.hr.performance_engine. The
# engine owns the real rules -- ownership, the review window, who may sign
# off -- and keeps them. This decorator states the audience where the route
# is, so a page-permission audit can see it; §9 treats an undeclared route
# as authorization drift even when the view behind it is safe.
@require_page_permission("performance_conversations")
def performance_value_save_view(request, commitment_id):
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.hr.models import ValueCommitment
    from apps.hr.performance_engine import save_value_reflection

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    commitment = (
        ValueCommitment.objects.filter(id=commitment_id)
        .select_related("review__staff")
        .first()
    )
    if commitment is None:
        return HttpResponseBadRequest("Unknown commitment.")
    data = {
        k: v
        for k, v in request.POST.items()
        if k not in ("csrfmiddlewaretoken", "staff")
    }
    try:
        save_value_reflection(commitment, data, request.user)
    except Forbidden as e:
        return HttpResponseForbidden(escape(str(e)))
    except BadRequest as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Saved.")
    _, target, caps = _resolve_conversation(request)
    return _conversation_redirect(request, commitment.review.staff_id, caps)


# Declared here as well as enforced in apps.hr.performance_engine. The
# engine owns the real rules -- ownership, the review window, who may sign
# off -- and keeps them. This decorator states the audience where the route
# is, so a page-permission audit can see it; §9 treats an undeclared route
# as authorization drift even when the view behind it is safe.
@require_page_permission("performance_conversations")
def performance_signoff_view(request, review_id):
    """The employee acknowledges and signs the conversation for the window."""
    from apps.core.exceptions import BadRequest
    from apps.hr.models import PerformanceReview
    from apps.hr.performance_engine import sign_off

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    review = (
        PerformanceReview.objects.filter(id=review_id).select_related("staff").first()
    )
    if review is None:
        return HttpResponseBadRequest("Unknown review.")
    window = request.POST.get("window", "")
    # Authorize against THIS review's employee — sign_off is a lock with no
    # engine-level relationship check, so a stranger must not reach it by
    # posting an arbitrary review id. Only the employee, their reviewer (the
    # reporting rule's, not any supervisor link) or HR. The engine refuses
    # the reviewer until the employee's reflection for the window is saved.
    from apps.hr.review_authority import is_reviewer_of

    is_employee = review.staff.user_id == request.user.id
    is_manager = not is_employee and is_reviewer_of(review.staff, request.user)
    is_hr = getattr(request.user, "active_role", "") in ("HumanResources", "Admin")
    if not (is_employee or is_manager or is_hr):
        return HttpResponseForbidden("You cannot sign this conversation off.")
    caps = {"employee"} if is_employee else set()
    try:
        sign_off(review, window, request.user)
    except BadRequest as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Conversation signed off and locked.")
    return _conversation_redirect(request, review.staff_id, caps)


# ── HR performance console (§4, §7) ─────────────────────────────────────────
# The one control surface for the cycle: create it, see readiness, activate or
# close a window (activation freezes every snapshot), approve or return each
# agreement. Every state change routes through the engine so its HR-only
# guards and audit rows apply; the view only gathers and dispatches.


def _require_hr(request):
    return getattr(request.user, "active_role", "") in ("HumanResources", "Admin")


@require_page_permission("performance_console")
def hr_performance_console_view(request):
    from apps.core.fy import get_operational_fy
    from apps.hr.models import PerformanceCycle, PerformanceReview
    from apps.hr.performance_engine import quarterly_readiness

    if not _require_hr(request):
        return render_access_denied(request, "The performance console is HR-only.")

    fy = request.GET.get("fy") or get_operational_fy()
    cycle = PerformanceCycle.objects.filter(fy=fy).first()
    readiness = quarterly_readiness(fy)

    scope_ids = list(_profile_scope(request).values_list("id", flat=True))
    reviews = (
        PerformanceReview.objects.filter(
            fy=fy, review_type="annual_priorities", staff_id__in=scope_ids
        )
        .select_related("staff__user")
        .order_by("staff__user__name")
    )
    STAGE_LABELS = {
        "not_started": "Draft — not started",
        "priorities_draft": "Employee drafting",
        "priorities_manager_review": "Manager review",
        "priorities_agreed": "Approved & locked",
        "manager_assessment": "Returned for correction",
    }
    review_rows = [
        {
            "review": r,
            "name": r.staff.user.name if r.staff.user_id else "—",
            "stage": r.stage,
            "stage_label": STAGE_LABELS.get(r.stage, r.stage.replace("_", " ").title()),
            "approved": r.stage in ("priorities_agreed",),
        }
        for r in reviews
    ]

    WINDOWS = [w for w in PerformanceCycle.WINDOWS if w[0] != "none"]
    from apps.hr.models import PerformanceRating

    context = {
        "fy": fy,
        "cycle": cycle,
        "readiness": readiness,
        "review_rows": review_rows,
        "windows": WINDOWS,
        "active_window": cycle.active_window if cycle else "none",
        "ratings": PerformanceRating.choices,
        "is_year_end": bool(cycle and cycle.active_window == "year_end"),
    }
    return render(request, "pages/hr/performance_console.html", context)


# Declared here as well as enforced in apps.hr.performance_engine. The
# engine owns the real rules -- ownership, the review window, who may sign
# off -- and keeps them. This decorator states the audience where the route
# is, so a page-permission audit can see it; §9 treats an undeclared route
# as authorization drift even when the view behind it is safe.
@require_page_permission("performance_console")
def hr_performance_action_view(request):
    """One POST endpoint for the console's state changes; `action` selects."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.core.fy import get_operational_fy
    from apps.hr.models import PerformanceCycle, PerformanceReview
    from apps.hr.performance_engine import (
        activate_pip,
        activate_window,
        approve_agreement,
        archive_review,
        build_draft_agreement,
        calibrate,
        close_window,
        confirm_final_rating,
        hr_review_separation,
        open_separation,
        pip_outcome,
        recommend_pip,
        reopen_conversation,
        return_for_correction,
        submit_for_calibration,
    )

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    if not _require_hr(request):
        return HttpResponseForbidden("HR only.")

    def _review():
        return PerformanceReview.objects.get(id=request.POST["review_id"])

    def _staff():
        return StaffProfile.objects.get(id=request.POST["staff_id"])

    action = request.POST.get("action", "")
    fy = request.POST.get("fy") or get_operational_fy()
    try:
        if action == "create_cycle":
            cycle, created = PerformanceCycle.objects.get_or_create(
                fy=fy, defaults={"status": "active", "opened_by": request.user}
            )
            # Generate a draft agreement for every active staff member in scope.
            made = 0
            for sp in _profile_scope(request).filter(onboarding_state="active"):
                build_draft_agreement(
                    sp, cycle, request.user, include_role_templates=False
                )
                made += 1
            messages.success(
                request,
                f"Cycle {'created' if created else 'already open'} · "
                f"{made} draft agreements ready.",
            )
        elif action == "activate_window":
            cycle = PerformanceCycle.objects.get(fy=fy)
            window = request.POST.get("window", "")
            deadline = request.POST.get("deadline") or None
            n = activate_window(cycle, window, request.user, deadline=deadline)
            messages.success(request, f"{window} activated · {n} snapshots frozen.")
        elif action == "close_window":
            cycle = PerformanceCycle.objects.get(fy=fy)
            close_window(cycle, request.user)
            messages.success(request, "Window closed. The form is locked again.")
        elif action == "approve":
            review = PerformanceReview.objects.get(id=request.POST["review_id"])
            n = approve_agreement(review, request.user)
            messages.success(
                request, f"Agreement approved · {n} target rows written to My Targets."
            )
        elif action == "return":
            review = PerformanceReview.objects.get(id=request.POST["review_id"])
            return_for_correction(review, request.POST.get("reason", ""), request.user)
            messages.success(request, "Returned for correction.")
        elif action == "reopen":
            review = PerformanceReview.objects.get(id=request.POST["review_id"])
            reopen_conversation(
                review,
                request.POST.get("window", ""),
                request.POST.get("reason", ""),
                request.user,
            )
            messages.success(request, "Conversation reopened for correction.")
        # ── Year-end calibration chain (§14) ────────────────────────────────
        elif action == "submit_calibration":
            submit_for_calibration(_review(), request.user)
            messages.success(request, "Ready for SLT calibration.")
        elif action == "calibrate":
            calibrate(
                _review(),
                request.POST.get("result", ""),
                request.POST.get("note", ""),
                request.user,
            )
            messages.success(request, "Calibration recorded.")
        elif action == "confirm_rating":
            confirm_final_rating(
                _review(), request.POST.get("rating", ""), request.user
            )
            messages.success(request, "Final rating confirmed.")
        elif action == "archive":
            archive_review(_review(), request.user)
            messages.success(request, "Review signed and archived.")
        # ── PIP (§15) ───────────────────────────────────────────────────────
        elif action == "recommend_pip":
            recommend_pip(_staff(), request.POST.get("reason", ""), request.user)
            messages.success(request, "Formal PIP recommended (draft).")
        elif action == "activate_pip":
            from apps.hr.models import PerformanceImprovementPlan

            plan = PerformanceImprovementPlan.objects.get(id=request.POST["plan_id"])
            activate_pip(
                plan, request.user, action_plan=request.POST.get("action_plan")
            )
            messages.success(request, "PIP activated with 30/60/90-day milestones.")
        elif action == "pip_outcome":
            from apps.hr.models import PerformanceImprovementPlan

            plan = PerformanceImprovementPlan.objects.get(id=request.POST["plan_id"])
            pip_outcome(
                plan,
                request.POST.get("outcome", ""),
                request.POST.get("note", ""),
                request.user,
            )
            messages.success(request, "PIP outcome recorded.")
        # ── Separation (§15) ────────────────────────────────────────────────
        elif action == "open_separation":
            open_separation(
                _staff(),
                {
                    "reason": request.POST.get("reason", ""),
                    "evidence": request.POST.get("evidence"),
                    "policy_basis": request.POST.get("policy_basis"),
                },
                request.user,
            )
            messages.success(request, "Separation opened — awaiting employee response.")
        elif action == "hr_review_separation":
            from apps.hr.models import SeparationConversation

            sep = SeparationConversation.objects.get(id=request.POST["separation_id"])
            hr_review_separation(sep, request.POST.get("note", ""), request.user)
            messages.success(request, "Separation moved to leadership approval.")
        else:
            return HttpResponseBadRequest("Unknown action.")
    except (BadRequest, Forbidden) as e:
        messages.error(request, str(e))
    except PerformanceCycle.DoesNotExist:
        messages.error(request, "No cycle exists for that year yet — create it first.")
    except PerformanceReview.DoesNotExist:
        messages.error(request, "That agreement no longer exists.")
    except (StaffProfile.DoesNotExist, KeyError):
        messages.error(request, "That record could not be found.")
    except ObjectDoesNotExist:
        messages.error(request, "That record no longer exists.")
    return local_redirect(f"/hr/performance-cycle?fy={fy}")


# ── Conversation document (§17) ─────────────────────────────────────────────
# The record is rendered from the LOCKED snapshot, never live data. Access is
# scope-checked (employee → own; manager → reports; leadership → their scope;
# HR → policy scope) and every open is audit-logged by the engine.


# Declared here as well as enforced in apps.hr.performance_engine. The
# engine owns the real rules -- ownership, the review window, who may sign
# off -- and keeps them. This decorator states the audience where the route
# is, so a page-permission audit can see it; §9 treats an undeclared route
# as authorization drift even when the view behind it is safe.
@require_page_permission("performance_conversations")
def performance_document_view(request, review_id, window):
    from apps.core.exceptions import BadRequest
    from apps.hr.models import PerformanceReview
    from apps.hr.performance_engine import conversation_document

    review = (
        PerformanceReview.objects.filter(id=review_id)
        .select_related("staff__user")
        .first()
    )
    if review is None:
        return HttpResponseBadRequest("Unknown review.")

    # Access is decided against THIS review's employee, not the viewer's own
    # ambient conversation: relationship (employee / reviewer / functional /
    # HR) OR leadership scope grants read; otherwise deny. The reviewer is the
    # reporting rule's (apps.hr.review_authority), including active cover.
    from apps.hr.review_authority import is_reviewer_of

    is_employee = review.staff.user_id == request.user.id
    is_manager = not is_employee and is_reviewer_of(review.staff, request.user)
    is_functional = review.functional_manager_id == request.user.id
    is_hr = getattr(request.user, "active_role", "") in ("HumanResources", "Admin")
    in_scope = _profile_scope(request).filter(id=review.staff_id).exists()
    if not (is_employee or is_manager or is_functional or is_hr or in_scope):
        return render_access_denied(
            request, "You may not open this conversation record."
        )
    try:
        # The engine writes the audit row for the download here.
        doc = conversation_document(review, window, request.user)
    except BadRequest as e:
        messages.error(request, str(e))
        return local_redirect(f"/performance-conversation?staff={review.staff_id}")

    WINDOW_LABELS = {
        "priority_setting": "FY Priority Setting",
        "q1": "Q1 Performance Conversation",
        "mid_year": "Mid-Year Performance Conversation",
        "q3": "Q3 Performance Conversation",
        "year_end": "End-of-Year Performance Conversation",
    }
    doc["window_label"] = WINDOW_LABELS.get(window, window)
    # Merge the FROZEN figures (from the snapshot) with the ratings and
    # reflections (which live on the priority, entered during the meeting).
    by_seq = {p.sequence: p for p in review.priorities.all()}
    merged = []
    for frozen in doc["priorities"]:
        p = by_seq.get(frozen["sequence"])
        merged.append(
            {
                "frozen": frozen,
                "employee_rating": getattr(
                    p, "get_employee_rating_display", lambda: None
                )()
                if p
                else None,
                "manager_rating": getattr(
                    p, "get_manager_rating_display", lambda: None
                )()
                if p
                else None,
                "functional_rating": getattr(
                    p, "get_functional_manager_rating_display", lambda: None
                )()
                if p
                else None,
                "employee_reflection": getattr(p, "employee_reflection", "")
                if p
                else "",
                "manager_assessment": getattr(p, "manager_assessment", "") if p else "",
                "agreed_action": getattr(p, "agreed_action", "") if p else "",
            }
        )
    doc["doc_rows"] = merged

    # §17: a downloadable Word record. No document library is installed, so we
    # serve the same record as a Word-openable HTML document (application/
    # msword) rather than adding a dependency silently — Word opens it natively.
    if request.GET.get("format") == "docx":
        from django.template.loader import render_to_string

        doc["as_docx"] = True
        html = render_to_string("pages/hr/conversation_document.html", doc, request)
        name = f"performance-{review.staff_id}-{window}.doc"
        resp = HttpResponse(html, content_type="application/msword")
        resp["Content-Disposition"] = f'attachment; filename="{name}"'
        return resp
    return render(request, "pages/hr/conversation_document.html", doc)


# Declared here as well as enforced in apps.hr.performance_engine. The
# engine owns the real rules -- ownership, the review window, who may sign
# off -- and keeps them. This decorator states the audience where the route
# is, so a page-permission audit can see it; §9 treats an undeclared route
# as authorization drift even when the view behind it is safe.
@require_page_permission("performance_conversations")
def performance_acknowledge_view(request, review_id):
    """The employee acknowledges their confirmed final rating (§14)."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.hr.models import PerformanceReview
    from apps.hr.performance_engine import acknowledge_review

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    review = (
        PerformanceReview.objects.filter(id=review_id).select_related("staff").first()
    )
    if review is None:
        return HttpResponseBadRequest("Unknown review.")
    try:
        acknowledge_review(review, request.user)
    except Forbidden as e:
        return HttpResponseForbidden(escape(str(e)))
    except BadRequest as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Final rating acknowledged.")
    return redirect("/my-performance?tab=conversations")


# ── Strategic priorities: the top of the cascade ─────────────────────────────
# Everything below exists so the RVP and CD can author DIRECTION and stop
# there. They set purpose, expected result and a weighting range; they never
# write an individual's milestones. Without a page, `StrategicPriority` is a
# table only a shell can reach, and the cascade starts from nothing.

_STRATEGY_AUTHORS = ("RegionalVicePresident", "CountryDirector")
_STRATEGY_VIEWERS = _STRATEGY_AUTHORS + ("HumanResources", "Admin")

# A plausible financial year. Bounds rather than "any four digits" so a
# nonsense year cannot become a filter that quietly matches nothing.
MIN_FY_YEAR = 2000
MAX_FY_YEAR = 2100


def _requested_fy(request, param="fy"):
    """A financial year taken from the request, or the operational one.

    An FY label is a four-digit year and nothing else. Validating here keeps
    user input out of two places it should never reach unchecked: the redirect
    URL these views build, and the query filters they run.

    The year is REBUILT from the parsed integer rather than returned as the
    string that arrived. Checking a string's shape and then handing back the
    original still passes the caller a value that came from the request — the
    check constrains what gets through, not what the value *is*. Formatting
    from the int means the returned string is constructed here, and nothing
    the client sent can reach a URL however the check is later loosened.
    """
    from apps.core.fy import get_operational_fy

    raw = (request.POST.get(param) or request.GET.get(param) or "").strip()
    if raw.isdigit() and len(raw) == 4:
        year = int(raw)
        if MIN_FY_YEAR <= year <= MAX_FY_YEAR:
            return f"{year:04d}"
    return get_operational_fy()


@require_page_permission("strategic_priorities")
def strategic_priorities_view(request):
    from apps.hr import priority_cascade
    from apps.hr.models import (
        PriorityAccountability,
        StrategicPriority,
        StrategicPriorityLevel,
        StrategicPriorityStatus,
    )
    from apps.hr.performance_engine import METRIC_KEYS

    role = getattr(request.user, "active_role", "")
    if role not in _STRATEGY_VIEWERS:
        return render_access_denied(
            request,
            "Strategic priorities are set by the RVP and Country Director and "
            "validated by HR.",
        )

    fy = _requested_fy(request)
    priorities = (
        StrategicPriority.objects.filter(fy=fy)
        .select_related("parent")
        .prefetch_related("role_rules")
        .order_by("level", "title")
    )

    coverage = priority_cascade.coverage_report(fy)
    reach = {row["priority_id"]: row for row in coverage["priorities"]}

    # The CD authors country priorities and may translate a published regional
    # one; the RVP authors regional. Offering a level the actor cannot publish
    # would produce a draft — or a Publish button — that can only ever be
    # refused, which reads as a broken page rather than a boundary.
    authorable = []
    if role == "RegionalVicePresident":
        authorable.append(StrategicPriorityLevel.REGIONAL)
    if role == "CountryDirector":
        authorable.append(StrategicPriorityLevel.COUNTRY)

    rows = []
    for priority in priorities:
        rules = sorted(priority.role_rules.all(), key=lambda r: r.role)
        carried = [
            r
            for r in rules
            if r.accountability != PriorityAccountability.NOT_APPLICABLE
        ]
        rows.append(
            {
                "priority": priority,
                "rules": rules,
                # Surfaced because it is the one thing that cannot be seen by
                # reading the priority: whether it reached anybody's agreement.
                "staff_reached": reach.get(priority.id, {}).get("staff_reached", 0),
                "inert": reach.get(priority.id, {}).get("inert", True),
                "carried_roles": len(carried),
                "distinct_metrics": len(
                    {r.metric_key for r in carried if r.metric_key}
                ),
                "publishable": bool(carried)
                and all((r.metric_key or "").strip() for r in carried),
                "editable": priority.level in authorable,
            }
        )

    context = {
        "fy": fy,
        "rows": rows,
        "can_author": bool(authorable),
        "authorable_levels": authorable,
        "roles": [r for r in _CASCADE_ROLES],
        "accountabilities": PriorityAccountability.choices,
        # Offered as a list, not a text box: a free-typed key that the engine
        # does not compute reports 0% forever and reads as an employee
        # failing. Publication refuses one, but by then it has been written
        # into a translation the author believed was saved.
        "metric_choices": sorted(METRIC_KEYS.items()),
        "statuses": StrategicPriorityStatus,
        "published_parents": [
            p
            for p in priorities
            if p.level == StrategicPriorityLevel.REGIONAL
            and p.status == StrategicPriorityStatus.PUBLISHED
        ],
        "inert_count": coverage["inert_count"],
        "manager_routing": sorted(priority_cascade.PRIORITY_SETTING_MANAGER.items()),
    }
    return render(request, "pages/hr/strategic_priorities.html", context)


#: The roles a strategic priority can be translated for. Partner roles are
#: excluded: they are external and hold no Edify performance agreement.
_CASCADE_ROLES = (
    "CCEO",
    "Program Lead",
    "CountryDirector",
    "ImpactAssessment",
    "ProjectCoordinator",
    "Accountant",
    "HumanResources",
)


@require_page_permission("strategic_priorities")
def strategic_priority_action_view(request):
    """One POST endpoint for the cascade's state changes; `action` selects."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.hr import priority_cascade
    from apps.hr.models import (
        PriorityAccountability,
        StrategicPriority,
        StrategicPriorityLevel,
        StrategicPriorityRoleRule,
    )

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    role = getattr(request.user, "active_role", "")
    if role not in _STRATEGY_AUTHORS:
        return HttpResponseForbidden("Only the RVP or Country Director may author.")

    fy = _requested_fy(request)
    action = request.POST.get("action", "")
    try:
        if action == "create_priority":
            level = request.POST.get("level") or StrategicPriorityLevel.REGIONAL
            # The author check runs here as well as at publish, so a draft the
            # actor could never publish is refused while it is still empty.
            priority_cascade._assert_can_author(request.user, level)
            title = (request.POST.get("title") or "").strip()
            purpose = (request.POST.get("strategic_purpose") or "").strip()
            if not title or not purpose:
                raise BadRequest("A priority needs a title and a strategic purpose.")
            parent_id = request.POST.get("parent") or None
            weight_min = int(request.POST.get("weight_min") or 10)
            weight_max = int(request.POST.get("weight_max") or 30)
            if weight_max < weight_min:
                raise BadRequest("The weighting range runs backwards.")
            StrategicPriority.objects.create(
                fy=fy,
                level=level,
                parent_id=parent_id,
                title=title[:255],
                strategic_purpose=purpose,
                target_guidance=(request.POST.get("target_guidance") or "").strip(),
                minimum_standard=(request.POST.get("minimum_standard") or "").strip(),
                weight_min=weight_min,
                weight_max=weight_max,
                is_mandatory=request.POST.get("is_mandatory") == "on",
                author_id=request.user.id,
            )
            messages.success(request, "Strategic priority drafted.")

        elif action == "set_role_rule":
            priority = StrategicPriority.objects.filter(
                id=request.POST.get("priority"), fy=fy
            ).first()
            if priority is None:
                raise BadRequest("Unknown strategic priority.")
            priority_cascade._assert_can_author(request.user, priority.level)
            # G4 (2026-08-20 audit): role rules on a PUBLISHED priority are
            # part of the locked commitment — weight/metric changes after
            # publication go through amendments.
            from apps.hr.models import StrategicPriorityStatus as _SPS

            if priority.status == _SPS.PUBLISHED:
                raise BadRequest(
                    "This priority is published and locked — role-rule "
                    "changes require an amendment."
                )
            target_role = request.POST.get("role") or ""
            if target_role not in _CASCADE_ROLES:
                raise BadRequest("Unknown role.")
            accountability = request.POST.get("accountability") or ""
            if accountability not in dict(PriorityAccountability.choices):
                raise BadRequest("Unknown accountability.")
            StrategicPriorityRoleRule.objects.update_or_create(
                priority=priority,
                role=target_role,
                defaults={
                    "accountability": accountability,
                    "metric_key": (request.POST.get("metric_key") or "").strip()
                    or None,
                    "outcome_statement": (
                        request.POST.get("outcome_statement") or ""
                    ).strip(),
                    "target_guidance": (
                        request.POST.get("rule_target_guidance") or ""
                    ).strip(),
                    "default_weight": int(request.POST.get("default_weight") or 20),
                },
            )
            messages.success(request, f"{target_role} translation saved.")

        elif action == "publish":
            priority = StrategicPriority.objects.filter(
                id=request.POST.get("priority"), fy=fy
            ).first()
            if priority is None:
                raise BadRequest("Unknown strategic priority.")
            priority_cascade.publish(priority, request.user)
            messages.success(request, f"“{priority.title}” published and now cascades.")
        else:
            return HttpResponseBadRequest("Unknown action.")
    except Forbidden as e:
        return HttpResponseForbidden(escape(str(e)))
    except BadRequest as e:
        messages.error(request, str(e))
    return redirect(f"/strategic-priorities?fy={fy}")
