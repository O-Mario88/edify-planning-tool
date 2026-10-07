"""Whose work a calendar shows, and what it shows of it.

Owner rule, 2026-08-20: a calendar is PERSONAL. Every role sees the work they
planned themselves; team and country views live on the oversight pages. The
Calendar page applied that rule inline. Planning's Calendar View did not have
it at all: it narrowed to a CCEO's own work and gave every other role the
whole country's year, written into the page.

`personal_plan` is the rule, once, for both. `planning_events` is what
Planning's Calendar View draws from it.
"""

from __future__ import annotations

import datetime

from django.db.models import Q

from apps.core.activity_types import COMPLETED_WORK_STATUSES
from apps.core.clock import local_day

#: Not on anyone's calendar: called off, or still waiting for the school's
#: owner to approve it. Everything else that has a date is, whatever its
#: status. Naming the statuses that ARE shown is how a rescheduled activity
#: came to vanish from Planning's Calendar View: `rescheduled` was not on the
#: list.
OFF_CALENDAR_STATUSES = ("cancelled", "rejected", "awaiting_owner_approval")


def personal_plan(activities, user):
    """Narrow `activities` to the reader's own plan.

    * A partner's plan is the work scheduled for their organisation.
    * A staff member's is the work they are responsible for, and the
      partner-delivered work they monitor (a partner's activity has no
      responsible staff, so it is reachable only through its monitor).

    Ownership is written under two ids (`apps.core.scoping.owner_ids`): both
    are read.
    """
    from apps.core.scoping import owner_ids, resolve_partner_ids

    partner_ids = resolve_partner_ids(user)
    if partner_ids:
        return activities.filter(assigned_partner_id__in=partner_ids)
    return plan_of(activities, owner_ids(user))


def plan_of(activities, holder_ids):
    """Narrow `activities` to the plan of the staff these ids name: the work
    they are responsible for, and the partner-delivered work they monitor.

    It is `personal_plan` for somebody who is not the reader — the calendar a
    Programme Lead opens for one of their CCEOs draws what that CCEO's own
    calendar does (`apps.activities.calendar_people`).
    """
    ids = [i for i in holder_ids if i]
    return activities.filter(
        Q(responsible_staff_id__in=ids)
        | Q(monitored_by_staff_id__in=ids, delivery_type="partner")
    )


def planning_events(user, fy: str) -> list[dict]:
    """The reader's dated work in a financial year, as FullCalendar events.

    Plain data for ``json_script``: the names of schools reach the page
    through a JSON encoder, not through a template that writes JSON by hand.
    """
    from apps.activities.editing import is_executed
    from apps.activities.group_actions import tickable_ids
    from apps.activities.models import Activity

    rows = list(
        personal_plan(
            Activity.objects.filter(deleted_at__isnull=True, fy=fy)
            .exclude(status__in=OFF_CALENDAR_STATUSES)
            .select_related("school", "cluster", "event_district")
            .order_by("planned_date", "scheduled_date", "created_at"),
            user,
        )
    )
    tickable = tickable_ids(rows, user)
    events = []
    for activity in rows:
        start = _start(activity)
        if start is None:
            # Handed to a partner and not dated yet: nothing to draw.
            continue
        name = activity.activity_name_snapshot or activity.get_activity_type_display()
        where = _where(activity)
        pick = activity.id in tickable
        event = {
            "id": activity.id,
            "title": f"{name} @ {where}" if where else name,
            "start": start.isoformat(),
            "classNames": [
                "fc-event-completed"
                if activity.status in COMPLETED_WORK_STATUSES
                else "fc-event-planned"
            ],
            "extendedProps": {
                # A tick box: live work the reader may move or cancel.
                "pick": pick,
                # A click opens the Reschedule drawer on staff work that is
                # still only a plan; anything else opens its own record.
                "reschedule": bool(
                    pick
                    and activity.delivery_type != "partner"
                    and not is_executed(activity)
                ),
                "status": activity.status,
                "school": activity.school.name if activity.school_id else "",
                "activity_type": name,
            },
        }
        if activity.end_date and activity.end_date > start:
            # FullCalendar's end is exclusive.
            event["end"] = (activity.end_date + datetime.timedelta(days=1)).isoformat()
        events.append(event)
    return events


def _start(activity) -> datetime.date | None:
    """The day it is on, in the country's own time: `scheduled_date` is a
    local midnight stored in UTC, and its UTC day is the day before."""
    if activity.scheduled_date:
        return local_day(activity.scheduled_date)
    return activity.planned_date


def _where(activity) -> str:
    if activity.school_id:
        return activity.school.name
    if activity.cluster_id:
        return activity.cluster.name
    return activity.venue or (
        activity.event_district.name if activity.event_district_id else ""
    )
