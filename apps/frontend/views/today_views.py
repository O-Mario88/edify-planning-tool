"""The Today workbench — Phase 5 of the operations roadmap.

One primary daily surface for field roles, composed from flows that already
behave well: the day package (route + next activity), the derived To-Do
queue (waiting-on-you and exceptions close themselves when state changes),
the autopilot's proposed week, and the day-completion state. Domain pages
remain as capabilities; a routine day should not need them.
"""

from functools import wraps

from django.contrib import messages
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.permissions import require_page_permission

WAITING_LIMIT = 6
EXCEPTION_LIMIT = 6


def _staff_guard(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect("/login")
        return view(request, *args, **kwargs)

    wrapped.has_permission_guard = True
    return wrapped


def _split_todos(principal) -> tuple[list, list]:
    """Split the derived To-Do queue into the workbench's two lists using
    the queue's OWN vocabulary (todo_service rows carry priority
    critical/high/medium/low and status_key, with action_url/description) —
    the seam that silently breaks if either side invents keys."""

    from apps.command_center.todo_service import get_cached_todos

    payload = get_cached_todos(principal)
    todos = payload.get("todos", [])
    exceptions = [
        todo
        for todo in todos
        if todo.get("priority") == "critical" or todo.get("status_key") == "blocked"
    ][:EXCEPTION_LIMIT]
    exception_ids = {todo.get("id") for todo in exceptions}
    waiting = [
        todo
        for todo in todos
        if todo.get("id") not in exception_ids and todo.get("actionable")
    ][:WAITING_LIMIT]
    return waiting, exceptions


def _debrief_done_today(user) -> bool:
    from datetime import datetime, time as dt_time

    from apps.debriefs.models import DailyDebrief

    today = timezone.localdate()
    tz = timezone.get_current_timezone()
    start = datetime.combine(today, dt_time.min, tzinfo=tz)
    end = datetime.combine(today, dt_time.max, tzinfo=tz)
    return DailyDebrief.objects.filter(
        submitted_by_user_id=user.id, date__range=(start, end)
    ).exists()


@require_page_permission("today")
@_staff_guard
def today_page(request):
    from apps.autopilot.services import live_proposal_for
    from apps.my_plan.day_package import build_day_package

    package = build_day_package(request.user)
    activities = [
        activity for group in package["routeGroups"] for activity in group["activities"]
    ]
    next_activity = next(
        (
            activity
            for activity in activities
            if activity["status"] in ("planned", "scheduled", "in_progress")
        ),
        None,
    )
    waiting, exceptions = _split_todos(request.user)
    proposal = live_proposal_for(getattr(request.user, "staff_profile_id", None))
    done_count = sum(
        1
        for activity in activities
        if activity["status"] not in ("planned", "scheduled")
    )
    return render(
        request,
        "pages/today/index.html",
        {
            "package": package,
            "next_activity": next_activity,
            "waiting": waiting,
            "exceptions": exceptions,
            "proposal": proposal,
            "debrief_done": _debrief_done_today(request.user),
            "done_count": done_count,
            "today_label": timezone.localdate().strftime("%A, %d %B %Y"),
        },
    )


@require_page_permission("today")
@_staff_guard
def today_action(request):
    from apps.core.exceptions import BadRequest
    from apps.accounts.models import StaffProfile
    from apps.autopilot.models import ProposedPlan
    from apps.autopilot.services import (
        accept_plan,
        dismiss_plan,
        generate_week_proposal,
    )

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    action = request.POST.get("action", "")
    try:
        if action == "prepare_week":
            staff = StaffProfile.objects.filter(
                id=getattr(request.user, "staff_profile_id", None)
            ).first()
            if staff is None:
                raise BadRequest("A staff profile is required to prepare a week.")
            plan = generate_week_proposal(staff)
            messages.success(
                request,
                f"Week of {plan.week_start:%d %b} prepared — "
                f"{plan.items.count()} visits to review.",
            )
        elif action == "accept_week":
            plan = ProposedPlan.objects.get(id=request.POST.get("plan"))
            if str(plan.staff_id) != str(getattr(request.user, "staff_profile_id", "")):
                return HttpResponseForbidden("A proposed week belongs to its owner.")
            result = accept_plan(plan, principal=request.user)
            messages.success(
                request,
                f"Week accepted — {len(result['created'])} activities are "
                "now planned work.",
            )
            for refusal in result["refused"]:
                messages.error(
                    request,
                    f"{refusal['school']}: {refusal['error']}",
                )
        elif action == "dismiss_week":
            plan = ProposedPlan.objects.get(id=request.POST.get("plan"))
            if str(plan.staff_id) != str(getattr(request.user, "staff_profile_id", "")):
                return HttpResponseForbidden("A proposed week belongs to its owner.")
            dismiss_plan(plan, principal=request.user)
            messages.success(request, "Draft week dismissed.")
        else:
            raise BadRequest("Unknown action.")
    except BadRequest as exc:
        messages.error(request, str(exc))
    return redirect("/today")
