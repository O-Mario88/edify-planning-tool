"""run_tracked_job — the single wrapper every periodic job runs through:
acquires a DB-backed lock (safe even if two scheduler processes somehow both
exist), records a ScheduledJobExecution row before/after, retries on
transient failure per the job's registry spec, and always releases the lock.

No job function should be invoked directly by the scheduler or a management
command without going through this — that is what makes locking, retries,
and health visibility apply uniformly instead of per-job reimplementation.
"""

from __future__ import annotations

import logging
import os
import socket
import time

from django.db.models import Q
from django.utils import timezone

from .registry import get_spec

logger = logging.getLogger("edify.jobs")


def runner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def acquire_lock(job_name: str, ttl_seconds: int) -> bool:
    """Atomic compare-and-swap lock acquire via a conditional UPDATE — safe
    under concurrent callers because the UPDATE...WHERE is a single
    statement the database serializes, not a check-then-write race."""
    from .models import ScheduledJobLock

    now = timezone.now()
    until = now + timezone.timedelta(seconds=ttl_seconds)
    ScheduledJobLock.objects.get_or_create(job_name=job_name)
    updated = (
        ScheduledJobLock.objects.filter(job_name=job_name)
        .filter(Q(locked_until__isnull=True) | Q(locked_until__lt=now))
        .update(locked_at=now, locked_until=until, locked_by=runner_id())
    )
    return updated == 1


def release_lock(job_name: str) -> None:
    from .models import ScheduledJobLock

    ScheduledJobLock.objects.filter(job_name=job_name, locked_by=runner_id()).update(
        locked_until=None, locked_by=""
    )


def run_tracked_job(job_name: str, func, retry_backoff_seconds: float = 0.0):
    """Run `func()` (no args, returns an int record-count or None) under a
    lock, with retry-on-failure per the registry spec, recording a
    ScheduledJobExecution row. Returns func()'s result, or None if the job
    was skipped (already locked) or failed after exhausting retries."""
    from .models import ScheduledJobExecution

    spec = get_spec(job_name)
    ttl = (spec.expected_runtime_seconds * 4) if spec else 600
    max_retries = spec.max_retries if (spec and spec.retryable) else 0

    if not acquire_lock(job_name, ttl_seconds=ttl):
        logger.warning(
            "Job %s is already locked by another runner -- skipping this trigger "
            "(prevents duplicate concurrent execution).",
            job_name,
        )
        return None

    execution = ScheduledJobExecution.objects.create(
        job_name=job_name,
        started_at=timezone.now(),
        status="running",
        runner=runner_id(),
    )
    attempt = 0
    try:
        while True:
            try:
                result = func()
                execution.completed_at = timezone.now()
                execution.duration_seconds = (
                    execution.completed_at - execution.started_at
                ).total_seconds()
                execution.status = "success"
                execution.records_processed = (
                    result if isinstance(result, int) else None
                )
                execution.retry_count = attempt
                execution.save(
                    update_fields=[
                        "completed_at",
                        "duration_seconds",
                        "status",
                        "records_processed",
                        "retry_count",
                        "updated_at",
                    ]
                )
                return result
            except Exception as exc:  # noqa: BLE001 — a job must never crash the scheduler process
                attempt += 1
                logger.exception("Job %s attempt %d failed: %s", job_name, attempt, exc)
                if attempt > max_retries:
                    execution.completed_at = timezone.now()
                    execution.duration_seconds = (
                        execution.completed_at - execution.started_at
                    ).total_seconds()
                    execution.status = "failed"
                    execution.error_message = str(exc)[:4000]
                    execution.retry_count = attempt - 1
                    execution.save(
                        update_fields=[
                            "completed_at",
                            "duration_seconds",
                            "status",
                            "error_message",
                            "retry_count",
                            "updated_at",
                        ]
                    )
                    return None
                if retry_backoff_seconds:
                    time.sleep(retry_backoff_seconds)
    finally:
        release_lock(job_name)
