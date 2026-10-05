"""Re-price open plans whose saved cost no longer agrees with the catalogue.

Owner, 2026-10-05: "I still see the old cost being fetched like even when the
cost is changed or deleted, it still fetches." Saving a rate re-prices the
plans already made (apps.budget.repricing); this is the same sweep by hand,
for the plans a deploy or a busy save did not reach.

Lists them by default; ``--apply`` re-prices them. A plan whose week has left
draft or whose money has moved is kept at the cost it was approved at.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from apps.budget.repricing import reprice_stale_plans, stale_plan_ids


class Command(BaseCommand):
    help = (
        "Re-price planned, unpaid activities whose saved cost lines carry a "
        "rate the Cost Catalogue has since changed or removed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Re-price them (default: list)."
        )
        parser.add_argument(
            "--minutes",
            type=float,
            default=0,
            help="Stop starting new plans after this many minutes (0: no limit).",
        )

    def handle(self, *args, **options):
        ids = stale_plan_ids()
        if not options["apply"]:
            self.stdout.write(
                f"{len(ids)} planned activit{'y' if len(ids) == 1 else 'ies'} "
                "priced with a cost the catalogue no longer holds. "
                "Run with --apply to re-price them."
            )
            return
        deadline = None
        if options["minutes"]:
            deadline = time.monotonic() + options["minutes"] * 60
        result = reprice_stale_plans(ids, deadline=deadline, write=self.stdout.write)
        self.stdout.write(
            self.style.SUCCESS(
                f"Re-priced {len(result['repriced'])}, kept "
                f"{len(result['kept'])}, not reached {len(result['left'])}."
            )
        )
