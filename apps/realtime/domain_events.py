"""
DomainEvent seam — the single seam every workflow reaches post-commit.

Does (best-effort — never rolls back the workflow):
  1) appends a hash-chained AuditLog row (via the AuditService),
  2) projects committed audit rows into DomainEventLog,
  3) writes per-recipient Notification rows (role-aware deep link + dedupe),
  4) pushes a realtime event to the bus.

This is the faithful port of the legacy DomainEventService.emit. Callers don't
import this directly in the hot path; workflow services call `emit` after a
successful state change. Best-effort: a failure here logs + swallows so the
workflow itself succeeds.
"""

from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from apps.core.cuid import cuid

from .bus import bus

logger = logging.getLogger("edify.domain_events")


def emit(
    *,
    event_type: str,
    actor_id: str,
    actor_role: str | None = None,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    payload: dict[str, Any] | None = None,
    notify: list[dict] | None = None,
    live_user_ids: list[str] | None = None,
) -> None:
    """Emit a domain event: audit it + notify + push realtime.

    `notify` is a list of {recipient_id, title, body?, target_route?, priority?,
    action_required?}. `live_user_ids` are the users who should get a realtime
    push (defaults to the notify recipients + the actor)."""
    try:
        _audit(event_type, subject_kind, subject_id, actor_id, actor_role, payload)
        event_id = cuid()
        notified: list[str] = []
        for spec in notify or []:
            rid = spec.get("recipient_id")
            if not rid:
                continue
            _create_notification(rid, event_type, event_id, spec)
            notified.append(rid)

        push_ids = list({*(live_user_ids or []), *notified, actor_id})
        live_event = {
            "type": event_type,
            "subjectKind": subject_kind,
            "subjectId": subject_id,
            "actorId": actor_id,
            "at": timezone.now().isoformat(),
            "meta": payload or {},
        }
        # Do not tell the UI about a mutation that has not committed yet.
        from django.db import transaction

        transaction.on_commit(lambda: bus.publish_many(push_ids, live_event))
    except Exception as exc:  # noqa: BLE001 — best-effort, never break the workflow
        logger.exception("DomainEvent emit failed for %s: %s", event_type, exc)


def notify_only(
    *,
    event_type: str,
    actor_id: str,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    notify: list[dict] | None = None,
    live_user_ids: list[str] | None = None,
) -> None:
    """Like emit but skips the actor-role/payload audit detail (notify-only)."""
    emit(
        event_type=event_type,
        actor_id=actor_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        notify=notify,
        live_user_ids=live_user_ids,
    )


def users_with_role(role: str) -> list[str]:
    from apps.accounts.models import User

    return list(
        User.objects.filter(
            deleted_at__isnull=True, status="active", roles__contains=[role]
        ).values_list("id", flat=True)
    )


def user_for_staff(staff_profile_id: str | None) -> str | None:
    if not staff_profile_id:
        return None
    from apps.accounts.models import StaffProfile

    sp = StaffProfile.objects.filter(id=staff_profile_id).first()
    return sp.user_id if sp else None


def publish_audit_event(
    *,
    event_type: str,
    subject_kind: str | None,
    subject_id: str | None,
    actor_id: str | None,
    payload: dict[str, Any] | None,
    audit_seq: int | None,
    success: bool,
    reason: str | None,
) -> None:
    """Project a committed audit row to the durable/realtime event stream.

    This function never writes AuditLog or Notification rows, so the audit
    projection cannot recurse into another audit event. It is called only by
    ``apps.audit.services`` through ``transaction.on_commit``.
    """
    try:
        _append_domain_event_log(
            event_type,
            subject_kind,
            subject_id,
            actor_id,
            {
                "auditSeq": audit_seq,
                "success": success,
                "reason": reason,
                "data": payload or {},
            },
        )
        if actor_id:
            bus.publish(
                actor_id,
                {
                    "type": event_type,
                    "subjectKind": subject_kind,
                    "subjectId": subject_id,
                    "actorId": actor_id,
                    "at": timezone.now().isoformat(),
                    "meta": payload or {},
                },
            )
    except Exception as exc:  # noqa: BLE001 — committed work must stay committed
        logger.exception("Audit event projection failed for %s: %s", event_type, exc)


def _append_domain_event_log(event_type, subject_kind, subject_id, actor_id, payload):
    from apps.audit.models import DomainEventLog

    DomainEventLog.objects.create(
        event_type=event_type,
        aggregate_type=subject_kind,
        aggregate_id=subject_id,
        actor_id=actor_id,
        payload=payload,
    )


def _audit(event_type, subject_kind, subject_id, actor_id, actor_role, payload):
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=event_type,
            subject_kind=subject_kind,
            subject_id=subject_id,
            actor_id=actor_id,
            actor_role=actor_role,
            payload=payload,
        )
    except Exception:  # noqa: BLE001
        # The audit app may not be present yet during the build.
        pass


def _create_notification(recipient_id, event_type, event_id, spec):
    from apps.notifications.services import WorkflowNotificationService

    WorkflowNotificationService.trigger(
        event_type=event_type,
        category=spec.get("category", "general"),
        priority=spec.get("priority", "normal"),
        title=spec.get("title", event_type),
        body=spec.get("body"),
        context_type=spec.get("context_type"),
        context_id=spec.get("context_id") or event_id,
        recipients=[recipient_id],
    )


__all__ = [
    "emit",
    "notify_only",
    "publish_audit_event",
    "users_with_role",
    "user_for_staff",
]
