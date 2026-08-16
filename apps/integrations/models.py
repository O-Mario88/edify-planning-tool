"""External-integration sync ledger — Phase 2 of the operations roadmap.

One row per (system, record): the reconciliation spine between Edify and
Salesforce/NetSuite. The row records what was pushed, what came back, and
what failed — so a failed external synchronisation is a visible exception
with an owner, and never invalidates or blocks the verified work inside
Edify. Manual references pasted by staff always win: a sync finding an
existing reference records itself as reconciled-manual and touches nothing.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class IntegrationSystem(models.TextChoices):
    SALESFORCE = "salesforce", "Salesforce"
    NETSUITE = "netsuite", "NetSuite"


class IntegrationSyncStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    RECONCILED_MANUAL = "reconciled_manual", "Reconciled (manual reference)"
    FAILED = "failed", "Failed"


class IntegrationSync(TimeStampedModel):
    id = CuidField()
    system = models.CharField(max_length=16, choices=IntegrationSystem.choices)
    context_type = models.CharField(max_length=32)  # activity | advance
    context_id = models.CharField(max_length=30, db_index=True)
    external_id = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(
        max_length=24,
        choices=IntegrationSyncStatus.choices,
        default=IntegrationSyncStatus.PENDING,
    )
    last_error = models.TextField(blank=True, default="")
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "integration_sync"
        constraints = [
            models.UniqueConstraint(
                fields=["system", "context_type", "context_id"],
                name="uniq_integration_sync_context",
            )
        ]
