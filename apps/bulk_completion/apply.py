"""Apply a confirmed batch: complete each ready line through the activity's
own completion workflow.

No status is written here. Each line calls the service a drawer calls for
the same work, so every gate, count, calendar, cost move and approval route
the drawers obey is obeyed here too:

* a staff visit: its Salesforce ID is reserved and the work handed in
  (``hand_in_with_id``, the Salesforce ID drawer's path);
* a staff training: ``complete()``, with its attendance and the register of
  the schools that attended (the Complete drawer's path);
* partner work the partner has handed in with its form: Impact Assessment's
  confirmation with the Salesforce ID (``ia_confirm``).

Uploaded staff work is then approved at once: it comes from the Salesforce
export, so no Programme Lead verifies it (owner, 2026-11-02). Work completed
from a drawer still waits for its lead (owner, 2026-10-15).

Every line runs in its own transaction, so a refusal rolls back that line
alone and the rest still complete. The batch is claimed before the first
line, so confirming twice — a double click, a second tab — processes it once;
and each line asks again whether its activity is still open, so a line whose
work was completed in the meantime is skipped rather than completed twice.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest

from .models import BatchStatus, BulkCompletionBatch, BulkKind, RowStatus
from .rules import is_done, is_open, is_partner

logger = logging.getLogger(__name__)

#: What a line says once its work is completed and counted.
APPROVED = "Completed and approved."

#: A batch left "completing" this long (a worker that died mid-way) may be
#: confirmed again; the lines it already finished keep their outcome.
STALE_CLAIM = timedelta(minutes=15)


def _claim(batch_id: str) -> bool:
    now = timezone.now()
    claimed = BulkCompletionBatch.objects.filter(
        pk=batch_id, status__in=(BatchStatus.STAGED, BatchStatus.QUEUED)
    ).update(status=BatchStatus.APPLYING, updated_at=now)
    if claimed:
        return True
    return bool(
        BulkCompletionBatch.objects.filter(
            pk=batch_id,
            status=BatchStatus.APPLYING,
            updated_at__lt=now - STALE_CLAIM,
        ).update(updated_at=now)
    )


def _school_pks(codes: list[str]) -> list[str]:
    from apps.schools.models import School

    found = dict(
        School.objects.filter(school_id__in=codes, deleted_at__isnull=True).values_list(
            "school_id", "id"
        )
    )
    return [found[code] for code in codes if code in found]


def _training_register(activity, row) -> tuple[list[str], list[str] | None]:
    """(attended school pks, visiting school pks or None) for complete()."""
    if not row.participating_school_codes:
        return list(activity.attended_school_ids or []), None
    pks = _school_pks(row.participating_school_codes)
    if not activity.cluster_id:
        return pks, None
    from apps.schools.models import School

    members = set(
        School.objects.filter(cluster_id=activity.cluster_id, pk__in=pks).values_list(
            "pk", flat=True
        )
    )
    return pks, [pk for pk in pks if pk not in members]


def _complete_staff_visit(activity, row, principal) -> None:
    from apps.activities.salesforce import (
        ENTRY_SOURCE_STAFF_SELF,
        reserve_salesforce_id,
    )
    from apps.activities.services import hand_in_with_id, sf_kind_for_activity

    kind = sf_kind_for_activity(activity)
    if kind is not None:
        # Idempotent for the activity's own current ID; refused as a duplicate
        # when another live activity holds it.
        reserve_salesforce_id(
            activity=activity,
            raw_value=row.salesforce_id,
            kind=kind,
            principal=principal,
            entry_source=ENTRY_SOURCE_STAFF_SELF,
        )
    if kind is None:
        _hand_in_without_id(activity, row, principal)
        return
    if hand_in_with_id(activity.id, principal, completed_on=row.completed_on) is None:
        raise BadRequest("This visit could not be handed in.")


def _hand_in_without_id(activity, row, principal) -> None:
    """Work Salesforce keeps no record of: handed in with its date alone."""
    from apps.activities.models import Activity
    from apps.activities.services import (
        STARTABLE_STATUSES,
        start_completion,
        submit_for_review,
    )

    Activity.objects.filter(pk=activity.pk).update(
        actual_delivery_date=row.completed_on
    )
    if activity.status in STARTABLE_STATUSES:
        start_completion(activity.id, principal=principal)
    submit_for_review(activity.id, principal)


def _complete_staff_training(activity, row, principal) -> None:
    from apps.activities.services import STARTABLE_STATUSES, complete, start_completion

    if activity.status in STARTABLE_STATUSES:
        start_completion(activity.id, principal=principal)
    attended, visiting = _training_register(activity, row)
    data = {
        "salesforceId": row.salesforce_id,
        "actualDeliveryDate": row.completed_on.isoformat() if row.completed_on else "",
        "teachersAttended": row.teachers_attended or 0,
        "leadersAttended": row.leaders_attended or 0,
        "attendedSchoolIds": attended,
    }
    if visiting is not None:
        data["visitingSchoolIds"] = visiting
    complete(activity.id, data, principal)


def _confirm_partner_work(activity, row, principal, batch) -> None:
    from apps.activities.services import ia_confirm

    ia_confirm(
        activity.id,
        {
            "salesforceId": row.salesforce_id,
            "verificationNote": f"Confirmed by bulk upload {batch.file_name}.",
        },
        principal,
    )


def _outcome(activity) -> str:
    status = activity.status
    if status == "submitted_to_pl":
        return "Completed. It counts once the Programme Lead approves it."
    if status == "awaiting_ia_verification":
        return "Completed. It counts once Impact Assessment verifies it."
    return APPROVED


def _approve_uploaded(activity, principal, batch) -> None:
    """Uploaded staff work needs no Programme Lead verification: it comes
    from the Salesforce export (owner, 2026-11-02). Work completed from a
    drawer is untouched by this and still waits for its lead."""
    from apps.pl_review.services import approve_uploaded_completion

    uploader = str(getattr(principal, "user_id", "") or principal.id)
    approve_uploaded_completion(activity, uploader, batch.id)


def _complete_line(row, batch, principal) -> tuple[str, str]:
    from apps.activities.models import Activity

    with transaction.atomic():
        activity = (
            Activity.objects.select_for_update()
            .filter(pk=row.activity_id, deleted_at__isnull=True)
            .first()
        )
        if activity is None:
            return RowStatus.FAILED, "The activity no longer exists."
        if is_done(activity):
            return RowStatus.ALREADY_COMPLETED, "Already completed before this upload."
        if not is_open(activity):
            return (
                RowStatus.FAILED,
                f"The activity is now {activity.get_status_display().lower()}.",
            )
        if is_partner(activity):
            _confirm_partner_work(activity, row, principal, batch)
        else:
            if batch.kind == BulkKind.TRAINING:
                _complete_staff_training(activity, row, principal)
            else:
                _complete_staff_visit(activity, row, principal)
            activity.refresh_from_db()
            _approve_uploaded(activity, principal, batch)
        activity.refresh_from_db()
        return RowStatus.COMPLETED, _outcome(activity)


def _refusal(exc: Exception) -> str:
    """What the uploader is told. A refusal the workflow raised on purpose is
    said as written; anything else is logged and named generically."""
    from rest_framework.exceptions import APIException

    if isinstance(exc, APIException):
        detail = exc.detail
        if isinstance(detail, (list, tuple)) and detail:
            detail = detail[0]
        text = str(detail or "").strip()
        if text:
            return text
    logger.exception("bulk completion line failed", exc_info=exc)
    return "This line could not be completed. Try it from the activity's drawer."


def _send_summaries(collected, batch, principal) -> None:
    from apps.notifications.services import WorkflowNotificationService

    who = getattr(principal, "name", "") or "Impact Assessment"
    texts = {
        "review": (
            "activity_submitted_for_review",
            "Completions awaiting your review",
            "{n} activities were completed by {who}'s bulk upload and wait "
            "for your approval.",
        ),
        "verification": (
            "activity_submitted_for_verification",
            "Work submitted for verification",
            "{n} activities from {who}'s bulk upload are waiting for you.",
        ),
    }
    for kind, counts in collected.items():
        event, title, body = texts[kind]
        for recipient, n in counts.items():
            try:
                WorkflowNotificationService.trigger(
                    event_type=event,
                    category="activity" if kind == "review" else "verification",
                    priority="high" if kind == "review" else "normal",
                    title=title,
                    body=body.format(n=n, who=who),
                    context_id=f"{batch.id}:{kind}",
                    recipients=[recipient],
                )
            except Exception:  # noqa: BLE001 - a notice never undoes completions
                logger.warning("bulk completion summary failed", exc_info=True)


def apply_batch(
    batch: BulkCompletionBatch, principal, *, deadline: float | None = None
) -> BulkCompletionBatch:
    """Complete every ready line once; return the batch as it now stands.

    With ``deadline`` (a ``time.monotonic()`` value) the scheduler worker
    stops between lines when its time is up and puts the batch back in the
    queue; the next run carries on from the first line still ready.
    """
    from apps.activities.notice_digest import collected_hand_in_notices

    if not _claim(batch.pk):
        batch.refresh_from_db()
        return batch
    rows = list(batch.rows.filter(status=RowStatus.READY).order_by("row_number"))
    waiting = {"review": Counter(), "verification": Counter()}
    for row in rows:
        if deadline is not None and time.monotonic() > deadline:
            _send_summaries(waiting, batch, principal)
            BulkCompletionBatch.objects.filter(pk=batch.pk).update(
                status=BatchStatus.QUEUED, updated_at=timezone.now()
            )
            batch.refresh_from_db()
            return batch
        # Each line's hand-in notices are held back; they are sent, as one
        # summary per reviewer, only for work the upload left unapproved.
        with collected_hand_in_notices() as notices:
            try:
                row.status, row.message = _complete_line(row, batch, principal)
            except Exception as exc:  # noqa: BLE001 - one line never stops the rest
                row.status, row.message = RowStatus.FAILED, _refusal(exc)
        if row.status == RowStatus.COMPLETED and row.message != APPROVED:
            for kind, counts in notices.items():
                waiting[kind].update(counts)
        row.save(update_fields=["status", "message", "updated_at"])
    _settle_joined_lines(batch)
    _send_summaries(waiting, batch, principal)
    return _finish(batch, principal)


def _settle_joined_lines(batch) -> None:
    """A line joined to another shares the outcome of the line it joined."""
    outcome = {
        row.activity_id: (row.status, row.row_number)
        for row in batch.rows.exclude(status=RowStatus.MERGED).filter(
            status__in=(RowStatus.COMPLETED, RowStatus.FAILED)
        )
    }
    for row in batch.rows.filter(status=RowStatus.MERGED):
        status, number = outcome.get(row.activity_id, (RowStatus.FAILED, None))
        row.status = status
        row.message = (
            f"Completed with row {number}'s training."
            if status == RowStatus.COMPLETED
            else f"Not completed: see row {number}."
            if number
            else row.message
        )
        row.save(update_fields=["status", "message", "updated_at"])


def _finish(batch, principal) -> BulkCompletionBatch:
    from .staging import _log

    counts = Counter(batch.rows.values_list("status", flat=True))
    batch.status = BatchStatus.APPLIED
    batch.applied_by = str(getattr(principal, "user_id", "") or principal.id)
    batch.applied_at = timezone.now()
    batch.outcome_counts = dict(counts)
    batch.save(
        update_fields=[
            "status",
            "applied_by",
            "applied_at",
            "outcome_counts",
            "updated_at",
        ]
    )
    _log(batch, "bulk_completion.applied", {"outcomes": dict(counts)})
    return batch
