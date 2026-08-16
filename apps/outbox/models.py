"""The transactional outbox — Phase 2 of the operations roadmap.

One durable event backbone for everything that must happen *after* a
business fact commits but must never be lost, duplicated, or done inline:
integration syncs, regeneration loops, fan-outs. The contract:

- **Enqueue inside the business transaction.** The event row commits with
  the business write or not at all — there is no window where the fact
  exists and its follow-up doesn't (or vice versa).
- **At-least-once delivery, idempotent handlers.** Workers claim with
  SELECT … FOR UPDATE SKIP LOCKED, retry with exponential backoff, and
  park exhausted events in the dead-letter state — visible, replayable,
  never silently dropped. Handlers must therefore tolerate replays; the
  registry refuses registration without an explicit idempotency note.
- **Failure is an exception, not an absence.** A dead event surfaces in
  System Health with its error; `manage.py outbox_requeue` replays it.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class OutboxStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    SUCCEEDED = "succeeded", "Succeeded"
    DEAD = "dead", "Dead letter"


class OutboxEvent(TimeStampedModel):
    id = CuidField()
    event_type = models.CharField(max_length=128, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    # Enqueue-time dedup: two enqueues with the same key are one event.
    # Callers pass a natural key (e.g. "salesforce.sync:<activity_id>") when
    # the event represents a state to converge on rather than an occurrence.
    idempotency_key = models.CharField(max_length=191, unique=True)
    status = models.CharField(
        max_length=16, choices=OutboxStatus.choices, default=OutboxStatus.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=8)
    next_attempt_at = models.DateTimeField(db_index=True)
    # Crash-safe claims: a PROCESSING row whose lock expired is reclaimable —
    # a worker that died mid-handler never strands its events.
    locked_by = models.CharField(max_length=128, blank=True, default="")
    locked_until = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    succeeded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "outbox_event"
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="idx_outbox_due"),
        ]
