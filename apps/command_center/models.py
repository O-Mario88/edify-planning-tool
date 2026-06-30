"""Command-center models — recommendation-led home feed + persistent alerts."""
from __future__ import annotations

from django.db import models

from apps.core.enums import NotificationPriority
from apps.core.models import CuidField, TimeStampedModel


class CommandCenterAlert(TimeStampedModel):
    """A persistent operational alert (generated from live data conditions)."""

    id = CuidField()
    alert_type = models.CharField(max_length=64)
    severity = models.CharField(max_length=16, choices=NotificationPriority.choices, default=NotificationPriority.HIGH)
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
    alert = models.ForeignKey(CommandCenterAlert, on_delete=models.CASCADE, related_name="dismissals")
    user_id = models.CharField(max_length=30)
    dismissed_until = models.DateTimeField()

    class Meta:
        db_table = "command_center_alert_dismissal"
        constraints = [
            models.UniqueConstraint(fields=["alert", "user_id"], name="uniq_alert_dismissal_user"),
        ]
        indexes = [models.Index(fields=["user_id"])]


__all__ = ["CommandCenterAlert", "CommandCenterAlertDismissal"]
