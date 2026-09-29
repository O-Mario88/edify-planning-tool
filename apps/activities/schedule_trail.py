"""Record each move of a plan's day, as it is saved (see schedule_models).

``Activity.from_db`` notes the day and status an activity was read with; the
save hook compares what is written with that note and, when the day moved or
the work was cancelled or restored, appends one ActivityScheduleChange. Reading
is free (the note is taken only when the three fields were loaded anyway, so a
narrow ``.only()`` read never pays a query for it), and a save that moves
nothing writes nothing.
"""

from __future__ import annotations

import logging
from datetime import date

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.activities.models import Activity

logger = logging.getLogger(__name__)

#: The fields a plan's place in time is read from.
PLAN_FIELDS = frozenset({"planned_date", "scheduled_date", "status"})
#: Work that is off the plan until it is restored.
OFF_PLAN_STATUSES = frozenset({"cancelled", "deferred"})


def due_day(planned_date, scheduled_date) -> date | None:
    """The day a plan is due: its planned date, else its scheduled instant's
    local day — the same rule every oversight surface counts periods by."""
    if planned_date:
        return planned_date
    if scheduled_date:
        from django.utils import timezone

        if timezone.is_aware(scheduled_date):
            return timezone.localtime(scheduled_date).date()
        return scheduled_date.date()
    return None


def remember(activity) -> None:
    activity._schedule_origin = (
        due_day(activity.planned_date, activity.scheduled_date),
        activity.status or "",
    )


def change_kind(before: tuple, after: tuple) -> str | None:
    """What a save did to a plan's place in time, if anything."""
    before_day, before_status = before
    after_day, after_status = after
    if before_status not in OFF_PLAN_STATUSES and after_status in OFF_PLAN_STATUSES:
        return "cancelled"
    if before_status in OFF_PLAN_STATUSES and after_status not in OFF_PLAN_STATUSES:
        return "restored"
    if before_day != after_day:
        return "scheduled" if before_day is None else "rescheduled"
    return None


@receiver(post_save, sender=Activity, dispatch_uid="activity_schedule_trail")
def _record_schedule_change(
    sender, instance, created, raw=False, update_fields=None, **kwargs
):
    if raw:
        return
    if created:
        remember(instance)
        return
    before = getattr(instance, "_schedule_origin", None)
    if before is None:
        # Built by hand or read without these fields: nothing to compare.
        return
    if update_fields is not None and not (PLAN_FIELDS & set(update_fields)):
        return
    after = (
        due_day(instance.planned_date, instance.scheduled_date),
        instance.status or "",
    )
    kind = change_kind(before, after)
    if kind is None:
        return
    try:
        from apps.activities.schedule_models import ActivityScheduleChange

        ActivityScheduleChange.objects.create(
            activity_id=instance.pk,
            kind=kind,
            from_day=before[0],
            to_day=after[0],
            from_status=before[1],
            to_status=after[1],
            reason=(instance.last_reason or "")[:512] if kind == "rescheduled" else "",
        )
    except Exception:  # noqa: BLE001 - the trail must never block the work
        logger.warning(
            "Could not record the schedule change of activity %s",
            instance.pk,
            exc_info=True,
        )
        return
    instance._schedule_origin = after


def tracking_since():
    """When this deployment began keeping the trail: the moment its migration
    was applied. Periods that started earlier have no recorded original plan."""
    from django.db.migrations.recorder import MigrationRecorder

    try:
        applied = (
            MigrationRecorder.Migration.objects.filter(
                app="activities", name=TRAIL_MIGRATION
            )
            .values_list("applied", flat=True)
            .first()
        )
    except Exception:  # noqa: BLE001 - no recorder table in some test setups
        return None
    return applied


TRAIL_MIGRATION = "0062_activity_schedule_change"
