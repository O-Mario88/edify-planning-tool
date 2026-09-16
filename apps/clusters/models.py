"""
Clusters models — groups of schools by sub-county.

Ports of Cluster, ClusterSubCounty (multi-sub-county coverage join),
SchoolClusterAssignment (school↔cluster). A cluster covers ONE OR MORE
sub-counties; eligibility is computed against this set.
"""

from __future__ import annotations

from django.db import models

from apps.core.enums import ClusterRecordStatus, ClusterType
from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class Cluster(SoftDeleteModel):
    """A cluster of schools (typically within a sub-county)."""

    id = CuidField()
    name = models.CharField(max_length=255)
    region = models.ForeignKey(
        "geography.Region", on_delete=models.RESTRICT, related_name="clusters"
    )
    district = models.ForeignKey(
        "geography.District", on_delete=models.RESTRICT, related_name="clusters"
    )
    # PRIMARY sub-county (first selected); display + back-compat.
    sub_county = models.ForeignKey(
        "geography.SubCounty",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clusters",
    )
    sub_county_name = models.CharField(
        max_length=255, null=True, blank=True
    )  # display fallback
    cluster_type = models.CharField(
        max_length=16, choices=ClusterType.choices, default=ClusterType.MIXED
    )
    status = models.CharField(
        max_length=32,
        choices=ClusterRecordStatus.choices,
        default=ClusterRecordStatus.ACTIVE,
    )
    override_reason = models.CharField(max_length=512, null=True, blank=True)
    responsible_staff_id = models.CharField(max_length=30, null=True, blank=True)
    cluster_leader_name = models.CharField(max_length=255, null=True, blank=True)
    cluster_leader_phone = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "cluster"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["district"]),
            models.Index(fields=["sub_county"]),
        ]

    def __str__(self) -> str:
        return self.name


class ClusterSubCounty(TimeStampedModel):
    """Join: the set of sub-counties a cluster covers (multi-sub-county support)."""

    id = CuidField()
    cluster = models.ForeignKey(
        Cluster, on_delete=models.CASCADE, related_name="covered_sub_counties"
    )
    sub_county = models.ForeignKey(
        "geography.SubCounty", on_delete=models.CASCADE, related_name="cluster_coverage"
    )

    class Meta:
        db_table = "cluster_sub_county"
        constraints = [
            models.UniqueConstraint(
                fields=["cluster", "sub_county"], name="uniq_cluster_subcounty"
            ),
        ]
        indexes = [models.Index(fields=["sub_county"])]


class SchoolClusterAssignment(TimeStampedModel):
    """Join: school ↔ cluster."""

    id = CuidField()
    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="cluster_assignments"
    )
    cluster = models.ForeignKey(
        Cluster, on_delete=models.CASCADE, related_name="assignments"
    )
    assigned_by = models.CharField(max_length=30)  # userId

    class Meta:
        db_table = "school_cluster_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "cluster"], name="uniq_school_cluster"
            ),
        ]


class CatchmentRelationship(models.TextChoices):
    PRIMARY = "primary", "Primary district"
    NEIGHBOURING = "neighbouring", "Approved neighbouring district"


class ClusterServiceDistrict(TimeStampedModel):
    """A district a cluster serves — its governed catchment (owner, 2026-09-15).

    Every cluster serves its own district (the PRIMARY row). A cluster that
    legitimately serves border communities may also serve specifically
    approved NEIGHBOURING districts, each with a reason and an effective
    window. A school may join a cluster only when its canonical district is in
    the cluster's active catchment on the day it joins; its own geography is
    never changed by joining.

    Rows are never deleted: ending a relationship sets ``active = False`` and
    ``effective_to``, so why a school once joined across a border stays
    answerable.
    """

    id = CuidField()
    cluster = models.ForeignKey(
        Cluster, on_delete=models.CASCADE, related_name="service_districts"
    )
    district = models.ForeignKey(
        "geography.District",
        on_delete=models.RESTRICT,
        related_name="cluster_catchments",
    )
    relationship_type = models.CharField(
        max_length=16,
        choices=CatchmentRelationship.choices,
        default=CatchmentRelationship.PRIMARY,
    )
    reason = models.TextField(blank=True, default="")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_by = models.CharField(max_length=30, blank=True, default="")
    approved_by = models.CharField(max_length=30, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.CharField(max_length=30, blank=True, default="")
    ended_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "cluster_service_district"
        ordering = ["relationship_type", "effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["cluster", "district"],
                condition=models.Q(active=True),
                name="uniq_active_cluster_service_district",
            ),
            models.UniqueConstraint(
                fields=["cluster"],
                condition=models.Q(active=True, relationship_type="primary"),
                name="uniq_active_primary_cluster_district",
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="cluster_catchment_dates_ordered",
            ),
        ]
        indexes = [models.Index(fields=["district", "active"])]

    def __str__(self) -> str:
        return f"{self.cluster_id} serves {self.district_id} ({self.relationship_type})"


class SchoolClusterMembership(TimeStampedModel):
    """The history of a school's cluster memberships (owner, 2026-09-15).

    ``School.cluster_id`` stays the canonical *current* membership that scope,
    planning and analytics read, and ``SchoolClusterAssignment`` its
    projection. This table is the record of how it got there: every join,
    change and removal opens or closes a row with who did it, why and when. At
    most one row per school is open, which is the database's own statement of
    "one active cluster".
    """

    id = CuidField()
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="cluster_membership_history",
    )
    cluster = models.ForeignKey(
        Cluster, on_delete=models.CASCADE, related_name="membership_history"
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    started_by = models.CharField(max_length=30, blank=True, default="")
    started_by_role = models.CharField(max_length=64, blank=True, default="")
    ended_by = models.CharField(max_length=30, blank=True, default="")
    start_reason = models.TextField(blank=True, default="")
    end_reason = models.TextField(blank=True, default="")
    # Snapshots at the moment of joining; the school's and cluster's districts
    # may change later and this row must still say what was true.
    school_district = models.ForeignKey(
        "geography.District",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    cluster_district = models.ForeignKey(
        "geography.District",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    relationship_type = models.CharField(max_length=16, blank=True, default="")
    catchment = models.ForeignKey(
        ClusterServiceDistrict,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memberships",
    )
    correlation_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "school_cluster_membership"
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["school"],
                condition=models.Q(ended_at__isnull=True),
                name="uniq_open_school_cluster_membership",
            )
        ]
        indexes = [models.Index(fields=["cluster", "ended_at"])]

    @property
    def is_cross_district(self) -> bool:
        return bool(
            self.school_district_id
            and self.cluster_district_id
            and self.school_district_id != self.cluster_district_id
        )


__all__ = [
    "CatchmentRelationship",
    "Cluster",
    "ClusterServiceDistrict",
    "ClusterSubCounty",
    "SchoolClusterAssignment",
    "SchoolClusterMembership",
]
