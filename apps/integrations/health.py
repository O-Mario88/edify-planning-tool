"""System Health contribution: the external-sync ledger, readable at last.

The reconciliation promise (a failed external sync is a visible exception,
never a silent absence) needs a reader: this block shows the ledger's
terminal states beside the flags, and flags-on-with-no-throughput as the
anomaly it is. Transport failures themselves live in the outbox dead-letter
panel with their replay path.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .models import IntegrationSync


def integrations_health() -> dict:
    by_key = {
        (row["system"], row["status"]): row["count"]
        for row in IntegrationSync.objects.values("system", "status")
        .annotate(count=Count("id"))
        .order_by()
    }
    systems = []
    checks = []
    now = timezone.now()
    for system, flag in (
        ("salesforce", "SALESFORCE_SYNC_ENABLED"),
        ("netsuite", "NETSUITE_SYNC_ENABLED"),
    ):
        enabled = bool(getattr(settings, flag, False))
        succeeded = by_key.get((system, "succeeded"), 0)
        manual = by_key.get((system, "reconciled_manual"), 0)
        systems.append(
            {
                "system": system,
                "enabled": enabled,
                "succeeded": succeeded,
                "reconciledManual": manual,
            }
        )
        if enabled and succeeded == 0 and manual == 0:
            checks.append(
                {
                    "key": f"integration_{system}_silent",
                    "severity": "warning",
                    "component": f"{system.title()} sync",
                    "current_state": (
                        "Enabled but the ledger shows no reconciled records"
                    ),
                    "expected_state": (
                        "Verified work reconciling by sync or manual reference"
                    ),
                    "last_check": now.isoformat(),
                    "owner": "Admin",
                    "recommended_action": (
                        "Check the outbox dead-letter panel — an enabled but "
                        "misconfigured transport fails loudly there."
                    ),
                    "resolution_link": "/system-health",
                }
            )
    return {"checks": checks, "systems": systems}
