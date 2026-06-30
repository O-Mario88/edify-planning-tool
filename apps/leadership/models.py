"""Leadership Decision Engine models — recommends; leadership decides."""
from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class DecisionType(models.TextChoices):
    RECRUITMENT = "recruitment", "Recruitment"
    STAFF_ADDITION = "staff_addition", "Staff Addition"
    PARTNER = "partner", "Partner"
    STAFF_HR = "staff_hr", "Staff HR"
    REGIONAL_INVESTMENT = "regional_investment", "Regional Investment"


class DecisionScopeType(models.TextChoices):
    COUNTRY = "country", "Country"
    REGION = "region", "Region"
    DISTRICT = "district", "District"
    SUB_COUNTY = "sub_county", "Sub County"
    CLUSTER = "cluster", "Cluster"
    SCHOOL = "school", "School"
    STAFF = "staff", "Staff"
    PARTNER = "partner", "Partner"


class DecisionRiskLevel(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class DecisionConfidenceLevel(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"
    INSUFFICIENT = "insufficient", "Insufficient"


class DecisionStatus(models.TextChoices):
    NEW = "new", "New"
    UNDER_REVIEW = "under_review", "Under Review"
    ACCEPTED = "accepted", "Accepted"
    ACCEPTED_WITH_CONDITIONS = "accepted_with_conditions", "Accepted with Conditions"
    REJECTED = "rejected", "Rejected"
    DEFERRED = "deferred", "Deferred"
    CONVERTED_TO_ACTION_PLAN = "converted_to_action_plan", "Converted to Action Plan"


class LeadershipDecisionInsight(TimeStampedModel):
    """A recommendation from the Leadership Decision Engine."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    quarter = models.CharField(max_length=8, null=True, blank=True)
    decision_type = models.CharField(max_length=32, choices=DecisionType.choices)
    scope_type = models.CharField(max_length=16, choices=DecisionScopeType.choices)
    scope_id = models.CharField(max_length=30, null=True, blank=True)
    scope_name = models.CharField(max_length=255, null=True, blank=True)
    recommendation = models.TextField()
    reason = models.TextField()
    risk_level = models.CharField(max_length=16, choices=DecisionRiskLevel.choices)
    confidence_level = models.CharField(max_length=16, choices=DecisionConfidenceLevel.choices)
    confidence_score = models.FloatField()
    evidence_summary = models.JSONField(null=True, blank=True)
    context_adjustment = models.CharField(max_length=512, null=True, blank=True)
    financial_implication = models.CharField(max_length=512, null=True, blank=True)
    suggested_action = models.CharField(max_length=512)
    alternatives = models.JSONField(null=True, blank=True)
    metrics = models.JSONField(null=True, blank=True)
    risk_flags = ArrayField(base_field=models.CharField(max_length=64), default=list, blank=True)
    status = models.CharField(max_length=32, choices=DecisionStatus.choices, default=DecisionStatus.NEW)
    reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_by_role = models.CharField(max_length=64, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(null=True, blank=True)
    generated_at = models.DateTimeField()

    class Meta:
        db_table = "leadership_decision_insight"
        indexes = [
            models.Index(fields=["fy", "decision_type"]),
            models.Index(fields=["scope_type", "scope_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["risk_level"]),
            models.Index(fields=["confidence_level"]),
        ]


class DecisionNote(TimeStampedModel):
    id = CuidField()
    insight = models.ForeignKey(LeadershipDecisionInsight, on_delete=models.CASCADE, related_name="notes")
    author_user_id = models.CharField(max_length=30)
    author_role = models.CharField(max_length=64)
    note = models.TextField()
    kind = models.CharField(max_length=32, default="note")


__all__ = [
    "DecisionType", "DecisionScopeType", "DecisionRiskLevel",
    "DecisionConfidenceLevel", "DecisionStatus",
    "LeadershipDecisionInsight", "DecisionNote",
]
