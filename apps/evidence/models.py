"""Evidence model — uploaded files for activities."""
from __future__ import annotations

from django.db import models

from apps.core.enums import EvidenceKind, EvidenceStatus
from apps.core.models import CuidField, TimeStampedModel


class EvidenceRecord(TimeStampedModel):
    """An evidence file attached to an activity (visit form, photo, PDF, …)."""

    id = CuidField()
    activity = models.ForeignKey("activities.Activity", on_delete=models.CASCADE, related_name="evidence")
    kind = models.CharField(max_length=32, choices=EvidenceKind.choices)
    uri = models.CharField(max_length=512)  # stored filename under EVIDENCE_STORAGE_DIR
    original_name = models.CharField(max_length=512, null=True, blank=True)
    mime_type = models.CharField(max_length=128, null=True, blank=True)
    file_extension = models.CharField(max_length=16, null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True)
    storage_provider = models.CharField(max_length=32, default="local")
    notes = models.TextField(null=True, blank=True)
    uploaded_by = models.CharField(max_length=30)
    uploader_role = models.CharField(max_length=32, null=True, blank=True)
    status = models.CharField(max_length=16, choices=EvidenceStatus.choices, default=EvidenceStatus.UPLOADED)
    reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=512, null=True, blank=True)
    scan_status = models.CharField(max_length=16, default="pending")  # pending|clean|infected|skipped
    quarantined = models.BooleanField(default=False)
    # Preview pipeline.
    preview_status = models.CharField(max_length=16, default="not_required")  # not_required|pending|ready|failed
    pdf_rendition_storage_key = models.CharField(max_length=512, null=True, blank=True)
    pdf_rendition_status = models.CharField(max_length=16, null=True, blank=True)
    pdf_rendition_error = models.CharField(max_length=512, null=True, blank=True)
    pdf_rendition_at = models.DateTimeField(null=True, blank=True)
    view_count = models.IntegerField(default=0)

    class Meta:
        db_table = "evidence_record"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["activity"]),
            models.Index(fields=["quarantined"]),
            models.Index(fields=["preview_status"]),
        ]


__all__ = ["EvidenceRecord"]
