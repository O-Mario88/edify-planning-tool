"""Bulk completion of school visits and trainings from a spreadsheet.

Owner, 2026-11-02: the Upload Center completes many visits or trainings in
one file instead of one drawer at a time. A file is staged first (every row
matched to the activity it completes and classified), shown as a preview, and
only applied when the uploader confirms. Applying runs each ready row through
the activity's own completion workflow (apps.activities.services), so nothing
here writes an activity's status: these two tables are the upload's record —
who sent which file, when, and what became of every row.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class BulkKind(models.TextChoices):
    VISIT = "visit", "School Visits"
    TRAINING = "training", "Trainings"


class BatchStatus(models.TextChoices):
    STAGED = "staged", "Awaiting confirmation"
    # Confirmed, waiting for the scheduler worker (a large file).
    QUEUED = "queued", "Queued to complete"
    APPLYING = "applying", "Completing"
    APPLIED = "applied", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class RowStatus(models.TextChoices):
    # Classified when the file is staged.
    READY = "ready", "Ready to complete"
    ALREADY_COMPLETED = "already_completed", "Already completed — skipped"
    DUPLICATE = "duplicate", "Duplicate in this file — skipped"
    MERGED = "merged", "Joined to an earlier row of the same training"
    REVIEW = "review", "Needs review"
    INVALID = "invalid", "Invalid"
    # Written when the batch is applied.
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Not completed"


#: Rows skipped on purpose: they need nothing from the uploader.
SKIPPED_STATUSES = (RowStatus.ALREADY_COMPLETED, RowStatus.DUPLICATE)
#: Rows left unprocessed because something about them must be put right.
PROBLEM_STATUSES = (RowStatus.REVIEW, RowStatus.INVALID, RowStatus.FAILED)


class BulkCompletionBatch(TimeStampedModel):
    """One uploaded file."""

    id = CuidField()
    kind = models.CharField(max_length=16, choices=BulkKind.choices)
    file_name = models.CharField(max_length=512)
    # SHA-256 of the file's bytes: a file sent again is recognised and the
    # uploader told when it was first sent. Its rows are classified afresh, so
    # work the first upload completed is skipped as already completed.
    file_sha256 = models.CharField(max_length=64, db_index=True)
    uploaded_by = models.CharField(max_length=30, db_index=True)  # User id
    uploaded_by_role = models.CharField(max_length=48, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=BatchStatus.choices, default=BatchStatus.STAGED
    )
    total_rows = models.IntegerField(default=0)
    applied_by = models.CharField(max_length=30, blank=True, default="")
    applied_at = models.DateTimeField(null=True, blank=True)
    # {status: count} once applied, so history pages read one row.
    outcome_counts = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "bulk_completion_batch"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} upload {self.file_name}"


class BulkCompletionRow(TimeStampedModel):
    """One spreadsheet line and what it does, or did, to one activity."""

    id = CuidField()
    batch = models.ForeignKey(
        BulkCompletionBatch, on_delete=models.CASCADE, related_name="rows"
    )
    row_number = models.IntegerField()  # the spreadsheet line, header = 1
    status = models.CharField(max_length=24, choices=RowStatus.choices)
    message = models.TextField(blank=True, default="")
    # The activity the row completes, once matched. A plain id rather than a
    # foreign key: the row is a historical record and must outlive the
    # activity being archived.
    activity_id = models.CharField(max_length=30, blank=True, default="")
    school_code = models.CharField(max_length=64, blank=True, default="")
    salesforce_id = models.CharField(max_length=128, blank=True, default="")
    completed_on = models.DateField(null=True, blank=True)
    teachers_attended = models.IntegerField(null=True, blank=True)
    leaders_attended = models.IntegerField(null=True, blank=True)
    # School IDs (the directory's codes) that attended a cluster or group
    # training, after the rows naming the same training were joined.
    participating_school_codes = models.JSONField(default=list, blank=True)
    # The row as uploaded, column heading -> cell, for the error report.
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "bulk_completion_row"
        ordering = ["row_number"]
        indexes = [models.Index(fields=["batch", "status"])]

    def __str__(self) -> str:
        return f"Row {self.row_number}: {self.get_status_display()}"
