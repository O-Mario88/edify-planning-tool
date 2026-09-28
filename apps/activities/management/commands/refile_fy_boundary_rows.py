"""List, and with --apply re-file, work filed under the day before its own.

Migration 0060 re-files once on deploy; this command shows what is left
afterwards. The rule is ``apps.activities.fy_boundary_refile``.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.activities.fy_boundary_refile import find_misfiled, refile_misfiled, report


class Command(BaseCommand):
    help = (
        "List activities, cost lines, advances, budget amendments and SSA "
        "records dated on 1 October, January, April or July that carry the "
        "year or quarter of the day before. --apply re-files them."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Re-file the rows. Without it nothing is written.",
        )

    def handle(self, *args, **options):
        rows = find_misfiled()
        if not rows:
            self.stdout.write("Nothing filed under the day before its own.")
            return
        if options["apply"]:
            with transaction.atomic():
                refile_misfiled(rows, out=self.stdout.write)
            return
        self.stdout.write(f"Would re-file {len(rows)} row(s):")
        for line in report(rows):
            self.stdout.write(line)
