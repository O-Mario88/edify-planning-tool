"""An in-school Training and its School Visit change together.

Owner, 2026-09-28: an in-school training and the visit it rides on are one
mission on one day — the visit carries the cost and the training carries none.
They are two records, and each door that changes one record changed one of
them: Reschedule moved the training and left its visit on the old day, Cancel
called off the visit and left a training with no visit to ride on. The Edit
drawer (`editing._moves_together`) and the group actions
(`group_actions._units`) already kept them together; the two single doors, on
the page and in the API, did not.

`reschedule` and `cancel` here are those two doors. Nothing in them is a new
rule: each record still goes through `services.reschedule` or
`services.cancel`, which decide who may change it, which dates it may take and
what happens to its money. What is added is the other half and one
transaction around the two, so a pair moves or stops as one and a refusal
part-way leaves neither half changed.

The other half joins only while it is still live. A half that was already
called off, or already carried out, is left as it is: moving a cancelled
visit would bring it back, and finished work is never changed as a side
effect of changing something else.

The callers that work through a list of their own (a school closing, a
partner withdrawn, a group of ticks) keep calling the services directly.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction

from apps.core.exceptions import BadRequest, EdifyAPIException

RESCHEDULE = "reschedule"
CANCEL = "cancel"

#: What the other half is given when it follows a reschedule: the day and the
#: reason, never the inputs that belong to the record that was asked for.
_SCHEDULE_KEYS = (
    "scheduledDate",
    "reason",
    "plannedMonth",
    "plannedWeek",
    "plannedDate",
)


def other_half(activity):
    """The other record of an in-school Training pair, or None."""
    from apps.activities.models import Activity

    records = Activity.objects.filter(deleted_at__isnull=True).select_related("school")
    if (
        activity.activity_type == "in_school_training"
        and activity.paired_school_visit_id
    ):
        return records.filter(
            id=activity.paired_school_visit_id, activity_type="school_visit"
        ).first()
    if activity.activity_type == "school_visit":
        return records.filter(
            paired_school_visit_id=activity.id, activity_type="in_school_training"
        ).first()
    return None


def joins(activity, *, action: str):
    """The other half, when `action` on this activity takes it too."""
    from apps.activities.editing import is_executed
    from apps.activities.group_actions import may_tick

    other = other_half(activity)
    if other is None or not may_tick(other.status):
        return None
    if action == RESCHEDULE and is_executed(other):
        return None
    return other


def label(activity) -> str:
    """How the drawers and refusals name a half: by what it is ("School
    Visit"), not by the course it teaches."""
    return activity.get_activity_type_display()


def reschedule(activity_id: str, data: dict, principal) -> dict:
    """The single Reschedule door: the activity, and its pair with it."""
    from apps.activities import services

    asked, other = _asked_and_other(activity_id, action=RESCHEDULE)
    if other is None:
        return services.reschedule(activity_id, data, principal)
    day = _target_day(data)
    follows = {key: data[key] for key in _SCHEDULE_KEYS if key in data}
    result: dict = {}
    with transaction.atomic():
        for member in _in_order(asked, other):
            if member.id == asked.id:
                result = services.reschedule(member.id, data, principal)
            elif day is not None and member.planned_date == day:
                # Already there: no move, and no reschedule counted against it.
                continue
            else:
                _with_its_pair(
                    member,
                    "moved",
                    lambda member=member: services.reschedule(
                        member.id, follows, principal
                    ),
                )
    return result


def cancel(activity_id: str, data: dict, principal) -> dict:
    """The single Cancel door: the activity, and its pair with it."""
    from apps.activities import services

    asked, other = _asked_and_other(activity_id, action=CANCEL)
    if other is None:
        return services.cancel(activity_id, data, principal)
    reason = {"reason": data.get("reason")}
    result: dict = {}
    with transaction.atomic():
        for member in _in_order(asked, other):
            if member.id == asked.id:
                result = services.cancel(member.id, data, principal)
            else:
                _with_its_pair(
                    member,
                    "cancelled",
                    lambda member=member: services.cancel(member.id, reason, principal),
                )
    return result


# ── Internals ────────────────────────────────────────────────────────────────


def _asked_and_other(activity_id: str, *, action: str):
    """The record asked for and the half that joins it. A record that is not
    there is left to the service, which refuses it in its own words."""
    from apps.activities.models import Activity

    asked = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if asked is None:
        return None, None
    return asked, joins(asked, action=action)


def _in_order(asked, other) -> list:
    """The record that was asked for, then the half that follows it: a rule
    that refuses both (a day that has passed, a blocked date) is then said
    once, of the record on the screen, in the service's own words."""
    return [asked, other]


def _target_day(data: dict) -> date | None:
    try:
        return date.fromisoformat(str(data.get("scheduledDate") or "")[:10])
    except ValueError:
        return None


def _with_its_pair(member, verb: str, change) -> None:
    """Change the half that was not asked for; if it refuses, say which half
    and why, and let the transaction leave both as they were."""
    try:
        change()
    except EdifyAPIException as exc:
        why = str(getattr(exc, "detail", "") or exc).strip()
        raise BadRequest(
            f"The {label(member).lower()} on the same day could not be {verb}, "
            f"and the two go together, so neither was changed. {why}".strip()
        ) from exc
