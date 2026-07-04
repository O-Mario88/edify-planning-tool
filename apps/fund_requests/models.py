"""Fund-request models — the Budget → Fund Request approval chain."""
from __future__ import annotations

from django.db import models

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
    total_amount = models.BigIntegerField()  # UGX, integer cents
    activity_count = models.IntegerField()
    status = models.CharField(max_length=32, choices=FundRequestStatus.choices, default=FundRequestStatus.SUBMITTED)
    reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=512, null=True, blank=True)
    disbursed_amount = models.BigIntegerField(null=True, blank=True)  # UGX
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    disburse_method = models.CharField(max_length=64, null=True, blank=True)
    disburse_reference = models.CharField(max_length=128, null=True, blank=True)
    accounted_amount = models.BigIntegerField(null=True, blank=True)  # UGX
    returned_amount = models.BigIntegerField(null=True, blank=True)  # UGX
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
    amount = models.BigIntegerField()  # UGX, integer cents
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


class AdvanceRequestStatus(models.TextChoices):
    """The weekly-advance lifecycle. A scheduled activity drafts an advance that
    the RESPONSIBLE user must confirm before the Accountant may disburse."""
    DRAFT_FROM_SCHEDULE = "draft_from_schedule", "Draft (from schedule)"
    PENDING_RESPONSIBLE_CONFIRMATION = "pending_responsible_confirmation", "Pending responsible confirmation"
    CONFIRMED_FOR_ADVANCE = "confirmed_for_advance", "Confirmed for advance"
    SELF_FUNDED_PENDING_REIMBURSEMENT = "self_funded_pending_reimbursement", "Self-funded (pending reimbursement)"
    NOT_REQUESTED = "not_requested", "Not requested"
    SUBMITTED_TO_ACCOUNTANT = "submitted_to_accountant", "Submitted to accountant"
    DISBURSED = "disbursed", "Disbursed"
    ACCOUNTABILITY_PENDING = "accountability_pending", "Accountability pending"
    ACCOUNTED = "accounted", "Accounted"
    REIMBURSEMENT_SUBMITTED = "reimbursement_submitted", "Reimbursement submitted"
    REIMBURSED = "reimbursed", "Reimbursed"
    RETURNED = "returned", "Returned"
    CANCELLED = "cancelled", "Cancelled"


# The funding choice the responsible user makes for a scheduled activity.
ADVANCE_TYPES = (
    ("advance", "Request Advance"),
    ("self_funded", "Use Own Funds (claim reimbursement later)"),
    ("not_requested", "Do Not Request Funds Yet"),
)


class AdvanceRequest(TimeStampedModel):
    """A weekly advance request, auto-created from an activity's budget line when
    the activity is scheduled. The responsible user (the scheduler/owner) confirms
    how they want it funded; the Accountant can only disburse after that
    confirmation. Self-funded advances skip disbursement and open a reimbursement
    path after completion + approval."""

    id = CuidField()
    activity = models.ForeignKey(
        "activities.Activity", on_delete=models.CASCADE, related_name="advance_requests"
    )
    budget_line = models.ForeignKey(
        "activities.ActivityScheduleCostLine", on_delete=models.CASCADE, related_name="advance_requests"
    )
    responsible_user_id = models.CharField(max_length=30, null=True, blank=True)  # the scheduler/owner (null for pure-partner activities until confirmed)
    # Period (mirrors the activity for fund-request bucket grouping).
    fy = models.CharField(max_length=16)
    quarter = models.CharField(max_length=8)
    month = models.IntegerField(null=True, blank=True)
    week = models.IntegerField(null=True, blank=True)
    planned_date = models.DateTimeField(null=True, blank=True)
    amount = models.BigIntegerField()  # UGX, integer (the budget-line amount)
    status = models.CharField(
        max_length=40, choices=AdvanceRequestStatus.choices,
        default=AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION,
    )
    advance_type = models.CharField(max_length=16, choices=ADVANCE_TYPES, default="advance")
    # Disbursement (advance path).
    disbursed_amount = models.BigIntegerField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    disburse_method = models.CharField(max_length=64, null=True, blank=True)
    disburse_reference = models.CharField(max_length=128, null=True, blank=True)
    # Accountability (advance path, after disbursement).
    accounted_amount = models.BigIntegerField(null=True, blank=True)
    returned_amount = models.BigIntegerField(null=True, blank=True)
    accountability_netsuite_id = models.CharField(max_length=128, null=True, blank=True)
    accountability_submitted_at = models.DateTimeField(null=True, blank=True)
    accountability_reviewed_at = models.DateTimeField(null=True, blank=True)
    # Confirmation / review audit.
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_note = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "advance_request"
        ordering = ["-created_at"]
        constraints = [
            # One advance per budget line (idempotent auto-creation).
            models.UniqueConstraint(fields=["budget_line"], name="uniq_advance_per_budget_line"),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["responsible_user_id"]),
            models.Index(fields=["fy", "month"]),
        ]


class WeeklyFundRequest(TimeStampedModel):
    """A weekly advance request aggregating all scheduled activities for that week."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    week_start_date = models.DateField()
    week_end_date = models.DateField()
    responsible_user = models.CharField(max_length=30)  # responsible user id
    responsible_role = models.CharField(max_length=64, null=True, blank=True)
    total_amount = models.BigIntegerField(default=0)  # UGX
    status = models.CharField(max_length=40, default="pending_responsible_confirmation")

    # Disbursement (advance path)
    disbursed_amount = models.BigIntegerField(null=True, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    disbursed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    disburse_method = models.CharField(max_length=64, null=True, blank=True)
    disburse_reference = models.CharField(max_length=128, null=True, blank=True)

    # Accountability (advance path, after disbursement)
    accounted_amount = models.BigIntegerField(null=True, blank=True)
    returned_amount = models.BigIntegerField(null=True, blank=True)
    accountability_netsuite_id = models.CharField(max_length=128, null=True, blank=True)
    accountability_submitted_at = models.DateTimeField(null=True, blank=True)
    accountability_reviewed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "weekly_fund_request"
        constraints = [
            models.UniqueConstraint(fields=["responsible_user", "week_start_date"], name="uniq_weekly_request_owner_week"),
        ]


class WeeklyFundRequestLine(TimeStampedModel):
    """An itemized line in a WeeklyFundRequest, linked to the original ActivityScheduleCostLine."""

    id = CuidField()
    weekly_fund_request = models.ForeignKey(WeeklyFundRequest, on_delete=models.CASCADE, related_name="lines")
    activity_budget_line = models.ForeignKey("activities.ActivityScheduleCostLine", on_delete=models.CASCADE, related_name="weekly_request_lines")
    line_item_type = models.CharField(max_length=64)
    description = models.CharField(max_length=255)
    quantity = models.IntegerField(default=1)
    unit_cost = models.BigIntegerField()
    total_cost = models.BigIntegerField()
    currency = models.CharField(max_length=8, default="UGX")

    class Meta:
        db_table = "weekly_fund_request_line"
        constraints = [
            models.UniqueConstraint(fields=["weekly_fund_request", "activity_budget_line"], name="uniq_weekly_line_budget_line"),
        ]


from .finance_models import (
    Disbursement,
    PartnerPayment,
    ReimbursementClaim,
    AccountabilityRecord,
    Receipt,
    NetSuiteExpenseRecord,
    FinanceReturn,
    VarianceReview,
    FinanceAuditLog
)

__all__ = [
    "FundRequestPeriod", "FundRequestStatus", "FundRequest", "FundRequestItem",
    "AdvanceRequestStatus", "AdvanceRequest", "WeeklyFundRequest", "WeeklyFundRequestLine",
    "Disbursement", "PartnerPayment", "ReimbursementClaim", "AccountabilityRecord",
    "Receipt", "NetSuiteExpenseRecord", "FinanceReturn", "VarianceReview", "FinanceAuditLog"
]
