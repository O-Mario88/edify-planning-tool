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


__all__ = ["Cluster", "ClusterSubCounty", "SchoolClusterAssignment"]
