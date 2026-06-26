"""Monthly work-plan budget models — CD→RVP monthly budget routing."""
from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class MonthlyWorkPlanBudgetStatus(models.TextChoices):
    DRAFT_GENERATED = "draft_generated", "Draft Generated"
    CD_REVIEW = "cd_review", "CD Review"
    ADMIN_PLAN_ADDED = "admin_plan_added", "Admin Plan Added"
    SUBMITTED_TO_RVP = "submitted_to_rvp", "Submitted to RVP"
    APPROVED_BY_RVP = "approved_by_rvp", "Approved by RVP"
    RETURNED_BY_RVP = "returned_by_rvp", "Returned by RVP"
    SENT_TO_ACCOUNTANT = "sent_to_accountant", "Sent to Accountant"
    DISBURSED = "disbursed", "Disbursed"
    CLOSED = "closed", "Closed"


class MonthlyWorkPlanBudget(TimeStampedModel):
    """Generated on the 25th for next month — the CD→RVP budget envelope."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    month_key = models.CharField(max_length=16)  # "2026-05"
    country_id = models.CharField(max_length=64, null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.CharField(max_length=30, null=True, blank=True)
    status = models.CharField(max_length=32, choices=MonthlyWorkPlanBudgetStatus.choices, default=MonthlyWorkPlanBudgetStatus.DRAFT_GENERATED)
    program_total = models.FloatField(default=0)
    admin_total = models.FloatField(default=0)
    total_amount = models.FloatField(default=0)
    activity_count = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    rvp_reviewed_at = models.DateTimeField(null=True, blank=True)
    rvp_reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    rvp_review_note = models.CharField(max_length=512, null=True, blank=True)
    sent_to_accountant_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "monthly_work_plan_budget"
        constraints = [models.UniqueConstraint(fields=["country_id", "month_key"], name="uniq_country_month")]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["fy", "month_key"])]


class AdminBudgetLine(TimeStampedModel):
    """A CD-added administrative budget line (rent, airtime, …)."""

    id = CuidField()
    monthly_budget = models.ForeignKey(MonthlyWorkPlanBudget, on_delete=models.CASCADE, related_name="admin_lines")
    cost_category = models.CharField(max_length=64)
    description = models.CharField(max_length=512)
    quantity = models.FloatField(default=1)
    unit_cost = models.FloatField()
    total_cost = models.FloatField()
    justification = models.TextField(null=True, blank=True)
    created_by_user_id = models.CharField(max_length=30)
    status = models.CharField(max_length=32, default="active")

    class Meta:
        db_table = "admin_budget_line"
        indexes = [models.Index(fields=["monthly_budget"])]


__all__ = ["MonthlyWorkPlanBudgetStatus", "MonthlyWorkPlanBudget", "AdminBudgetLine"]
