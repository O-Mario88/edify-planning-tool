"""Budget Intelligence models — the financial decision engine."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import CuidField, TimeStampedModel
from apps.leadership.models import (
    DecisionConfidenceLevel,
    DecisionRiskLevel,
    DecisionScopeType,
    DecisionStatus,
)


class ImpactYield(models.TextChoices):
    HIGH = "high", "High"
    HEALTHY = "healthy", "Healthy"
    WEAK = "weak", "Weak"
    LOW = "low", "Low"
    INSUFFICIENT = "insufficient", "Insufficient"


class BudgetIntelligenceInsight(TimeStampedModel):
    """A recommendation from the Budget Intelligence / Financial Decision Engine."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    period_type = models.CharField(max_length=16)  # month|quarter|fy|week
    period = models.CharField(max_length=32)
    insight_type = models.CharField(
        max_length=32
    )  # monthly|partner|activity|regional|...
    scope_type = models.CharField(max_length=16, choices=DecisionScopeType.choices)
    scope_id = models.CharField(max_length=30, null=True, blank=True)
    scope_name = models.CharField(max_length=255, null=True, blank=True)
    recommendation = models.TextField()
    reason = models.TextField()
    risk_level = models.CharField(max_length=16, choices=DecisionRiskLevel.choices)
    impact_yield = models.CharField(max_length=16, choices=ImpactYield.choices)
    confidence_level = models.CharField(
        max_length=16, choices=DecisionConfidenceLevel.choices
    )
    confidence_score = models.FloatField()
    amount_affected = models.FloatField(null=True, blank=True)
    evidence_summary = models.JSONField(null=True, blank=True)
    financial_implication = models.CharField(max_length=512, null=True, blank=True)
    suggested_action = models.CharField(max_length=512)
    alternatives = models.JSONField(null=True, blank=True)
    metrics = models.JSONField(null=True, blank=True)
    risk_flags = ArrayField(
        base_field=models.CharField(max_length=64), default=list, blank=True
    )
    status = models.CharField(
        max_length=32, choices=DecisionStatus.choices, default=DecisionStatus.NEW
    )
    reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_by_role = models.CharField(max_length=64, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(null=True, blank=True)
    generated_at = models.DateTimeField()

    class Meta:
        db_table = "budget_intelligence_insight"
        indexes = [
            models.Index(fields=["fy", "insight_type"]),
            models.Index(fields=["scope_type", "scope_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["impact_yield"]),
        ]


class FinanceDecisionNote(TimeStampedModel):
    id = CuidField()
    insight = models.ForeignKey(
        BudgetIntelligenceInsight, on_delete=models.CASCADE, related_name="notes"
    )
    author_user_id = models.CharField(max_length=30)
    author_role = models.CharField(max_length=64)
    note = models.TextField()
    kind = models.CharField(max_length=32, default="note")


__all__ = ["ImpactYield", "BudgetIntelligenceInsight", "FinanceDecisionNote"]
