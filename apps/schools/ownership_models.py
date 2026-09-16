"""Who owns a school, and the record of every time that changed.

Owner brief, 2026-09-15: Admin and Impact Assessment may move a school, or a
whole district's schools, from one staff member to another. Two distinct
business objects, neither of which touches geography:

* **Reassign School Owner** — the active StaffSchoolAssignment moves. The
  school's district, sub-county, parish and village do not.
* **Reassign District Portfolio Owner** — the same act for every school one
  person holds in a district, recorded once as a batch and once per school.

``School.account_owner_id`` and ``StaffSchoolAssignment`` stay the current
answer that scope, planning and targets read; these rows are the history, with
the actor, the reason, the effective date and what happened to the open work.

Approved target allocations are never rewritten by a transfer. Where one
depended on the portfolio that moved, the transfer is marked
``TARGET_RECONCILIATION_REQUIRED`` and IA and the Programme Lead are asked to
reconcile it through the governed amendment workflow.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class OpenActivityDecision(models.TextChoices):
    KEEP = "keep", "Keep open activities with their current owner"
    TRANSFER = "transfer", "Transfer eligible open activities to the new owner"


class TargetReconciliation(models.TextChoices):
    NOT_REQUIRED = "not_required", "No approved target depends on this portfolio"
    REQUIRED = "required", "Target reconciliation required"
    RESOLVED = "resolved", "Target reconciliation resolved"


class DistrictPortfolioTransfer(TimeStampedModel):
    """One district's schools moving from one staff member to another."""

    id = CuidField()
    district = models.ForeignKey(
        "geography.District",
        on_delete=models.PROTECT,
        related_name="portfolio_transfers",
    )
    from_staff = models.ForeignKey(
        "accounts.StaffProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="district_portfolios_given",
    )
    to_staff = models.ForeignKey(
        "accounts.StaffProfile",
        on_delete=models.PROTECT,
        related_name="district_portfolios_taken",
    )
    effective_date = models.DateField()
    reason = models.TextField()
    open_activity_decision = models.CharField(
        max_length=16,
        choices=OpenActivityDecision.choices,
        default=OpenActivityDecision.KEEP,
    )
    school_count = models.PositiveIntegerField(default=0)
    activities_transferred = models.PositiveIntegerField(default=0)
    actor_id = models.CharField(max_length=30, blank=True, default="")
    actor_role = models.CharField(max_length=64, blank=True, default="")
    correlation_id = models.CharField(max_length=64, blank=True, default="")
    target_reconciliation_status = models.CharField(
        max_length=16,
        choices=TargetReconciliation.choices,
        default=TargetReconciliation.NOT_REQUIRED,
    )
    preview = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "district_portfolio_transfer"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["district", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.district_id}: {self.from_staff_id} → {self.to_staff_id}"


class SchoolOwnershipTransfer(TimeStampedModel):
    """One school's portfolio ownership moving, kept for good."""

    id = CuidField()
    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="ownership_transfers"
    )
    from_staff = models.ForeignKey(
        "accounts.StaffProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="schools_given",
    )
    to_staff = models.ForeignKey(
        "accounts.StaffProfile",
        on_delete=models.PROTECT,
        related_name="schools_taken",
    )
    effective_date = models.DateField()
    reason = models.TextField()
    open_activity_decision = models.CharField(
        max_length=16,
        choices=OpenActivityDecision.choices,
        default=OpenActivityDecision.KEEP,
    )
    transferred_activity_ids = models.JSONField(default=list, blank=True)
    kept_activity_ids = models.JSONField(default=list, blank=True)
    actor_id = models.CharField(max_length=30, blank=True, default="")
    actor_role = models.CharField(max_length=64, blank=True, default="")
    correlation_id = models.CharField(max_length=64, blank=True, default="")
    batch = models.ForeignKey(
        DistrictPortfolioTransfer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="school_transfers",
    )
    target_reconciliation_status = models.CharField(
        max_length=16,
        choices=TargetReconciliation.choices,
        default=TargetReconciliation.NOT_REQUIRED,
    )
    target_reconciliation_note = models.TextField(blank=True, default="")
    target_reconciliation_resolved_by = models.CharField(
        max_length=30, blank=True, default=""
    )
    target_reconciliation_resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "school_ownership_transfer"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["school", "-created_at"]),
            models.Index(fields=["target_reconciliation_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.school_id}: {self.from_staff_id} → {self.to_staff_id}"
