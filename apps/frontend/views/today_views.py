"""The Today workbench — Phase 5 of the operations roadmap.

One primary daily surface for field roles, composed from flows that already
behave well: the day package (route + next activity), the derived To-Do
queue (waiting-on-you and exceptions close themselves when state changes),
the autopilot's proposed week, and the day-completion state. Domain pages
remain as capabilities; a routine day should not need them.

A Programme Lead's day is mostly other people's decisions (owner, 2026-09-13):
their Today opens on what waits on them — leadership handoffs ahead of their
own field chores — and their team in the field, and folds the route and the
proposed week into one line when no schools are assigned to them directly.
The CCEO's and Project Coordinator's workbench is unchanged.

Today and Dashboard are one page for the CCEO, the Program Lead and the
Project Coordinator (owner, 2026-09-14): the workbench is the Dashboard's
Today view, opened first, and one "Dashboard" link replaces the two.
"""

from functools import wraps

from django.contrib import messages
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.permissions import require_page_permission

WAITING_LIMIT = 6
EXCEPTION_LIMIT = 6
# How many of the team's activities today the Programme Lead's block lists
# before sending them to Team Oversight.
TEAM_TODAY_LIMIT = 12
# Work that was never going to happen is not on anyone's day.
_RELEASED_STATUSES = ("cancelled", "rejected", "deferred", "not_planned")


def _staff_guard(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "is_authenticated", False):
            return redirect("/login")
        return view(request, *args, **kwargs)

    wrapped.has_permission_guard = True
    return wrapped


def _split_todos(
    principal, *, leadership_first: bool = False
) -> tuple[list, list, int]:
    """Split the derived To-Do queue into the workbench's two lists using
    the queue's OWN vocabulary (todo_service rows carry priority
    critical/high/medium/low and status_key, with action_url/description) —
    the seam that silently breaks if either side invents keys.

    Returns (waiting, exceptions, queue total). For a Programme Lead the
    waiting list puts leadership handoffs — the team's and collaborators'
    requests for a decision — ahead of the lead's own field chores, keeping
    the queue's priority order inside each band (owner, 2026-09-13)."""

    from apps.command_center.todo_service import (
        get_cached_todos,
        is_leadership_handoff,
    )

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
    ]
    if leadership_first:
        waiting.sort(key=lambda todo: 0 if is_leadership_handoff(todo) else 1)
    return waiting[:WAITING_LIMIT], exceptions, payload.get("total", len(todos))


def _team_today(principal) -> dict:
    """The Programme Lead's team in the field today, and the completions
    waiting for the lead's confirmation.

    The officers are the lead's team (apps.hr.team_roster.team_members);
    an activity is theirs by the queue's attribution rule — the responsible
    staff member, or the monitoring one on partner delivery. Two reads for
    the activities and one for the review queue, whatever the team's size.
    """
    from django.db.models import Q

    from apps.activities.models import Activity
    from apps.hr.team_roster import team_members
    from apps.pl_review.services import queue as review_queue

    today = timezone.localdate()
    members = team_members(principal)
    owner_of: dict[str, str] = {}
    name_of: dict[str, str] = {}
    for member in members:
        name_of[member.id] = (member.user.name if member.user_id else "") or "CCEO"
        owner_of[member.id] = member.id
        if member.user_id:
            owner_of[member.user_id] = member.id
    ids = list(owner_of)
    if not ids:
        return {
            "groups": [],
            "activity_count": 0,
            "limit": TEAM_TODAY_LIMIT,
            "officers": 0,
            "completions": 0,
        }
    todays = (
        Activity.objects.filter(deleted_at__isnull=True)
        .filter(
            Q(planned_date=today)
            | Q(planned_date__isnull=True, scheduled_date__date=today)
        )
        .filter(
            Q(responsible_staff_id__in=ids)
            | Q(responsible_staff_id__isnull=True, monitored_by_staff_id__in=ids)
        )
        .exclude(status__in=_RELEASED_STATUSES)
    )
    groups: dict[str, list] = {}
    for activity in todays.select_related("school", "cluster").order_by(
        "scheduled_date", "id"
    )[:TEAM_TODAY_LIMIT]:
        owner = owner_of.get(activity.responsible_staff_id) or owner_of.get(
            activity.monitored_by_staff_id
        )
        if not owner:
            continue
        where = (
            activity.school.name
            if activity.school_id
            else (activity.cluster.name if activity.cluster_id else "Programme work")
        )
        groups.setdefault(owner, []).append(
            {
                "name": activity.get_activity_type_display(),
                "where": where,
                "status": activity.get_status_display(),
                "partner": activity.delivery_type == "partner",
            }
        )
    try:
        completions = len(review_queue(principal))
    except Exception:  # noqa: BLE001 - the review queue never breaks Today
        completions = 0
    return {
        "groups": [
            {"name": name_of[owner], "activities": rows}
            for owner, rows in sorted(groups.items(), key=lambda kv: name_of[kv[0]])
        ],
        "activity_count": todays.count(),
        "limit": TEAM_TODAY_LIMIT,
        "officers": len(members),
        "completions": completions,
    }


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


# Roles whose Today lives inside the Dashboard, as its Today view (owner,
# 2026-09-14: "merge today and dashboard as dashboard"). /today still answers
# for bookmarks and older notification links by opening that view.
DASHBOARD_TODAY_ROLES = ("CCEO", "Program Lead", "ProjectCoordinator")
DASHBOARD_TODAY_URL = "/dashboard?view=today"


def today_home_url(user) -> str:
    """Where the Today workbench lives for this user."""
    if getattr(user, "active_role", "") in DASHBOARD_TODAY_ROLES:
        return DASHBOARD_TODAY_URL
    return "/today"


def build_today_context(request) -> dict:
    """Everything the Today workbench renders (partials/today/workbench.html),
    for the Dashboard's Today view and the standalone page alike."""
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
    is_program_lead = getattr(request.user, "active_role", "") == "Program Lead"
    waiting, exceptions, queue_total = _split_todos(
        request.user, leadership_first=is_program_lead
    )
    team_today = _team_today(request.user) if is_program_lead else None
    has_own_portfolio = True
    if is_program_lead:
        from apps.core.scoping import resolve_user_scope

        has_own_portfolio = bool(resolve_user_scope(request.user).own_school_ids)
    proposal = (
        live_proposal_for(getattr(request.user, "staff_profile_id", None))
        if has_own_portfolio
        else None
    )
    done_count = sum(
        1
        for activity in activities
        if activity["status"] not in ("planned", "scheduled")
    )
    return {
        "package": package,
        "next_activity": next_activity,
        "waiting": waiting,
        "exceptions": exceptions,
        "queue_total": queue_total,
        "is_program_lead": is_program_lead,
        "team_today": team_today,
        "has_own_portfolio": has_own_portfolio,
        "proposal": proposal,
        "debrief_done": _debrief_done_today(request.user),
        "done_count": done_count,
        "today_label": timezone.localdate().strftime("%A, %d %B %Y"),
    }


@require_page_permission("today")
@_staff_guard
def today_panel(request):
    """The Dashboard's Today view, fetched by the panel once the dashboard has
    painted: the workbench reads the To-Do queue, which grows with the estate,
    so the dashboard response never waits for it (scale gate, 2026-09-14)."""
    return render(
        request,
        "partials/today/dashboard_view.html",
        {"today": build_today_context(request)},
    )


@require_page_permission("today")
@_staff_guard
def today_page(request):
    home = today_home_url(request.user)
    if home != "/today":
        return redirect(home)
    return render(request, "pages/today/index.html", build_today_context(request))


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
    return redirect(today_home_url(request.user))
