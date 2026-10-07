"""
Management command: settle_closed_schools

Report — and with --apply, release — what closed schools still hold: an
invitation to a cluster session not yet held, a project enrolment with no
project work behind it, an open data-quality issue.

Closing a school has released all three since 2026-10-07; a school closed
before that kept them (apps.schools.closed_school_settlement). The deploy ran
the same repair once as schools migration 0024. This stays for a dry run and
for any drift.

Usage:
    python manage.py settle_closed_schools            # report only
    python manage.py settle_closed_schools --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Report or release what closed schools still hold."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Release it. Without this the command only reports.",
        )

    def handle(self, *args, **options):
        from apps.schools import closed_school_settlement as settlement

        found = settlement.find_live()
        if not found:
            self.stdout.write("No closed school holds anything.")
            return
        for row in found:
            self.stdout.write(row.line())
        if not options["apply"]:
            self.stdout.write(
                f"{len(found)} closed school(s) still hold something. "
                "Run again with --apply to release it."
            )
            return
        for row in found:
            result = settlement.settle(row.school_pk)
            self.stdout.write(
                f"  {row.school_code or row.school_pk}: left "
                f"{result['invitations']} session(s) and {result['projects']} "
                f"project(s); {result['issues']} issue(s) closed."
            )
        left = settlement.find_live()
        self.stdout.write(
            f"Done. {len(left)} closed school(s) keep an enrolment their "
            "project delivered work under."
            if left
            else "Done. No closed school holds anything."
        )
