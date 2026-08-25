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


class CostCatalogue(TimeStampedModel):
    """The active CD Country Cost Catalogue — one per country + fiscal year.

    Versioned: the CD publishes a new version when rates change. Exactly one
    catalogue may be `is_active=True` per (country, fy). The CostSetting rate
    rows belong to a catalogue; every activity cost snapshot stamps the
    catalogue id + version so an activity always traces back to the rate card
    it was priced against (the financial source of truth)."""

    id = CuidField()
    country = models.CharField(max_length=64, default="Uganda")
    fy = models.CharField(max_length=16)
    version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    label = models.CharField(max_length=255, null=True, blank=True)
    published_by = models.CharField(max_length=30, null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    # CD-set operational target for Daily Visit Batch scheduling: the max
    # schools a staff member may schedule for one day (hard cap — excess is
    # rejected) and the threshold below which a scheduling reason is required.
    required_school_visits_per_day = models.IntegerField(default=5)

    class Meta:
        db_table = "cost_catalogue"
        ordering = ["-fy", "-version"]
        constraints = [
            # One active catalogue per (country, fy). Partial unique index so
            # inactive/draft catalogues don't collide.
            models.UniqueConstraint(
                fields=["country", "fy", "is_active"],
                name="uniq_active_catalogue_per_country_fy",
                condition=models.Q(is_active=True),
            ),
            models.UniqueConstraint(
                fields=["country", "fy", "version"],
                name="uniq_catalogue_country_fy_version",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.country} FY{self.fy} v{self.version}"


class CostSetting(TimeStampedModel):
    """The CD-owned Country Cost Register rate card. key = stable string.

    unit_cost is stored as integer UGX (whole shillings); all money math is
    integer-based to avoid float rounding. 1 unit = 1 UGX."""

    id = CuidField()
    key = models.CharField(max_length=128, unique=True)
    label = models.CharField(max_length=255)
    unit_cost = models.BigIntegerField()  # UGX, integer (whole shillings)
    fy = models.CharField(max_length=16, null=True, blank=True)
    version = models.IntegerField(default=1)  # bumped on every rate change
    created_by = models.CharField(max_length=30, null=True, blank=True)  # CD userId
    # The catalogue this rate belongs to. Nullable for back-compat with rows
    # created before catalogues existed (they attach to the seeded active one).
    catalogue = models.ForeignKey(
        CostCatalogue,
        on_delete=models.CASCADE,
        related_name="rates",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "cost_setting"
        ordering = ["label"]
        constraints = [
            # INT-01. The rate card is upstream of every shilling the
            # platform ever computes — costing.py multiplies unit_cost by a
            # quantity — so a negative rate would propagate a negative amount
            # into every cost line, fund request and advance derived from it.
            #
            # >= 0, not > 0: costing.py distinguishes a MISSING rate (None →
            # the activity is flagged costMissing and blocked from funding)
            # from a rate of zero, which is a real, priced "no charge" entry.
            models.CheckConstraint(
                condition=models.Q(unit_cost__gte=0),
                name="cost_setting_unit_cost_non_negative",
            ),
        ]


class CostSettingHistory(TimeStampedModel):
    """Append-only change history for the CD Country Cost Register."""

    id = CuidField()
    key = models.CharField(max_length=128)
    label = models.CharField(max_length=255)
    old_unit_cost = models.BigIntegerField(
        null=True, blank=True
    )  # UGX; null on first create
    new_unit_cost = models.BigIntegerField()  # UGX
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
        constraints = [
            # INT-01. This is the audit twin of CostSetting.unit_cost and
            # must accept exactly the same values, or a rate the register
            # holds becomes a rate its history cannot record. old_unit_cost
            # is null on the first create (see the field comment).
            models.CheckConstraint(
                condition=models.Q(new_unit_cost__gte=0),
                name="cost_setting_history_new_unit_cost_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(old_unit_cost__isnull=True)
                | models.Q(old_unit_cost__gte=0),
                name="cost_setting_history_old_unit_cost_non_negative",
            ),
        ]


class MonthlyFundRequest(TimeStampedModel):
    """A legacy monthly fund-request summary row (per staff/month)."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    month = models.IntegerField()
    staff_id = models.CharField(max_length=30, null=True, blank=True)
    amount = models.BigIntegerField()  # UGX
    status = models.CharField(max_length=32, default="submitted")

    class Meta:
        db_table = "monthly_fund_request"
        constraints = [
            # INT-01. Legacy and currently write-free, which is exactly why
            # it is worth pinning now: the next thing to write it will be an
            # import or a repair script with no service layer in front of it.
            # >= 0 for the same reason as every other summed money column.
            models.CheckConstraint(
                condition=models.Q(amount__gte=0),
                name="monthly_fund_request_amount_non_negative",
            ),
        ]


class BudgetAmendmentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    UNDER_REVIEW = "under_review", "Under Review"
    APPROVED = "approved", "Approved"
    RETURNED = "returned", "Returned"
    REJECTED = "rejected", "Rejected"
    APPLIED = "applied", "Applied"
    CANCELLED = "cancelled", "Cancelled"


class BudgetAmendment(TimeStampedModel):
    """Formal change to a finance-locked activity's schedule/period.

    The cost-snapshot lock (apps.budget.costing_service) refuses to rebuild
    lines once money is confirmed or moved — this is the sanctioned path its
    message points to. v1 scope: move a locked activity's date/period without
    delete-recreating its cost lines (the snapshot rows are preserved; only
    their period stamps move on apply). Amount changes are recorded for audit
    but the snapshot amounts are immutable once money moved."""

    id = CuidField()
    activity = models.ForeignKey(
        "activities.Activity",
        on_delete=models.CASCADE,
        related_name="budget_amendments",
    )
    original_date = models.DateField(null=True, blank=True)
    new_date = models.DateField()
    original_amount = models.BigIntegerField(default=0)  # UGX
    original_fy = models.CharField(max_length=16, null=True, blank=True)
    original_quarter = models.CharField(max_length=8, null=True, blank=True)
    new_fy = models.CharField(max_length=16, null=True, blank=True)
    new_quarter = models.CharField(max_length=8, null=True, blank=True)
    reason = models.TextField()
    requested_by = models.CharField(max_length=30)
    reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    review_note = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=BudgetAmendmentStatus.choices,
        default=BudgetAmendmentStatus.SUBMITTED,
    )
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "budget_amendment"
        ordering = ["-created_at"]
        constraints = [
            # INT-01. The recorded cost of the activity BEFORE the amendment
            # — a historical fact copied from the snapshot, so it inherits
            # the snapshot's floor. Its own `default=0` settles the boundary:
            # zero is the documented value for an amendment that carries no
            # cost yet, so >= 0.
            models.CheckConstraint(
                condition=models.Q(original_amount__gte=0),
                name="budget_amendment_original_amount_non_negative",
            ),
            # The whole point of an amendment is to move an activity's date,
            # so a new_date earlier than the original is legal and ordinary
            # (a reschedule forward or back) — deliberately NOT constrained.
        ]


__all__ = [
    "CostCatalogue",
    "CostSetting",
    "CostSettingHistory",
    "MonthlyFundRequest",
    "BudgetAmendment",
    "BudgetAmendmentStatus",
]
