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

from django.db import transaction

from apps.core.audit_hash import CanonicalAuditFields, canonical_audit, chain_hash
from apps.core.request_context import get_request_context

from .models import AuditLog

logger = logging.getLogger("edify.audit")


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
                from apps.accounts.models import TemporaryCoverageAssignment, StaffProfile
                from django.utils import timezone
                now = timezone.now()
                sp = StaffProfile.objects.filter(user_id=actor_id).first()
                if sp:
                    cov = TemporaryCoverageAssignment.objects.filter(
                        covering_staff=sp,
                        start_datetime__lte=now,
                        end_datetime__gte=now,
                        status="active"
                    ).select_related("original_staff__user", "leave_request").first()
                    if cov:
                        if not payload:
                            payload = {}
                        elif not isinstance(payload, dict):
                            payload = {"original_payload": payload}
                        payload.update({
                            "acting_for": {
                                "staff_profile_id": cov.original_staff.id,
                                "user_id": cov.original_staff.user.id,
                                "name": cov.original_staff.user.name,
                            },
                            "reason": "Leave Coverage",
                            "leave_request_id": cov.leave_request.id,
                        })
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
            # select_for_update on the tail serializes chain appends so prevHash
            # always points at the true tail (the legacy used a Postgres advisory
            # lock; row-level locking on the last row achieves the same).
            last = (
                AuditLog.objects.select_for_update()
                .order_by("-seq")
                .only("hash", "seq")
                .first()
            )
            prev_hash = last.hash if last else None
            next_seq = (last.seq + 1) if last else 1
            hash_value = chain_hash(prev_hash or "", canonical_audit(fields))
            AuditLog.objects.create(
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
    except Exception as exc:  # noqa: BLE001 — audit must never break the workflow
        logger.error("Failed to write audit (%s): %s", action, exc)


def verify_chain() -> dict:
    """Recompute the chain end-to-end. Returns {ok, brokenAt}."""
    prev_hash: str | None = None
    for row in AuditLog.objects.order_by("seq").iterator():
        expected = chain_hash(prev_hash or "", canonical_audit(_row_to_fields(row)))
        if row.hash != expected:
            return {"ok": False, "brokenAt": row.seq}
        prev_hash = row.hash
    return {"ok": True, "brokenAt": None}


def _row_to_fields(row: AuditLog) -> CanonicalAuditFields:
    return CanonicalAuditFields(
        action=row.action, subject_kind=row.subject_kind, subject_id=row.subject_id,
        actor_id=row.actor_id, actor_role=row.actor_role, success=row.success,
        reason=row.reason, ip_address=row.ip_address, user_agent=row.user_agent,
        correlation_id=row.correlation_id, payload=row.payload,
    )


__all__ = ["log", "verify_chain"]
