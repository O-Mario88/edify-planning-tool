"""Enqueue, drain, and replay for the durable outbox.

Delivery is at-least-once; handlers are idempotent by contract (the
registry refuses a handler without an idempotency note). Backoff is
deterministic — min(2^attempts × 30s, 1h) — so tests and incident reviews
can reason about exactly when a retry fires.
"""

from __future__ import annotations

import logging
import socket
import time
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import OutboxEvent, OutboxStatus

logger = logging.getLogger("edify.outbox")

BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 3600
# How long one claim owns an event before a crashed worker's rows become
# reclaimable. Generous relative to any sane handler runtime.
CLAIM_SECONDS = 300

_HANDLERS: dict[str, dict] = {}


def register(event_type: str, *, idempotency_note: str):
    """Register the handler for an event type.

    ``idempotency_note`` is mandatory documentation of WHY replaying this
    handler is safe — the same discipline the scheduled-job registry
    enforces. A handler that cannot write that sentence is not ready for
    at-least-once delivery.
    """

    if not (idempotency_note or "").strip():
        raise ValueError("An outbox handler requires an idempotency note.")

    def decorator(func):
        if event_type in _HANDLERS:
            raise ValueError(f"Duplicate outbox handler for {event_type!r}.")
        _HANDLERS[event_type] = {
            "func": func,
            "idempotency_note": idempotency_note,
        }
        return func

    return decorator


def registered_event_types() -> list[str]:
    return sorted(_HANDLERS)


def enqueue(
    event_type: str,
    payload: dict | None = None,
    *,
    idempotency_key: str | None = None,
    delay_seconds: int = 0,
) -> OutboxEvent:
    """Write one durable event inside the caller's transaction.

    Rides the ambient atomic block on purpose: if the business write rolls
    back, the event goes with it. With an explicit key, a repeat enqueue
    converges on the existing row (state to reach, not occurrence to count).
    """

    from apps.core.models import cuid

    key = idempotency_key or f"{event_type}:{cuid()}"
    event, _created = OutboxEvent.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "event_type": event_type,
            "payload": payload or {},
            "next_attempt_at": timezone.now() + timedelta(seconds=delay_seconds),
        },
    )
    return event


def enqueue_many(
    event_type: str, items: list[tuple[dict, str]], *, delay_seconds: int = 0
) -> int:
    """Write many durable events of one type in a single statement.

    `items` is [(payload, idempotency_key), …]. Same contract as `enqueue` —
    rides the ambient transaction, and an existing key converges instead of
    duplicating (`ignore_conflicts` on the unique key) — but the cost is one
    INSERT however many rows arrive, which is what a batch import needs: the
    per-row loop was the difference between O(1) and O(n) queries per upload.
    """

    if not items:
        return 0
    due = timezone.now() + timedelta(seconds=delay_seconds)
    created = OutboxEvent.objects.bulk_create(
        [
            OutboxEvent(
                event_type=event_type,
                payload=payload or {},
                idempotency_key=key,
                next_attempt_at=due,
            )
            for payload, key in items
        ],
        ignore_conflicts=True,
    )
    return len(created)


def _backoff_seconds(attempts: int) -> int:
    return min(BASE_BACKOFF_SECONDS * (2**attempts), MAX_BACKOFF_SECONDS)


def _claim_batch(batch_size: int, worker_id: str) -> list[str]:
    """Claim due events with SKIP LOCKED so concurrent drains never collide.

    Due = pending and scheduled, or processing with an expired claim (a
    worker died mid-handler; its events must not strand).
    """

    from django.db.models import Q

    now = timezone.now()
    due = Q(status=OutboxStatus.PENDING, next_attempt_at__lte=now) | Q(
        status=OutboxStatus.PROCESSING, locked_until__lt=now
    )
    with transaction.atomic():
        ids = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(due)
            .order_by("next_attempt_at")
            .values_list("id", flat=True)[:batch_size]
        )
        if ids:
            OutboxEvent.objects.filter(id__in=ids).update(
                status=OutboxStatus.PROCESSING,
                locked_by=worker_id,
                locked_until=now + timedelta(seconds=CLAIM_SECONDS),
            )
    return ids


def _finish(event_id: str, *, error: str | None) -> None:
    """Record one attempt's outcome in its own small transaction."""

    with transaction.atomic():
        event = OutboxEvent.objects.select_for_update().get(id=event_id)
        event.attempts += 1
        if error is None:
            event.status = OutboxStatus.SUCCEEDED
            event.succeeded_at = timezone.now()
            event.last_error = ""
        elif event.attempts >= event.max_attempts:
            event.status = OutboxStatus.DEAD
            event.last_error = error[:4000]
            _notify_dead_letter(event)
        else:
            event.status = OutboxStatus.PENDING
            event.next_attempt_at = timezone.now() + timedelta(
                seconds=_backoff_seconds(event.attempts)
            )
            event.last_error = error[:4000]
        event.locked_by = ""
        event.locked_until = None
        event.save(
            update_fields=[
                "attempts",
                "status",
                "succeeded_at",
                "next_attempt_at",
                "last_error",
                "locked_by",
                "locked_until",
                "updated_at",
            ]
        )


def drain(
    *, batch_size: int = 50, time_budget_seconds: int = 45, worker_id: str = ""
) -> dict:
    """Process due events until the queue is quiet or the budget is spent.

    Each handler runs in its own transaction: one poisoned event fails
    alone, backs off alone, and eventually dead-letters alone — it never
    takes the batch with it.
    """

    worker_id = worker_id or f"{socket.gethostname()}:{time.monotonic_ns()}"
    started = time.monotonic()
    processed = succeeded = failed = 0
    while time.monotonic() - started < time_budget_seconds:
        ids = _claim_batch(batch_size, worker_id)
        if not ids:
            break
        for event_id in ids:
            event = OutboxEvent.objects.get(id=event_id)
            handler = _HANDLERS.get(event.event_type)
            processed += 1
            if handler is None:
                _finish(
                    event_id,
                    error=f"No handler registered for {event.event_type!r}.",
                )
                failed += 1
                continue
            try:
                with transaction.atomic():
                    handler["func"](event.payload)
            except Exception as exc:  # noqa: BLE001 — recorded, retried, DLQ'd
                logger.warning(
                    "Outbox handler %s failed (attempt %s): %s",
                    event.event_type,
                    event.attempts + 1,
                    exc,
                )
                _finish(event_id, error=f"{type(exc).__name__}: {exc}")
                failed += 1
            else:
                _finish(event_id, error=None)
                succeeded += 1
    return {"processed": processed, "succeeded": succeeded, "failed": failed}


def _notify_dead_letter(event) -> None:
    """A dead letter is an incident, not a dashboard curiosity: Admins hear
    about it without opening System Health (constitution: every failure a
    visible exception). Idempotent per event via the notification service's
    own re-fire semantics; never breaks the finish path."""

    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService

        admins = list(
            User.objects.filter(is_active=True, active_role="Admin").values_list(
                "id", flat=True
            )
        )
        if not admins:
            return
        WorkflowNotificationService.trigger(
            event_type="outbox.dead_letter",
            category="platform",
            priority="high",
            title="Outbox event dead-lettered",
            body=(
                f"{event.event_type} exhausted its retries: "
                f"{event.last_error[:200]} — fix the cause, then replay with "
                "outbox_requeue."
            ),
            context_type="OutboxEvent",
            context_id=str(event.id),
            recipients=admins,
        )
    except Exception:  # noqa: BLE001 — notification must never break _finish
        logger.debug("dead-letter notification failed", exc_info=True)


def requeue_dead(event_ids: list[str] | None = None) -> int:
    """Replay dead-lettered events after the underlying cause is fixed.

    Resets the attempt budget; the events re-enter the ordinary retry
    discipline rather than getting one desperate shot.
    """

    queryset = OutboxEvent.objects.filter(status=OutboxStatus.DEAD)
    if event_ids:
        queryset = queryset.filter(id__in=event_ids)
    return queryset.update(
        status=OutboxStatus.PENDING,
        attempts=0,
        next_attempt_at=timezone.now(),
        locked_by="",
        locked_until=None,
    )
