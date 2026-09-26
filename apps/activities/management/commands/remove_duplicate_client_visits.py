"""List, and with --apply remove, duplicate client school visits.

Migration 0058 runs the removal once on deploy; this command shows what is
left afterwards, or removes copies that reached the data some other way (an
import). The rule is ``apps.activities.duplicate_visits``.
"""

from django.core.management.base import BaseCommand

from apps.activities.duplicate_visits import (
    find_duplicate_client_visits,
    remove_duplicate_client_visits,
    report,
)


class Command(BaseCommand):
    help = (
        "List copies of the same visit at the same client school on the same "
        "day, and which copy stays. --apply removes the others."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Remove the duplicates. Without it nothing is written.",
        )

    def handle(self, *args, **options):
        groups = find_duplicate_client_visits()
        if not groups:
            self.stdout.write("No duplicate client school visits.")
            return
        if options["apply"]:
            remove_duplicate_client_visits(groups, out=self.stdout.write)
            return
        copies = sum(len(g.removed) for g in groups)
        self.stdout.write(
            f"Would remove {copies} duplicate client school visit(s) across "
            f"{len(groups)} school-day(s):"
        )
        for line in report(groups):
            self.stdout.write(line)
