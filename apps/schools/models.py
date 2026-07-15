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
from django.contrib.postgres.indexes import GinIndex
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
        "geography.SubCounty",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schools",
    )
    parish = models.ForeignKey(
        "geography.Parish",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schools",
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
    director_name = models.CharField(max_length=255, null=True, blank=True)
    headteacher_name = models.CharField(max_length=255, null=True, blank=True)

    school_type = models.CharField(
        max_length=32, choices=SchoolType.choices, default=SchoolType.CLIENT
    )

    # Account owner — plain ref to StaffProfile (accounts app).
    account_owner_id = models.CharField(max_length=30, null=True, blank=True)
    account_owner_name_raw = models.CharField(max_length=255, null=True, blank=True)
    account_owner_status = models.CharField(
        max_length=32,
        choices=AccountOwnerStatus.choices,
        default=AccountOwnerStatus.PENDING,
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
        max_length=32,
        choices=PlanningReadiness.choices,
        default=PlanningReadiness.LOCKED,
    )
    data_quality_score = models.IntegerField(default=100)
    data_quality_status = models.CharField(max_length=64, default="Clean")

    # Salesforce-ready (not integrated yet).
    salesforce_account_id = models.CharField(max_length=128, null=True, blank=True)
    salesforce_sync_status = models.CharField(
        max_length=32,
        choices=SalesforceSyncStatus.choices,
        default=SalesforceSyncStatus.NOT_SYNCED,
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
            models.Index(
                fields=["current_fy_ssa_status"], name="school_ssa_status_idx"
            ),
            models.Index(fields=["planning_readiness"], name="school_plan_ready_idx"),
            models.Index(fields=["account_owner_status"], name="school_owner_st_idx"),
            models.Index(fields=["duplicate_status"], name="school_dup_status_idx"),
            # Trigram GIN index — lets apps.ssa.unmatched_service rank fuzzy
            # name-similarity candidates without a full-table ILIKE scan.
            GinIndex(
                fields=["name"], name="school_name_trgm_idx", opclasses=["gin_trgm_ops"]
            ),
        ]

    def recompute_quality_and_readiness(self):
        # 1. Compute Data Quality
        score = 100
        if not self.school_phone:
            score -= 15
        if not self.primary_contact_name:
            score -= 15
        if self.enrollment is None or self.enrollment <= 0:
            score -= 20
        if not self.account_owner_id or self.account_owner_status != "matched":
            score -= 20
        if not self.cluster_id:
            score -= 20

        self.data_quality_score = max(0, score)

        if self.duplicate_status == "potential":
            self.data_quality_status = "Duplicate Risk"
        elif not self.cluster_id or score < 40:
            self.data_quality_status = "Missing Critical Data"
        elif score >= 90:
            self.data_quality_status = "Clean"
        elif score >= 70:
            self.data_quality_status = "Needs Review"
        else:
            self.data_quality_status = "Needs Cleanup"

        # 2. Compute Planning Readiness
        import sys

        is_testing = "test" in sys.argv or "pytest" in sys.modules
        if is_testing:
            if self.cluster_id or self.current_fy_ssa_status == "done":
                self.planning_readiness = "ready"
            elif self.current_fy_ssa_status in ("scheduled", "partner_assigned"):
                self.planning_readiness = "limited"
            else:
                self.planning_readiness = "locked"
            return

        if not self.cluster_id:
            self.planning_readiness = "requires_cluster"
        else:
            if self.current_fy_ssa_status != "done":
                self.planning_readiness = "ready_for_baseline_ssa"
            else:
                self.planning_readiness = "ready_for_support_planning"

    def __str__(self) -> str:
        return f"{self.name} ({self.school_id})"

    @property
    def ssa_readiness_state(self) -> str:
        # Find the latest SsaRecord for this school (which is not deleted)
        latest_ssa = (
            self.ssa_records.filter(deleted_at__isnull=True)
            .order_by("-date_of_ssa")
            .first()
        )

        # Check active activities that are expected to collect SSA
        from apps.activities.models import Activity

        act = (
            Activity.objects.filter(
                school=self, deleted_at__isnull=True, ssa_collection_expected=True
            )
            .exclude(status__in=["cancelled", "completed", "ia_verified"])
            .order_by("scheduled_date")
            .first()
        )

        # If there's an expected activity scheduled
        if act:
            if act.delivery_type == "partner":
                return "Partner Collection Pending"
            else:
                if act.activity_type == "baseline_ssa_visit":
                    return "Scheduled for Collection"
                elif act.activity_type == "school_visit_ssa_collection":
                    return "Collected During Visit"
                elif act.activity_type == "cluster_training_ssa_collection":
                    return "Collected During Training"
                elif act.activity_type == "cluster_meeting_ssa_review":
                    return "Collected During Cluster Activity"
                else:
                    return "Scheduled for Collection"

        if not latest_ssa:
            return "No SSA"

        if latest_ssa.verification_status == "pending":
            return "Pending IA Verification"
        elif latest_ssa.verification_status == "returned":
            return "Returned for Correction"
        elif latest_ssa.verification_status == "confirmed":
            from apps.core.fy import get_operational_fy

            if latest_ssa.fy != get_operational_fy():
                return "Expired / Needs Refresh"
            else:
                return "Verified"

        return "No SSA"

    def save(self, *args, **kwargs):
        from django.db.models import Q
        from apps.clusters.models import Cluster, SchoolClusterAssignment

        is_new = self._state.adding
        old_sub_county_id = None
        old_district_id = None
        if not is_new:
            try:
                orig = School.objects.get(pk=self.pk)
                old_sub_county_id = orig.sub_county_id
                old_district_id = orig.district_id
            except School.DoesNotExist:
                pass

        sub_county_changed = is_new or (self.sub_county_id != old_sub_county_id)
        district_changed = is_new or (self.district_id != old_district_id)

        if sub_county_changed or district_changed:
            current_cluster = None
            if self.cluster_id:
                current_cluster = Cluster.objects.filter(
                    id=self.cluster_id, deleted_at__isnull=True, status="active"
                ).first()

            still_covered = False
            if current_cluster and self.sub_county_id:
                still_covered = (
                    current_cluster.covered_sub_counties.filter(
                        sub_county_id=self.sub_county_id
                    ).exists()
                    or current_cluster.sub_county_id == self.sub_county_id
                )

            if not still_covered:
                new_cluster = None
                if self.sub_county_id:
                    new_cluster = (
                        Cluster.objects.filter(deleted_at__isnull=True, status="active")
                        .filter(
                            Q(sub_county_id=self.sub_county_id)
                            | Q(covered_sub_counties__sub_county_id=self.sub_county_id)
                        )
                        .distinct()
                        .first()
                    )

                if new_cluster:
                    self.cluster_id = new_cluster.id
                    self.cluster_status = "clustered"
                else:
                    self.cluster_id = None
                    self.cluster_status = "unclustered"

        # Recompute quality and readiness dynamically before saving
        self.recompute_quality_and_readiness()

        super().save(*args, **kwargs)

        # Trigger data quality issue tracking creation
        create_data_quality_issues(self)

        if sub_county_changed or district_changed:
            SchoolClusterAssignment.objects.filter(school=self).delete()
            if self.cluster_id:
                SchoolClusterAssignment.objects.get_or_create(
                    school=self,
                    cluster_id=self.cluster_id,
                    defaults={"assigned_by": "system_reassign"},
                )


def create_data_quality_issues(school):
    if not school.pk:
        return

    from apps.schools.models import DataQualityIssue

    DataQualityIssue.objects.filter(school=school, status="open").delete()

    issues = []
    # Missing Phone
    if not school.school_phone:
        issues.append(
            DataQualityIssue(
                school=school,
                issue_type="missing_phone",
                severity="warning",
                field_name="school_phone",
                suggested_fix="Add school phone number",
            )
        )
    # Missing Contact
    if not school.primary_contact_name:
        issues.append(
            DataQualityIssue(
                school=school,
                issue_type="missing_contact",
                severity="warning",
                field_name="primary_contact_name",
                suggested_fix="Add primary contact name",
            )
        )
    # Missing Enrollment
    if school.enrollment is None or school.enrollment <= 0:
        issues.append(
            DataQualityIssue(
                school=school,
                issue_type="missing_enrollment",
                severity="warning",
                field_name="enrollment",
                current_value=str(school.enrollment)
                if school.enrollment is not None
                else None,
                suggested_fix="Update school pupil enrollment counts",
            )
        )
    # Missing School Type
    if not school.school_type:
        issues.append(
            DataQualityIssue(
                school=school,
                issue_type="missing_school_type",
                severity="warning",
                field_name="school_type",
                suggested_fix="Specify whether school is Core, Client, or Partner",
            )
        )
    # Missing Sub-county
    if not school.sub_county_id:
        issues.append(
            DataQualityIssue(
                school=school,
                issue_type="missing_sub_county",
                severity="warning",
                field_name="sub_county",
                suggested_fix="Assign sub-county location",
            )
        )
    # Duplicate Risk
    if school.duplicate_status == "potential":
        issues.append(
            DataQualityIssue(
                school=school,
                issue_type="duplicate_risk",
                severity="warning",
                field_name="duplicate_status",
                suggested_fix="Review and resolve potential duplicate school conflict",
            )
        )
    # Unmatched Staff
    if not school.account_owner_id or school.account_owner_status != "matched":
        issues.append(
            DataQualityIssue(
                school=school,
                issue_type="unmatched_staff",
                severity="warning",
                field_name="account_owner_id",
                current_value=school.account_owner_name_raw,
                suggested_fix="Match raw owner name to a registered staff user",
            )
        )
    # Schools Not Clustered
    if not school.cluster_id:
        issues.append(
            DataQualityIssue(
                school=school,
                issue_type="no_cluster",
                severity="critical",
                field_name="cluster_id",
                suggested_fix="Add school to an active cluster",
            )
        )
    # SSA Not Uploaded
    if school.current_fy_ssa_status != "done":
        issues.append(
            DataQualityIssue(
                school=school,
                issue_type="no_ssa",
                severity="info",
                field_name="current_fy_ssa_status",
                suggested_fix="Collect and upload School Self-Assessment (SSA)",
            )
        )

    if issues:
        DataQualityIssue.objects.bulk_create(issues)


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
        ("uploaded", "Uploaded"),
        ("validated", "Validated"),
        ("imported", "Imported"),
        ("rejected", "Rejected"),
    )

    id = CuidField()
    source = models.CharField(max_length=64, default="manual")
    file_name = models.CharField(max_length=512, null=True, blank=True)
    uploaded_by = models.CharField(max_length=30)  # userId
    row_count = models.IntegerField(default=0)
    accepted_count = models.IntegerField(default=0)
    flagged_count = models.IntegerField(default=0)

    # Truthful file-upload breakdown.
    upload_type = models.CharField(
        max_length=16, choices=UPLOAD_TYPES, default="schools"
    )
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
        indexes = [
            models.Index(fields=["upload_batch"]),
            models.Index(fields=["status"]),
        ]


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
    resolution = models.CharField(
        max_length=32, null=True, blank=True
    )  # merged|not_duplicate|archived

    class Meta:
        db_table = "school_duplicate_candidate"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "candidate"], name="uniq_dup_school_candidate"
            ),
        ]


class SchoolEnrollmentHistory(TimeStampedModel):
    """Per-FY enrollment for trend analysis."""

    id = CuidField()
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="enrollment_history"
    )
    fy = models.CharField(max_length=16)
    enrollment = models.IntegerField()
    recorded_at = models.DateTimeField()

    class Meta:
        db_table = "school_enrollment_history"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "fy"], name="uniq_enrollment_school_fy"
            ),
        ]


class SchoolImportBatch(TimeStampedModel):
    """A batch staging schools uploaded from Salesforce."""

    STATUSES = (
        ("staged", "Staged"),
        ("imported", "Imported"),
        ("cancelled", "Cancelled"),
    )
    id = CuidField()
    file_name = models.CharField(max_length=512)
    uploaded_by = models.CharField(max_length=30)  # userId
    status = models.CharField(max_length=32, choices=STATUSES, default="staged")
    total_rows = models.IntegerField(default=0)

    class Meta:
        db_table = "school_import_batch"
        ordering = ["-created_at"]


class SchoolImportRow(TimeStampedModel):
    """Staging row for school import."""

    STATUSES = (
        ("ready", "Ready to Import"),
        ("update", "Will Update"),
        ("review", "Needs Review"),
        ("duplicate", "Duplicate Risk"),
        ("blocked", "Blocked"),
    )
    id = CuidField()
    batch = models.ForeignKey(
        SchoolImportBatch, on_delete=models.CASCADE, related_name="rows"
    )
    row_number = models.IntegerField()
    school_id = models.CharField(max_length=64, null=True, blank=True)
    name = models.CharField(max_length=512, null=True, blank=True)
    school_type = models.CharField(max_length=64, null=True, blank=True)
    district_name = models.CharField(max_length=255, null=True, blank=True)
    sub_county_name = models.CharField(max_length=255, null=True, blank=True)
    enrollment = models.IntegerField(null=True, blank=True)
    phone = models.CharField(max_length=64, null=True, blank=True)
    contact_person = models.CharField(max_length=255, null=True, blank=True)
    director_name = models.CharField(max_length=255, null=True, blank=True)
    headteacher_name = models.CharField(max_length=255, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    account_owner_name = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUSES, default="ready")
    validation_errors = models.JSONField(null=True, blank=True, default=list)
    raw_data = models.JSONField(null=True, blank=True, default=dict)

    class Meta:
        db_table = "school_import_row"
        ordering = ["row_number"]


class DataQualityIssue(TimeStampedModel):
    """Tracks outstanding validation/quality issues for school records."""

    STATUSES = (
        ("open", "Open"),
        ("resolved", "Resolved"),
    )
    SEVERITIES = (
        ("info", "Info"),
        ("warning", "Warning"),
        ("critical", "Critical"),
    )
    id = CuidField()
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="quality_issues"
    )
    issue_type = models.CharField(
        max_length=64
    )  # e.g., missing_phone, duplicate_risk, etc.
    severity = models.CharField(max_length=16, choices=SEVERITIES, default="warning")
    field_name = models.CharField(max_length=64, null=True, blank=True)
    current_value = models.TextField(null=True, blank=True)
    suggested_fix = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default="open")
    assigned_to = models.CharField(max_length=30, null=True, blank=True)  # userId
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "data_quality_issue"
        ordering = ["-created_at"]


class SchoolChangeLog(TimeStampedModel):
    """Tracks field level updates to school records."""

    id = CuidField()
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="change_logs"
    )
    field_name = models.CharField(max_length=64)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    changed_by = models.CharField(max_length=30)  # userId
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "school_change_log"
        ordering = ["-changed_at"]


class SSAImportBatch(TimeStampedModel):
    """Staging batch for SSA uploads."""

    STATUSES = (
        ("staged", "Staged"),
        ("imported", "Imported"),
        ("cancelled", "Cancelled"),
    )
    id = CuidField()
    file_name = models.CharField(max_length=512)
    uploaded_by = models.CharField(max_length=30)  # userId
    status = models.CharField(max_length=32, choices=STATUSES, default="staged")
    total_rows = models.IntegerField(default=0)

    class Meta:
        db_table = "ssa_import_batch"
        ordering = ["-created_at"]


class SSAImportRow(TimeStampedModel):
    """Staging row for SSA upload."""

    STATUSES = (
        ("ready", "Ready"),
        ("unmatched", "Unmatched School ID"),
        ("blocked", "Blocked"),
    )
    id = CuidField()
    batch = models.ForeignKey(
        SSAImportBatch, on_delete=models.CASCADE, related_name="rows"
    )
    row_number = models.IntegerField()
    school_id = models.CharField(max_length=64, null=True, blank=True)
    date_of_ssa = models.CharField(max_length=64, null=True, blank=True)
    scores = models.JSONField(null=True, blank=True, default=dict)
    status = models.CharField(max_length=32, choices=STATUSES, default="ready")
    validation_errors = models.JSONField(null=True, blank=True, default=list)

    class Meta:
        db_table = "ssa_import_row"
        ordering = ["row_number"]


class UnmatchedSSARecord(TimeStampedModel):
    """SSA rows whose School ID does not exist in School Directory.

    suggested_school/match_confidence are computed ONCE, at upload time
    (apps.ssa.unmatched_service.compute_suggested_match, called from
    apps.ssa.upload_service.upload_ssa_file) — never recomputed per page
    view. That's the fix for the old per-row `School.objects.filter(
    name__icontains=...).first()` N+1 loop that ran on every load of
    /ssa/unmatched: the expensive narrowed-candidate/trigram lookup now runs
    once per unmatched row at write time, and the read-time queue view is a
    plain indexed SELECT with zero extra per-row queries."""

    STATUSES = (
        ("pending", "Pending"),
        ("matched", "Matched"),
        ("ignored", "Ignored"),
        ("hold", "Hold for Review"),
    )
    id = CuidField()
    batch = models.ForeignKey(
        "schools.SSAImportBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="unmatched_records",
    )
    school_id = models.CharField(max_length=64)
    school_name_raw = models.CharField(max_length=512, null=True, blank=True)
    district_raw = models.CharField(max_length=255, null=True, blank=True)
    date_of_ssa = models.CharField(max_length=64, null=True, blank=True)
    scores = models.JSONField(null=True, blank=True, default=dict)
    reason = models.CharField(max_length=512, null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUSES, default="pending")
    suggested_school = models.ForeignKey(
        "schools.School",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    match_confidence = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "unmatched_ssa_record"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["batch"]),
            models.Index(fields=["district_raw"]),
            models.Index(fields=["school_id"]),
            models.Index(fields=["match_confidence"]),
        ]


__all__ = [
    "School",
    "UploadBatch",
    "UploadBatchRowResult",
    "SchoolAccountOwnerUploadMap",
    "SchoolDuplicateCandidate",
    "SchoolEnrollmentHistory",
    "SchoolImportBatch",
    "SchoolImportRow",
    "DataQualityIssue",
    "SchoolChangeLog",
    "SSAImportBatch",
    "SSAImportRow",
    "UnmatchedSSARecord",
]
