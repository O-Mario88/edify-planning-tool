"""
Audit models — the tamper-evident hash-chained AuditLog + append-only
DomainEventLog.

AuditLog.seq is a monotonic BigAutoField (chain is verified in seq order so
ms-resolution createdAt ties are unambiguous). hash = sha256(prevHash + canonical
(record)); prevHash links to the previous row. A model-level guard + the chain
verification make the log tamper-evident.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel
from apps.core.rbac import EdifyRole


class AuditLog(models.Model):
    """Tamper-evident audit row. Never UPDATEd or DELETEd in normal operation."""

    id = CuidField()
    # Monotonic insert order — assigned under a lock in log() (see services.py).
    # The legacy used a Postgres autoincrement BigInt; we assign manually in a
    # serialized transaction so prevHash always points at the true tail.
    # unique=True is the concurrency guard the chain was missing: two
    # concurrent log() calls could lock the same tail, compute the same seq,
    # and both commit — four duplicate seqs and a broken chain in the dev DB
    # proved it. With the constraint, the second writer fails and log()'s
    # swallow-and-continue contract turns the race into a lost audit row
    # rather than a corrupted chain.
    seq = models.BigIntegerField(null=True, blank=True, unique=True)
    action = models.CharField(max_length=128)
    subject_kind = models.CharField(max_length=64, null=True, blank=True)
    subject_id = models.CharField(max_length=30, null=True, blank=True)
    actor_id = models.CharField(max_length=30, null=True, blank=True)
    actor_role = models.CharField(
        max_length=64,
        choices=[(r.value, r.value) for r in EdifyRole],
        null=True,
        blank=True,
    )
    payload = models.JSONField(null=True, blank=True)
    # Request provenance (captured via request context).
    ip_address = models.CharField(max_length=128, null=True, blank=True)
    user_agent = models.CharField(max_length=512, null=True, blank=True)
    correlation_id = models.CharField(max_length=64, null=True, blank=True)
    success = models.BooleanField(default=True)
    reason = models.CharField(max_length=512, null=True, blank=True)
    # Hash chain.
    prev_hash = models.CharField(max_length=128, null=True, blank=True)
    hash = models.CharField(max_length=128, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_log"
        indexes = [
            models.Index(fields=["subject_kind", "subject_id"]),
            models.Index(fields=["actor_id"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["seq"]),
            models.Index(fields=["action"]),
            models.Index(fields=["correlation_id"]),
        ]


class DomainEventLog(TimeStampedModel):
    """Append-only domain event log (the seam's first action)."""

    id = CuidField()
    event_type = models.CharField(max_length=128)
    aggregate_type = models.CharField(max_length=64, null=True, blank=True)
    aggregate_id = models.CharField(max_length=30, null=True, blank=True)
    actor_id = models.CharField(max_length=30, null=True, blank=True)
    payload = models.JSONField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "domain_event_log"
        indexes = [
            models.Index(fields=["event_type"]),
            models.Index(fields=["aggregate_type", "aggregate_id"]),
            models.Index(fields=["processed_at"]),
        ]


__all__ = ["AuditLog", "DomainEventLog"]


class AuditChainCheckpoint(models.Model):
    """How far the hash chain has been verified, and the hash it ended on.

    verify_chain() recomputed every row on every call. Measured at 62.1
    microseconds a row, which is 62 seconds at a million rows and over five
    minutes at five — on the request path, holding a connection, because
    System Health calls it. This platform writes an audit row for nearly every
    action, so a million rows is a first-year number, not a hypothetical.

    Storing the hash the verification ended on is what makes an incremental
    check still tamper-evident rather than a weaker check that only looks at
    recent rows. Each row's hash covers the previous hash, so a retroactive
    edit has two possible outcomes and both are caught:

      * the editor does not recompute the rows after it — the chain breaks at
        the very next row, which any later verification walks straight into;
      * the editor does recompute them — then the hash at the checkpoint seq
        no longer matches the one recorded here, and the mismatch is the
        detection.

    Singleton by design: one chain, one frontier.
    """

    SINGLETON_ID = "audit-chain-checkpoint"

    id = models.CharField(max_length=64, primary_key=True, default=SINGLETON_ID)
    # The last sequence number proven correct, and the hash it produced.
    verified_through_seq = models.BigIntegerField(null=True, blank=True)
    verified_hash = models.CharField(max_length=128, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    # Set when a verification fails, so the failure survives the request that
    # found it and System Health keeps reporting it until it is resolved.
    broken_at_seq = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "audit_chain_checkpoint"
