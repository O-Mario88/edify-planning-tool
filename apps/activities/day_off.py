"""Planned work that sits on a day nobody is working.

Owner, 2026-10-05: "mark all activities planned on public holidays and days
staff set for leave red and alert the staff to reschedule the activities for
that day."

An activity is on a day off when it is still waiting for its day and any day
it runs on is:

- a public holiday (apps.core.public_holidays — the national calendar and the
  days recorded under Holidays & Blackouts), whoever delivers it; or
- a day its responsible staff member is on approved leave. A request still
  waiting for approval marks nothing: it is private to the person who made it
  and is not yet time off.

Work that has started or finished is left alone — a new date no longer helps.
Scheduling on such a day is still allowed (the calendar restrictions were
lifted on 2026-09-30); the mark and the notice are what is left to say so.

The Calendar, My Plan and the Work Plan read ``day_off_marks`` for the rows
they draw; ``send_day_off_alerts`` is the notice.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.core.clock import local_day
from apps.core.public_holidays import public_holidays_between

HOLIDAY = "holiday"
LEAVE = "leave"

#: Work still waiting for its day: the only work a new date helps.
AWAITING_DELIVERY = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "rescheduled",
)

DAY_OFF_EVENT = "activity_on_day_off"
#: How many activities a notice names before "and N more".
_NAMED = 3


@dataclass(frozen=True)
class DayOff:
    """One day off an activity runs on."""

    day: date
    kind: str
    #: The holiday, or the person on leave.
    name: str
    cover: str = ""

    @property
    def short(self) -> str:
        """The day and what it is, short enough for a table cell."""
        what = "Public holiday" if self.kind == HOLIDAY else "On leave"
        return f"{self.day:%a %-d %b} · {what}"

    @property
    def sentence(self) -> str:
        day = f"{self.day:%a %-d %b}"
        if self.kind == HOLIDAY:
            return f"{day} is a public holiday ({self.name})."
        text = f"{self.name} is on leave on {day}."
        if self.cover:
            text += f" {self.cover} is covering."
        return text


@dataclass(frozen=True)
class DayOffMark:
    """Why one activity is marked, in the words each surface shows."""

    days: tuple[DayOff, ...]

    @property
    def kinds(self) -> set[str]:
        return {day.kind for day in self.days}

    @property
    def label(self) -> str:
        if self.kinds == {HOLIDAY}:
            return "Public holiday"
        if self.kinds == {LEAVE}:
            return "On leave"
        return "Holiday and leave"

    @property
    def summary(self) -> str:
        """The first day off, and how many more: one line whatever the
        activity's length, for a column that must not wrap."""
        more = len(self.days) - 1
        return self.days[0].short + (f" +{more} more" if more else "")

    @property
    def why(self) -> str:
        return " ".join(day.sentence for day in self.days)

    @property
    def advice(self) -> str:
        return f"{self.why} Reschedule this activity."


def activity_span(activity) -> tuple[date, date] | None:
    """The days an activity runs on, read the way My Plan reads its date."""
    start = activity.planned_date or local_day(activity.scheduled_date)
    if not start:
        return None
    end = (
        activity.end_date if activity.end_date and activity.end_date > start else start
    )
    return start, end


def _days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _leave_by_owner(owner_ids: set[str], first: date, last: date) -> dict:
    """owner id (StaffProfile or User, as activities store either) ->
    (name, [(start, end, cover name)]) for approved leave in [first, last]."""
    from apps.accounts.models import Leave, StaffProfile

    if not owner_ids:
        return {}
    profiles = list(
        StaffProfile.objects.filter(
            Q(id__in=owner_ids) | Q(user_id__in=owner_ids)
        ).values_list("id", "user_id", "user__name")
    )
    if not profiles:
        return {}
    spells: dict[str, list] = defaultdict(list)
    for staff_id, start, end, cover in Leave.objects.filter(
        staff_id__in=[profile_id for profile_id, _, _ in profiles],
        status="approved",
        start_date__lte=last.isoformat(),
        end_date__gte=first.isoformat(),
    ).values_list("staff_id", "start_date", "end_date", "covering_staff__user__name"):
        try:
            spells[staff_id].append(
                (date.fromisoformat(start), date.fromisoformat(end), cover or "")
            )
        except (TypeError, ValueError):
            continue
    by_owner = {}
    for profile_id, user_id, name in profiles:
        if profile_id in spells:
            entry = (name or "The responsible staff member", spells[profile_id])
            by_owner[profile_id] = entry
            by_owner[user_id] = entry
    return by_owner


def day_off_marks(activities, *, spans: dict | None = None) -> dict[str, DayOffMark]:
    """activity id -> its mark, for the activities that sit on a day off.

    ``spans`` overrides the days of an activity (id -> (start, end)) for a
    page that has already worked them out its own way.
    """
    waiting = {}
    for activity in activities:
        if activity.status not in AWAITING_DELIVERY:
            continue
        span = (spans or {}).get(activity.id) or activity_span(activity)
        if span:
            waiting[activity.id] = (activity, span[0], span[1])
    if not waiting:
        return {}

    first = min(start for _, start, _ in waiting.values())
    last = max(end for _, _, end in waiting.values())
    holidays = public_holidays_between(first, last)
    leave = _leave_by_owner(
        {
            activity.responsible_staff_id
            for activity, _, _ in waiting.values()
            if activity.responsible_staff_id
        },
        first,
        last,
    )

    marks = {}
    for activity_id, (activity, start, end) in waiting.items():
        days = []
        name, spells = leave.get(activity.responsible_staff_id, ("", ()))
        for day in _days(start, end):
            if day in holidays:
                days.append(DayOff(day, HOLIDAY, holidays[day]))
            for leave_start, leave_end, cover in spells:
                if leave_start <= day <= leave_end:
                    days.append(DayOff(day, LEAVE, name, cover))
                    break
        if days:
            marks[activity_id] = DayOffMark(tuple(days))
    return marks


def _activity_label(activity) -> str:
    place = (
        getattr(activity.school, "name", "")
        if activity.school_id
        else getattr(activity.cluster, "name", "")
        if activity.cluster_id
        else (activity.venue or "")
    )
    kind = activity.activity_name_snapshot or activity.get_activity_type_display()
    return f"{kind} at {place}" if place else kind


def _owner_user_ids(activities) -> dict[str, str]:
    """activity id -> the login that can move it: the responsible staff
    member, or the partner organisation for partner-delivered work."""
    from apps.accounts.models import StaffProfile
    from apps.partners.models import Partner

    staff_ids = {a.responsible_staff_id for a in activities if a.responsible_staff_id}
    partner_ids = {
        a.assigned_partner_id
        for a in activities
        if not a.responsible_staff_id and a.assigned_partner_id
    }
    user_of_profile = dict(
        StaffProfile.objects.filter(id__in=staff_ids).values_list("id", "user_id")
    )
    user_of_partner = dict(
        Partner.objects.filter(id__in=partner_ids).values_list("id", "user_id")
    )
    owners = {}
    for activity in activities:
        if activity.responsible_staff_id:
            # A legacy row carries the User id itself.
            owner = user_of_profile.get(
                activity.responsible_staff_id, activity.responsible_staff_id
            )
        else:
            owner = user_of_partner.get(activity.assigned_partner_id)
        if owner:
            owners[activity.id] = owner
    return owners


def send_day_off_alerts(
    today: date | None = None, *, user_id: str | None = None, horizon_days: int = 120
) -> int:
    """Tell each person which of their coming activities sit on a day off.

    One notice per person per day off, keyed to that day. A re-run says
    nothing twice, a day whose list changes is said again with the new list,
    and the notice is closed once the person has nothing left on that day.
    ``user_id`` keeps the sweep to one person's work and notices. Returns the
    number of notices sent.
    """
    from apps.accounts.models import StaffProfile
    from apps.activities.models import Activity
    from apps.notifications.models import Notification
    from apps.notifications.services import WorkflowNotificationService
    from apps.partners.models import Partner

    today = today or timezone.localdate()
    until = today + timedelta(days=horizon_days)
    coming = (
        Activity.objects.filter(deleted_at__isnull=True, status__in=AWAITING_DELIVERY)
        .filter(
            Q(planned_date__lte=until)
            | Q(planned_date__isnull=True, scheduled_date__date__lte=until)
        )
        .filter(
            Q(end_date__gte=today)
            | Q(planned_date__gte=today)
            | Q(planned_date__isnull=True, scheduled_date__date__gte=today)
        )
    )
    notices = Notification.objects.filter(
        source_event_type=DAY_OFF_EVENT, resolved_at__isnull=True
    ).exclude(status="archived")
    if user_id:
        staff_ids = [
            user_id,
            *StaffProfile.objects.filter(user_id=user_id).values_list("id", flat=True),
        ]
        partner_ids = list(
            Partner.objects.filter(user_id=user_id).values_list("id", flat=True)
        )
        coming = coming.filter(
            Q(responsible_staff_id__in=staff_ids)
            | Q(assigned_partner_id__in=partner_ids)
        )
        notices = notices.filter(recipient_id=user_id)
    coming = list(
        coming.select_related("school", "cluster").order_by(
            "planned_date", "created_at"
        )
    )
    marks = day_off_marks(coming)
    marked = [activity for activity in coming if activity.id in marks]
    owners = _owner_user_ids(marked)

    # (person, day off) -> the activities to move and the reason for the day.
    todo: dict[tuple[str, date], dict] = {}
    for activity in marked:
        owner = owners.get(activity.id)
        if not owner or (user_id and owner != user_id):
            continue
        for day_off in marks[activity.id].days:
            if day_off.day < today:
                continue
            entry = todo.setdefault((owner, day_off.day), {"work": [], "why": []})
            if activity not in entry["work"]:
                entry["work"].append(activity)
            reason = (
                f"a public holiday ({day_off.name})"
                if day_off.kind == HOLIDAY
                else "a day you are on leave"
            )
            if reason not in entry["why"]:
                entry["why"].append(reason)

    live = {(notice.recipient_id, notice.context_id): notice for notice in notices}
    sent = 0
    for (owner, day), entry in todo.items():
        key = f"dayoff-{day.isoformat()}"
        work = entry["work"]
        count = len(work)
        named = "; ".join(_activity_label(a) for a in work[:_NAMED])
        more = count - _NAMED
        body = f"{day:%A %-d %B} is {' and '.join(entry['why'])}. Move: {named}" + (
            f"; and {more} more." if more > 0 else "."
        )
        notice = live.pop((owner, key), None)
        if notice is not None and notice.body == body:
            continue
        if (
            notice is None
            and Notification.objects.filter(
                recipient_id=owner,
                source_event_type=DAY_OFF_EVENT,
                context_id=key,
                body=body,
            ).exists()
        ):
            # Told exactly this already, and they put the notice away.
            continue
        # A live notice for the day is updated in place and shown as new.
        WorkflowNotificationService.trigger(
            event_type=DAY_OFF_EVENT,
            category="activity",
            # Normal, not high: high sets action_required, and the escalation
            # sweep would turn every holiday into an urgent notice.
            priority="normal",
            title=(
                f"Reschedule {count} activit{'y' if count == 1 else 'ies'} "
                f"planned for {day:%a %-d %b}"
            ),
            body=body,
            context_type="day_off",
            context_id=key,
            recipients=[owner],
        )
        sent += 1

    # Whatever is left has nothing on its day any more.
    stale = [notice.id for notice in live.values()]
    if stale:
        now = timezone.now()
        Notification.objects.filter(id__in=stale).update(
            resolved_at=now, status="archived", action_required=False, updated_at=now
        )
    return sent


def settle_day_off_alerts(activity) -> None:
    """After an activity moves or is cancelled, bring its owner's notices up
    to date. One look-up when the owner has no open notice; never raises —
    a notice must not stand in the way of the change that prompted it."""
    from apps.notifications.models import Notification

    try:
        owner = _owner_user_ids([activity]).get(activity.id)
        if not owner:
            return
        if not Notification.objects.filter(
            recipient_id=owner,
            source_event_type=DAY_OFF_EVENT,
            resolved_at__isnull=True,
        ).exists():
            return
        send_day_off_alerts(user_id=owner)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("day-off notices not settled")
