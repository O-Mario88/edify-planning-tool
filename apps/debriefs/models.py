"""Daily debrief models — staff + partner field debriefs."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class DebriefType(models.TextChoices):
    STAFF = "staff", "Staff"
    PARTNER = "partner", "Partner"
    MERGED = "merged", "Merged"


class DebriefStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    REVIEWED = "reviewed", "Reviewed"
    MERGED = "merged", "Merged"
    RETURNED = "returned", "Returned"
    ARCHIVED = "archived", "Archived"


class DailyDebrief(SoftDeleteModel):
    """A daily field debrief (staff or partner)."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    date = models.DateTimeField()
    submitted_by_user_id = models.CharField(max_length=30)
    submitted_by_role = models.CharField(max_length=64)
    staff_id = models.CharField(max_length=30, null=True, blank=True)
    partner_id = models.CharField(max_length=30, null=True, blank=True)
    debrief_type = models.CharField(
        max_length=16, choices=DebriefType.choices, default=DebriefType.STAFF
    )
    status = models.CharField(
        max_length=16, choices=DebriefStatus.choices, default=DebriefStatus.SUBMITTED
    )
    summary = models.TextField(null=True, blank=True)
    what_happened = models.TextField(null=True, blank=True)
    what_went_well = models.TextField(null=True, blank=True)
    what_did_not_go_well = models.TextField(null=True, blank=True)
    blockers = ArrayField(
        base_field=models.CharField(max_length=255), default=list, blank=True
    )
    blocker_other = models.CharField(max_length=512, null=True, blank=True)
    support_needed = models.TextField(null=True, blank=True)
    recommendations = models.TextField(null=True, blank=True)
    next_action = models.CharField(max_length=512, null=True, blank=True)
    linked_school_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    linked_cluster_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    linked_partner_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    linked_project_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    linked_activity_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    parent_debrief_id = models.CharField(max_length=30, null=True, blank=True)
    merged_into_debrief_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(null=True, blank=True)
    submitted_at = models.DateTimeField()

    class Meta:
        db_table = "daily_debrief"
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["fy", "date"]),
            models.Index(fields=["submitted_by_user_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["partner_id"]),
        ]


class DailyDebriefRecipient(TimeStampedModel):
    """Routing of a debrief to its recipients (PL/CD/IA/HR)."""

    id = CuidField()
    debrief = models.ForeignKey(
        DailyDebrief, on_delete=models.CASCADE, related_name="recipients"
    )
    recipient_user_id = models.CharField(max_length=30)
    recipient_role = models.CharField(max_length=64)
    routing_reason = models.CharField(max_length=255, null=True, blank=True)
    action_required = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "daily_debrief_recipient"
        indexes = [
            models.Index(fields=["recipient_user_id", "read_at"]),
            models.Index(fields=["debrief"]),
        ]


__all__ = ["DebriefType", "DebriefStatus", "DailyDebrief", "DailyDebriefRecipient"]
