"""
Geography models — the Uganda admin hierarchy (Region → District → SubCounty →
Parish → Village), plus SubRegion (an organizational mapping layer, NOT COD-AB),
GeographyAlias (tolerant matching), and BoundaryImportRun (provenance audit).

Ports of the legacy Prisma geography models. COD-AB pcodes/sources/confidence
are preserved on the boundary tables.

Note: legacy Prisma used "plain ref" string columns (e.g. District.regionId). We
promote these to real ForeignKeys here — Django auto-creates the `<fk>_id`
column with the same DB name, so the schema stays compatible. ForeignKey fields
are named without the `_id` suffix to avoid Django's E006 clash.
"""
from __future__ import annotations

from django.db import models

from apps.core.enums import DistrictType
from apps.core.models import CuidField, TimeStampedModel


class Region(TimeStampedModel):
    """Ugandan region (admin1). COD-AB pcode e.g. 'UG3'."""

    id = CuidField()
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=64, null=True, blank=True, unique=True)
    pcode = models.CharField(max_length=64, null=True, blank=True, unique=True)
    source = models.CharField(max_length=255, null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "region"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SubRegion(TimeStampedModel):
    """Organizational mapping layer (NOT COD-AB)."""

    id = CuidField()
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name="sub_regions")
    name = models.CharField(max_length=255, unique=True)
    normalized_name = models.CharField(max_length=255)
    source = models.CharField(max_length=64, default="CONTROLLED")
    confidence = models.CharField(max_length=64, default="REVIEW_REQUIRED")
    verified_by = models.CharField(max_length=255, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "sub_region"


class District(TimeStampedModel):
    """Ugandan district (admin2)."""

    id = CuidField()
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=64, null=True, blank=True, unique=True)
    pcode = models.CharField(max_length=64, null=True, blank=True, unique=True)
    source = models.CharField(max_length=255, null=True, blank=True)
    region = models.ForeignKey(Region, on_delete=models.RESTRICT, related_name="districts")
    sub_region = models.ForeignKey(
        SubRegion, on_delete=models.SET_NULL, null=True, blank=True, related_name="districts"
    )
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    # Nullable, no default: classifying primary vs. secondary is a manual CD/Admin
    # data-entry step (not derivable from any existing field), required for
    # Daily Visit Batch costing/scheduling validation.
    district_type = models.CharField(
        max_length=16, choices=DistrictType.choices, null=True, blank=True
    )

    class Meta:
        db_table = "district"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["region", "name"], name="uniq_district_region_name"),
        ]

    def __str__(self) -> str:
        return self.name


class County(TimeStampedModel):
    """Ugandan county (admin3)."""

    id = CuidField()
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name="counties")
    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255)
    pcode = models.CharField(max_length=64, null=True, blank=True, unique=True)
    source = models.CharField(max_length=255, null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "county"
        constraints = [
            models.UniqueConstraint(fields=["district", "name"], name="uniq_county_district_name"),
        ]


class SubCounty(TimeStampedModel):
    """Ugandan sub-county (admin3/4 depending on dataset)."""

    id = CuidField()
    name = models.CharField(max_length=255)
    seeded = models.BooleanField(default=False)
    pcode = models.CharField(max_length=64, null=True, blank=True, unique=True)
    source = models.CharField(max_length=255, null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name="sub_counties")
    county = models.ForeignKey(
        County, on_delete=models.SET_NULL, null=True, blank=True, related_name="sub_counties"
    )

    class Meta:
        db_table = "sub_county"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["district", "name"], name="uniq_subcounty_district_name"),
        ]

    def __str__(self) -> str:
        return self.name


class Parish(TimeStampedModel):
    """Ugandan parish (admin4)."""

    id = CuidField()
    name = models.CharField(max_length=255)
    pcode = models.CharField(max_length=64, null=True, blank=True, unique=True)
    source = models.CharField(max_length=255, null=True, blank=True)
    confidence = models.CharField(max_length=64, null=True, blank=True)
    sub_county = models.ForeignKey(SubCounty, on_delete=models.CASCADE, related_name="parishes")

    class Meta:
        db_table = "parish"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["sub_county", "name"], name="uniq_parish_subcounty_name"),
        ]


class Village(TimeStampedModel):
    """Ugandan village (admin5) — the leaf."""

    id = CuidField()
    name = models.CharField(max_length=255)
    parish = models.ForeignKey(Parish, on_delete=models.CASCADE, related_name="villages")
    source = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "village"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["parish", "name"], name="uniq_village_parish_name"),
        ]
        indexes = [models.Index(fields=["parish"])]


class SecondaryDistrictGroupStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    INACTIVE = "inactive", "Inactive"


class SecondaryDistrictGroup(TimeStampedModel):
    """CD/Admin-approved group of nearby secondary districts that may be
    combined in one staff member's same-day Daily Visit Batch (e.g. a
    "Kitgum Secondary Route" covering Lamwo/Pader/Agago). Only groups with
    status=APPROVED count for same-day scheduling validation."""

    id = CuidField()
    name = models.CharField(max_length=255, unique=True)
    status = models.CharField(
        max_length=16, choices=SecondaryDistrictGroupStatus.choices,
        default=SecondaryDistrictGroupStatus.DRAFT,
    )
    approved_by = models.CharField(max_length=30, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "secondary_district_group"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SecondaryDistrictGroupMember(TimeStampedModel):
    """Join: the set of districts a SecondaryDistrictGroup covers."""

    id = CuidField()
    group = models.ForeignKey(SecondaryDistrictGroup, on_delete=models.CASCADE, related_name="members")
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name="secondary_group_memberships")

    class Meta:
        db_table = "secondary_district_group_member"
        constraints = [
            models.UniqueConstraint(fields=["group", "district"], name="uniq_secondary_group_district"),
        ]
        indexes = [models.Index(fields=["district"])]


class GeographyAlias(TimeStampedModel):
    """Tolerant matching aliases for free-text uploads."""

    id = CuidField()
    admin_level = models.CharField(max_length=64)
    admin_id = models.CharField(max_length=30)
    alias = models.CharField(max_length=255)
    normalized_alias = models.CharField(max_length=255)
    source = models.CharField(max_length=255, null=True, blank=True)
    confidence = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "geography_alias"
        constraints = [
            models.UniqueConstraint(fields=["admin_level", "normalized_alias"], name="uniq_geoalias_level_norm"),
        ]
        indexes = [models.Index(fields=["admin_level", "admin_id"])]


class BoundaryImportRun(TimeStampedModel):
    """Provenance audit for boundary imports."""

    id = CuidField()
    source_name = models.CharField(max_length=255)
    source_url = models.CharField(max_length=1024, null=True, blank=True)
    source_last_modified = models.CharField(max_length=255, null=True, blank=True)
    imported_at = models.DateTimeField()
    imported_by = models.CharField(max_length=255, null=True, blank=True)
    level_counts = models.JSONField(default=dict)
    checksum = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=64)
    errors = models.JSONField(null=True, blank=True)
    warnings = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "boundary_import_run"


__all__ = [
    "Region",
    "SubRegion",
    "District",
    "County",
    "SubCounty",
    "Parish",
    "Village",
    "GeographyAlias",
    "BoundaryImportRun",
    "SecondaryDistrictGroupStatus",
    "SecondaryDistrictGroup",
    "SecondaryDistrictGroupMember",
]
