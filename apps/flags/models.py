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


class EscalationStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    RESOLVED = "resolved", "Resolved"


class EscalationSeverity(models.TextChoices):
    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    NORMAL = "normal", "Normal"


class LeadershipEscalation(TimeStampedModel):
    """A CD→RVP escalation — the missing upward path.

    The CD cockpit rendered an "Escalate to RVP" action with nothing behind it,
    and the RVP had no inbound surface of any kind: flags only ever travel
    CD→PL by construction, and strategy notes only travel RVP→CD. A country
    director facing something above their authority (a structural funding gap,
    a partner failing across regions, a decision needing regional trade-off)
    had no way to put it in front of the person who can decide it.

    Deliberately distinct from CdFlag: that is a quality-assurance handoff to
    an operator, this is a decision request to an approver, and it carries the
    RVP's decision back as a first-class field.
    """

    id = CuidField()
    raised_by_user_id = models.CharField(max_length=30)  # the CD
    raised_by_name = models.CharField(max_length=255, null=True, blank=True)
    # Null means "any RVP" — escalations are addressed to the role, since a
    # country has exactly one RVP above it and hard-wiring an id would strand
    # the item whenever the post changes hands.
    assigned_to_user_id = models.CharField(max_length=30, null=True, blank=True)
    country_id = models.CharField(max_length=64, default="Uganda")

    category = models.CharField(max_length=64)
    subject = models.CharField(max_length=255)
    detail = models.TextField()
    requested_decision = models.CharField(max_length=512, null=True, blank=True)
    severity = models.CharField(
        max_length=16,
        choices=EscalationSeverity.choices,
        default=EscalationSeverity.NORMAL,
    )
    # What the escalation is about, so the RVP can open the underlying record.
    scope_type = models.CharField(max_length=32, null=True, blank=True)
    scope_id = models.CharField(max_length=30, null=True, blank=True)
    scope_name = models.CharField(max_length=255, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=16, choices=EscalationStatus.choices, default=EscalationStatus.OPEN
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    # The RVP's answer — the reason this is not just a message thread.
    decision = models.CharField(max_length=64, null=True, blank=True)
    decision_note = models.TextField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "leadership_escalation"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "severity"]),
            models.Index(fields=["raised_by_user_id"]),
            models.Index(fields=["country_id", "status"]),
        ]

    @property
    def is_open(self) -> bool:
        return self.status != EscalationStatus.RESOLVED

    @property
    def age_days(self) -> int:
        from django.utils import timezone

        return (timezone.now() - self.created_at).days


__all__ = [
    "CdFlagStatus",
    "CdFlag",
    "EscalationStatus",
    "EscalationSeverity",
    "LeadershipEscalation",
]
