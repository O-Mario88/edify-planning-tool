"""Visit Requests — one page, two lenses.

An owner (CCEO, Programme Lead, Project Coordinator) sees the visits other
people have scheduled into their portfolio and decides on each. A request-only
country role (Country Director, Impact Assessment, Accountant) schedules from
Planning and follows what became of each request here. The rule itself lives
in apps.planning.visit_requests; this module only shows it.
"""

from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.permissions import RolePermissionService, require_page_permission
from apps.planning import visit_requests


def _owner_names(activities) -> dict[str, str]:
    """approval_owner_id -> name, one query for the page."""
    from apps.accounts.models import StaffProfile

    ids = {a.approval_owner_id for a in activities if a.approval_owner_id}
    if not ids:
        return {}
    return {
        sp.id: (sp.user.name if sp.user else "") or "the school's owner"
        for sp in StaffProfile.objects.filter(id__in=ids).select_related("user")
    }


def _requester_names(activities) -> dict[str, str]:
    """responsible_staff_id -> name, both id spaces, one query."""
    from apps.accounts.models import StaffProfile

    ids = {a.responsible_staff_id for a in activities if a.responsible_staff_id}
    if not ids:
        return {}
    names: dict[str, str] = {}
    for sp in StaffProfile.objects.filter(
        Q(id__in=ids) | Q(user_id__in=ids)
    ).select_related("user"):
        name = (sp.user.name if sp.user else "") or "A staff member"
        names[sp.id] = name
        if sp.user_id:
            names[sp.user_id] = name
    return names


@require_page_permission("visit_requests")
def visit_requests_page(request):
    user = request.user
    is_requester = RolePermissionService.can_request_school_visit(user)

    pending = list(visit_requests.pending_for_owner(user))
    requester_names = _requester_names(pending)
    for a in pending:
        a.requester_name = requester_names.get(a.responsible_staff_id, "A staff member")

    mine = list(visit_requests.requests_by(user)) if is_requester else []
    owner_names = _owner_names(mine)
    for a in mine:
        a.owner_name = owner_names.get(a.approval_owner_id, "the school's owner")

    context = {
        "is_requester": is_requester,
        "pending": pending,
        "mine": mine,
        "awaiting": visit_requests.AWAITING,
    }
    return render(request, "pages/planning/visit_requests.html", context)


@require_page_permission("visit_requests")
@require_POST
def visit_request_decide(request, activity_id, decision):
    if decision not in ("approve", "decline"):
        return HttpResponse("Unknown decision.", status=404)
    note = (request.POST.get("note") or request.POST.get("reason") or "").strip()
    try:
        if decision == "approve":
            a = visit_requests.approve(activity_id, request.user, note)
            where = a.school.name if a.school_id and a.school else "the school"
            messages.success(
                request,
                f"Visit to {where} approved. It is now on the requester's plan.",
            )
        else:
            a = visit_requests.decline(activity_id, request.user, note)
            where = a.school.name if a.school_id and a.school else "the school"
            messages.success(
                request, f"Visit to {where} declined. The requester has been told."
            )
    except Forbidden:
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(activity_id),
            actor_id=str(request.user.id),
            actor_role=getattr(request.user, "active_role", None),
            success=False,
            reason="Attempted to decide a visit request for a school they do not own.",
        )
        return HttpResponseForbidden("You are not allowed to perform this action.")
    except (BadRequest, NotFoundError) as exc:
        messages.error(request, str(exc))
    return redirect(visit_requests.QUEUE_URL)
