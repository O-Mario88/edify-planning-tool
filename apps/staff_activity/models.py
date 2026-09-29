"""Manager follow-ups raised from the Staff Activity Log.

Owner, 2026-09-29: a Programme Lead follows up with an officer, and a Country
Director follows up about an officer through that officer's Programme Lead —
never around them. A follow-up is support, not a sanction: nothing here lowers
a score, marks anyone absent or opens a PIP.

The time and action figures themselves are not stored here: they are read
from the presence record (apps.accounts PresenceTime, LoginEvent) and the audit
chain (apps.audit) whenever the log is drawn. A follow-up keeps a snapshot of
what the manager saw when they raised it, so a later reader knows why.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class FollowUpTrigger(models.TextChoices):
    NO_LOGIN = "no_login", "No login"
    LOW_ENGAGEMENT = "low_engagement", "Low platform engagement"
    PLANNING_NOT_DONE = "planning_not_done", "Required planning not completed"
    EVIDENCE_NOT_DONE = "evidence_not_done", "Evidence work not completed"
    REPEATED_ERRORS = "repeated_errors", "Repeated system errors"
    WORKFLOW_SUPPORT = "workflow_support", "Workflow support required"
    EXCESSIVE_TIME = "excessive_time", "Excessive time / possible usability problem"
    TRAINING = "training", "Training required"
    OTHER = "other", "Other"


class FollowUpStatus(models.TextChoices):
    SENT = "sent", "Sent"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    SUPPORT_SCHEDULED = "support_scheduled", "Support scheduled"
    WAITING_FOR_STAFF = "waiting_for_staff", "Waiting for staff"
    RESOLVED_BY_ACTIVITY = "resolved_by_activity", "Resolved by activity"
    RESOLVED_BY_MANAGER = "resolved_by_manager", "Resolved by manager"
    RETURNED = "returned", "Returned for clarification"
    ESCALATED = "escalated", "Escalated"
    CLOSED = "closed", "Closed"
    CANCELED = "canceled", "Canceled"


OPEN_STATUSES = (
    FollowUpStatus.SENT,
    FollowUpStatus.ACKNOWLEDGED,
    FollowUpStatus.SUPPORT_SCHEDULED,
    FollowUpStatus.WAITING_FOR_STAFF,
    FollowUpStatus.RETURNED,
    FollowUpStatus.ESCALATED,
)


class FollowUpPriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"


class FollowUpRoute(models.TextChoices):
    # A Programme Lead (or any supervisor) with a person they supervise.
    MANAGER_TO_STAFF = "manager_to_staff", "Manager to staff member"
    # A Country Director about an officer, sent to the officer's Programme
    # Lead, who then follows up with the officer.
    DIRECTOR_TO_MANAGER = "director_to_manager", "Country Director to manager"


class StaffUsageFollowUp(TimeStampedModel):
    id = CuidField()
    # The person whose platform use prompted the follow-up.
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="usage_follow_ups_about",
    )
    # Who must act on it: the staff member, or — on the Country Director's
    # route — their manager.
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="usage_follow_ups_assigned",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="usage_follow_ups_created",
    )
    route = models.CharField(
        max_length=24,
        choices=FollowUpRoute.choices,
        default=FollowUpRoute.MANAGER_TO_STAFF,
    )
    period_key = models.CharField(max_length=16, default="day")
    period_start = models.DateField()
    period_end = models.DateField()
    trigger = models.CharField(max_length=32, choices=FollowUpTrigger.choices)
    # What the manager saw when they raised it: logins, active minutes,
    # meaningful actions, schools acted on, failed actions.
    snapshot = models.JSONField(default=dict, blank=True)
    note = models.TextField()
    priority = models.CharField(
        max_length=8, choices=FollowUpPriority.choices, default=FollowUpPriority.NORMAL
    )
    due_date = models.DateField()
    status = models.CharField(
        max_length=24,
        choices=FollowUpStatus.choices,
        default=FollowUpStatus.SENT,
        db_index=True,
    )
    resolution = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_follow_ups_resolved",
    )
    # Every state change: [{"at", "by", "by_name", "status", "note"}]. The
    # same transitions are written to the audit chain.
    history = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "staff_usage_follow_up"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["assignee", "status"], name="usage_fu_assignee_status"
            ),
            models.Index(fields=["subject", "status"], name="usage_fu_subject_status"),
            models.Index(
                fields=["created_by", "status"], name="usage_fu_creator_status"
            ),
        ]

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def history_rows(self) -> list[dict]:
        """The history for display: local times and status labels."""
        from datetime import datetime

        from django.utils import timezone

        labels = dict(FollowUpStatus.choices)
        rows = []
        for entry in self.history or []:
            try:
                at = timezone.localtime(datetime.fromisoformat(entry.get("at") or ""))
            except (TypeError, ValueError):
                at = None
            rows.append(
                {
                    **entry,
                    "at": at,
                    "status_label": labels.get(
                        entry.get("status"), entry.get("status", "")
                    ),
                }
            )
        return rows

    def __str__(self) -> str:  # pragma: no cover - admin display
        return f"{self.get_trigger_display()} · {self.subject_id} ({self.status})"
