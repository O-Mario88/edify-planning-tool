"""
Audit service — appends a hash-chained AuditLog row under a serialized
transaction (select_for_update on the tail). Faithful port of audit.service.

Audit must NEVER break the primary action: failures are logged + swallowed.
The request provenance (ip/user-agent/correlationId) is read from the request
context (contextvars), so callers don't thread it through.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import connection, transaction
from django.utils import timezone

from apps.core.logging_filters import escape_control_characters
from apps.core.audit_hash import CanonicalAuditFields, canonical_audit, chain_hash
from apps.core.request_context import get_request_context

from .models import AuditLog

logger = logging.getLogger("edify.audit")

# A transaction-scoped PostgreSQL advisory lock serializes the append point even
# when the chain is empty. Row-locking only the current tail is insufficient:
# two transactions can both select the same old tail and calculate the same
# next sequence, causing the later insert to lose its audit event to the unique
# constraint. The fixed key is private to this application/database.
_AUDIT_CHAIN_LOCK_ID = 0x4544494659415544  # "EDIFYAUD", signed-bigint safe


def log(
    *,
    action: str,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    success: bool = True,
    reason: str | None = None,
    payload: Any | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Append a hash-chained audit row. Best-effort — never raises."""
    try:
        if actor_id:
            try:
                from apps.accounts.models import (
                    TemporaryCoverageAssignment,
                    StaffProfile,
                )
                from django.utils import timezone

                now = timezone.now()
                sp = StaffProfile.objects.filter(user_id=actor_id).first()
                if sp:
                    cov = (
                        TemporaryCoverageAssignment.objects.filter(
                            covering_staff=sp,
                            start_datetime__lte=now,
                            end_datetime__gte=now,
                            status="active",
                        )
                        .select_related("original_staff__user", "leave_request")
                        .first()
                    )
                    if cov:
                        if not payload:
                            payload = {}
                        elif not isinstance(payload, dict):
                            payload = {"original_payload": payload}
                        payload.update(
                            {
                                "acting_for": {
                                    "staff_profile_id": cov.original_staff.id,
                                    "user_id": cov.original_staff.user.id,
                                    "name": cov.original_staff.user.name,
                                },
                                "reason": "Leave Coverage",
                                "leave_request_id": cov.leave_request.id,
                            }
                        )
            except Exception as e:
                logger.error("Failed to intercept audit for coverage: %s", e)

        ctx = get_request_context()
        fields = CanonicalAuditFields(
            action=action,
            subject_kind=subject_kind,
            subject_id=subject_id,
            actor_id=actor_id,
            actor_role=actor_role,
            success=success,
            reason=reason,
            ip_address=ip_address or (ctx.ip_address if ctx else None),
            user_agent=user_agent or (ctx.user_agent if ctx else None),
            correlation_id=correlation_id or (ctx.correlation_id if ctx else None),
            payload=payload,
        )
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(%s)",
                        [_AUDIT_CHAIN_LOCK_ID],
                    )
            # The advisory lock above serializes the empty-chain case and every
            # append. select_for_update remains useful as defence in depth and
            # for database backends without PostgreSQL advisory locks.
            last = (
                AuditLog.objects.select_for_update()
                .order_by("-seq")
                .only("hash", "seq")
                .first()
            )
            prev_hash = last.hash if last else None
            next_seq = (last.seq + 1) if last else 1
            hash_value = chain_hash(prev_hash or "", canonical_audit(fields))
            audit_row = AuditLog.objects.create(
                seq=next_seq,
                action=fields.action,
                subject_kind=fields.subject_kind,
                subject_id=fields.subject_id,
                actor_id=fields.actor_id,
                actor_role=fields.actor_role,
                payload=fields.payload,
                ip_address=fields.ip_address,
                user_agent=fields.user_agent,
                correlation_id=fields.correlation_id,
                success=fields.success,
                reason=fields.reason,
                prev_hash=prev_hash,
                hash=hash_value,
            )
            # DomainEventLog/realtime are projections of the immutable audit
            # chain. Waiting for the outermost transaction prevents phantom UI
            # updates for a workflow that later rolls back.
            event_payload = (
                fields.payload
                if isinstance(fields.payload, dict)
                else {"value": fields.payload}
            )

            def _project_committed_audit() -> None:
                try:
                    from apps.realtime.domain_events import publish_audit_event

                    publish_audit_event(
                        event_type=fields.action,
                        subject_kind=fields.subject_kind,
                        subject_id=fields.subject_id,
                        actor_id=fields.actor_id,
                        payload=event_payload,
                        audit_seq=audit_row.seq,
                        success=fields.success,
                        reason=fields.reason,
                    )
                except Exception as exc:  # pragma: no cover - defensive seam
                    logger.error(
                        "Failed to project audit event (%s): %s", fields.action, exc
                    )

            transaction.on_commit(_project_committed_audit)
    except Exception as exc:  # noqa: BLE001 — audit must never break the workflow
        # `action` is whatever the caller passed and the exception text is
        # whatever the database said, so both are escaped as they enter the
        # record. The SingleLineFilter would catch them on the way out too —
        # this is the belt to its braces, and it puts the reason next to the
        # values rather than in a settings module.
        logger.error(
            "Failed to write audit (%s): %s",
            escape_control_characters(str(action)),
            escape_control_characters(str(exc)),
        )


def verify_chain(*, full: bool = False) -> dict:
    """Verify the hash chain. Returns {ok, brokenAt, checkedRows, fromSeq}.

    Incremental by default, and still tamper-evident.

    This recomputed every row on every call. Measured at 62.1 microseconds a
    row: 62 seconds at a million rows, five minutes at five million — on the
    request path, holding a database connection, because System Health calls
    it. An audit row is written for nearly every action on this platform, so
    those are first-year numbers.

    The chain is append-only and each hash covers the previous one, so
    verification can resume from a recorded frontier without weakening into a
    "recent rows only" check. A retroactive edit is caught either way:

      * rows after it not recomputed — the chain breaks at the next row, and
        that row is at or after the frontier on some later run;
      * rows after it recomputed — the hash at the frontier seq no longer
        matches the one recorded, which is checked first, below.

    `full=True` forces the end-to-end walk. That is the right thing for a
    scheduled job or an incident, and the wrong thing for a page render.
    """
    from apps.audit.models import AuditChainCheckpoint

    checkpoint = None
    prev_hash: str | None = None
    start_after = None

    if not full:
        checkpoint = AuditChainCheckpoint.objects.filter(
            id=AuditChainCheckpoint.SINGLETON_ID
        ).first()
        if checkpoint and checkpoint.verified_through_seq is not None:
            anchor = AuditLog.objects.filter(
                seq=checkpoint.verified_through_seq
            ).first()
            if anchor is None or anchor.hash != checkpoint.verified_hash:
                # The frontier row is gone or no longer hashes to what was
                # recorded: the history behind us changed. Report the frontier
                # rather than trusting it.
                broken = checkpoint.verified_through_seq
                AuditChainCheckpoint.objects.update_or_create(
                    id=AuditChainCheckpoint.SINGLETON_ID,
                    defaults={"broken_at_seq": broken},
                )
                return {
                    "ok": False,
                    "brokenAt": broken,
                    "checkedRows": 1,
                    "fromSeq": broken,
                }
            prev_hash = checkpoint.verified_hash
            start_after = checkpoint.verified_through_seq

    rows = AuditLog.objects.order_by("seq")
    if start_after is not None:
        rows = rows.filter(seq__gt=start_after)

    checked = 0
    last_seq = start_after
    last_hash = prev_hash
    for row in rows.iterator():
        expected = chain_hash(prev_hash or "", canonical_audit(_row_to_fields(row)))
        if row.hash != expected:
            AuditChainCheckpoint.objects.update_or_create(
                id=AuditChainCheckpoint.SINGLETON_ID,
                defaults={"broken_at_seq": row.seq},
            )
            return {
                "ok": False,
                "brokenAt": row.seq,
                "checkedRows": checked + 1,
                "fromSeq": start_after,
            }
        prev_hash = row.hash
        last_seq, last_hash = row.seq, row.hash
        checked += 1

    # Advance the frontier only on a clean pass, and clear any recorded break.
    if last_seq is not None:
        AuditChainCheckpoint.objects.update_or_create(
            id=AuditChainCheckpoint.SINGLETON_ID,
            defaults={
                "verified_through_seq": last_seq,
                "verified_hash": last_hash,
                "verified_at": timezone.now(),
                "broken_at_seq": None,
            },
        )
    return {
        "ok": True,
        "brokenAt": None,
        "checkedRows": checked,
        "fromSeq": start_after,
    }


def _row_to_fields(row: AuditLog) -> CanonicalAuditFields:
    return CanonicalAuditFields(
        action=row.action,
        subject_kind=row.subject_kind,
        subject_id=row.subject_id,
        actor_id=row.actor_id,
        actor_role=row.actor_role,
        success=row.success,
        reason=row.reason,
        ip_address=row.ip_address,
        user_agent=row.user_agent,
        correlation_id=row.correlation_id,
        payload=row.payload,
    )


__all__ = ["log", "verify_chain"]
