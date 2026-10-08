"""Acting Leadership: the page, and the drawers that appoint, change and cancel.

A Programme Lead appoints one of their officers Acting Programme Lead, and a
Country Director one of their Leads Acting Country Director, for one calendar
month. Who may appoint whom, for which month, and every refusal come from
``apps.acting.services``; these views only ask it. The seat is always the
appointing leader's own, so no request names a team or a country.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import render
from django.utils.html import escape
from django.views.decorators.http import require_http_methods

from apps.acting import services
from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.core.permissions import require_page_permission

PAGE_URL = "/acting-leadership"

_REFUSALS = (BadRequest, ConflictError, Forbidden, NotFoundError)


def _message(exc) -> str:
    return str(getattr(exc, "detail", exc))


def _refresh(message: str) -> HttpResponse:
    """Close the drawer and redraw the page with the saved state."""
    response = HttpResponse(
        f'<p class="pill pill-success" role="status">{escape(message)}</p>'
    )
    response["HX-Trigger"] = "close-drawer"
    response["HX-Redirect"] = PAGE_URL
    return response


def _row(assignment):
    assignment.scope_text = services.scope_label(assignment)
    return assignment


@require_page_permission("acting_leadership")
@require_http_methods(["GET"])
def acting_leadership_view(request):
    """Current, upcoming and past acting appointments in the reader's reach."""
    board = services.board(request.user)
    for rows in board.values():
        for row in rows:
            _row(row)
    entry = services.appointing_policy(request.user)
    return render(
        request,
        "pages/acting/index.html",
        {
            **board,
            "appoints": entry,
            "has_candidates": bool(
                entry and services.eligible_appointees(request.user, entry)
            ),
        },
    )


@require_page_permission("acting_leadership")
@require_http_methods(["GET", "POST"])
def acting_appoint_view(request):
    """Appoint an acting leader: choose, read the statement, confirm."""
    entry = services.appointing_policy(request.user)
    source = request.POST if request.method == "POST" else request.GET
    months = services.month_options()
    values = {
        "appointee": (source.get("appointee") or "").strip(),
        "month": (source.get("month") or "").strip()
        # The usual appointment is made ahead, for next month.
        or (months[1]["value"] if len(months) > 1 else months[0]["value"]),
    }
    context = {
        "drawer_size": "md",
        "entry": entry,
        "candidates": services.eligible_appointees(request.user, entry)
        if entry
        else [],
        "months": months,
        "values": values,
        "selected_month": next(
            (m for m in months if m["value"] == values["month"]), None
        ),
        "step": "choose",
    }
    if entry is None:
        return render(
            request, "partials/acting/appoint_drawer.html", context, status=403
        )
    if request.method != "POST":
        return render(request, "partials/acting/appoint_drawer.html", context)

    step = (request.POST.get("step") or "review").strip()
    try:
        if step == "confirm":
            assignment = services.appoint(
                request.user,
                appointee_staff_id=values["appointee"],
                month=values["month"],
            )
            return _refresh(
                f"{assignment.appointee.name} is {assignment.label} for "
                f"{assignment.period_label}."
            )
        context["preview"] = services.preview(
            request.user,
            appointee_staff_id=values["appointee"],
            month=values["month"],
        )
        context["step"] = "confirm"
    except _REFUSALS as exc:
        context["validation_error"] = _message(exc)
    return render(request, "partials/acting/appoint_drawer.html", context)


@require_page_permission("acting_leadership")
@require_http_methods(["GET"])
def acting_record_view(request, assignment_id):
    """One appointment's record: who, by whom, what was granted, what was done."""
    try:
        assignment = _row(services.get_visible(request.user, assignment_id))
    except NotFoundError:
        return render(
            request,
            "partials/acting/record_drawer.html",
            {"drawer_size": "lg", "missing": True},
            status=404,
        )
    return render(
        request,
        "partials/acting/record_drawer.html",
        {
            "drawer_size": "lg",
            "assignment": assignment,
            "can_manage": services.may_manage(request.user, assignment),
            "actions": services.actions_under(assignment),
            # When the lifecycle sweep recorded the start and the end. Passed
            # by these names: the stylesheet build indexes template words and
            # reads a class into the field names.
            "started_at": assignment.activated_at,
            "ended_at": assignment.expired_at,
            "snapshot": assignment.grant_snapshot or {},
        },
    )


@require_page_permission("acting_leadership")
@require_http_methods(["GET", "POST"])
def acting_cancel_view(request, assignment_id):
    """Cancel an upcoming or active appointment; the record is kept."""
    context = {"drawer_size": "md"}
    try:
        assignment = _row(services.get_visible(request.user, assignment_id))
    except NotFoundError:
        return render(
            request,
            "partials/acting/cancel_drawer.html",
            {**context, "missing": True},
            status=404,
        )
    context.update(
        assignment=assignment,
        may_change=services.may_manage(request.user, assignment)
        and assignment.state() in ("upcoming", "active"),
        reason=(request.POST.get("reason") or "").strip(),
    )
    if request.method == "POST":
        try:
            services.cancel(request.user, assignment.id, reason=context["reason"])
        except _REFUSALS as exc:
            context["validation_error"] = _message(exc)
            return render(request, "partials/acting/cancel_drawer.html", context)
        return _refresh(
            f"{assignment.appointee.name}'s {assignment.short_label} appointment "
            f"for {assignment.period_label} is cancelled."
        )
    return render(request, "partials/acting/cancel_drawer.html", context)


@require_page_permission("acting_leadership")
@require_http_methods(["GET", "POST"])
def acting_reschedule_view(request, assignment_id):
    """Move an appointment that has not begun to another month."""
    context = {"drawer_size": "md"}
    try:
        assignment = _row(services.get_visible(request.user, assignment_id))
    except NotFoundError:
        return render(
            request,
            "partials/acting/reschedule_drawer.html",
            {**context, "missing": True},
            status=404,
        )
    months = services.month_options()
    source = request.POST if request.method == "POST" else request.GET
    chosen = (source.get("month") or "").strip() or (
        f"{assignment.start_date.year:04d}-{assignment.start_date.month:02d}"
    )
    context.update(
        assignment=assignment,
        may_change=services.appointing_policy(request.user) is not None
        and assignment.seat_id == getattr(request.user, "staff_profile_id", None)
        and assignment.is_upcoming(),
        months=months,
        month=chosen,
        selected_month=next((m for m in months if m["value"] == chosen), None),
    )
    if request.method == "POST":
        try:
            changed = services.reschedule(request.user, assignment.id, month=chosen)
        except _REFUSALS as exc:
            context["validation_error"] = _message(exc)
            return render(request, "partials/acting/reschedule_drawer.html", context)
        return _refresh(
            f"{changed.appointee.name}'s {changed.short_label} appointment is "
            f"now for {changed.period_label}."
        )
    return render(request, "partials/acting/reschedule_drawer.html", context)
