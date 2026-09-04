"""Planning models — the CCEO's monthly plan and team actions.

AnnualPlan / AnnualPlanActivity used to live here too. Nothing read or wrote
them (the 2026-07-14 audit listed them as dead), so they were dropped along
with their table in migration 0009.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


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
    est_cost_cents = models.BigIntegerField(default=0)
    status = models.CharField(max_length=32, default="Planned")
    intervention_area = models.CharField(max_length=64, null=True, blank=True)
    delivery_type = models.CharField(max_length=16, null=True, blank=True)
    partner_name = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "monthly_plan_activity"
        indexes = [models.Index(fields=["plan"])]


# Defined in its own module because it is a different kind of thing from the
# plan models above — accountability rather than intent — but re-exported here
# so Django's app-loading discovers it.
from apps.planning.action_models import (  # noqa: E402
    ACTIVE_STATES,
    RELEASING_STATES,
    ActionPriority,
    ActionState,
    TeamAction,
)

__all__ = [
    "MonthlyPlan",
    "MonthlyPlanActivity",
    "TeamAction",
    "ActionState",
    "ActionPriority",
    "ACTIVE_STATES",
    "RELEASING_STATES",
]
