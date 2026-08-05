"""School Actions — the sender's monitoring board and the recipient's queue.

Both pages show only the signed-in user's own rows: `actions_sent` filters on
sender_id, `actions_received` on recipient_id. Scoping is therefore intrinsic
rather than something a filter has to remember — which is why `my_actions` is
open to every role. There is no wider set of rows for a permissive gate to
expose. `actions_sent` is narrower only because the roles that cannot send
have nothing to monitor.

Every state change goes through `action_service`, never through the ORM here.
The service is where the refusals live (only the sender may cancel; a
system-verifiable condition cannot be hand-closed), and a view that wrote
`state` directly would walk straight past them.
"""

from __future__ import annotations

from django.http import HttpResponseForbidden
from django.shortcuts import render

from apps.core.permissions import require_page_permission
from apps.planning import action_service
from apps.planning.action_models import TeamAction
from apps.planning.action_workspace import actions_received, actions_sent


@require_page_permission("actions_sent")
def actions_sent_view(request):
    """What I have delegated, and whether it is moving."""
    tab = (request.GET.get("tab") or "open").strip()
    data = actions_sent(request.user, tab=tab)
    context = {
        **data,
        "page_title": "Actions Sent",
        "page_eyebrow": "Urgent Attention",
        "page_intro": (
            "School issues you have assigned. Each one leaves the urgent list "
            "when it is sent and closes here when the record shows the work is "
            "done."
        ),
        "empty_message": "You have not sent any school actions yet.",
        "back_url": "/dashboard",
        "back_label": "Dashboard",
    }
    if request.headers.get("HX-Request"):
        return render(request, "partials/actions/table.html", context)
    return render(request, "pages/actions/workspace.html", context)


@require_page_permission("my_actions")
def my_actions_view(request):
    """What I have been handed, and by when."""
    tab = (request.GET.get("tab") or "open").strip()
    data = actions_received(request.user, tab=tab)
    context = {
        **data,
        "page_title": "My Actions",
        "page_eyebrow": "Urgent Attention",
        "page_intro": (
            "School issues assigned to you. These close automatically once the "
            "record shows the work is complete."
        ),
        "empty_message": "Nothing has been assigned to you.",
        "back_url": "/dashboard",
        "back_label": "Dashboard",
    }
    if request.headers.get("HX-Request"):
        return render(request, "partials/actions/table.html", context)
    return render(request, "pages/actions/workspace.html", context)


# ── State changes ────────────────────────────────────────────────────────────

# Who may perform each transition, checked against the row rather than the
# role: an action is a two-party record, and the only people with standing are
# the two parties (plus Admin, who can unstick anything).
_RECIPIENT_ONLY = {"acknowledge", "start", "block", "return"}
_SENDER_ONLY = {"cancel", "escalate"}


@require_page_permission("my_actions")
def action_transition_view(request, action_id: str, transition: str):
    """Apply one lifecycle transition and re-render the row's workspace.

    Returns the refreshed table rather than a fragment so the counts, the tab
    membership and the row all move together — a row that changed state while
    its tab counts did not would read as a bug.
    """
    if request.method != "POST":
        return HttpResponseForbidden("POST only.")

    action = TeamAction.objects.filter(id=action_id).first()
    if not action:
        return HttpResponseForbidden("Action not found.")

    uid = getattr(request.user, "id", None)
    is_admin = getattr(request.user, "active_role", "") == "Admin"
    if transition in _RECIPIENT_ONLY and uid != action.recipient_id and not is_admin:
        return HttpResponseForbidden("This action was not assigned to you.")
    if transition in _SENDER_ONLY and uid != action.sender_id and not is_admin:
        return HttpResponseForbidden("You did not send this action.")

    reason = (request.POST.get("reason") or "").strip()
    error = ""
    try:
        if transition == "acknowledge":
            action_service.acknowledge(action, request.user)
        elif transition == "start":
            action_service.start(action, request.user)
        elif transition == "block":
            action_service.block(action, request.user, reason)
        elif transition == "return":
            action_service.return_to_sender(action, request.user, reason)
        elif transition == "cancel":
            action_service.cancel(action, request.user, reason)
        elif transition == "escalate":
            action_service.escalate(action, request.user)
        elif transition == "resolve":
            action_service.resolve_manually(action, request.user, reason)
        else:
            return HttpResponseForbidden("Unknown transition.")
    except action_service.ActionError as exc:
        error = str(exc)

    perspective = "sender" if uid == action.sender_id else "recipient"
    tab = (request.POST.get("tab") or request.GET.get("tab") or "open").strip()
    data = (
        actions_sent(request.user, tab=tab)
        if perspective == "sender"
        else actions_received(request.user, tab=tab)
    )
    return render(request, "partials/actions/table.html", {**data, "error": error})
