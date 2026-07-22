from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render

from apps.accounts.models import Leave, StaffProfile
from apps.core.permissions import render_access_denied, require_page_permission
from apps.hr.models import (
    Application,
    CompensationRecord,
    ComplianceRequirement,
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
    return {"label": label, "value": value, "helper": helper, "tone": tone}


def _profile_scope(request):
    """Return the staff scope visible to the active role.

    Admin is organization-wide, PL is limited to its supervised team, and the
    remaining leadership/people roles are country-scoped when their profile has
    a country. This prevents a shared HR surface from widening data access.
    """

    profiles = StaffProfile.objects.select_related("user").filter(
        user__deleted_at__isnull=True
    )
    role = getattr(request.user, "active_role", "")
    if role == "Admin":
        return profiles

    viewer = getattr(request.user, "staff_profile", None)
    if role in {"Program Lead", "ProgramLead"} and viewer:
        return profiles.filter(
            Q(id=viewer.id) | Q(supervisor_links__supervisor=viewer)
        ).distinct()
    if viewer and viewer.country:
        return profiles.filter(country=viewer.country)
    return profiles.none()


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
):
    paginator = Paginator(rows, 25)
    page = paginator.get_page(request.GET.get("page") or 1)
    context = {
        "title": title,
        "description": description,
        "metrics": metrics,
        "page_obj": page,
        "rows": page.object_list,
        "primary_action": primary_action,
        "empty_title": empty_title,
        "empty_body": empty_body,
        "search": (request.GET.get("q") or "").strip(),
    }
    return render(request, "pages/hr/module_workspace.html", context)


@require_page_permission("org_structure")
def org_structure_view(request):
    profiles = _search_profiles(
        _profile_scope(request), (request.GET.get("q") or "").strip()
    )
    rows = [
        {
            "cells": [
                _cell("Team member", profile.user.name, primary=True),
                _cell("Role", profile.title or profile.user.active_role),
                _cell("Department", profile.department),
                _cell("Country", profile.country),
                _cell("Lifecycle", profile.get_onboarding_state_display(), status=True),
            ]
        }
        for profile in profiles.order_by("department", "user__name")
    ]
    return _render_workspace(
        request,
        title="Organization Structure",
        description="A live, role-scoped directory of reporting capacity, departments, countries, and staff lifecycle state.",
        metrics=[
            _metric(
                "People in scope",
                profiles.count(),
                "active and onboarding profiles",
                "info",
            ),
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
                "Countries",
                profiles.values("country").distinct().count(),
                "operating footprint",
            ),
        ],
        rows=rows,
        primary_action={"label": "Open People Directory", "href": "/staff"},
    )


@require_page_permission("workforce_planning")
def workforce_planning_view(request):
    profiles = _search_profiles(
        _profile_scope(request), (request.GET.get("q") or "").strip()
    )
    grouped = (
        profiles.values("department", "country")
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
                _cell("Department", item["department"] or "Unassigned", primary=True),
                _cell("Country", item["country"]),
                _cell("Headcount", item["headcount"]),
                _cell("Active", item["active"]),
                _cell(
                    "Pending activation", item["pending"], status=item["pending"] > 0
                ),
            ]
        }
        for item in grouped
    ]
    return _render_workspace(
        request,
        title="Workforce Planning & Capacity",
        description="A truthful headcount and activation view derived from the current people directory—without forecast or budget values that have not been configured.",
        metrics=[
            _metric("Headcount", profiles.count(), "people in your access scope"),
            _metric(
                "Active",
                profiles.filter(onboarding_state="active").count(),
                "available workforce",
                "success",
            ),
            _metric(
                "Pending",
                profiles.filter(onboarding_state="pending").count(),
                "awaiting activation",
                "warning",
            ),
            _metric(
                "Vacancies",
                Vacancy.objects.filter(
                    status__in=["Approved", "Open", "Screening"]
                ).count(),
                "approved or recruiting",
                "info",
            ),
        ],
        rows=rows,
        primary_action={"label": "Review Recruitment", "href": "/recruitment"},
        empty_title="No workforce profiles in this scope",
    )


@require_page_permission("recruitment")
def recruitment_view(request):
    query = (request.GET.get("q") or "").strip()
    vacancies = Vacancy.objects.select_related("reporting_manager").annotate(
        application_count=Count("applications")
    )
    viewer = getattr(request.user, "staff_profile", None)
    if request.user.active_role != "Admin":
        vacancies = (
            vacancies.filter(country=getattr(viewer, "country", ""))
            if viewer
            else vacancies.none()
        )
    if query:
        vacancies = vacancies.filter(
            Q(role__icontains=query)
            | Q(department__icontains=query)
            | Q(country__icontains=query)
            | Q(status__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Vacancy", vacancy.role, primary=True),
                _cell("Department", vacancy.department),
                _cell("Country", vacancy.country),
                _cell("Applications", vacancy.application_count),
                _cell("Target start", vacancy.target_start_date),
                _cell("Status", vacancy.status, status=True),
            ]
        }
        for vacancy in vacancies.order_by("-created_at")
    ]
    return _render_workspace(
        request,
        title="Recruitment & Vacancies",
        description="Approved and active vacancies connected to the real candidate pipeline, reporting owners, and target start dates.",
        metrics=[
            _metric(
                "Open",
                vacancies.filter(status="Open").count(),
                "accepting candidates",
                "success",
            ),
            _metric(
                "Pending approval",
                vacancies.filter(status="Pending Approval").count(),
                "requiring decision",
                "warning",
            ),
            _metric(
                "In screening",
                vacancies.filter(status="Screening").count(),
                "active selection",
                "info",
            ),
            _metric(
                "Applications",
                Application.objects.filter(vacancy__in=vacancies).count(),
                "across visible vacancies",
            ),
        ],
        rows=rows,
        primary_action={
            "label": "Open Candidate Pipeline",
            "href": "/candidate-pipeline",
        },
        empty_title="No vacancies have been created",
        empty_body="Approved job openings will appear here once HR starts the recruitment workflow.",
    )


@require_page_permission("candidate_pipeline")
def candidate_pipeline_view(request):
    query = (request.GET.get("q") or "").strip()
    applications = Application.objects.select_related("candidate", "vacancy")
    viewer = getattr(request.user, "staff_profile", None)
    if request.user.active_role != "Admin":
        applications = (
            applications.filter(vacancy__country=getattr(viewer, "country", ""))
            if viewer
            else applications.none()
        )
    if query:
        applications = applications.filter(
            Q(candidate__name__icontains=query)
            | Q(candidate__email__icontains=query)
            | Q(vacancy__role__icontains=query)
            | Q(stage__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Candidate", application.candidate.name, primary=True),
                _cell("Vacancy", application.vacancy.role),
                _cell("Country", application.vacancy.country),
                _cell("Stage", application.stage, status=True),
                _cell("Updated", application.updated_at.date()),
            ]
        }
        for application in applications.order_by("-updated_at")
    ]
    return _render_workspace(
        request,
        title="Candidate Pipeline",
        description="Every candidate application, scoped to visible vacancies and grouped by its current evidence-backed selection stage.",
        metrics=[
            _metric("Applications", applications.count(), "visible candidate records"),
            _metric(
                "Screening",
                applications.filter(stage__in=["Screened", "Shortlisted"]).count(),
                "in early assessment",
                "info",
            ),
            _metric(
                "Interviews",
                applications.filter(
                    stage__in=[
                        "Interview 1",
                        "Interview 2",
                        "Assessment",
                        "Reference Check",
                    ]
                ).count(),
                "in active selection",
                "warning",
            ),
            _metric(
                "Hired",
                applications.filter(stage="Hired").count(),
                "accepted candidates",
                "success",
            ),
        ],
        rows=rows,
        primary_action={"label": "Review Vacancies", "href": "/recruitment"},
        empty_title="No candidate applications yet",
    )


@require_page_permission("onboarding")
def onboarding_view(request):
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
                _cell("Status", plan.status, status=True),
            ]
        }
        for plan in plans.order_by("-created_at")
    ]
    return _render_workspace(
        request,
        title="Staff Onboarding",
        description="New-hire activation plans with live checklist completion, start dates, and ownership context.",
        metrics=[
            _metric("Plans", plans.count(), "onboarding records in scope"),
            _metric(
                "Active",
                plans.filter(status="Active").count(),
                "fully activated",
                "success",
            ),
            _metric(
                "In progress",
                plans.exclude(status__in=["Active", "Overdue"]).count(),
                "moving through checklist",
                "info",
            ),
            _metric(
                "Overdue",
                plans.filter(status="Overdue").count(),
                "requiring intervention",
                "danger",
            ),
        ],
        rows=rows,
        primary_action={"label": "Open People Directory", "href": "/staff"},
        empty_title="No onboarding plans in this scope",
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
    if (
        request.headers.get("HX-Request") == "true"
        and request.GET.get("partial") == "tracker"
    ):
        return render(request, "partials/hr/pd_dashboard/tracker_table.html", context)
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/hr/pd_dashboard/body.html", context)
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
            currency=request.POST.get("currency") or "UGX",
            apply_to_existing=request.POST.get("apply_to_existing") == "on",
        )
        messages.success(
            request, f"PD allocation updated for {ROLE_LABELS.get(role, role)}."
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect(f"/cpd-learning?fy={fy}&country={country}")


@require_page_permission("cpd_learning")
def pd_dashboard_action_view(request):
    """send_reminder / sign_off dispatched from the HR Action Center."""
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

            PDCourseTrackingService.sign_off(request_id, request.user)
            messages.success(request, "Course signed off and closed.")
        elif action == "send_reminder":
            from apps.professional_development.approval_service import (
                PDApprovalRoutingService,
            )
            from apps.professional_development.models import (
                ProfessionalDevelopmentRequest,
            )

            req = ProfessionalDevelopmentRequest.objects.filter(id=request_id).first()
            if not req or not req.owner_user_id:
                raise BadRequest("Request not found.")
            PDApprovalRoutingService._notify(
                req.owner_user_id,
                "Reminder from HR",
                f"HR sent you a reminder about “{req.course_name}” — check My Professional Development for what's due.",
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
            for req in due_qs:
                if req.owner_user_id:
                    PDApprovalRoutingService._notify(
                        req.owner_user_id,
                        "Reminder from HR",
                        f"HR sent you a reminder about “{req.course_name}” — check My Professional Development.",
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
    return redirect(f"/cpd-learning?fy={fy}&country={country}")


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
    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    reviews = PerformanceReview.objects.filter(staff_id__in=visible_ids).select_related(
        "staff__user"
    )
    if query:
        reviews = reviews.filter(
            Q(staff__user__name__icontains=query)
            | Q(period__icontains=query)
            | Q(review_type__icontains=query)
            | Q(status__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Team member", review.staff.user.name, primary=True),
                _cell("Period", review.period),
                _cell("Review type", review.review_type),
                _cell("Due", review.due_date),
                _cell("Score", f"{review.score:.0f}%"),
                _cell("Status", review.status, status=True),
            ]
        }
        for review in reviews.order_by("due_date", "staff__user__name")
    ]
    return _render_workspace(
        request,
        title="Performance Reviews",
        description="A period-aware review register connected to staff identity, due dates, calibrated scores, and review state.",
        metrics=[
            _metric("Reviews", reviews.count(), "records in access scope"),
            _metric(
                "Completed",
                reviews.filter(status__in=["Completed", "Closed"]).count(),
                "finished reviews",
                "success",
            ),
            _metric(
                "Manager pending",
                reviews.filter(status="Manager Review Pending").count(),
                "awaiting supervisor",
                "warning",
            ),
            _metric(
                "Average score",
                f"{(sum(r.score for r in reviews) / reviews.count()):.0f}%"
                if reviews.count()
                else "0%",
                "across visible reviews",
                "info",
            ),
        ],
        rows=rows,
        primary_action={"label": "Open Team Targets", "href": "/team-targets/"},
        empty_title="No performance reviews in this scope",
    )


@require_page_permission("recovery_plans")
def recovery_plans_view(request):
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
    rows = [
        {
            "cells": [
                _cell("Team member", plan.staff.user.name, primary=True),
                _cell("Cause", plan.cause),
                _cell("Start", plan.start_date),
                _cell("Review by", plan.end_date),
                _cell("Status", plan.status, status=True),
            ]
        }
        for plan in plans.order_by("end_date")
    ]
    return _render_workspace(
        request,
        title="Performance Recovery Plans",
        description="Active and completed improvement plans with explicit causes, time windows, and escalation state.",
        metrics=[
            _metric("Plans", plans.count(), "visible recovery records"),
            _metric(
                "Active",
                plans.filter(status__in=["Active", "Progress Review"]).count(),
                "under active review",
                "warning",
            ),
            _metric(
                "Escalated",
                plans.filter(status="Escalated").count(),
                "requiring leadership",
                "danger",
            ),
            _metric(
                "Completed",
                plans.filter(status__in=["Successfully Completed", "Closed"]).count(),
                "closed outcomes",
                "success",
            ),
        ],
        rows=rows,
        primary_action={"label": "Review Team Performance", "href": "/team-targets/"},
        empty_title="No recovery plans in this scope",
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
    query = (request.GET.get("q") or "").strip()
    # The highest-privacy register on the platform was the ONE HR surface with
    # no scope at all — every grievance, harassment, whistleblowing and
    # safeguarding case in every country, with `is_confidential` rendered as a
    # label that filtered nothing. The model carries no country or subject
    # field, so the owner's country is the available bound today.
    cases = _employee_relations_scope(request.user)
    if query:
        cases = cases.filter(
            Q(case_type__icontains=query)
            | Q(status__icontains=query)
            | Q(severity__icontains=query)
            | Q(case_owner__name__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Case type", case.case_type, primary=True),
                _cell("Severity", case.severity.title(), status=True),
                _cell(
                    "Owner", case.case_owner.name if case.case_owner else "Unassigned"
                ),
                _cell(
                    "Confidentiality",
                    "Restricted" if case.is_confidential else "Standard",
                ),
                _cell("Updated", case.updated_at.date()),
                _cell("Status", case.status, status=True),
            ]
        }
        for case in cases.order_by("-updated_at")
    ]
    return _render_workspace(
        request,
        title="Employee Relations Cases",
        description="A restricted case register for grievances, conduct, safeguarding, and whistleblowing—details remain protected from the overview surface.",
        metrics=[
            _metric(
                "Open cases",
                cases.exclude(status__in=["Resolved", "Closed"]).count(),
                "requiring case ownership",
            ),
            _metric(
                "Triage",
                cases.filter(status__in=["Submitted", "Triage"]).count(),
                "awaiting assessment",
                "warning",
            ),
            _metric(
                "Critical",
                cases.filter(severity="critical")
                .exclude(status__in=["Resolved", "Closed"])
                .count(),
                "urgent restricted cases",
                "danger",
            ),
            _metric(
                "Resolved",
                cases.filter(status__in=["Resolved", "Closed"]).count(),
                "closed case records",
                "success",
            ),
        ],
        rows=rows,
        primary_action={"label": "Review HR Dashboard", "href": "/dashboard"},
        empty_title="No employee-relations cases",
        empty_body="No confidential case records are visible in your current scope.",
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
    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    records = CompensationRecord.objects.filter(
        staff_id__in=visible_ids
    ).select_related("staff__user")
    if query:
        records = records.filter(
            Q(staff__user__name__icontains=query)
            | Q(salary_band__icontains=query)
            | Q(benefits_tier__icontains=query)
            | Q(status__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Team member", record.staff.user.name, primary=True),
                _cell("Role", record.staff.title or record.staff.user.active_role),
                _cell("Country", record.staff.country),
                _cell("Salary band", record.salary_band),
                _cell("Benefits tier", record.benefits_tier),
                _cell("Status", record.status, status=True),
            ]
        }
        for record in records.order_by("staff__user__name")
    ]
    profiles = _profile_scope(request)
    return _render_workspace(
        request,
        title="Compensation & Benefits",
        description="A privacy-conscious readiness register for pay bands and benefits tiers. Bank accounts and salary amounts are deliberately excluded from this overview.",
        metrics=[
            _metric("Compensation profiles", records.count(), "configured records"),
            _metric(
                "Approved",
                records.filter(status="Approved").count(),
                "completed HR review",
                "success",
            ),
            _metric(
                "In review",
                records.exclude(status="Approved").count(),
                "requiring HR action",
                "warning",
            ),
            _metric(
                "Missing profiles",
                max(profiles.count() - records.count(), 0),
                "staff without a record",
                "danger",
            ),
        ],
        rows=rows,
        primary_action={"label": "Open People Directory", "href": "/staff"},
        empty_title="No compensation profiles in this scope",
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
            "label": "Review Finance Operations",
            "href": "/finance/fund-allocation",
        },
        empty_title="No payroll-readiness checks in this scope",
    )


@require_page_permission("compliance_register")
def compliance_register_view(request):
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
    rows = [
        {
            "cells": [
                _cell("Team member", record.staff.user.name, primary=True),
                _cell("Requirement", record.requirement.name),
                _cell("Jurisdiction", record.requirement.country),
                _cell("Expiry", record.expiry_date),
                _cell(
                    "Verified by",
                    record.verified_by.name if record.verified_by else "Not verified",
                ),
                _cell("Status", record.status, status=True),
            ]
        }
        for record in records.order_by("expiry_date", "staff__user__name")
    ]
    requirements = ComplianceRequirement.objects.all()
    return _render_workspace(
        request,
        title="Compliance Register",
        description="Employee compliance evidence connected to jurisdictional requirements, expiry dates, and named verification authority.",
        metrics=[
            _metric("Requirements", requirements.count(), "configured controls"),
            _metric(
                "Compliant",
                records.filter(status="Compliant").count(),
                "verified records",
                "success",
            ),
            _metric(
                "Due soon",
                records.filter(status="Due Soon").count(),
                "approaching expiry",
                "warning",
            ),
            _metric(
                "Missing or expired",
                records.filter(status__in=["Missing", "Expired"]).count(),
                "requiring remediation",
                "danger",
            ),
        ],
        rows=rows,
        primary_action={"label": "Review Policies", "href": "/policies"},
        empty_title="No employee compliance records in this scope",
    )


@require_page_permission("policies")
def policies_view(request):
    query = (request.GET.get("q") or "").strip()
    requirements = ComplianceRequirement.objects.annotate(
        record_count=Count("employeecompliancerecord")
    )
    if query:
        requirements = requirements.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(country__icontains=query)
        )
    rows = [
        {
            "cells": [
                _cell("Policy or requirement", requirement.name, primary=True),
                _cell("Jurisdiction", requirement.country),
                _cell(
                    "Mandatory",
                    "Mandatory" if requirement.is_mandatory else "Optional",
                    status=True,
                ),
                _cell("Employee records", requirement.record_count),
                _cell("Updated", requirement.updated_at.date()),
            ]
        }
        for requirement in requirements.order_by("country", "name")
    ]
    return _render_workspace(
        request,
        title="Policies & Core Documents",
        description="The configured compliance-policy register. Document acknowledgements are not claimed until a dedicated acknowledgement model exists.",
        metrics=[
            _metric(
                "Configured", requirements.count(), "policy and compliance controls"
            ),
            _metric(
                "Mandatory",
                requirements.filter(is_mandatory=True).count(),
                "required controls",
                "warning",
            ),
            _metric(
                "Optional",
                requirements.filter(is_mandatory=False).count(),
                "advisory controls",
                "info",
            ),
            _metric(
                "Jurisdictions",
                requirements.values("country").distinct().count(),
                "countries or global scope",
            ),
        ],
        rows=rows,
        primary_action={
            "label": "Open Compliance Register",
            "href": "/compliance-register",
        },
        empty_title="No policies or compliance controls configured",
    )


@require_page_permission("offboarding")
def offboarding_view(request):
    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    plans = OffboardingPlan.objects.filter(staff_id__in=visible_ids).select_related(
        "staff__user", "handover_owner__user"
    )
    if query:
        plans = plans.filter(
            Q(staff__user__name__icontains=query)
            | Q(status__icontains=query)
            | Q(handover_owner__user__name__icontains=query)
        )
    from apps.hr.offboarding_service import accounts_past_last_working_day

    overdue_exits = (
        accounts_past_last_working_day().filter(staff_id__in=visible_ids).count()
    )

    rows = [
        {
            "cells": [
                _cell("Team member", plan.staff.user.name, primary=True),
                _cell("Role", plan.staff.title or plan.staff.user.active_role),
                _cell("Last working day", plan.last_working_day),
                _cell(
                    "Handover owner",
                    plan.handover_owner.user.name
                    if plan.handover_owner
                    else "Unassigned",
                ),
                _cell(
                    "Clearance",
                    "Completed" if plan.clearance_completed else "Pending",
                    status=True,
                ),
                _cell("Status", plan.status, status=True),
            ]
        }
        for plan in plans.order_by("last_working_day")
    ]
    return _render_workspace(
        request,
        title="Staff Offboarding",
        description="A controlled transition register covering handover ownership, final working dates, clearance, and closure state.",
        metrics=[
            _metric("Plans", plans.count(), "offboarding records in scope"),
            _metric(
                "In progress",
                plans.exclude(status="Closed").count(),
                "active transitions",
                "warning",
            ),
            _metric(
                "Handover gaps",
                plans.filter(handover_owner__isnull=True)
                .exclude(status="Closed")
                .count(),
                "without a named owner",
                "danger",
            ),
            _metric(
                "Closed",
                plans.filter(status="Closed").count(),
                "completed transitions",
                "success",
            ),
            # Nothing read `last_working_day`, so this condition was invisible:
            # an account stayed live past its approved termination date
            # indefinitely, with the person still in every roster and scope.
            _metric(
                "Past exit date, still active",
                overdue_exits,
                "accounts to close now",
                "danger" if overdue_exits else "success",
            ),
        ],
        rows=rows,
        primary_action={"label": "Open People Directory", "href": "/staff"},
        empty_title="No offboarding plans in this scope",
    )


@require_page_permission("hr_analytics")
def hr_analytics_view(request):
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
    return _render_workspace(
        request,
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
    events = AuditLog.objects.filter(
        Q(action__startswith="hr.")
        | Q(action__startswith="pd.")
        | Q(action__startswith="pd_")
        | Q(action__startswith="leave.")
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
                _cell("Action", event.action, primary=True),
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
        primary_action={"label": "Open System Health", "href": "/system-health"},
        empty_title="No HR audit events recorded yet",
    )


@require_page_permission("my_performance")
def my_performance_view(request):
    """My Performance — the employee's agreement, live progress, development
    and values. Progress is derived on read from the verified ledger; the
    page never shows a typed number."""
    from apps.hr.models import PerformanceCycle, PerformanceReview
    from apps.hr.performance_engine import development_rows, live_progress

    sp = getattr(request.user, "staff_profile", None)
    if sp is None:
        return render_access_denied(request, "No staff profile is linked.")
    from apps.core.fy import get_operational_fy

    fy = get_operational_fy()
    cycle = PerformanceCycle.objects.filter(fy=fy).first()
    review = PerformanceReview.objects.filter(
        staff=sp, fy=fy, review_type="annual_priorities"
    ).first()
    if cycle and review is None:
        from apps.hr.performance_engine import build_draft_agreement

        review = build_draft_agreement(sp, cycle, request.user)

    priorities = []
    if review:
        for p in review.priorities.all():
            progress = live_progress(p)
            priorities.append({"p": p, "progress": progress})
    context = {
        "cycle": cycle,
        "review": review,
        "priorities": priorities,
        "development": development_rows(review) if review else [],
        "values": list(review.value_commitments.all()) if review else [],
        "tab": request.GET.get("tab", "priorities"),
    }
    return render(request, "pages/hr/my_performance.html", context)
