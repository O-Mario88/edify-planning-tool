"""The schedule trail — every time a plan moved, and from where to where.

An activity keeps one scheduled date: rescheduling overwrites it and bumps
``reschedule_count``. That is right for the work, and it leaves oversight
blind to what a period's plan WAS — a month that started with 400 visits and
quietly moved 60 into the next looks, a month later, like a month that planned
340 and delivered them. Country Execution & Completion Oversight keeps the
original plan visible (owner spec, 2026-09-28, §7), so the moves are recorded
here as they happen (apps.activities.schedule_trail).

Append-only; a row never changes. Written for every ORM save that moves a
plan's day or cancels or restores it. A bulk ``QuerySet.update()`` bypasses
it, as it bypasses every signal — the trail says when it began, and the page
reads a period's original plan only for periods that began after that.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.core.models import CuidField
from apps.activities.models import Activity


class ScheduleChangeKind(models.TextChoices):
    SCHEDULED = (
        "scheduled",
        "Scheduled",
    )  # first given a day (a Partner dating a handover)
    RESCHEDULED = "rescheduled", "Rescheduled"
    CANCELLED = "cancelled", "Cancelled"
    RESTORED = "restored", "Restored"


class ActivityScheduleChange(models.Model):
    id = CuidField()
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="schedule_changes"
    )
    kind = models.CharField(max_length=16, choices=ScheduleChangeKind.choices)
    from_day = models.DateField(null=True, blank=True)
    to_day = models.DateField(null=True, blank=True)
    from_status = models.CharField(max_length=32, blank=True, default="")
    to_status = models.CharField(max_length=32, blank=True, default="")
    reason = models.CharField(max_length=512, blank=True, default="")
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "activity_schedule_change"
        indexes = [
            models.Index(
                fields=["activity", "changed_at"], name="idx_sched_change_activity"
            ),
            models.Index(fields=["changed_at"], name="idx_sched_change_at"),
            models.Index(fields=["from_day"], name="idx_sched_change_from"),
            models.Index(fields=["to_day"], name="idx_sched_change_to"),
        ]
