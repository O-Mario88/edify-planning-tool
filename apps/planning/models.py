"""Planning models — annual + monthly plans."""

from __future__ import annotations

from django.db import models

from apps.core.enums import ActivityType
from apps.core.models import CuidField, TimeStampedModel


class AnnualPlan(TimeStampedModel):
    id = CuidField()
    fy = models.CharField(max_length=16)
    owner_staff_id = models.CharField(max_length=30, null=True, blank=True)
    status = models.CharField(max_length=32, default="draft")

    class Meta:
        db_table = "annual_plan"
        constraints = [
            models.UniqueConstraint(
                fields=["fy", "owner_staff_id"], name="uniq_annualplan_fy_owner"
            )
        ]


class AnnualPlanActivity(TimeStampedModel):
    id = CuidField()
    annual_plan = models.ForeignKey(
        AnnualPlan, on_delete=models.CASCADE, related_name="activities"
    )
    activity_type = models.CharField(max_length=48, choices=ActivityType.choices)
    school_id = models.CharField(max_length=30, null=True, blank=True)
    cluster_id = models.CharField(max_length=30, null=True, blank=True)
    quarter = models.CharField(max_length=8)
    month = models.IntegerField(null=True, blank=True)
    week = models.IntegerField(null=True, blank=True)


class MonthlyPlan(TimeStampedModel):
    """The CCEO's plan-as-list for one operational month."""

    id = CuidField()
    month_iso = models.CharField(max_length=16)  # "2026-05"
    owner_staff_id = models.CharField(max_length=30)
    owner_name = models.CharField(max_length=255, null=True, blank=True)
    country_id = models.CharField(max_length=64, default="Uganda")
    status = models.CharField(max_length=32, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by_id = models.CharField(max_length=30, null=True, blank=True)
    returned_reason = models.CharField(max_length=512, null=True, blank=True)
    total_cost_cents = models.IntegerField(default=0)

    class Meta:
        db_table = "monthly_plan"
        constraints = [
            models.UniqueConstraint(
                fields=["month_iso", "owner_staff_id"],
                name="uniq_monthlyplan_month_owner",
            )
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["owner_staff_id"]),
        ]


class MonthlyPlanActivity(TimeStampedModel):
    id = CuidField()
    plan = models.ForeignKey(
        MonthlyPlan, on_delete=models.CASCADE, related_name="activities"
    )
    kind = models.CharField(max_length=48)
    title = models.CharField(max_length=255)
    week_of_month = models.IntegerField(default=1)
    scheduled_date = models.CharField(max_length=32, null=True, blank=True)
    school_id = models.CharField(max_length=30, null=True, blank=True)
    assignee_id = models.CharField(max_length=30, null=True, blank=True)
    # Despite the field name, this holds plain integer UGX (whole
    # shillings), not cents -- see apps.activities.models.Activity.est_cost_cents.
    est_cost_cents = models.IntegerField(default=0)
    status = models.CharField(max_length=32, default="Planned")
    intervention_area = models.CharField(max_length=64, null=True, blank=True)
    delivery_type = models.CharField(max_length=16, null=True, blank=True)
    partner_name = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "monthly_plan_activity"
        indexes = [models.Index(fields=["plan"])]


__all__ = ["AnnualPlan", "AnnualPlanActivity", "MonthlyPlan", "MonthlyPlanActivity"]
