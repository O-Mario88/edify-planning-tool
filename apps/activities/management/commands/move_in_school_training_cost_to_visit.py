"""List, and with --apply move, in-school Training costs onto their School Visits.

Migration 0060 moves them once on deploy; this command shows what is left
afterwards (a pair whose money had already moved is kept as it was). The rule
is ``apps.activities.pair_costing``.
"""

from django.core.management.base import BaseCommand

from apps.activities.pair_costing import (
    find_pair_trainings_carrying_cost,
    move_pair_costs_to_visits,
)


class Command(BaseCommand):
    help = (
        "List undelivered in-school Trainings that still carry the visit cost "
        "their paired School Visit should carry. --apply moves it."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Move the cost. Without it nothing is written.",
        )

    def handle(self, *args, **options):
        ids = find_pair_trainings_carrying_cost()
        if not ids:
            self.stdout.write("No in-school Training carries its visit's cost.")
            return
        if options["apply"]:
            result = move_pair_costs_to_visits(ids, write=self.stdout.write)
            self.stdout.write(
                f"Moved {len(result['moved'])}, kept {len(result['skipped'])}."
            )
            return
        self.stdout.write(
            f"Would move the cost of {len(ids)} in-school Training(s) to their "
            "School Visits:"
        )
        for activity_id in ids:
            self.stdout.write(f"  {activity_id}")
