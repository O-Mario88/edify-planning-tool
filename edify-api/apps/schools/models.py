"""
Schools models — the School Directory is the source of truth.

Ports of School, UploadBatch, SchoolAccountOwnerUploadMap,
SchoolDuplicateCandidate, SchoolEnrollmentHistory.

Note on relations: the legacy schema used plain-ref string columns for
subRegionId/countyId/accountOwnerId (some enforced, some not). We promote the
geography FKs (region/district/subCounty/parish) to real ForeignKeys; the
account-owner link stays a plain CharField (it references StaffProfile, which
lives in the accounts app — a real FK would create a cross-app dependency that
the legacy deliberately avoided for the audit/assignment flexibility). The
cluster FK is added once the clusters app exists.
"""
from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.enums import (
    AccountOwnerStatus,
    ClusterStatus,
    DuplicateStatus,
    PlanningReadiness,
    SchoolType,
    SalesforceSyncStatus,
    SsaStatus,
)
from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class School(SoftDeleteModel):
    """The operational source-of-truth school record."""

    id = CuidField()
    # Human/operational id used across the app — distinct from the PK.
    school_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=512)

    # Geography — enforced FKs to the geography app.
    region = models.ForeignKey(
        "geography.Region", on_delete=models.RESTRICT, related_name="schools"
    )
    district = models.ForeignKey(
        "geography.District", on_delete=models.RESTRICT, related_name="schools"
    )
    sub_county = models.ForeignKey(
        "geography.SubCounty", on_delete=models.SET_NULL, null=True, blank=True, related_name="schools"
    )
    parish = models.ForeignKey(
        "geography.Parish", on_delete=models.SET_NULL, null=True, blank=True, related_name="schools"
    )
    # Resolved official sub-region / county ids (plain refs — joined in code).
    sub_region_id = models.CharField(max_length=30, null=True, blank=True)
    county_id = models.CharField(max_length=30, null=True, blank=True)

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # ORIGINAL uploaded geography text — preserved verbatim for audit.
    uploaded_region_text = models.CharField(max_length=255, null=True, blank=True)
    uploaded_district_text = models.CharField(max_length=255, null=True, blank=True)
    uploaded_sub_county_text = models.CharField(max_length=255, null=True, blank=True)
    uploaded_parish_text = models.CharField(max_length=255, null=True, blank=True)
    geography_match_status = models.CharField(max_length=64, null=True, blank=True)
    geography_match_confidence = models.FloatField(null=True, blank=True)
    geography_match_warnings = models.JSONField(null=True, blank=True)

    shipping_address = models.CharField(max_length=512, null=True, blank=True)
    school_phone = models.CharField(max_length=64, null=True, blank=True)
    primary_contact_name = models.CharField(max_length=255, null=True, blank=True)
    primary_contact_phone = models.CharField(max_length=64, null=True, blank=True)
    enrollment = models.IntegerField(null=True, blank=True)
    # Date the enrolment figure was last captured (from the onboarding upload).
    last_enrollment_date = models.DateField(null=True, blank=True)

    school_type = models.CharField(
        max_length=32, choices=SchoolType.choices, default=SchoolType.CLIENT
    )

    # Account owner — plain ref to StaffProfile (accounts app).
    account_owner_id = models.CharField(max_length=30, null=True, blank=True)
    account_owner_name_raw = models.CharField(max_length=255, null=True, blank=True)
    account_owner_status = models.CharField(
        max_length=32, choices=AccountOwnerStatus.choices, default=AccountOwnerStatus.PENDING
    )
    duplicate_status = models.CharField(
        max_length=32, choices=DuplicateStatus.choices, default=DuplicateStatus.NONE
    )

    # Cluster — plain ref; FK added by the clusters app migration.
    cluster_id = models.CharField(max_length=30, null=True, blank=True)
    cluster_status = models.CharField(
        max_length=32, choices=ClusterStatus.choices, default=ClusterStatus.UNCLUSTERED
    )

    current_fy_ssa_status = models.CharField(
        max_length=32, choices=SsaStatus.choices, default=SsaStatus.NOT_DONE
    )
    planning_readiness = models.CharField(
        max_length=32, choices=PlanningReadiness.choices, default=PlanningReadiness.LOCKED
    )

    # Salesforce-ready (not integrated yet).
    salesforce_account_id = models.CharField(max_length=128, null=True, blank=True)
    salesforce_sync_status = models.CharField(
        max_length=32, choices=SalesforceSyncStatus.choices, default=SalesforceSyncStatus.NOT_SYNCED
    )
    salesforce_last_synced_at = models.DateTimeField(null=True, blank=True)
    salesforce_sync_error = models.CharField(max_length=512, null=True, blank=True)

    created_by_ia = models.BooleanField(default=False)
    upload_batch_id = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "school"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["region"]),
            models.Index(fields=["district"]),
            models.Index(fields=["cluster_id"]),
            models.Index(fields=["school_type"]),
            # Directory filter-bar + dashboard conditional-COUNT fields.
            models.Index(fields=["cluster_status"], name="school_cluster_st_idx"),
            models.Index(fields=["current_fy_ssa_status"], name="school_ssa_status_idx"),
            models.Index(fields=["planning_readiness"], name="school_plan_ready_idx"),
            models.Index(fields=["account_owner_status"], name="school_owner_st_idx"),
            models.Index(fields=["duplicate_status"], name="school_dup_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.school_id})"


class UploadBatch(TimeStampedModel):
    """A batch of uploads (schools / SSA; manual / csv / xlsx / future: salesforce).

    The original `row_count / accepted_count / flagged_count` columns are kept for
    back-compat with the legacy `POST /schools/bulk` flow; the file-upload endpoint
    additionally populates the truthful created/updated/skipped/failed/duplicate
    breakdown + per-row results (UploadBatchRowResult)."""

    UPLOAD_TYPES = (("schools", "Schools"), ("ssa", "SSA"))
    STATUSES = (
        ("completed", "Completed"),
        ("completed_with_errors", "Completed with errors"),
        ("failed", "Failed"),
    )

    id = CuidField()
    source = models.CharField(max_length=64, default="manual")
    file_name = models.CharField(max_length=512, null=True, blank=True)
    uploaded_by = models.CharField(max_length=30)  # userId
    row_count = models.IntegerField(default=0)
    accepted_count = models.IntegerField(default=0)
    flagged_count = models.IntegerField(default=0)

    # Truthful file-upload breakdown.
    upload_type = models.CharField(max_length=16, choices=UPLOAD_TYPES, default="schools")
    original_file_name = models.CharField(max_length=512, null=True, blank=True)
    total_rows = models.IntegerField(default=0)
    created_rows = models.IntegerField(default=0)
    updated_rows = models.IntegerField(default=0)
    skipped_rows = models.IntegerField(default=0)
    failed_rows = models.IntegerField(default=0)
    duplicate_rows = models.IntegerField(default=0)
    status = models.CharField(max_length=32, choices=STATUSES, default="completed")
    error_summary = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "upload_batch"
        ordering = ["-created_at"]


class UploadBatchRowResult(TimeStampedModel):
    """One row outcome within an UploadBatch — the per-row audit trail."""

    STATUSES = (
        ("created", "Created"),
        ("updated", "Updated"),
        ("skipped", "Skipped"),
        ("failed", "Failed"),
        ("duplicate", "Duplicate"),
    )

    id = CuidField()
    upload_batch = models.ForeignKey(
        UploadBatch, on_delete=models.CASCADE, related_name="row_results"
    )
    row_number = models.IntegerField()
    school_id = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES)
    error_message = models.TextField(null=True, blank=True)
    raw_data_json = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "upload_batch_row_result"
        ordering = ["upload_batch", "row_number"]
        indexes = [models.Index(fields=["upload_batch"]), models.Index(fields=["status"])]


class SchoolAccountOwnerUploadMap(TimeStampedModel):
    """Maps raw uploaded owner names to matched staff during bulk upload."""

    id = CuidField()
    upload_batch = models.ForeignKey(
        UploadBatch, on_delete=models.CASCADE, related_name="owner_maps"
    )
    school_id_raw = models.CharField(max_length=128)
    owner_name_raw = models.CharField(max_length=255)
    matched_staff_id = models.CharField(max_length=30, null=True, blank=True)
    matched = models.BooleanField(default=False)

    class Meta:
        db_table = "school_account_owner_upload_map"


class SchoolDuplicateCandidate(TimeStampedModel):
    """A potential duplicate pair (self-referential School ↔ School)."""

    id = CuidField()
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="duplicate_candidates"
    )
    candidate = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="duplicate_matches"
    )
    score = models.IntegerField()  # 0-100 similarity
    reasons = ArrayField(base_field=models.CharField(max_length=64), default=list)
    resolved = models.BooleanField(default=False)
    resolution = models.CharField(max_length=32, null=True, blank=True)  # merged|not_duplicate|archived

    class Meta:
        db_table = "school_duplicate_candidate"
        constraints = [
            models.UniqueConstraint(fields=["school", "candidate"], name="uniq_dup_school_candidate"),
        ]


class SchoolEnrollmentHistory(TimeStampedModel):
    """Per-FY enrollment for trend analysis."""

    id = CuidField()
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="enrollment_history")
    fy = models.CharField(max_length=16)
    enrollment = models.IntegerField()
    recorded_at = models.DateTimeField()

    class Meta:
        db_table = "school_enrollment_history"
        constraints = [
            models.UniqueConstraint(fields=["school", "fy"], name="uniq_enrollment_school_fy"),
        ]


__all__ = [
    "School",
    "UploadBatch",
    "UploadBatchRowResult",
    "SchoolAccountOwnerUploadMap",
    "SchoolDuplicateCandidate",
    "SchoolEnrollmentHistory",
]
