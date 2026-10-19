"""Confirm the staff SSA a Programme Lead has approved that the old rule
left pending: a lead's own, and a CCEO's keyed on a visit the lead approved
(owner, 2026-10-16). See ``apps.ssa.pl_confirmation``; migration ssa 0011
runs it on deploy.

DRY RUN BY DEFAULT. Pass --apply to write.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Confirm pending staff SSA a Programme Lead keyed or approved "
        "(dry run unless --apply)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def handle(self, *args, **options):
        from apps.ssa.pl_confirmation import confirm_left_pending

        apply = options["apply"]
        rows = confirm_left_pending(apply=apply)
        for row in rows:
            outcome = f" skipped: {row['skipped']}" if "skipped" in row else ""
            self.stdout.write(
                f"{row['id']}: school {row['school']} FY{row['fy']} "
                f"({row['basis']}){outcome}"
            )
        self.stdout.write(
            f"{'Confirmed' if apply else 'Would confirm'}: {len(rows)} SSA "
            f"record{'' if len(rows) == 1 else 's'}."
        )
        if not apply:
            self.stdout.write("Dry run: nothing was changed. Pass --apply to write.")
