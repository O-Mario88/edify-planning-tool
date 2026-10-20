"""List, and with --apply change, the School Visit + SSA Collection visits
that become In-school Training + SSA Collection (owner, 2026-10-20).

Migration 0069 applies the change once on deploy; run this first to see the
list against the live data, and afterwards to confirm nothing is left. The
rule is ``apps.activities.ssa_collection_to_training``.
"""

from django.core.management.base import BaseCommand

from apps.activities.ssa_collection_to_training import convert


class Command(BaseCommand):
    help = (
        "List the staff School Visit + SSA Collection visits still on the plan "
        "that become In-school Training + SSA Collection, and the ones left as "
        "they are. --apply changes them."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Change them. Without it nothing is written.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        found = convert(apply=apply)
        converted, left = found["converted"], found["left"]
        verb = "Changed" if apply else "Would change"
        self.stdout.write(
            f"{verb} {len(converted)} School Visit + SSA Collection visit(s) to "
            "In-school Training + SSA Collection (each asks for its training "
            "when completed):"
        )
        for row in converted:
            self.stdout.write(
                f"  {row['id']}  {row['school']} ({row['schoolId']})  "
                f"{row['day']}  {row['status']}  was {row['purposeBefore'] or '-'}"
            )
        self.stdout.write(
            f"Left as they are: {len(left)} (completed, with a reviewer, "
            "returned or cancelled):"
        )
        for row in left:
            self.stdout.write(
                f"  {row['id']}  {row['school']} ({row['schoolId']})  "
                f"{row['day']}  {row['status']}"
            )
        if not apply and converted:
            self.stdout.write("Nothing was written. Run with --apply to change them.")
