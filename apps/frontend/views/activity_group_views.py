"""Reschedule or cancel the ticked activities (owner, 2026-10-05).

Two drawers, opened by the bar that appears once an activity is ticked on My
Plan, the Work Plan, a profile's Planned table or the Calendar
(partials/activities/selection_bar.html). GET lists the ticked activities and
says which ones the action will leave and why; POST runs the single
reschedule or cancel for each (apps.activities.group_actions) and reports
what happened to every one.

Gated like the single drawers they stand beside: the `my_plan` page.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render

from apps.activities import group_actions
from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest
from apps.core.htmx_errors import error_fragment
from apps.core.permissions import require_page_permission
from apps.core.redirects import local_redirect

RESCHEDULE_PATH = "/activity-selection/reschedule"
CANCEL_PATH = "/activity-selection/cancel"


def _ticked(request) -> list[str]:
    """The ticked ids: one comma-joined `ids` when a drawer is opened (a
    hundred ids fit a query string that way), `activity_ids` when it posts."""
    if request.method == "POST":
        return request.POST.getlist("activity_ids")
    return [part for part in (request.GET.get("ids") or "").split(",") if part]


def _came_from(request):
    from urllib.parse import urlsplit

    path = urlsplit(request.META.get("HTTP_REFERER") or "").path
    return local_redirect(path, fallback="/my-plan")


def _names(picks, *, limit: int = 3) -> str:
    """ "A at X (why); B at Y (why) and 4 more" for a flash message."""
    shown = "; ".join(
        f"{p.title} at {p.where} ({p.refusal.rstrip('.')})" for p in picks[:limit]
    )
    more = len(picks) - limit
    return f"{shown} and {more} more" if more > 0 else shown


def _finish(request, outcome, *, done_message: str, template: str, verb: str):
    """Reload with the summary when anything changed; otherwise keep the
    drawer open with each activity's reason."""
    if outcome.done:
        message = done_message
        if outcome.refused:
            message += f" Not {verb}: {_names(outcome.refused)}."
        messages.success(request, message)
        if request.headers.get("HX-Request") != "true":
            return _came_from(request)
        response = HttpResponse(status=204)
        response["HX-Trigger"] = "close-drawer"
        response["HX-Refresh"] = "true"
        return response
    if request.headers.get("HX-Request") != "true":
        messages.error(request, f"Nothing was {verb}: {_names(outcome.refused)}.")
        return _came_from(request)
    return render(request, template, {"refused": outcome.refused, "verb": verb})


def _audit(request, action: str, outcome, payload: dict) -> None:
    for pick in outcome.done:
        audit_log(
            action=action,
            subject_kind="Activity",
            subject_id=str(pick.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            payload={**payload, "group": True},
        )
    for pick in outcome.refused:
        audit_log(
            action=action,
            subject_kind="Activity",
            subject_id=str(pick.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason=pick.refusal,
            payload={**payload, "group": True},
        )


def _drawer(request, template: str, *, action: str, also=None):
    try:
        picks = group_actions.selection(_ticked(request), request.user, action=action)
    except BadRequest as exc:
        return render(request, template, {"error": str(exc.detail)}, status=400)
    ready = [p for p in picks if not p.refusal]
    context = {
        "picks": picks,
        "ready": ready,
        "left": [p for p in picks if p.refusal],
        "joined": any(p.joined for p in ready),
        "drawer_size": "md",
    }
    if also:
        context.update(also(picks))
    return render(request, template, context)


@require_page_permission("my_plan")
def group_reschedule_view(request):
    """Move the ticked activities to one date."""
    template = "partials/my_plan/group_reschedule_drawer.html"
    if request.method != "POST":
        return _drawer(request, template, action=group_actions.RESCHEDULE)
    day = (request.POST.get("scheduled_date") or "").strip()
    reason = (request.POST.get("reason") or "").strip()
    try:
        outcome = group_actions.reschedule(_ticked(request), day, reason, request.user)
    except BadRequest as exc:
        return error_fragment(exc, status=400)
    _audit(request, "reschedule_activity", outcome, {"new_date": day, "reason": reason})
    count = len(outcome.done)
    from datetime import date

    return _finish(
        request,
        outcome,
        done_message=(
            f"{count} activit{'y' if count == 1 else 'ies'} moved to "
            f"{date.fromisoformat(day):%-d %B %Y}."
        ),
        template="partials/my_plan/group_outcome.html",
        verb="moved",
    )


@require_page_permission("my_plan")
def group_cancel_view(request):
    """Cancel the ticked activities, with one reason."""
    template = "partials/my_plan/group_cancel_drawer.html"
    if request.method != "POST":
        return _drawer(
            request,
            template,
            action=group_actions.CANCEL,
            also=lambda picks: {
                "money_moved": len(group_actions.money_moved_ids(picks)),
                "tells_partner": any(
                    p.activity.assigned_partner_id for p in picks if not p.refusal
                ),
            },
        )
    reason = (request.POST.get("reason") or "").strip()
    try:
        outcome = group_actions.cancel(_ticked(request), reason, request.user)
    except BadRequest as exc:
        return error_fragment(exc, action="Cancellation Error", status=400)
    _audit(request, "cancel_activity", outcome, {"reason": reason})
    count = len(outcome.done)
    return _finish(
        request,
        outcome,
        done_message=f"{count} activit{'y' if count == 1 else 'ies'} cancelled.",
        template="partials/my_plan/group_outcome.html",
        verb="cancelled",
    )
