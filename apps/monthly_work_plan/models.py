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
    status = models.CharField(
        max_length=32,
        choices=MonthlyWorkPlanBudgetStatus.choices,
        default=MonthlyWorkPlanBudgetStatus.DRAFT_GENERATED,
    )
    program_total = models.BigIntegerField(default=0)  # UGX
    admin_total = models.BigIntegerField(default=0)  # UGX
    total_amount = models.BigIntegerField(default=0)  # UGX
    activity_count = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    rvp_reviewed_at = models.DateTimeField(null=True, blank=True)
    rvp_reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    rvp_review_note = models.CharField(max_length=512, null=True, blank=True)
    sent_to_accountant_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "monthly_work_plan_budget"
        constraints = [
            models.UniqueConstraint(
                fields=["country_id", "month_key"], name="uniq_country_month"
            )
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["fy", "month_key"]),
        ]


class AdminBudgetLine(TimeStampedModel):
    """A CD-added administrative budget line (rent, airtime, …)."""

    id = CuidField()
    monthly_budget = models.ForeignKey(
        MonthlyWorkPlanBudget, on_delete=models.CASCADE, related_name="admin_lines"
    )
    cost_category = models.CharField(max_length=64)
    description = models.CharField(max_length=512)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=1
    )  # qty may be fractional (days)
    unit_cost = models.BigIntegerField()  # UGX
    total_cost = models.BigIntegerField()  # UGX
    justification = models.TextField(null=True, blank=True)
    created_by_user_id = models.CharField(max_length=30)
    status = models.CharField(max_length=32, default="active")

    class Meta:
        db_table = "admin_budget_line"
        indexes = [models.Index(fields=["monthly_budget"])]


__all__ = ["MonthlyWorkPlanBudgetStatus", "MonthlyWorkPlanBudget", "AdminBudgetLine"]


class CountryAnnualBudgetStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED_TO_RVP = "submitted_to_rvp", "Submitted to RVP"
    APPROVED_BY_RVP = "approved_by_rvp", "RVP Approved"
    RETURNED_BY_RVP = "returned_by_rvp", "Returned by RVP"


class CountryAnnualBudget(TimeStampedModel):
    """The CD's annual country budget envelope — RVP approval locks the
    baseline; monthly allocations then reference the approved annual ceiling
    and any change requires a formal amendment (a new returned/resubmitted
    cycle), never a silent edit."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    # Full country name — the same convention every MonthlyWorkPlanBudget
    # write path uses (see services._rvp_country_scope). The old "UG" code
    # default split the identifier space in two.
    country_id = models.CharField(max_length=64, default="Uganda")
    strategic_priorities = models.TextField(null=True, blank=True)
    target_schools = models.IntegerField(default=0)
    target_activities = models.IntegerField(default=0)
    planned_staff_visits = models.IntegerField(default=0)
    planned_partner_visits = models.IntegerField(default=0)
    core_package_schools = models.IntegerField(default=0)
    cluster_activities = models.IntegerField(default=0)
    special_project_total = models.BigIntegerField(default=0)  # UGX
    admin_total = models.BigIntegerField(default=0)  # UGX
    program_total = models.BigIntegerField(default=0)  # UGX
    total_amount = models.BigIntegerField(default=0)  # UGX
    monthly_phasing = models.JSONField(default=list, blank=True)  # 12 amounts
    quarterly_phasing = models.JSONField(default=list, blank=True)  # 4 amounts
    prior_year_total = models.BigIntegerField(default=0)
    expected_impact = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=CountryAnnualBudgetStatus.choices,
        default=CountryAnnualBudgetStatus.DRAFT,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    rvp_reviewed_at = models.DateTimeField(null=True, blank=True)
    rvp_reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    rvp_review_note = models.CharField(max_length=512, null=True, blank=True)
    baseline_locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "country_annual_budget"
        constraints = [
            models.UniqueConstraint(
                fields=["country_id", "fy"], name="uniq_country_annual_fy"
            )
        ]
        indexes = [models.Index(fields=["status"])]


class RVPApprovalDecision(TimeStampedModel):
    """Immutable audit row for every RVP decision — monthly budgets, annual
    budgets, special-project strategy, partner strategy."""

    id = CuidField()
    decision_type = models.CharField(
        max_length=32
    )  # monthly_budget | annual_budget | special_project | partner
    subject_id = models.CharField(max_length=64)  # budget/project/partner id
    subject_label = models.CharField(max_length=255)
    action = models.CharField(
        max_length=32
    )  # approve | return | scale | pause | close | ...
    reason = models.CharField(max_length=512, null=True, blank=True)
    decided_by = models.CharField(max_length=30)
    amount = models.BigIntegerField(default=0)
    fy = models.CharField(max_length=16, null=True, blank=True)

    class Meta:
        db_table = "rvp_approval_decision"
        indexes = [models.Index(fields=["decision_type", "subject_id"])]


class StrategyNoteStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    DONE = "done", "Done"
    CANCELLED = "cancelled", "Cancelled"


class StrategyNote(TimeStampedModel):
    """Accountable RVP executive guidance — never untracked free text: each
    note has an owner (Country Director), a deadline and a status, creates a
    CD To-Do and a notification."""

    id = CuidField()
    author_id = models.CharField(max_length=30)  # RVP user id
    priority_label = models.CharField(max_length=128)  # strategic priority category
    scope = models.CharField(max_length=128, default="Regional")
    instruction = models.TextField()
    expected_outcome = models.TextField(null=True, blank=True)
    responsible_cd_id = models.CharField(max_length=30, null=True, blank=True)
    deadline = models.DateField(null=True, blank=True)
    review_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=StrategyNoteStatus.choices,
        default=StrategyNoteStatus.OPEN,
    )

    class Meta:
        db_table = "rvp_strategy_note"
        indexes = [models.Index(fields=["status", "responsible_cd_id"])]
