"""Scheduled work for the Document Library.

Each function is idempotent and safe to re-run: they are registered in
apps.realtime.registry and executed through `run_tracked_job`, which supplies
the lock, the retry and the System Health visibility.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

#: Reminder cadence, in days before the due date. A day appears once, so the
#: same condition never produces two messages on one day.
REMINDER_DAYS_BEFORE = (7, 3, 1, 0)


def activate_effective_documents() -> int:
    """Move published documents to Effective once their date arrives."""
    from apps.documents.models import DocumentAsset, DocumentStatus

    today = timezone.localdate()
    count = 0
    for document in DocumentAsset.objects.filter(
        status=DocumentStatus.PUBLISHED, current_version__isnull=False
    ).select_related("current_version"):
        effective = document.current_version.effective_date
        if effective and effective <= today:
            document.status = DocumentStatus.EFFECTIVE
            document.save(update_fields=["status", "updated_at"])
            count += 1
    return count


def expire_documents() -> int:
    """Mark a document expired once its version's expiry date has passed."""
    from apps.documents.models import DocumentAsset, DocumentStatus, READABLE_STATUSES

    today = timezone.localdate()
    count = 0
    for document in DocumentAsset.objects.filter(
        status__in=READABLE_STATUSES, current_version__isnull=False
    ).select_related("current_version"):
        expiry = document.current_version.expiry_date
        if expiry and expiry < today:
            document.status = DocumentStatus.EXPIRED
            document.save(update_fields=["status", "updated_at"])
            count += 1
    return count


def retry_failed_previews(limit: int = 20) -> int:
    """Give failed conversions another chance.

    Conversion depends on a converter being installed and responsive, so a
    failure is often about the host at that moment rather than the file.
    """
    from apps.documents.models import DocumentVersion, PreviewStatus
    from apps.documents.storage import build_preview

    retried = 0
    for version in DocumentVersion.objects.filter(
        preview_status=PreviewStatus.FAILED
    ).order_by("-created_at")[:limit]:
        version.preview_status = PreviewStatus.PENDING
        version.preview_uri = ""
        version.save(update_fields=["preview_status", "preview_uri", "updated_at"])
        build_preview(version)
        retried += 1
    return retried


def send_acknowledgement_reminders() -> int:
    """Remind people whose response is due — once per condition per day.

    Deduplicated on `last_reminded_at`: a job that runs twice in a day, or a
    person who matches two cadence steps at once, still receives one message.
    """
    from apps.documents.models import AcknowledgementState, DocumentAcknowledgement
    from apps.notifications.services import WorkflowNotificationService

    today = timezone.localdate()
    now = timezone.now()
    sent = 0

    pending = DocumentAcknowledgement.objects.filter(
        state=AcknowledgementState.PENDING, due_date__isnull=False
    ).select_related("document")

    for ack in pending:
        days_left = (ack.due_date - today).days
        overdue = days_left < 0
        if not overdue and days_left not in REMINDER_DAYS_BEFORE:
            continue
        # Compare in the same timezone the rest of this function works in.
        # `last_reminded_at` is stored UTC-aware, so `.date()` gives the UTC
        # day while `today` is the local one -- for the hours the offset spans
        # (three, for Africa/Nairobi) they disagree, the dedupe silently fails,
        # and a person receives a second reminder for the same condition on the
        # same day. Found by the suite crossing midnight mid-run.
        if ack.last_reminded_at and timezone.localdate(ack.last_reminded_at) == today:
            continue  # already reminded today

        WorkflowNotificationService.trigger(
            event_type="documents.acknowledgement_overdue"
            if overdue
            else "documents.acknowledgement_due",
            category="policy",
            priority="high" if overdue or days_left <= 1 else "normal",
            title=(
                f"Overdue: {ack.document.title}"
                if overdue
                else f"Due {'today' if days_left == 0 else f'in {days_left} days'}: "
                f"{ack.document.title}"
            ),
            body=ack.document.acknowledgement_reason
            or "This document is waiting for your response.",
            context_type="document_acknowledgement",
            context_id=ack.id,
            recipients=[ack.user_id],
        )
        ack.reminder_count += 1
        ack.last_reminded_at = now
        ack.save(update_fields=["reminder_count", "last_reminded_at", "updated_at"])
        sent += 1
    return sent


def finalise_engagement_sessions(idle_minutes: int = 30) -> int:
    """Close viewer sessions nobody came back to.

    An unfinalised session is one the reader may still be in; closing it after
    a long gap keeps the roll-up honest without inventing an end time.
    """
    from apps.documents.models import DocumentEngagementSession

    cutoff = timezone.now() - timedelta(minutes=idle_minutes)
    return DocumentEngagementSession.objects.filter(
        finalised=False, last_heartbeat_at__lt=cutoff
    ).update(finalised=True, updated_at=timezone.now())
