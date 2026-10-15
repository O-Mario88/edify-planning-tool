"""Hand in a CCEO's or a Programme Lead's work that holds its Salesforce ID
but was never handed in, and approve a lead's own (owner, 2026-10-15). See
``apps.pl_review.handed_in``; migration 0067 runs it on deploy.

DRY RUN BY DEFAULT. Pass --apply to write.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Hand in staff work that holds its Salesforce ID but was never handed "
        "in, and approve a Programme Lead's own (dry run unless --apply)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def handle(self, *args, **options):
        from apps.pl_review.handed_in import hand_in_entered_work

        apply = options["apply"]
        rows = hand_in_entered_work(apply=apply)
        for row in rows:
            self.stdout.write(f"{row['id']}: {row['from']} -> {row['to']}")
        self.stdout.write(
            f"{'Handed in' if apply else 'Would hand in'}: {len(rows)} activit"
            f"{'y' if len(rows) == 1 else 'ies'}."
        )
        if not apply:
            self.stdout.write("Dry run: nothing was changed. Pass --apply to write.")
