"""Exports prepared in the background (apps.reports.export_jobs)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class ExportJob(TimeStampedModel):
    """One export a person asked for, built by the scheduler worker as them.

    ``path`` is the export's own address with its query, exactly as the
    export drawer would have downloaded it; the worker answers it through the
    export's own view, so the file is the one a direct download gives. The
    file is kept for ``export_jobs.KEEP_FOR`` and then removed.
    """

    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    STATUS_CHOICES = [
        (PENDING, "Waiting"),
        (RUNNING, "Preparing"),
        (READY, "Ready"),
        (FAILED, "Failed"),
    ]

    id = CuidField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="export_jobs"
    )
    path = models.CharField(max_length=4000)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # When the person's drawer last asked how it was going: a file that is
    # ready long after they stopped asking is announced by a notification.
    last_polled_at = models.DateTimeField(null=True, blank=True)
    file = models.FileField(upload_to="exports/", max_length=512, blank=True)
    filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=128, blank=True)
    size = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        db_table = "export_job"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.path} ({self.status})"
