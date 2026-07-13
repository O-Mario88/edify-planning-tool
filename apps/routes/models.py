"""Route Intelligence models — the feasibility twin of Daily Visit Batch costing.

DailyVisitBatch (apps.daily_visit_batches) answers "what does this visit day
cost?"; DailyVisitRouteBatch answers "can this visit day actually be completed?"
They share the same natural key (responsible_user, visit_date) and must agree
on the school set — a System Health check flags any drift.

Location sources are used in strict priority order (never text-first):
  1. Coordinates            (SchoolGeoPoint override, else School.latitude/longitude)
  2. District + Sub-county  (structured FKs from the school upload)
  3. District + Parish      (structured FK)
  4. Shipping-address text  (phrase parsing with stopword filtering)
  5. Manual review          (needs_cleanup — a Data Quality To-Do, never a rejection)

The mandate's "SecondaryRouteGroup" already exists as
apps.geography.SecondaryDistrictGroup (CD/Admin-approved, status gated) — the
route layer reuses it rather than duplicating the concept.
"""

from __future__ import annotations

from django.db import models

from apps.core.enums import DistrictType
from apps.core.models import CuidField, TimeStampedModel


class LocationSource(models.TextChoices):
    COORDINATES = "coordinates", "Coordinates"
    DISTRICT_SUBCOUNTY = "district_subcounty", "District + Sub-county"
    DISTRICT_PARISH = "district_parish", "District + Parish"
    ADDRESS_TEXT = "address_text", "Shipping Address Parsing"
    NONE = "none", "Manual Review Needed"


class LocationConfidence(models.TextChoices):
    HIGH = "high", "High confidence"
    MEDIUM = "medium", "Medium confidence"
    LOW = "low", "Low confidence"
    NEEDS_CLEANUP = "needs_cleanup", "Needs location cleanup"


class RouteStatus(models.TextChoices):
    EXCELLENT = "excellent", "Excellent"
    GOOD = "good", "Good"
    RISKY = "risky", "Risky"
    NOT_FEASIBLE = "not_feasible", "Not Feasible"
    BLOCKED = "blocked", "Blocked"


class SchoolGeoPoint(TimeStampedModel):
    """Verified/corrected coordinates for a school — the strongest location
    source. Overrides School.latitude/longitude when present (upload data is
    never mutated; cleanup lands here with provenance)."""

    id = CuidField()
    school_id = models.CharField(max_length=30, unique=True)  # schools.School.id
    latitude = models.FloatField()
    longitude = models.FloatField()
    source = models.CharField(max_length=32, default="manual")  # manual | upload | geocoded
    captured_by = models.CharField(max_length=30, null=True, blank=True)  # User.id

    class Meta:
        db_table = "school_geo_point"
        indexes = [models.Index(fields=["school_id"])]

    def __str__(self) -> str:
        return f"GeoPoint({self.school_id}, {self.latitude}, {self.longitude})"


class SchoolLocationConfidence(TimeStampedModel):
    """Cached result of the location-source resolution for one school:
    which source won, the meaningful location tokens extracted, and how much
    the route engine should trust it. Refreshed whenever a route batch or
    preview touches the school."""

    id = CuidField()
    school_id = models.CharField(max_length=30, unique=True)
    source_used = models.CharField(
        max_length=32, choices=LocationSource.choices, default=LocationSource.NONE
    )
    confidence = models.CharField(
        max_length=16, choices=LocationConfidence.choices, default=LocationConfidence.NEEDS_CLEANUP
    )
    # Meaningful location phrases (generic words already removed),
    # e.g. ["Goma", "Nakifuma Hill"].
    tokens = models.JSONField(default=list)
    area_label = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "school_location_confidence"
        indexes = [models.Index(fields=["confidence"])]

    def __str__(self) -> str:
        return f"LocationConfidence({self.school_id}, {self.confidence})"


class DailyVisitRouteBatch(TimeStampedModel):
    """Route feasibility for one staff member's school-visit day. Built/rebuilt
    from the day's planned visits whenever the paired DailyVisitBatch changes;
    read by the planning preview, My Plan, PL dashboard and System Health."""

    id = CuidField()
    responsible_user = models.CharField(max_length=30)  # accounts.User.id
    visit_date = models.DateField()
    district_type = models.CharField(
        max_length=16, choices=DistrictType.choices, null=True, blank=True
    )
    district = models.ForeignKey(
        "geography.District", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="route_batches",
    )
    secondary_district_group = models.ForeignKey(
        "geography.SecondaryDistrictGroup", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="route_batches",
    )
    cost_batch = models.ForeignKey(
        "daily_visit_batches.DailyVisitBatch", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="route_batches",
    )

    # The day's schools, in the best visit sequence the engine could find.
    school_ids = models.JSONField(default=list)
    school_count = models.IntegerField(default=0)
    # Detected local grouping, e.g. ["Goma Division", "Nakifuma Hill"].
    area_labels = models.JSONField(default=list)
    sub_county_ids = models.JSONField(default=list)

    # Route math (minutes/km are estimates; provenance in `coords_used`).
    coords_used = models.IntegerField(default=0)  # schools with usable coordinates
    est_distance_km = models.FloatField(null=True, blank=True)
    est_travel_minutes = models.IntegerField(default=0)
    visit_minutes = models.IntegerField(default=0)
    buffer_minutes = models.IntegerField(default=0)
    day_load_minutes = models.IntegerField(default=0)
    available_minutes = models.IntegerField(default=0)
    feasible = models.BooleanField(default=True)

    quality_score = models.IntegerField(default=0)  # 0–100
    status = models.CharField(
        max_length=16, choices=RouteStatus.choices, default=RouteStatus.GOOD
    )
    confidence = models.CharField(
        max_length=16, choices=LocationConfidence.choices, default=LocationConfidence.MEDIUM
    )
    warnings = models.JSONField(default=list)
    target_snapshot = models.IntegerField(null=True, blank=True)  # CD schools/day at build time

    class Meta:
        db_table = "daily_visit_route_batch"
        constraints = [
            models.UniqueConstraint(
                fields=["responsible_user", "visit_date"],
                name="uniq_daily_visit_route_batch_user_date",
            ),
        ]
        indexes = [
            models.Index(fields=["visit_date"]),
            models.Index(fields=["responsible_user"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"RouteBatch({self.responsible_user}, {self.visit_date}, {self.status})"


class RouteValidationIssue(TimeStampedModel):
    """One rule violation / data problem detected on a route batch."""

    id = CuidField()
    batch = models.ForeignKey(
        DailyVisitRouteBatch, on_delete=models.CASCADE, related_name="issues"
    )
    code = models.CharField(max_length=64)  # e.g. mixed_district_types
    severity = models.CharField(max_length=16, default="warning")  # info|warning|blocking
    message = models.CharField(max_length=512)

    class Meta:
        db_table = "route_validation_issue"
        indexes = [models.Index(fields=["code"])]


class RouteRecommendation(TimeStampedModel):
    """One engine suggestion attached to a route batch (swap an outlier
    school, add nearby schools to reach the CD target, split the day...)."""

    id = CuidField()
    batch = models.ForeignKey(
        DailyVisitRouteBatch, on_delete=models.CASCADE, related_name="recommendations"
    )
    kind = models.CharField(max_length=32)  # swap | add | split | reduce
    message = models.CharField(max_length=512)
    school_ids = models.JSONField(default=list)  # schools the suggestion refers to

    class Meta:
        db_table = "route_recommendation"


__all__ = [
    "SchoolGeoPoint",
    "SchoolLocationConfidence",
    "DailyVisitRouteBatch",
    "RouteValidationIssue",
    "RouteRecommendation",
    "LocationSource",
    "LocationConfidence",
    "RouteStatus",
]
