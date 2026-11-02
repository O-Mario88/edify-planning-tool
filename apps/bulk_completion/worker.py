"""Large uploads are completed by the scheduler worker, not the request.

A web request is cut off after a minute (Procfile, WEB_TIMEOUT_SECONDS), and
a file of hundreds of lines takes longer than that to complete line by line.
So a confirmed batch with more than ``INLINE_LINES`` ready lines is queued;
the scheduler's every-minute job completes it as the person who confirmed
it, a stretch at a time, and tells them when it is done. The same pattern as
exports prepared in the background (apps.reports.export_jobs).

Where no worker is running (a laptop, the test suite, a stopped scheduler)
the batch is completed in the request that confirmed it, as before.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.utils import timezone

from .models import BatchStatus, BulkCompletionBatch

logger = logging.getLogger(__name__)

#: The scheduler job that completes queued batches (apps.realtime.registry).
JOB_NAME = "bulk_completion"
#: Ready lines a confirm completes at once, inside its own request.
INLINE_LINES = 40
#: A worker that ran this recently is taken to be alive.
WORKER_FRESH = timedelta(minutes=3)


def worker_is_running() -> bool:
    from apps.realtime.models import ScheduledJobExecution

    return ScheduledJobExecution.objects.filter(
        job_name=JOB_NAME,
        status__in=("success", "running"),
        started_at__gte=timezone.now() - WORKER_FRESH,
    ).exists()


def queue(batch: BulkCompletionBatch, principal) -> bool:
    """Hand a confirmed batch to the worker. False when it was not staged."""
    return bool(
        BulkCompletionBatch.objects.filter(
            pk=batch.pk, status=BatchStatus.STAGED
        ).update(
            status=BatchStatus.QUEUED,
            applied_by=str(getattr(principal, "user_id", "") or principal.id),
            updated_at=timezone.now(),
        )
    )


def _announce(batch: BulkCompletionBatch, user) -> None:
    from apps.notifications.services import WorkflowNotificationService

    from .report import summary

    counts = summary(batch)
    try:
        WorkflowNotificationService.trigger(
            event_type="bulk_completion_finished",
            category="activity",
            priority="normal",
            title="Bulk upload completed",
            body=(
                f"{batch.file_name}: {counts['completed']} completed, "
                f"{counts['skipped'] + counts['duplicates']} skipped, "
                f"{counts['review'] + counts['invalid'] + counts['failed']} not "
                "completed."
            ),
            context_type="bulk_completion_batch",
            context_id=batch.id,
            recipients=[user],
        )
    except Exception:  # noqa: BLE001 - the completions stand without the notice
        logger.warning("bulk completion notice failed", exc_info=True)


def work(seconds: float = 50) -> int:
    """Complete queued batches, oldest first, for up to ``seconds``."""
    from apps.accounts.models import User

    from .apply import apply_batch

    deadline = time.monotonic() + seconds
    finished = 0
    for batch in BulkCompletionBatch.objects.filter(status=BatchStatus.QUEUED).order_by(
        "updated_at"
    ):
        if time.monotonic() > deadline:
            break
        user = User.objects.filter(pk=batch.applied_by or batch.uploaded_by).first()
        if user is None:
            logger.warning("bulk completion %s has no user to act as", batch.pk)
            continue
        batch = apply_batch(batch, user, deadline=deadline)
        if batch.status == BatchStatus.APPLIED:
            _announce(batch, user)
            finished += 1
    return finished
