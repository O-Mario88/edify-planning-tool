"""Command-center models — recommendation-led home feed + persistent alerts."""

from __future__ import annotations

from django.db import models

from apps.core.enums import NotificationPriority
from apps.core.models import CuidField, TimeStampedModel


class CommandCenterAlert(TimeStampedModel):
    """A persistent operational alert (generated from live data conditions)."""

    id = CuidField()
    alert_type = models.CharField(max_length=64)
    severity = models.CharField(
        max_length=16,
        choices=NotificationPriority.choices,
        default=NotificationPriority.HIGH,
    )
    scope = models.CharField(max_length=64, null=True, blank=True)
    context_type = models.CharField(max_length=64, null=True, blank=True)
    context_id = models.CharField(max_length=30, null=True, blank=True)
    title = models.CharField(max_length=255)
    body = models.TextField(null=True, blank=True)
    target_route = models.CharField(max_length=255, null=True, blank=True)
    condition_hash = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=16, default="open")

    class Meta:
        db_table = "command_center_alert"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["alert_type", "status"]),
        ]


class CommandCenterAlertDismissal(TimeStampedModel):
    """Per-user dismissal of an alert (hidden until a moment, then reappears if
    still unresolved)."""

    id = CuidField()
    alert = models.ForeignKey(
        CommandCenterAlert, on_delete=models.CASCADE, related_name="dismissals"
    )
    user_id = models.CharField(max_length=30)
    dismissed_until = models.DateTimeField()

    class Meta:
        db_table = "command_center_alert_dismissal"
        constraints = [
            models.UniqueConstraint(
                fields=["alert", "user_id"], name="uniq_alert_dismissal_user"
            ),
        ]
        indexes = [models.Index(fields=["user_id"])]


__all__ = ["CommandCenterAlert", "CommandCenterAlertDismissal"]


class TodayActionRecord(TimeStampedModel):
    """A decision someone took from a Today row (owner, 2026-09-14).

    The decision itself lives in its domain record and audit row; this is the
    record that it was cleared from Today, which "cleared today" counts
    (apps.command_center.today_actions).
    """

    id = CuidField()
    user_id = models.CharField(max_length=30, db_index=True)
    todo_id = models.CharField(max_length=128)
    kind = models.CharField(max_length=64)
    operation = models.CharField(max_length=32)
    record_id = models.CharField(max_length=64)
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "command_center_today_action"
        indexes = [models.Index(fields=["user_id", "created_at"])]


class TodoSnooze(TimeStampedModel):
    """A To-Do a person put aside until a day (owner, 2026-09-14).

    Hides the item from their Today until `until`; the work itself is not
    touched, and a still-open item is back on the day it was snoozed to.
    """

    id = CuidField()
    user_id = models.CharField(max_length=30)
    todo_id = models.CharField(max_length=128)
    title = models.CharField(max_length=255, blank=True, default="")
    until = models.DateField()

    class Meta:
        db_table = "command_center_todo_snooze"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "todo_id"], name="todo_snooze_one_per_item"
            )
        ]
        indexes = [models.Index(fields=["user_id", "until"])]
