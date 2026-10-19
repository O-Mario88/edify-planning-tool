"""The day work was done, and what it frees (owner, 2026-10-16).

"add the date filed when the activity (school was visited or the group
training or cluster meeting) was completed on the completion drawer so that
the actual completion date is captured. if an activity is completed earlier
the system should record the actual completion date then free the planned
date for another activity to be rescheduled or planned." Asked, the owner
chose that the date may be today or any day before it ("some users complete
activities the day after or days after") and never a future day; then, told
that a day keeps its visits' money and a day whose request has left draft
takes no new visit: "move the money to the completed date as well".

So completion records ``Activity.actual_delivery_date``
(``completion_day`` checks it), and work done on another day than planned
moves there with its money (``move_to_completed_day``): the day it was
planned for is kept as ``planned_date_before_completion`` and is free for
other work. The money moves the way a reschedule moves it
(``services._reprice_moved_activity``), a week whose request was sent and not
paid coming back to its owner. Where it cannot move — a partner's work,
another financial year, a week already paid, a day that cannot take the
visit — the work is completed all the same, its day recorded and its money
left where it was planned, and the reason is written to the audit log.
"""

from __future__ import annotations

from datetime import date, datetime, time

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest

FUTURE_DAY = "The completion date cannot be in the future."
NO_DAY = "Enter the date the activity was completed."


def completion_day(raw) -> date | None:
    """The day the work was done as entered: None when none was given, a
    refusal when it is not a date or is after today."""
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        day = timezone.localtime(raw).date() if timezone.is_aware(raw) else raw.date()
    elif isinstance(raw, date):
        day = raw
    else:
        try:
            day = date.fromisoformat(str(raw).strip()[:10])
        except ValueError as exc:
            raise BadRequest(NO_DAY) from exc
    if day > timezone.localdate():
        raise BadRequest(FUTURE_DAY)
    return day


def _planned_day(activity) -> date | None:
    from apps.core.clock import local_day

    return activity.planned_date or (
        local_day(activity.scheduled_date) if activity.scheduled_date else None
    )


def _why_it_stays(activity, day: date) -> str | None:
    """Why this work's money cannot follow it to ``day``, or None."""
    from apps.core.fy import get_operational_fy

    if activity.delivery_type == "partner":
        return "partner work is paid on the partner's own date"
    if str(get_operational_fy(day)) != str(activity.fy):
        return "the day it was done is in another financial year"
    return None


def move_to_completed_day(activity, principal) -> str:
    """Move completed work done on another day than planned to that day,
    with its money. Returns "same day", "moved" or "kept: <reason>"; never
    refuses the completion it follows."""
    from apps.activities.models import Activity

    fresh = Activity.objects.filter(pk=activity.pk).first()
    if fresh is None:
        return "same day"
    day = fresh.actual_delivery_date
    planned = _planned_day(fresh)
    if day is None or planned is None or day == planned:
        return "same day"
    reason = _why_it_stays(fresh, day)
    if reason is None:
        try:
            with transaction.atomic():
                _move(fresh, day, planned, principal)
        except BadRequest as exc:
            reason = str(getattr(exc, "detail", exc))
    if reason is not None:
        _audit(fresh, principal, planned, day, moved=False, reason=reason)
        return f"kept: {reason}"
    _audit(fresh, principal, planned, day, moved=True)
    activity.refresh_from_db()
    return "moved"


def _move(activity, day: date, planned: date, principal) -> None:
    from apps.activities.models import Activity
    from apps.activities.services import _reprice_moved_activity, _schedule_period
    from apps.core.fy import get_quarter_for_date
    from apps.daily_visit_batches.costs_follow import costs_follow
    from apps.fund_requests.plan_changes import (
        change_in_hand,
        planner_change,
        take_back_for_plan_change,
    )

    on_its_own = change_in_hand() is None
    with (
        planner_change(principal, activity),
        transaction.atomic(),
        costs_follow(principal, when=on_its_own),
    ):
        a = Activity.objects.select_for_update().get(pk=activity.pk)
        # A week whose request was sent and not paid comes back to its owner
        # and is rebuilt from the changed plan, as a reschedule does; a paid
        # week refuses, and the money stays.
        take_back_for_plan_change(a, principal, days=(planned, day))
        hour = (
            timezone.localtime(a.scheduled_date).time() if a.scheduled_date else time(9)
        )
        new_date = timezone.make_aware(
            datetime.combine(day, hour), timezone.get_current_timezone()
        )
        planned_date, planned_month, planned_week = _schedule_period(new_date, {})
        if a.end_date and a.planned_date:
            a.end_date = planned_date + (a.end_date - a.planned_date)
        a.planned_date_before_completion = a.planned_date_before_completion or planned
        a.scheduled_date = new_date
        a.quarter = get_quarter_for_date(new_date)
        a.planned_date = planned_date
        a.planned_month = planned_month
        a.planned_week = planned_week
        a.save(
            update_fields=[
                "planned_date_before_completion",
                "scheduled_date",
                "quarter",
                "planned_date",
                "planned_month",
                "planned_week",
                "end_date",
                "updated_at",
            ]
        )
        _reprice_moved_activity(
            a, {"reason": f"Completed on {day:%d %b %Y}"}, principal
        )


def _audit(activity, principal, planned, day, *, moved: bool, reason: str = ""):
    from apps.audit.services import log as audit_log

    audit_log(
        action="activity_moved_to_completed_day"
        if moved
        else "activity_completed_on_another_day",
        subject_kind="Activity",
        subject_id=str(activity.id),
        actor_id=str(getattr(principal, "id", "") or ""),
        actor_role=getattr(principal, "active_role", None),
        reason=reason or None,
        payload={
            "plannedDate": planned.isoformat(),
            "completedOn": day.isoformat(),
            "moved": moved,
        },
    )
