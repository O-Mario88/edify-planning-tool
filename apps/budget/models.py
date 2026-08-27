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


class RateCardKind(models.TextChoices):
    REFERENCE = "reference", "Internal Reference"
    OPERATIONAL = "operational", "Country Approved Operational"


class RateCardStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    UNDER_REVIEW = "under_review", "Under Review"
    PUBLISHED = "published", "Published"
    SUPERSEDED = "superseded", "Superseded"
    RETIRED = "retired", "Retired"


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
    kind = models.CharField(
        max_length=16,
        choices=RateCardKind.choices,
        default=RateCardKind.OPERATIONAL,
    )
    status = models.CharField(
        max_length=16,
        choices=RateCardStatus.choices,
        default=RateCardStatus.PUBLISHED,
    )
    version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    label = models.CharField(max_length=255, null=True, blank=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=8, default="UGX")
    created_by = models.CharField(max_length=30, null=True, blank=True)
    reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    approved_by = models.CharField(max_length=30, null=True, blank=True)
    published_by = models.CharField(max_length=30, null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    is_provisional = models.BooleanField(default=False)
    source_note = models.CharField(max_length=512, null=True, blank=True)
    material_difference_threshold_bps = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Approved warning threshold in basis points; null means not configured.",
    )
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
                fields=["country", "fy", "kind", "is_active"],
                name="uniq_active_catalogue_per_country_fy",
                condition=models.Q(is_active=True),
            ),
            models.UniqueConstraint(
                fields=["country", "fy", "kind", "version"],
                name="uniq_catalogue_country_fy_version",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_from__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="rate_card_effective_dates_ordered",
            ),
            models.CheckConstraint(
                condition=~models.Q(country="Uganda") | models.Q(currency="UGX"),
                name="uganda_rate_card_currency_ugx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.country} FY{self.fy} v{self.version}"


class CostSetting(TimeStampedModel):
    """The CD-owned Country Cost Register rate card. key = stable string.

    unit_cost is stored as integer UGX (whole shillings); all money math is
    integer-based to avoid float rounding. 1 unit = 1 UGX."""

    id = CuidField()
    key = models.CharField(max_length=128)
    label = models.CharField(max_length=255)
    unit_cost = models.BigIntegerField()  # UGX, integer (whole shillings)
    fy = models.CharField(max_length=16, null=True, blank=True)
    version = models.IntegerField(default=1)  # bumped on every rate change
    unit = models.CharField(max_length=64, default="unit")
    approved_minimum = models.BigIntegerField(null=True, blank=True)
    geographic_scope = models.CharField(max_length=128, null=True, blank=True)
    costing_profile_scope = models.CharField(max_length=64, null=True, blank=True)
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
            models.CheckConstraint(
                condition=models.Q(approved_minimum__isnull=True)
                | models.Q(approved_minimum__gte=0),
                name="cost_setting_approved_minimum_non_negative",
            ),
            models.UniqueConstraint(
                fields=["catalogue", "key"],
                name="uniq_rate_card_component",
            ),
        ]


class ActivityCostStatus(models.TextChoices):
    ESTIMATED = "estimated", "Estimated Operational Cost"
    APPROVED = "approved", "Approved Operating Limit"
    AMENDMENT_REQUIRED = "amendment_required", "Cost Amendment Required"
    DISBURSED = "disbursed", "Disbursed"
    ACCOUNTED = "accounted", "Accounted"
    CLOSED = "closed", "Closed"


class ActivityCostSnapshot(TimeStampedModel):
    """Immutable dual-cost calculation metadata for one activity revision.

    Only ``operational_cost`` feeds the payable ActivityScheduleCostLine rows.
    ``reference_cost`` is restricted benchmark metadata and may remain null.
    """

    id = CuidField()
    activity = models.ForeignKey(
        "activities.Activity", on_delete=models.CASCADE, related_name="cost_snapshots"
    )
    sequence = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True)
    activity_catalogue_item_id = models.CharField(max_length=30, null=True, blank=True)
    activity_catalogue_version = models.PositiveIntegerField(null=True, blank=True)
    costing_profile_version = models.CharField(max_length=64, null=True, blank=True)
    reference_rate_card = models.ForeignKey(
        CostCatalogue,
        on_delete=models.PROTECT,
        related_name="reference_activity_snapshots",
        null=True,
        blank=True,
    )
    operational_rate_card = models.ForeignKey(
        CostCatalogue,
        on_delete=models.PROTECT,
        related_name="operational_activity_snapshots",
        null=True,
        blank=True,
    )
    reference_cost = models.BigIntegerField(null=True, blank=True)
    operational_cost = models.BigIntegerField(default=0)
    approved_operating_limit = models.BigIntegerField(null=True, blank=True)
    amount_disbursed = models.BigIntegerField(default=0)
    actual_accounted_spend = models.BigIntegerField(default=0)
    unused_balance = models.BigIntegerField(default=0)
    reimbursement_amount = models.BigIntegerField(default=0)
    calculation_inputs = models.JSONField(default=dict)
    reference_breakdown = models.JSONField(default=list)
    operational_breakdown = models.JSONField(default=list)
    warnings = models.JSONField(default=list)
    missing_configuration = models.JSONField(default=list)
    calculated_at = models.DateTimeField()
    calculated_by = models.CharField(max_length=30, null=True, blank=True)
    recalculation_reason = models.CharField(max_length=512, null=True, blank=True)
    approved_by = models.CharField(max_length=30, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    cost_status = models.CharField(
        max_length=32,
        choices=ActivityCostStatus.choices,
        default=ActivityCostStatus.ESTIMATED,
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="revisions",
    )

    class Meta:
        db_table = "activity_cost_snapshot"
        ordering = ["-sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["activity"],
                condition=models.Q(is_current=True),
                name="uniq_current_activity_cost_snapshot",
            ),
            models.UniqueConstraint(
                fields=["activity", "sequence"],
                name="uniq_activity_cost_snapshot_sequence",
            ),
            models.CheckConstraint(
                condition=models.Q(reference_cost__isnull=True)
                | models.Q(reference_cost__gte=0),
                name="activity_reference_cost_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(operational_cost__gte=0),
                name="activity_operational_cost_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(approved_operating_limit__isnull=True)
                | models.Q(approved_operating_limit__gte=0),
                name="activity_approved_limit_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_disbursed__gte=0)
                & models.Q(actual_accounted_spend__gte=0)
                & models.Q(unused_balance__gte=0)
                & models.Q(reimbursement_amount__gte=0),
                name="activity_cost_ledger_amounts_non_negative",
            ),
        ]


class CostReviewReason(models.TextChoices):
    ROUTE = "route_conditions_changed", "Route conditions changed"
    TRANSPORT = "transport_rate_changed", "Transport rate changed"
    ACCOMMODATION = "accommodation_needed", "Accommodation became necessary"
    PARTICIPANTS = "participant_count_changed", "Participant count changed"
    VENUE = "venue_cost_changed", "Venue cost changed"
    LOCATION = "school_location_inaccurate", "School location is inaccurate"
    COMPONENT = "cost_component_missing", "Required cost component is missing"
    OTHER = "other", "Other"


class ActivityCostReview(TimeStampedModel):
    id = CuidField()
    activity = models.ForeignKey(
        "activities.Activity", on_delete=models.CASCADE, related_name="cost_reviews"
    )
    snapshot = models.ForeignKey(
        ActivityCostSnapshot, on_delete=models.PROTECT, related_name="reviews"
    )
    reason_code = models.CharField(max_length=48, choices=CostReviewReason.choices)
    explanation = models.TextField()
    evidence = models.JSONField(default=list, blank=True)
    proposed_inputs = models.JSONField(default=dict, blank=True)
    current_operational_cost = models.BigIntegerField(default=0)
    proposed_operational_cost = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=24, default="submitted")
    requested_by = models.CharField(max_length=30)
    reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    review_note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "activity_cost_review"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(current_operational_cost__gte=0),
                name="cost_review_current_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(proposed_operational_cost__isnull=True)
                | models.Q(proposed_operational_cost__gte=0),
                name="cost_review_proposed_amount_non_negative",
            ),
        ]


class StrategicReserveStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    CLOSED = "closed", "Closed"


class CountryStrategicActivityReserve(TimeStampedModel):
    id = CuidField()
    country = models.CharField(max_length=64, default="Uganda")
    fy = models.CharField(max_length=16)
    period_key = models.CharField(max_length=16, blank=True, default="")
    opening_reserve = models.BigIntegerField(default=0)
    approved_additions = models.BigIntegerField(default=0)
    cleared_savings_transferred = models.BigIntegerField(default=0)
    amount_committed = models.BigIntegerField(default=0)
    amount_disbursed = models.BigIntegerField(default=0)
    amount_returned = models.BigIntegerField(default=0)
    status = models.CharField(
        max_length=16,
        choices=StrategicReserveStatus.choices,
        default=StrategicReserveStatus.DRAFT,
    )
    approved_by = models.CharField(max_length=30, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    @property
    def available_balance(self) -> int:
        return max(
            0,
            int(self.opening_reserve)
            + int(self.approved_additions)
            + int(self.cleared_savings_transferred)
            + int(self.amount_returned)
            - int(self.amount_committed)
            - int(self.amount_disbursed),
        )

    class Meta:
        db_table = "country_strategic_activity_reserve"
        constraints = [
            models.UniqueConstraint(
                fields=["country", "fy", "period_key"],
                name="uniq_country_strategic_reserve_period",
            ),
            models.CheckConstraint(
                condition=models.Q(opening_reserve__gte=0)
                & models.Q(approved_additions__gte=0)
                & models.Q(cleared_savings_transferred__gte=0)
                & models.Q(amount_committed__gte=0)
                & models.Q(amount_disbursed__gte=0)
                & models.Q(amount_returned__gte=0),
                name="strategic_reserve_amounts_non_negative",
            ),
        ]


class ReserveActivationStatus(models.TextChoices):
    SUGGESTED = "suggested", "Suggested"
    AWAITING_CD = "awaiting_cd", "Awaiting CD Review"
    AWAITING_RVP = "awaiting_rvp", "Awaiting RVP Approval"
    APPROVED = "approved", "Approved"
    DISBURSEMENT_PENDING = "disbursement_pending", "Disbursement Pending"
    DISBURSED = "disbursed", "Disbursed"
    ACCOUNTED = "accounted", "Accounted"
    RETURNED = "returned", "Returned"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Canceled"


class StrategicReserveActivation(TimeStampedModel):
    id = CuidField()
    reserve = models.ForeignKey(
        CountryStrategicActivityReserve,
        on_delete=models.PROTECT,
        related_name="activations",
    )
    activity = models.ForeignKey(
        "activities.Activity",
        on_delete=models.PROTECT,
        related_name="reserve_activations",
    )
    reason_normal_funding_insufficient = models.TextField()
    operational_cost = models.BigIntegerField(default=0)
    requested_amount = models.BigIntegerField()
    expected_outcome = models.TextField()
    required_implementation_date = models.DateField()
    alternative_considered = models.TextField()
    balance_before = models.BigIntegerField(default=0)
    balance_after = models.BigIntegerField(default=0)
    requested_by = models.CharField(max_length=30)
    cd_approved_by = models.CharField(max_length=30, null=True, blank=True)
    rvp_approved_by = models.CharField(max_length=30, null=True, blank=True)
    status = models.CharField(
        max_length=24,
        choices=ReserveActivationStatus.choices,
        default=ReserveActivationStatus.SUGGESTED,
    )

    class Meta:
        db_table = "strategic_reserve_activation"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(operational_cost__gte=0)
                & models.Q(requested_amount__gt=0)
                & models.Q(balance_before__gte=0)
                & models.Q(balance_after__gte=0),
                name="reserve_activation_amounts_valid",
            )
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
    "RateCardKind",
    "RateCardStatus",
    "CostCatalogue",
    "CostSetting",
    "CostSettingHistory",
    "ActivityCostStatus",
    "ActivityCostSnapshot",
    "CostReviewReason",
    "ActivityCostReview",
    "StrategicReserveStatus",
    "CountryStrategicActivityReserve",
    "ReserveActivationStatus",
    "StrategicReserveActivation",
    "MonthlyFundRequest",
    "BudgetAmendment",
    "BudgetAmendmentStatus",
]
