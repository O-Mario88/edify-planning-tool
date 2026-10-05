"""Re-price open plans whose saved cost still carries a retired rate.

Owner, 2026-10-04: "Group Trainings Planned for This FY does not show cost.
It shows UGX 0." A cluster training scheduled while the per-session
`cluster_meetings_trainings` rate was charged kept that line after budget
migration 0023 deleted the rate, and kept the recipe of its day (no
participant meals). Work that has not happened yet should carry today's
recipe, so this re-prices it through the one cost writer
(`apps.activities.services.reprice_activity`), which also rebuilds its draft
weekly and monthly requests.

Only plans that are still editable (planned, scheduled, rescheduled) and that
no money has moved on are touched. Completed, verified and paid work keeps
the cost it was priced at; `planned_minimum_amounts` reads its retired lines
at their saved amount.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.activities.editing import EDITABLE_STATUSES
from apps.activities.models import Activity
from apps.budget.models import ActivityCostSnapshot
from apps.budget.reference import RETIRED_COST_SETTING_KEYS
from apps.core.exceptions import BadRequest

UNPAID_PAYMENT_STATUSES = ("", "none")


def stale_open_activity_ids() -> list[str]:
    """Open, unpaid activities whose current snapshot prices a retired rate."""
    open_ids = set(
        Activity.objects.filter(
            deleted_at__isnull=True,
            status__in=EDITABLE_STATUSES,
        )
        .filter(payment_status__in=UNPAID_PAYMENT_STATUSES)
        .values_list("id", flat=True)
    )
    stale = []
    for activity_id, breakdown in ActivityCostSnapshot.objects.filter(
        is_current=True, activity_id__in=open_ids
    ).values_list("activity_id", "operational_breakdown"):
        if any(
            line.get("key") in RETIRED_COST_SETTING_KEYS for line in breakdown or []
        ):
            stale.append(activity_id)
    return sorted(stale)


class Command(BaseCommand):
    help = (
        "Re-price planned, unpaid activities whose saved cost still carries a "
        "retired rate, so the plan tables show today's recipe."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be re-priced without changing data.",
        )

    def handle(self, *args, **options):
        from apps.activities.services import reprice_activity

        dry_run = options["dry_run"]
        repriced = skipped = 0
        for activity in Activity.objects.filter(id__in=stale_open_activity_ids()):
            before = activity.est_cost_cents
            if dry_run:
                self.stdout.write(
                    f"Would re-price {activity.id} ({activity.activity_type}), "
                    f"now UGX {before or 0:,}."
                )
                repriced += 1
                continue
            try:
                reprice_activity(activity)
            except BadRequest as exc:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"Skipped {activity.id}: {exc}"))
                continue
            activity.refresh_from_db(fields=["est_cost_cents"])
            repriced += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"Re-priced {activity.id} ({activity.activity_type}): "
                    f"UGX {before or 0:,} -> UGX {activity.est_cost_cents or 0:,}."
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Would re-price' if dry_run else 'Re-priced'} {repriced} "
                f"activit{'y' if repriced == 1 else 'ies'}; {skipped} skipped."
            )
        )
