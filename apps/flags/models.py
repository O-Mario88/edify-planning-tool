"""CD→PL flag handoff model."""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class CdFlagStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    RESOLVED = "resolved", "Resolved"


class CdFlag(TimeStampedModel):
    """A CD-raised, PL-assigned action item (the CD monitors + flags; the PL
    plans). Persisted + notification-backed."""

    id = CuidField()
    raised_by_user_id = models.CharField(max_length=30)  # the CD
    raised_by_name = models.CharField(max_length=255, null=True, blank=True)
    assigned_to_user_id = models.CharField(max_length=30)  # the Program Lead
    category = models.CharField(max_length=64)
    scope_type = models.CharField(max_length=32, null=True, blank=True)
    scope_id = models.CharField(max_length=30, null=True, blank=True)
    scope_name = models.CharField(max_length=255, null=True, blank=True)
    note = models.TextField()
    recommended_action = models.CharField(max_length=512, null=True, blank=True)
    priority = models.CharField(max_length=16, default="normal")
    due_date = models.CharField(max_length=32, null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=CdFlagStatus.choices, default=CdFlagStatus.OPEN
    )
    resolution_note = models.TextField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cd_flag"
        indexes = [
            models.Index(fields=["assigned_to_user_id", "status"]),
            models.Index(fields=["raised_by_user_id"]),
        ]


__all__ = ["CdFlagStatus", "CdFlag"]
