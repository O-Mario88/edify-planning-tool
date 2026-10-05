"""Reschedule or cancel several activities in one go.

Owner, 2026-10-05: "add also group reschedule where the users use checkboxes
to mark all the clusters meetings or group training, or schools visits
scheduled using checkboxes and then select reschedule in the action buttons
... Make sure group cancel also is there so that users can be able to cancel
activities in group."

Nothing here is a new rule. Each ticked activity goes through the door a
single one goes through — `services.reschedule` or `services.cancel` — so who
may move it, which dates it may take, what happens to its cost, its weekly
request and its partner's notice are all decided where they already were.
This module adds the three things a group needs and a single activity does
not:

* An answer per activity. One refusal does not undo the rest: each activity is
  its own transaction, and the reader is told which ones were left and why.
* What can be said before anything is changed. `selection` reads the ticked
  activities and marks the ones the action cannot take (already carried out,
  not the reader's to run, already cancelled), so the drawer shows them before
  it is confirmed.
* The other half of an in-school Training. The training and its school visit
  are one mission on one day (owner, 2026-09-28), so ticking either brings the
  other, and the two move or stop together, as `editing.edit` moves them.

A group cancel leaves finished work alone, as the row menu does: work that is
completed, verified or closed is cancelled from its own record, one at a
time, never swept up with a page of ticks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction

from apps.core.clock import local_day
from apps.core.exceptions import BadRequest

logger = logging.getLogger(__name__)

#: The most activities one group action takes. A page of a table is 50 rows
#: and a month of a calendar is seldom more than this; each activity re-prices
#: and re-files its own request, so the limit is what keeps one click from
#: becoming a request that runs for minutes.
MAX_SELECTION = 100

RESCHEDULE = "reschedule"
CANCEL = "cancel"

#: Work a group cancel does not touch: it is finished, or already called off.
_FINISHED_STATUSES = frozenset(
    {"completed", "ia_verified", "accountant_confirmed", "closed"}
)
_CALLED_OFF_STATUSES = frozenset({"cancelled", "rejected"})

_UNEXPECTED = "Could not be changed. The error has been logged."


def may_tick(status: str | None) -> bool:
    """Whether a row with this status carries a tick box: work that is still
    live. Which of the two actions takes it is said in the drawer."""
    return (status or "") not in _FINISHED_STATUSES | _CALLED_OFF_STATUSES


@dataclass
class Pick:
    """One ticked activity, and whether the action can take it."""

    activity: object
    title: str
    where: str
    day: date | None
    end_day: date | None = None
    #: Why this one is left as it is; empty when the action can go ahead.
    refusal: str = ""
    #: Brought in by its pair rather than ticked.
    joined: bool = False
    #: The ids that move or stop together with this one, in the order they
    #: are changed: itself, or an in-school Training and then its visit.
    unit: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.activity.id


@dataclass
class Outcome:
    """What a group action did."""

    done: list[Pick] = field(default_factory=list)
    refused: list[Pick] = field(default_factory=list)


def tickable_ids(activities, principal) -> set[str]:
    """Which of these activities carry a tick box for this reader on a
    calendar: live work they hold themselves and may run.

    A calendar draws a month of a whole team's work, so the three checks the
    services make (`profile_activities._may_run`) are asked only of the
    activities the reader holds directly: their own, a partner's they
    monitor, or their organisation's. Everything else is somebody else's to
    move and has no box, without a query to find that out.
    """
    from apps.activities.profile_activities import _may_run
    from apps.core.permissions import RolePermissionService
    from apps.core.scoping import owner_ids, resolve_partner_ids

    if not RolePermissionService.can_view_page(principal, "my_plan"):
        return set()
    mine = set(owner_ids(principal))
    partners = set(resolve_partner_ids(principal) or [])
    return {
        a.id
        for a in activities
        if may_tick(a.status)
        and (
            a.responsible_staff_id in mine
            or a.monitored_by_staff_id in mine
            or (a.assigned_partner_id and a.assigned_partner_id in partners)
        )
        and _may_run(a, principal)
    }


def clean_ids(raw_ids) -> list[str]:
    """The ticked ids, once each, in the order they were ticked."""
    seen: dict[str, None] = {}
    for raw in raw_ids or []:
        value = str(raw or "").strip()
        if value:
            seen.setdefault(value, None)
    ids = list(seen)
    if not ids:
        raise BadRequest("Tick at least one activity first.")
    if len(ids) > MAX_SELECTION:
        raise BadRequest(
            f"Tick at most {MAX_SELECTION} activities at a time. "
            f"{len(ids)} are ticked."
        )
    return ids


def selection(raw_ids, principal, *, action: str) -> list[Pick]:
    """The ticked activities the reader can see, marked for `action`.

    An id the reader cannot see is dropped without a word: it did not come
    from a tick box on a page they were shown.
    """
    from apps.activities.models import Activity
    from apps.core.permissions import RolePermissionService

    ids = clean_ids(raw_ids)
    found = {
        a.id: a
        for a in Activity.objects.filter(
            id__in=ids, deleted_at__isnull=True
        ).select_related("school", "cluster", "event_district")
    }
    ticked = [
        found[i]
        for i in ids
        if i in found and RolePermissionService.can_view_record(principal, found[i])
    ]
    picks: list[Pick] = []
    for unit in _units(ticked):
        together = tuple(member.id for member in unit)
        for member in unit:
            pick = _pick(member, joined=member.id not in ids)
            pick.unit = together
            pick.refusal = _refusal(member, principal, action=action)
            picks.append(pick)
    by_id = {p.id: p for p in picks}
    for pick in picks:
        # Said before anything is confirmed: a pair one half of which cannot
        # be changed is left whole.
        blocked = next((by_id[i] for i in pick.unit if by_id[i].refusal), None)
        if blocked is not None and not pick.refusal:
            pick.refusal = _with_pair(blocked)
    picks.sort(key=lambda p: (p.day or date.max, p.where.casefold(), p.title))
    return picks


def reschedule(raw_ids, raw_day, reason, principal) -> Outcome:
    """Move every ticked activity that can move to `raw_day`."""
    from apps.activities import services

    reason = str(reason or "").strip()
    try:
        day = date.fromisoformat(str(raw_day or "").strip())
    except ValueError:
        raise BadRequest("Choose the date these activities move to.") from None
    if not reason:
        raise BadRequest("Give the reason these activities are moving.")
    payload = {
        "scheduledDate": day.isoformat(),
        "reason": reason,
        "plannedMonth": day.month,
        "plannedWeek": min(5, (day.day - 1) // 7 + 1),
    }

    def move(activity):
        services.reschedule(activity.id, payload, principal)

    picks = selection(raw_ids, principal, action=RESCHEDULE)
    by_id = {p.id: p for p in picks}
    for pick in picks:
        # Nothing to move, and no reschedule to count against the activity.
        # One half of a pair already on the day stays put while the other
        # half joins it.
        if not pick.refusal and all(by_id[i].day == day for i in pick.unit):
            pick.refusal = "Already on this date."
    return _apply(picks, act=move, skip=lambda pick: pick.day == day)


def cancel(raw_ids, reason, principal) -> Outcome:
    """Cancel every ticked activity that is still live."""
    from apps.activities import services

    reason = str(reason or "").strip()
    if not reason:
        raise BadRequest("Give the reason these activities are being cancelled.")

    def call_off(activity):
        services.cancel(activity.id, {"reason": reason}, principal)

    return _apply(selection(raw_ids, principal, action=CANCEL), act=call_off)


def money_moved_ids(picks) -> set[str]:
    """The picks whose advance has already been disbursed: cancelling them
    does not make that money go away (`cancel_activity_drawer_view`)."""
    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES, AdvanceRequest

    ids = [p.id for p in picks if not p.refusal]
    if not ids:
        return set()
    return set(
        AdvanceRequest.objects.filter(
            activity_id__in=ids, status__in=MONEY_MOVED_ADVANCE_STATUSES
        ).values_list("activity_id", flat=True)
    )


# ── Internals ────────────────────────────────────────────────────────────────


def _apply(picks, *, act, skip=None) -> Outcome:
    by_id = {p.id: p for p in picks}
    outcome = Outcome()
    handled: set[str] = set()
    for pick in picks:
        if pick.id in handled:
            continue
        unit = [by_id[i] for i in pick.unit]
        handled.update(pick.unit)
        blocked = next((member for member in unit if member.refusal), None)
        if blocked is None:
            blocked = _change(unit, act=act, skip=skip)
        if blocked is None:
            outcome.done.extend(unit)
            continue
        for member in unit:
            member.refusal = member.refusal or _with_pair(blocked)
            outcome.refused.append(member)
    return outcome


def _change(unit, *, act, skip) -> Pick | None:
    """Apply `act` to a unit; the member that refused it, or None."""
    member = unit[0]
    try:
        # One transaction for the unit: a pair moves or stays as one, and a
        # refusal part-way leaves nothing half-written.
        with transaction.atomic():
            for member in unit:
                if skip is None or not skip(member):
                    act(member.activity)
    except Exception as exc:  # noqa: BLE001 — reported per activity
        member.refusal = _message(exc, member)
        return member
    return None


def _message(exc: Exception, pick) -> str:
    from apps.core.htmx_errors import error_message, is_user_facing

    if not is_user_facing(exc):
        logger.error(
            "Group action failed for activity %s",
            getattr(pick, "id", "?"),
            exc_info=exc,
        )
        return _UNEXPECTED
    return error_message(exc)


def _with_pair(blocked: Pick) -> str:
    return (
        f"Left as it is: {blocked.title.lower()} on the same day could not be "
        "changed, and the two go together."
    )


def _refusal(activity, principal, *, action: str) -> str:
    """Why `action` will not take this activity, in the service's own words."""
    from apps.activities import services
    from apps.activities.editing import is_executed
    from apps.core.exceptions import EdifyAPIException

    status = activity.status or ""
    if action == CANCEL:
        if status in _CALLED_OFF_STATUSES:
            return "Already cancelled."
        if status in _FINISHED_STATUSES:
            return "Already completed. Cancel it from its own record."
    elif is_executed(activity):
        return "Already carried out, so it keeps its date."
    elif activity.delivery_type == "partner" and not _is_its_partner(
        activity, principal
    ):
        # The row menu offers staff no Reschedule on a partner's delivery:
        # the partner dates its own work.
        return "A partner's work keeps the date the partner set."
    try:
        services._assert_in_scope(activity, principal)
        services._assert_may_schedule(activity, principal)
        services._assert_may_execute(activity, principal)
        if action == RESCHEDULE:
            services._assert_not_awaiting_owner(activity)
    except EdifyAPIException as exc:
        return str(getattr(exc, "detail", "") or exc)
    return ""


def _is_its_partner(activity, principal) -> bool:
    from apps.core.scoping import resolve_partner_ids

    return bool(activity.assigned_partner_id) and activity.assigned_partner_id in (
        resolve_partner_ids(principal) or []
    )


def _pick(activity, *, joined: bool) -> Pick:
    if activity.school_id:
        where = activity.school.name
    elif activity.cluster_id:
        where = activity.cluster.name
    else:
        where = activity.venue or (
            activity.event_district.name if activity.event_district_id else ""
        )
    day = _day(activity)
    end = activity.end_date if activity.end_date and activity.end_date != day else None
    return Pick(
        activity=activity,
        title=activity.activity_name_snapshot or activity.get_activity_type_display(),
        where=where or "Programme work",
        day=day,
        end_day=end,
        joined=joined,
    )


def _day(activity) -> date | None:
    if activity.planned_date:
        return activity.planned_date
    return local_day(activity.scheduled_date) if activity.scheduled_date else None


def _units(activities) -> list[list]:
    """Each activity with the other half of its in-school Training pair, the
    training first — the order `editing._moves_together` moves them in."""
    from apps.activities.models import Activity

    by_id = {a.id: a for a in activities}
    visit_of = {
        a.id: a.paired_school_visit_id
        for a in activities
        if a.activity_type == "in_school_training" and a.paired_school_visit_id
    }
    visit_ids = [a.id for a in activities if a.activity_type == "school_visit"]
    training_of: dict[str, str] = {}
    if visit_ids:
        training_of = dict(
            Activity.objects.filter(
                paired_school_visit_id__in=visit_ids,
                activity_type="in_school_training",
                deleted_at__isnull=True,
            ).values_list("paired_school_visit_id", "id")
        )
    missing = [
        i
        for i in list(visit_of.values()) + list(training_of.values())
        if i not in by_id
    ]
    if missing:
        for other in Activity.objects.filter(
            id__in=missing, deleted_at__isnull=True
        ).select_related("school", "cluster", "event_district"):
            by_id[other.id] = other
    units: list[list] = []
    placed: set[str] = set()
    for a in activities:
        if a.id in placed:
            continue
        training_id = a.id if a.id in visit_of else training_of.get(a.id)
        visit_id = visit_of.get(a.id) or (a.id if a.id in training_of else None)
        training, visit = by_id.get(training_id), by_id.get(visit_id)
        unit = [training, visit] if training and visit else [a]
        units.append(unit)
        placed.update(member.id for member in unit)
    return units
