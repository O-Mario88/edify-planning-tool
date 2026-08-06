"""ScheduledJobExecution / ScheduledJobLock — the persistent record of every
periodic job run, and the distributed lock that keeps the same job from
running twice concurrently (two scheduler processes, or a slow run
overlapping the next trigger).

This is what SchedulerHealthService (apps/realtime/registry.py) and System
Health read to answer "is background automation actually alive" instead of
trusting the presence of a scheduler process alone.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class ScheduledJobExecution(TimeStampedModel):
    """One row per job run attempt. Append-only history; SchedulerHealthService
    reads the latest row per job_name for health state."""

    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    id = CuidField()
    job_name = models.CharField(max_length=64, db_index=True)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="running")
    duration_seconds = models.FloatField(null=True, blank=True)
    records_processed = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    # Which process ran this (hostname:pid) -- lets System Health surface
    # "two different processes both think they own this job" as a defect.
    runner = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "scheduled_job_execution"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["job_name", "-started_at"]),
            models.Index(fields=["status", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.job_name} @ {self.started_at} ({self.status})"


class ScheduledJobLock(TimeStampedModel):
    """A DB-backed mutual-exclusion lock, one row per job_name. Acquired via
    an atomic conditional UPDATE (compare-and-swap on locked_until), so it
    works correctly even if two scheduler processes exist (the failure mode
    this whole system is designed to make survivable, not just avoid)."""

    job_name = models.CharField(max_length=64, primary_key=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "scheduled_job_lock"

    def __str__(self) -> str:
        return f"lock:{self.job_name}"
