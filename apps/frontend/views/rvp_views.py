"""RVP executive actions — annual budget decisions, special-project strategy
decisions, strategy notes, and the approval center drawer.

Monthly budget approve/return stays on the canonical /country-budget/action
path (country_budget_service). Everything here is oversight: no field
execution, no disbursement."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render

from apps.core.permissions import require_page_permission
from apps.core.navigation import get_user_role_slug


def _require_rvp(request):
    return get_user_role_slug(request.user) in ("RVP", "ADMIN")


@require_page_permission("rvp_annual_action")
def rvp_annual_action_view(request, budget_id):
    if not _require_rvp(request):
        return HttpResponseForbidden("RVP only.")
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.monthly_work_plan.services import rvp_annual_decide

    action = (request.POST.get("action") or "").strip()
    try:
        b = rvp_annual_decide(
            budget_id, action, {"note": request.POST.get("note")}, request.user
        )
        messages.success(
            request,
            f"Annual budget FY {b.fy} "
            f"{'approved — baseline locked' if action == 'approve' else 'returned'}.",
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect("/dashboard")


@require_page_permission("rvp_project_decision")
def rvp_project_decision_view(request, project_id):
    """§18 — strategic project decision with confirmation + audit. Updates no
    field plans; records the decision and notifies the CD."""
    if not _require_rvp(request):
        return HttpResponseForbidden("RVP only.")
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    from apps.monthly_work_plan.services import _rvp_audit, _rvp_notify
    from apps.projects.models import Project

    ALLOWED = {
        "scale": "Approve Scale",
        "continue": "Continue Current Scope",
        "redesign": "Request Redesign",
        "pause": "Pause New Assignments",
        "reduce_budget": "Reduce Budget",
        "increase_budget": "Increase Budget",
        "close": "Close Project",
        "measure": "Request Additional Measurement",
    }
    action = (request.POST.get("action") or "").strip()
    if action not in ALLOWED:
        return HttpResponseBadRequest("Unknown project decision.")
    project = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if project is None:
        return HttpResponseBadRequest("Project not found.")
    reason = (request.POST.get("reason") or "").strip()
    _rvp_audit(
        "special_project", project.id, project.name, action, request.user, reason=reason
    )
    from apps.accounts.models import User

    for cd_user in User.objects.filter(
        roles__contains=["CountryDirector"], status="active"
    ):
        _rvp_notify(
            cd_user.id,
            f"RVP decision: {ALLOWED[action]}",
            f"{project.name} — {reason or 'strategic decision recorded.'}",
            "/projects",
        )
    messages.success(request, f"{ALLOWED[action]} recorded for {project.name}.")
    return redirect("/dashboard")


@require_page_permission("rvp_strategy_note")
def rvp_strategy_note_view(request):
    if not _require_rvp(request):
        return HttpResponseForbidden("RVP only.")
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    from apps.core.exceptions import BadRequest
    from apps.monthly_work_plan.services import create_strategy_note

    try:
        create_strategy_note(
            {
                "priority": request.POST.get("priority"),
                "scope": request.POST.get("scope"),
                "instruction": request.POST.get("instruction"),
                "expected_outcome": request.POST.get("expected_outcome"),
                "responsible_cd_id": request.POST.get("responsible_cd_id"),
                "deadline": request.POST.get("deadline") or None,
                "review_date": request.POST.get("review_date") or None,
            },
            request.user,
        )
        messages.success(
            request,
            "Strategy note recorded — the Country Director "
            "has been notified and a To-Do created.",
        )
    except BadRequest as exc:
        messages.error(request, str(exc))
    return redirect("/dashboard")


@require_page_permission("rvp_approvals")
def rvp_approvals_drawer_view(request):
    """The RVP Approval Center — monthly + annual queues, returned items and
    the immutable decision history."""
    if not _require_rvp(request):
        return HttpResponseForbidden("RVP only.")
    from apps.core.fy import get_operational_fy
    from apps.monthly_work_plan.models import (
        CountryAnnualBudget,
        MonthlyWorkPlanBudget,
        RVPApprovalDecision,
    )
    from apps.analytics.rvp_dashboard_service import RVPDashboardService

    from django.db.models import Q

    from apps.monthly_work_plan.services import _rvp_country_scope

    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    scope_country = _rvp_country_scope()
    monthly = MonthlyWorkPlanBudget.objects.filter(fy=fy).filter(
        Q(country_id=scope_country) | Q(country_id__isnull=True) | Q(country_id="")
    )
    return render(
        request,
        "partials/dashboards/rvp/approvals_drawer.html",
        {
            "fy": fy,
            "monthly_pending": [
                RVPDashboardService._budget_row(b)
                for b in monthly.filter(status="submitted_to_rvp").order_by("month_key")
            ],
            "monthly_returned": [
                RVPDashboardService._budget_row(b)
                for b in monthly.filter(status="returned_by_rvp").order_by(
                    "-month_key"
                )[:6]
            ],
            "annuals": [
                RVPDashboardService._annual_row(b)
                for b in CountryAnnualBudget.objects.filter(
                    fy=fy, country_id=scope_country
                )
            ],
            "history": RVPApprovalDecision.objects.order_by("-created_at")[:15],
        },
    )
