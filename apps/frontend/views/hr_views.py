from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render

from apps.accounts.models import Leave, StaffProfile
from apps.core.permissions import require_page_permission
from apps.hr.models import (
    Application,
    CompensationRecord,
    ComplianceRequirement,
    EmployeeComplianceRecord,
    EmployeeRelationsCase,
    HRAuditEvent,
    OffboardingPlan,
    OnboardingPlan,
    PayrollReadinessRecord,
    PerformanceImprovementPlan,
    PerformanceReview,
    SuccessionCandidate,
    Vacancy,
)


SUCCESS_TERMS = ("active", "approved", "closed", "completed", "compliant", "hired", "open", "ready", "resolved", "verified")
DANGER_TERMS = ("critical", "escalated", "expired", "missing", "overdue", "rejected", "suspended")
WARNING_TERMS = ("draft", "pending", "review", "screen", "triage", "progress", "submitted")


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
    if role == "ProgramLead" and viewer:
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


def _render_workspace(request, *, title, description, metrics, rows, primary_action, empty_title="No records in this scope", empty_body="New records will appear here as the connected workflow progresses."):
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
    profiles = _search_profiles(_profile_scope(request), (request.GET.get("q") or "").strip())
    rows = [
        {"cells": [
            _cell("Team member", profile.user.name, primary=True),
            _cell("Role", profile.title or profile.user.active_role),
            _cell("Department", profile.department),
            _cell("Country", profile.country),
            _cell("Lifecycle", profile.get_onboarding_state_display(), status=True),
        ]}
        for profile in profiles.order_by("department", "user__name")
    ]
    return _render_workspace(
        request,
        title="Organization Structure",
        description="A live, role-scoped directory of reporting capacity, departments, countries, and staff lifecycle state.",
        metrics=[
            _metric("People in scope", profiles.count(), "active and onboarding profiles", "info"),
            _metric("Active", profiles.filter(onboarding_state="active").count(), "fully activated staff", "success"),
            _metric("Departments", profiles.exclude(department__isnull=True).exclude(department="").values("department").distinct().count(), "represented in this scope"),
            _metric("Countries", profiles.values("country").distinct().count(), "operating footprint"),
        ],
        rows=rows,
        primary_action={"label": "Open People Directory", "href": "/staff"},
    )


@require_page_permission("workforce_planning")
def workforce_planning_view(request):
    profiles = _search_profiles(_profile_scope(request), (request.GET.get("q") or "").strip())
    grouped = profiles.values("department", "country").annotate(
        headcount=Count("id"),
        active=Count("id", filter=Q(onboarding_state="active")),
        pending=Count("id", filter=Q(onboarding_state="pending")),
    ).order_by("country", "department")
    rows = [{"cells": [
        _cell("Department", item["department"] or "Unassigned", primary=True),
        _cell("Country", item["country"]),
        _cell("Headcount", item["headcount"]),
        _cell("Active", item["active"]),
        _cell("Pending activation", item["pending"], status=item["pending"] > 0),
    ]} for item in grouped]
    return _render_workspace(
        request,
        title="Workforce Planning & Capacity",
        description="A truthful headcount and activation view derived from the current people directory—without forecast or budget values that have not been configured.",
        metrics=[
            _metric("Headcount", profiles.count(), "people in your access scope"),
            _metric("Active", profiles.filter(onboarding_state="active").count(), "available workforce", "success"),
            _metric("Pending", profiles.filter(onboarding_state="pending").count(), "awaiting activation", "warning"),
            _metric("Vacancies", Vacancy.objects.filter(status__in=["Approved", "Open", "Screening"]).count(), "approved or recruiting", "info"),
        ],
        rows=rows,
        primary_action={"label": "Review Recruitment", "href": "/recruitment"},
        empty_title="No workforce profiles in this scope",
    )


@require_page_permission("recruitment")
def recruitment_view(request):
    query = (request.GET.get("q") or "").strip()
    vacancies = Vacancy.objects.select_related("reporting_manager").annotate(application_count=Count("applications"))
    viewer = getattr(request.user, "staff_profile", None)
    if request.user.active_role != "Admin":
        vacancies = vacancies.filter(country=getattr(viewer, "country", "")) if viewer else vacancies.none()
    if query:
        vacancies = vacancies.filter(Q(role__icontains=query) | Q(department__icontains=query) | Q(country__icontains=query) | Q(status__icontains=query))
    rows = [{"cells": [
        _cell("Vacancy", vacancy.role, primary=True),
        _cell("Department", vacancy.department),
        _cell("Country", vacancy.country),
        _cell("Applications", vacancy.application_count),
        _cell("Target start", vacancy.target_start_date),
        _cell("Status", vacancy.status, status=True),
    ]} for vacancy in vacancies.order_by("-created_at")]
    return _render_workspace(
        request,
        title="Recruitment & Vacancies",
        description="Approved and active vacancies connected to the real candidate pipeline, reporting owners, and target start dates.",
        metrics=[
            _metric("Open", vacancies.filter(status="Open").count(), "accepting candidates", "success"),
            _metric("Pending approval", vacancies.filter(status="Pending Approval").count(), "requiring decision", "warning"),
            _metric("In screening", vacancies.filter(status="Screening").count(), "active selection", "info"),
            _metric("Applications", Application.objects.filter(vacancy__in=vacancies).count(), "across visible vacancies"),
        ],
        rows=rows,
        primary_action={"label": "Open Candidate Pipeline", "href": "/candidate-pipeline"},
        empty_title="No vacancies have been created",
        empty_body="Approved job openings will appear here once HR starts the recruitment workflow.",
    )


@require_page_permission("candidate_pipeline")
def candidate_pipeline_view(request):
    query = (request.GET.get("q") or "").strip()
    applications = Application.objects.select_related("candidate", "vacancy")
    viewer = getattr(request.user, "staff_profile", None)
    if request.user.active_role != "Admin":
        applications = applications.filter(vacancy__country=getattr(viewer, "country", "")) if viewer else applications.none()
    if query:
        applications = applications.filter(Q(candidate__name__icontains=query) | Q(candidate__email__icontains=query) | Q(vacancy__role__icontains=query) | Q(stage__icontains=query))
    rows = [{"cells": [
        _cell("Candidate", application.candidate.name, primary=True),
        _cell("Vacancy", application.vacancy.role),
        _cell("Country", application.vacancy.country),
        _cell("Stage", application.stage, status=True),
        _cell("Updated", application.updated_at.date()),
    ]} for application in applications.order_by("-updated_at")]
    return _render_workspace(
        request,
        title="Candidate Pipeline",
        description="Every candidate application, scoped to visible vacancies and grouped by its current evidence-backed selection stage.",
        metrics=[
            _metric("Applications", applications.count(), "visible candidate records"),
            _metric("Screening", applications.filter(stage__in=["Screened", "Shortlisted"]).count(), "in early assessment", "info"),
            _metric("Interviews", applications.filter(stage__in=["Interview 1", "Interview 2", "Assessment", "Reference Check"]).count(), "in active selection", "warning"),
            _metric("Hired", applications.filter(stage="Hired").count(), "accepted candidates", "success"),
        ],
        rows=rows,
        primary_action={"label": "Review Vacancies", "href": "/recruitment"},
        empty_title="No candidate applications yet",
    )


@require_page_permission("onboarding")
def onboarding_view(request):
    visible_ids = _profile_scope(request).values("id")
    query = (request.GET.get("q") or "").strip()
    plans = OnboardingPlan.objects.filter(staff_id__in=visible_ids).select_related("staff__user").annotate(
        total_tasks=Count("tasks"), completed_tasks=Count("tasks", filter=Q(tasks__is_completed=True))
    )
    if query:
        plans = plans.filter(Q(staff__user__name__icontains=query) | Q(staff__country__icontains=query) | Q(status__icontains=query))
    rows = [{"cells": [
        _cell("Team member", plan.staff.user.name, primary=True),
        _cell("Role", plan.staff.title or plan.staff.user.active_role),
        _cell("Country", plan.staff.country),
        _cell("Start date", plan.start_date),
        _cell("Checklist", f"{plan.completed_tasks} of {plan.total_tasks}"),
        _cell("Status", plan.status, status=True),
    ]} for plan in plans.order_by("-created_at")]
    return _render_workspace(
        request,
        title="Staff Onboarding",
        description="New-hire activation plans with live checklist completion, start dates, and ownership context.",
        metrics=[
            _metric("Plans", plans.count(), "onboarding records in scope"),
            _metric("Active", plans.filter(status="Active").count(), "fully activated", "success"),
            _metric("In progress", plans.exclude(status__in=["Active", "Overdue"]).count(), "moving through checklist", "info"),
            _metric("Overdue", plans.filter(status="Overdue").count(), "requiring intervention", "danger"),
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
            sent = 0
            for req in ProfessionalDevelopmentRequest.objects.filter(
                status__in=due_statuses
            ):
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
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Succession Planning",
            "capabilities": [
                "Critical roles dependency risk map.",
                "Potential successor profiles and readiness states.",
                "Individual development roadmaps.",
            ],
        },
    )


@require_page_permission("performance_reviews")
def performance_reviews_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Performance Reviews",
            "capabilities": [
                "Periodic review cycles setup and schedules.",
                "Self-assessments and manager feedback calibration.",
                "Target achievement scores rollup.",
            ],
        },
    )


@require_page_permission("recovery_plans")
def recovery_plans_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Performance Recovery Plans",
            "capabilities": [
                "Performance Improvement Plans (PIP) registration.",
                "Recovery milestones tracking and actions logging.",
                "PIP completion and escalation workflows.",
            ],
        },
    )


@require_page_permission("culture_engagement")
def culture_engagement_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Culture & Engagement",
            "capabilities": [
                "Staff satisfaction surveys and eNPS trackers.",
                "Recognition and reward nominations.",
                "Regional culture events registry.",
            ],
        },
    )


@require_page_permission("employee_relations")
def employee_relations_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Employee Relations Cases",
            "capabilities": [
                "Confidential grievance logging and triage workflows.",
                "Disciplinary hearings and findings register.",
                "Safeguarding and whistleblowing escalation channels.",
            ],
        },
    )


@require_page_permission("wellness")
def wellness_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Staff Wellness & Support",
            "capabilities": [
                "Work-life balance metrics monitoring.",
                "Counseling and employee assistance resources.",
                "Health & safety incident reports.",
            ],
        },
    )


@require_page_permission("compensation_benefits")
def compensation_benefits_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Compensation & Benefits",
            "capabilities": [
                "Grade structure and salary bands configuration.",
                "Allowance items and health insurance tier mapping.",
                "Staff bank details vault.",
            ],
        },
    )


@require_page_permission("payroll_readiness")
def payroll_readiness_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Payroll Readiness",
            "capabilities": [
                "Monthly payroll adjustments register (new joins, exits, leaves).",
                "Disbursement details verification checklists.",
                "Pay slip generation and bank upload sheets.",
            ],
        },
    )


@require_page_permission("compliance_register")
def compliance_register_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Compliance Register",
            "capabilities": [
                "Mandatory compliance requirements configuration by country.",
                "Staff compliance records tracking (contracts, permits, training).",
                "Expirations alerting and audit readiness status.",
            ],
        },
    )


@require_page_permission("policies")
def policies_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Policies & Core Documents",
            "capabilities": [
                "Organizational policy documents center.",
                "Mandatory policy acknowledgement tracking.",
                "Local labor regulation compliance standards.",
            ],
        },
    )


@require_page_permission("offboarding")
def offboarding_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "Staff Offboarding",
            "capabilities": [
                "Resignation and termination workflow checklist.",
                "Handover ownership assignment and equipment return checks.",
                "Exit interviews logging and finance clearance signoffs.",
            ],
        },
    )


@require_page_permission("hr_analytics")
def hr_analytics_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "HR Analytics & Workforce Insights",
            "capabilities": [
                "Workforce demographics and gender balance reports.",
                "Attrition and retention trends analytics.",
                "Target achievement vs. salary correlations.",
            ],
        },
    )


@require_page_permission("hr_audit_log")
def hr_audit_log_view(request):
    return render(
        request,
        "pages/hr/placeholder.html",
        {
            "title": "HR System Audit Log",
            "capabilities": [
                "Auditable logs of sensitive PII data modifications.",
                "Role reassignment and permissions changes tracking.",
                "Compliance override logging.",
            ],
        },
    )
