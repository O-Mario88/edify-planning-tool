from django.contrib import messages
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render

from apps.core.permissions import require_page_permission


@require_page_permission("org_structure")
def org_structure_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Organization Structure",
        "capabilities": [
            "Visual organogram reporting lines mapping.",
            "Functional department structures and roles hierarchy.",
            "Cross-functional team matrix definitions."
        ]
    })


@require_page_permission("workforce_planning")
def workforce_planning_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Workforce Planning & Capacity",
        "capabilities": [
            "FTE headcount targets and budget gap analysis.",
            "Staff workload distribution and overload analysis.",
            "Recruitment priorities planning."
        ]
    })


@require_page_permission("recruitment")
def recruitment_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Recruitment & Vacancies",
        "capabilities": [
            "Requisition and vacancy approval workflows.",
            "Job descriptions registry and salary bands mapping.",
            "Integration with global recruitment channels."
        ]
    })


@require_page_permission("candidate_pipeline")
def candidate_pipeline_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Candidate Pipeline",
        "capabilities": [
            "Applicant tracking system (ATS) pipeline states.",
            "Interview schedules and screening forms.",
            "Reference check logging and offer letter generation."
        ]
    })


@require_page_permission("onboarding")
def onboarding_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Staff Onboarding",
        "capabilities": [
            "New hire orientation checklist tracking.",
            "Automated system account setup queues.",
            "Documents collection and supervisor orientation tasks."
        ]
    })


@require_page_permission("cpd_learning")
def cpd_learning_view(request):
    """HR Professional Development Dashboard (§16) — the management
    command-center sitting beside the employee-owned My Professional
    Development page. Same underlying data, HR/CD/PL oversight scope."""
    from apps.professional_development.hr_dashboard_service import HRPDDashboardService

    if not getattr(request.user, "staff_profile_id", None):
        return HttpResponseForbidden("No staff profile on this account.")
    params = {
        "fy": request.GET.get("fy"), "country": request.GET.get("country"),
        "role": request.GET.get("role"), "status": request.GET.get("status"),
        "reminder": request.GET.get("reminder"), "q": request.GET.get("q"),
        "page": request.GET.get("page"),
    }
    try:
        context = HRPDDashboardService.get_dashboard(request.user, params)
    except ValueError:
        return HttpResponseBadRequest("Invalid filter value.")
    if request.headers.get("HX-Request") == "true" and request.GET.get("partial") == "tracker":
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
        PD_ELIGIBLE_ROLES,
        ROLE_LABELS,
        HRPDDashboardService,
    )
    from apps.professional_development.models import PDRoleAllocation

    role = request.GET.get("role") or request.POST.get("role") or ""
    fy = request.GET.get("fy") or request.POST.get("fy") or get_operational_fy()
    country = request.GET.get("country") or request.POST.get("country") or "Uganda"

    if request.method == "GET":
        existing = PDRoleAllocation.objects.filter(role=role, fy=fy, country=country).first()
        from apps.accounts.models import StaffProfile

        staff_count = StaffProfile.objects.filter(user__active_role=role, country=country).count()
        return render(request, "partials/hr/pd_dashboard/adjust_allocation_drawer.html", {
            "role": role, "role_label": ROLE_LABELS.get(role, role), "fy": fy, "country": country,
            "existing": existing, "staff_count": staff_count,
            "per_staff": (existing.annual_allocation_cents / 100) if existing else 0,
        })

    try:
        amount = float(request.POST.get("annual_allocation") or 0)
    except ValueError:
        return HttpResponseBadRequest("Invalid amount.")
    try:
        HRPDDashboardService.adjust_role_allocation(
            request.user, role=role, fy=fy, country=country, amount_major=amount,
            currency=request.POST.get("currency") or "UGX",
            apply_to_existing=request.POST.get("apply_to_existing") == "on",
        )
        messages.success(request, f"PD allocation updated for {ROLE_LABELS.get(role, role)}.")
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
            from apps.professional_development.completion_service import PDCourseTrackingService

            PDCourseTrackingService.sign_off(request_id, request.user)
            messages.success(request, "Course signed off and closed.")
        elif action == "send_reminder":
            from apps.professional_development.approval_service import PDApprovalRoutingService
            from apps.professional_development.models import ProfessionalDevelopmentRequest

            req = ProfessionalDevelopmentRequest.objects.filter(id=request_id).first()
            if not req or not req.owner_user_id:
                raise BadRequest("Request not found.")
            PDApprovalRoutingService._notify(
                req.owner_user_id, "Reminder from HR",
                f"HR sent you a reminder about “{req.course_name}” — check My Professional Development for what's due.",
                req,
            )
            messages.success(request, f"Reminder sent to {req.staff_name}.")
        elif action == "bulk_send_reminders":
            from apps.professional_development.approval_service import PDApprovalRoutingService
            from apps.professional_development.models import ProfessionalDevelopmentRequest

            bucket = request.POST.get("bucket") or ""
            due_statuses = {
                "not_started": ("submitted_to_supervisor", "submitted_to_hr", "pending_exception",
                                "approved_pending_funding", "approved_unfunded", "disbursed", "enrollment_pending"),
                "in_progress": ("enrollment_confirmed", "in_progress"),
                "pending_certificate": ("ended", "marked_complete"),
                "pending_accountability": ("bamboohr_confirmed", "accountability_submitted"),
            }.get(bucket, ())
            sent = 0
            for req in ProfessionalDevelopmentRequest.objects.filter(status__in=due_statuses):
                if req.owner_user_id:
                    PDApprovalRoutingService._notify(
                        req.owner_user_id, "Reminder from HR",
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
    return render(request, "pages/hr/placeholder.html", {
        "title": "Succession Planning",
        "capabilities": [
            "Critical roles dependency risk map.",
            "Potential successor profiles and readiness states.",
            "Individual development roadmaps."
        ]
    })


@require_page_permission("performance_reviews")
def performance_reviews_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Performance Reviews",
        "capabilities": [
            "Periodic review cycles setup and schedules.",
            "Self-assessments and manager feedback calibration.",
            "Target achievement scores rollup."
        ]
    })


@require_page_permission("recovery_plans")
def recovery_plans_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Performance Recovery Plans",
        "capabilities": [
            "Performance Improvement Plans (PIP) registration.",
            "Recovery milestones tracking and actions logging.",
            "PIP completion and escalation workflows."
        ]
    })


@require_page_permission("culture_engagement")
def culture_engagement_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Culture & Engagement",
        "capabilities": [
            "Staff satisfaction surveys and eNPS trackers.",
            "Recognition and reward nominations.",
            "Regional culture events registry."
        ]
    })


@require_page_permission("employee_relations")
def employee_relations_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Employee Relations Cases",
        "capabilities": [
            "Confidential grievance logging and triage workflows.",
            "Disciplinary hearings and findings register.",
            "Safeguarding and whistleblowing escalation channels."
        ]
    })


@require_page_permission("wellness")
def wellness_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Staff Wellness & Support",
        "capabilities": [
            "Work-life balance metrics monitoring.",
            "Counseling and employee assistance resources.",
            "Health & safety incident reports."
        ]
    })


@require_page_permission("compensation_benefits")
def compensation_benefits_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Compensation & Benefits",
        "capabilities": [
            "Grade structure and salary bands configuration.",
            "Allowance items and health insurance tier mapping.",
            "Staff bank details vault."
        ]
    })


@require_page_permission("payroll_readiness")
def payroll_readiness_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Payroll Readiness",
        "capabilities": [
            "Monthly payroll adjustments register (new joins, exits, leaves).",
            "Disbursement details verification checklists.",
            "Pay slip generation and bank upload sheets."
        ]
    })


@require_page_permission("compliance_register")
def compliance_register_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Compliance Register",
        "capabilities": [
            "Mandatory compliance requirements configuration by country.",
            "Staff compliance records tracking (contracts, permits, training).",
            "Expirations alerting and audit readiness status."
        ]
    })


@require_page_permission("policies")
def policies_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Policies & Core Documents",
        "capabilities": [
            "Organizational policy documents center.",
            "Mandatory policy acknowledgement tracking.",
            "Local labor regulation compliance standards."
        ]
    })


@require_page_permission("offboarding")
def offboarding_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "Staff Offboarding",
        "capabilities": [
            "Resignation and termination workflow checklist.",
            "Handover ownership assignment and equipment return checks.",
            "Exit interviews logging and finance clearance signoffs."
        ]
    })


@require_page_permission("hr_analytics")
def hr_analytics_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "HR Analytics & Workforce Insights",
        "capabilities": [
            "Workforce demographics and gender balance reports.",
            "Attrition and retention trends analytics.",
            "Target achievement vs. salary correlations."
        ]
    })


@require_page_permission("hr_audit_log")
def hr_audit_log_view(request):
    return render(request, "pages/hr/placeholder.html", {
        "title": "HR System Audit Log",
        "capabilities": [
            "Auditable logs of sensitive PII data modifications.",
            "Role reassignment and permissions changes tracking.",
            "Compliance override logging."
        ]
    })
