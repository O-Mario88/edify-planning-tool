"""
Daily Visit Batch — the shared-cost grouping for staff-conducted school
visits. School visit costing is day-based, not isolated per school: a
staff member's same-day visits to N schools share one daily transport/
lunch(/accommodation/dinner) cost pool, split evenly across the N schools.

See apps/daily_visit_batches/services.py for the scheduling/validation/
recalculation logic and apps/daily_visit_batches/pricing.py for the pure
cost-splitting math.
"""
from __future__ import annotations

from django.db import models

from apps.core.enums import DistrictType
from apps.core.models import CuidField, TimeStampedModel


class DailyVisitBatch(TimeStampedModel):
    """One staff member + one planned date + one shared daily cost pool.

    Locking is never cached here: whether a batch may still be recalculated
    is always derived live from the linked WeeklyFundRequest's status (the
    same convention ActivityScheduleCostLine already relies on), so it can't
    drift out of sync.
    """

    id = CuidField()
    # apps.accounts.User.id — NOT StaffProfile.id. Must match
    # ActivityScheduleCostLine.responsible_user / WeeklyFundRequest.responsible_user.
    responsible_user = models.CharField(max_length=30)
    visit_date = models.DateField()
    district_type = models.CharField(max_length=16, choices=DistrictType.choices)
    secondary_district_group = models.ForeignKey(
        "geography.SecondaryDistrictGroup", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="batches",
    )
    cost_catalogue = models.ForeignKey(
        "budget.CostCatalogue", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="daily_visit_batches",
    )
    catalogue_version = models.IntegerField(null=True, blank=True)
    # Snapshot of the exact per-day catalogue rates used at last recalculation,
    # e.g. {"primary_transport_per_day": 50000, "primary_lunch_per_day": 12000}.
    # Stored (not re-derived) so later rate changes don't corrupt the
    # transparent breakdown display — same provenance principle already used
    # for ActivityScheduleCostLine.catalogue_version elsewhere.
    rate_snapshot = models.JSONField(default=dict)
    daily_pool_amount = models.BigIntegerField(default=0)  # sum(rate_snapshot.values())
    school_count = models.IntegerField(default=0)  # live active-member count, kept in sync on every recalc
    per_school_amount = models.BigIntegerField(default=0)  # daily_pool_amount // school_count, display summary only
    required_target_snapshot = models.IntegerField(null=True, blank=True)
    # Required when school_count < required_target_snapshot (inflates cost/school).
    reason = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "daily_visit_batch"
        constraints = [
            models.UniqueConstraint(
                fields=["responsible_user", "visit_date"], name="uniq_daily_visit_batch_user_date"
            ),
        ]
        indexes = [
            models.Index(fields=["visit_date"]),
            models.Index(fields=["district_type"]),
            models.Index(fields=["responsible_user"]),
        ]

    def __str__(self) -> str:
        return f"DailyVisitBatch({self.responsible_user}, {self.visit_date}, {self.district_type})"


__all__ = ["DailyVisitBatch"]
