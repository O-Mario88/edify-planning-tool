"""Fund-request models — the Budget → Fund Request approval chain."""
from __future__ import annotations

from django.db import models

from apps.core.enums import VerificationStatus
from apps.core.models import CuidField, TimeStampedModel


class FundRequestPeriod(models.TextChoices):
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    ANNUAL = "annual", "Annual"


class FundRequestStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    RETURNED = "returned", "Returned"
    REJECTED = "rejected", "Rejected"
    DISBURSED = "disbursed", "Disbursed"
    DRAFT = "draft", "Draft"
    SUBMITTED_TO_PL = "submitted_to_pl", "Submitted to PL"
    APPROVED_BY_PL = "approved_by_pl", "Approved by PL"
    SUBMITTED_TO_CD = "submitted_to_cd", "Submitted to CD"
    APPROVED_BY_CD = "approved_by_cd", "Approved by CD"
    SUBMITTED_TO_RVP = "submitted_to_rvp", "Submitted to RVP"
    APPROVED_BY_RVP = "approved_by_rvp", "Approved by RVP"
    SENT_TO_ACCOUNTANT = "sent_to_accountant", "Sent to Accountant"
    CLOSED = "closed", "Closed"
    RETURNED_BY_PL = "returned_by_pl", "Returned by PL"
    RETURNED_BY_CD = "returned_by_cd", "Returned by CD"
    RETURNED_BY_RVP = "returned_by_rvp", "Returned by RVP"
    RETURNED_BY_ACCOUNTANT = "returned_by_accountant", "Returned by Accountant"


class FundRequest(TimeStampedModel):
    """A submitted snapshot of a period's scheduled+costed work, routed for
    approval (PL → CD → RVP → Accountant)."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    period = models.CharField(max_length=16, choices=FundRequestPeriod.choices)
    period_key = models.CharField(max_length=32)  # "2026" | "2026-Q3" | "2026-M2"
    scope = models.CharField(max_length=16)  # own | team | country
    submitted_by_user_id = models.CharField(max_length=30)
    submitted_by_role = models.CharField(max_length=64)
    total_amount = models.FloatField()
    activity_count = models.IntegerField()
    status = models.CharField(max_length=32, choices=FundRequestStatus.choices, default=FundRequestStatus.SUBMITTED)
    reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=512, null=True, blank=True)
    disbursed_amount = models.FloatField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    disburse_method = models.CharField(max_length=64, null=True, blank=True)
    disburse_reference = models.CharField(max_length=128, null=True, blank=True)
    accounted_amount = models.FloatField(null=True, blank=True)
    returned_amount = models.FloatField(null=True, blank=True)
    accountability_status = models.CharField(max_length=32, null=True, blank=True)
    accountability_netsuite_id = models.CharField(max_length=128, null=True, blank=True)
    accountability_submitted_at = models.DateTimeField(null=True, blank=True)
    accountability_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fund_request"
        constraints = [
            models.UniqueConstraint(
                fields=["submitted_by_user_id", "period", "period_key"],
                name="uniq_request_period_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["fy", "period"]),
            models.Index(fields=["submitted_by_user_id"]),
        ]


class FundRequestItem(TimeStampedModel):
    """Links a cost line to a fund request."""

    id = CuidField()
    fund_request = models.ForeignKey(FundRequest, on_delete=models.CASCADE, related_name="items")
    activity_id = models.CharField(max_length=30)
    activity_schedule_cost_line_id = models.CharField(max_length=30)
    amount = models.FloatField()
    period = models.CharField(max_length=16, choices=FundRequestPeriod.choices)
    period_key = models.CharField(max_length=32)
    added_after_generation = models.BooleanField(default=False)

    class Meta:
        db_table = "fund_request_item"
        constraints = [
            models.UniqueConstraint(fields=["fund_request", "activity_schedule_cost_line_id"], name="uniq_request_costline"),
            models.UniqueConstraint(fields=["activity_schedule_cost_line_id", "period", "period_key"], name="uniq_costline_period"),
        ]
        indexes = [models.Index(fields=["activity_id"])]


__all__ = ["FundRequestPeriod", "FundRequestStatus", "FundRequest", "FundRequestItem"]
