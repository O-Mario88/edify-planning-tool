"""Escalations — the upward decision channel.

The CD cockpit offered "Escalate to RVP" with no endpoint behind it, and the
RVP had no inbound surface at all. This is both halves, one level at a time:
a CCEO raises to their Programme Lead, a PL to the Country Director, the CD to
the RVP — and the addressee decides, with the reasoning coming back attached.
"""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.permissions import require_page_permission
from apps.core.rbac import EdifyRole
from apps.flags import escalation_service


@require_page_permission("escalations")
def escalations_view(request):
    role = getattr(request.user, "active_role", "")
    is_rvp = role in (
        EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        EdifyRole.ADMIN.value,
    )
    # The level this principal decides for, if any — PL, CD or RVP. Admin
    # decides everything through the service's override.
    decider_level = escalation_service.ADDRESSEE_FOR_ROLE.get(role)
    can_decide = bool(decider_level) or role == EdifyRole.ADMIN.value

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "raise":
                esc = escalation_service.raise_escalation(
                    {
                        "category": request.POST.get("category"),
                        "severity": request.POST.get("severity"),
                        "subject": request.POST.get("subject"),
                        "detail": request.POST.get("detail"),
                        "requested_decision": request.POST.get("requested_decision"),
                        "due_date": request.POST.get("due_date") or None,
                    },
                    request.user,
                )
                addressee = escalation_service.ADDRESSEE_LABELS[esc.addressed_role]
                messages.success(
                    request,
                    f"Escalated to the {addressee} — “{esc.subject}”. "
                    "They have been notified.",
                )
            elif action == "acknowledge":
                escalation_service.acknowledge(
                    request.POST.get("escalation_id"), request.user
                )
                messages.success(request, "Escalation acknowledged.")
            elif action == "resolve":
                esc = escalation_service.resolve(
                    request.POST.get("escalation_id"),
                    {
                        "decision": request.POST.get("decision"),
                        "decision_note": request.POST.get("decision_note"),
                    },
                    request.user,
                )
                raiser = esc.raised_by_name or "the raiser"
                messages.success(
                    request, f"Decision recorded — {raiser} has been notified."
                )
            else:
                messages.error(request, "Unknown action.")
        except (BadRequest, Forbidden, NotFoundError) as exc:
            messages.error(request, str(exc))
        return redirect("/escalations")

    board = escalation_service.board(request.user)
    return render(
        request,
        "pages/escalations/index.html",
        {
            "board": board,
            "is_rvp": is_rvp,
            "can_raise": bool(board["raise_to"]),
            "can_decide": can_decide,
            "decider_level": decider_level,
            "decider_label": escalation_service.ADDRESSEE_LABELS.get(decider_level),
        },
    )
