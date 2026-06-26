"""
Budget models — the cost spine. Ports of CostSetting (the CD-owned rate card),
CostSettingHistory (append-only version history), MonthlyFundRequest.

The costing ENGINE itself is pure logic (costing.py) — the single source of
truth for activity cost. No staff invents a cost; if a required rate is missing,
the activity is flagged costMissing and must not enter a budget / fund request.
"""
from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class CostSetting(TimeStampedModel):
    """The CD-owned Country Cost Register rate card. key = stable string."""

    id = CuidField()
    key = models.CharField(max_length=128, unique=True)
    label = models.CharField(max_length=255)
    unit_cost = models.FloatField()
    fy = models.CharField(max_length=16, null=True, blank=True)
    version = models.IntegerField(default=1)  # bumped on every rate change
    created_by = models.CharField(max_length=30, null=True, blank=True)  # CD userId

    class Meta:
        db_table = "cost_setting"
        ordering = ["label"]


class CostSettingHistory(TimeStampedModel):
    """Append-only change history for the CD Country Cost Register."""

    id = CuidField()
    key = models.CharField(max_length=128)
    label = models.CharField(max_length=255)
    old_unit_cost = models.FloatField(null=True, blank=True)  # null on first create
    new_unit_cost = models.FloatField()
    version = models.IntegerField()  # the new version after this change
    fy = models.CharField(max_length=16, null=True, blank=True)
    changed_by_user_id = models.CharField(max_length=30)
    reason = models.CharField(max_length=512, null=True, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cost_setting_history"
        indexes = [
            models.Index(fields=["key"]),
            models.Index(fields=["changed_at"]),
        ]


class MonthlyFundRequest(TimeStampedModel):
    """A legacy monthly fund-request summary row (per staff/month)."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    month = models.IntegerField()
    staff_id = models.CharField(max_length=30, null=True, blank=True)
    amount = models.FloatField()
    status = models.CharField(max_length=32, default="submitted")

    class Meta:
        db_table = "monthly_fund_request"


__all__ = ["CostSetting", "CostSettingHistory", "MonthlyFundRequest"]
