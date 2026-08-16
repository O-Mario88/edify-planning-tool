"""Salesforce/NetSuite sync flows on the durable outbox.

The 15-minute standard's §3a names two proof pastes — the SF ID and the
NetSuite ID — that exist only because these integrations don't. This module
is the framework that retires them: when a sync flag is on, the platform
pushes the record and stores the returned reference; the paste fields stay
as the manual fallback and a manually pasted reference ALWAYS wins.

Disabled by default (`SALESFORCE_SYNC_ENABLED` / `NETSUITE_SYNC_ENABLED`):
with a flag off nothing enqueues and today's manual flow remains the law.
Turning a flag on is an operations act that requires the transport
credentials (see the roadmap's Phase 2 prerequisites) — enabled-but-
misconfigured is a real incident and surfaces as outbox dead letters, never
as silently missing references.

Failure semantics (constitution): a failed external sync is a visible
exception with a replay path. It never invalidates, blocks, or un-verifies
work inside Edify.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.outbox.services import enqueue, register

from .models import IntegrationSync, IntegrationSyncStatus, IntegrationSystem

logger = logging.getLogger("edify.integrations")


class IntegrationNotConfigured(Exception):
    """Raised when a sync flag is on but the transport has no credentials —
    an operations incident, delivered to the outbox dead-letter queue."""


def sync_enabled(system: str) -> bool:
    flag = {
        IntegrationSystem.SALESFORCE: "SALESFORCE_SYNC_ENABLED",
        IntegrationSystem.NETSUITE: "NETSUITE_SYNC_ENABLED",
    }[system]
    return bool(getattr(settings, flag, False))


def push_to_external(system: str, resource: str, payload: dict) -> str:
    """The single transport seam: push one record, return its external id.

    Implementing this against the live APIs is the credentialed half of
    Phase 2c (API auth, versioning, rate limits) and is deliberately the
    ONLY function that will change when credentials arrive. Until then it
    refuses loudly rather than pretending.
    """

    raise IntegrationNotConfigured(
        f"{system} transport is not configured — set the API credentials and "
        "implement push_to_external before enabling the sync flag."
    )


def _record(system, context_type, context_id, *, status, external_id="", error=""):
    IntegrationSync.objects.update_or_create(
        system=system,
        context_type=context_type,
        context_id=str(context_id),
        defaults={
            "status": status,
            "external_id": external_id,
            "last_error": error[:4000],
            "synced_at": (
                timezone.now()
                if status
                in (
                    IntegrationSyncStatus.SUCCEEDED,
                    IntegrationSyncStatus.RECONCILED_MANUAL,
                )
                else None
            ),
        },
    )


# ── Enqueue seams (called from the canonical services) ───────────────────────


def enqueue_activity_salesforce_sync(activity_id: str) -> None:
    """Called when an activity reaches IA verification. No-op unless the
    Salesforce flag is on — the manual SF-ID paste remains the law until
    then. Idempotency key converges repeat verifications onto one event."""

    if not sync_enabled(IntegrationSystem.SALESFORCE):
        return
    enqueue(
        "integrations.salesforce.activity",
        {"activityId": str(activity_id)},
        idempotency_key=f"sf:activity:{activity_id}",
    )


def enqueue_advance_netsuite_sync(advance_id: str) -> None:
    """Called when the Accountant disburses an advance. No-op unless the
    NetSuite flag is on — the manual NetSuite-ID entry remains the law."""

    if not sync_enabled(IntegrationSystem.NETSUITE):
        return
    enqueue(
        "integrations.netsuite.advance",
        {"advanceId": str(advance_id)},
        idempotency_key=f"ns:advance:{advance_id}",
    )


# ── Outbox handlers ──────────────────────────────────────────────────────────


@register(
    "integrations.salesforce.activity",
    idempotency_note=(
        "Converges on state: an activity that already carries a Salesforce "
        "id (manual paste or a prior sync) records reconciled and is never "
        "pushed again; the push itself upserts by activity id."
    ),
)
def _sync_activity_to_salesforce(payload: dict) -> None:
    from apps.activities.models import Activity

    activity = Activity.objects.filter(id=payload.get("activityId")).first()
    if activity is None:
        # The activity was removed after enqueue — nothing to converge on.
        return
    if activity.salesforce_activity_id:
        _record(
            IntegrationSystem.SALESFORCE,
            "activity",
            activity.id,
            status=IntegrationSyncStatus.RECONCILED_MANUAL,
            external_id=activity.salesforce_activity_id,
        )
        return
    # A transport failure propagates to the outbox (retry → DLQ), which
    # carries the error and the replay path; a FAILED ledger row here
    # would be rolled back with the failed attempt anyway.
    external_id = push_to_external(
        IntegrationSystem.SALESFORCE,
        "activity",
        {
            "activityId": activity.id,
            "activityType": activity.activity_type,
            "schoolId": activity.school_id,
            "plannedDate": (
                activity.planned_date.isoformat() if activity.planned_date else None
            ),
            "status": activity.status,
        },
    )
    activity.salesforce_activity_id = external_id
    activity.save(update_fields=["salesforce_activity_id", "updated_at"])
    _record(
        IntegrationSystem.SALESFORCE,
        "activity",
        activity.id,
        status=IntegrationSyncStatus.SUCCEEDED,
        external_id=external_id,
    )


@register(
    "integrations.netsuite.advance",
    idempotency_note=(
        "Converges on state: an advance that already carries an "
        "accountability NetSuite id records reconciled and is never pushed "
        "again; the push upserts by advance id."
    ),
)
def _sync_advance_to_netsuite(payload: dict) -> None:
    from apps.fund_requests.models import AdvanceRequest

    advance = AdvanceRequest.objects.filter(id=payload.get("advanceId")).first()
    if advance is None:
        return
    if advance.accountability_netsuite_id:
        _record(
            IntegrationSystem.NETSUITE,
            "advance",
            advance.id,
            status=IntegrationSyncStatus.RECONCILED_MANUAL,
            external_id=advance.accountability_netsuite_id,
        )
        return
    # A transport failure propagates to the outbox (retry → DLQ), which
    # carries the error and the replay path; a FAILED ledger row here
    # would be rolled back with the failed attempt anyway.
    external_id = push_to_external(
        IntegrationSystem.NETSUITE,
        "advance",
        {
            "advanceId": advance.id,
            "status": advance.status,
            "amount": str(getattr(advance, "amount", "") or ""),
        },
    )
    advance.accountability_netsuite_id = external_id
    advance.save(update_fields=["accountability_netsuite_id", "updated_at"])
    _record(
        IntegrationSystem.NETSUITE,
        "advance",
        advance.id,
        status=IntegrationSyncStatus.SUCCEEDED,
        external_id=external_id,
    )
