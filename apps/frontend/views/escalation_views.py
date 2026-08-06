"""Escalations — the CD→RVP decision channel.

The CD cockpit offered "Escalate to RVP" with no endpoint behind it, and the
RVP had no inbound surface at all. This is both halves: the CD raises, the RVP
decides, and the decision comes back with its reasoning attached.
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
    is_cd = role in (EdifyRole.COUNTRY_DIRECTOR.value, EdifyRole.ADMIN.value)

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
                messages.success(
                    request,
                    f"Escalated to the RVP — “{esc.subject}”. "
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
                messages.success(
                    request,
                    "Decision recorded — the Country Director has been notified.",
                )
            else:
                messages.error(request, "Unknown action.")
        except (BadRequest, Forbidden, NotFoundError) as exc:
            messages.error(request, str(exc))
        return redirect("/escalations")

    return render(
        request,
        "pages/escalations/index.html",
        {
            "board": escalation_service.board(request.user),
            "is_rvp": is_rvp,
            "can_raise": is_cd,
        },
    )
