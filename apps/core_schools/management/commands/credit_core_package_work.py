"""Count the work already on the calendar in the Core packages.

Owner, 2026-09-27: every visit and training at a Core School counts as V1..V4
/ T1..T4 of its package, wherever it was scheduled. New work is linked as it
is saved (apps.core_schools.package_credit); this brings existing work up to
date — the same repair migration core_schools 0005 applied on deploy, for a
database that gains unlinked work some other way (an import, a restore).

DRY RUN BY DEFAULT. Pass --apply to write.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Link Core School visits and trainings to their package slots, give "
        "back slots partners no longer hold, and hold slots for waiting "
        "handovers (dry run unless --apply)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")
        parser.add_argument("--fy", default=None, help="Limit activities to one FY.")
        parser.add_argument(
            "--school", default=None, help="Limit to one school's business id."
        )

    def handle(self, *args, **options):
        from apps.core_schools.package_credit import repair_package_links

        apply = options["apply"]
        report = repair_package_links(
            apply=apply, fy=options["fy"], school_code=options["school"]
        )
        verb = "" if apply else "Would "
        self.stdout.write(
            f"{verb}release {len(report['released'])} slot(s) held for partners "
            "who no longer hold the work."
        )
        self.stdout.write(
            f"{verb}hold a slot for {len(report['reserved'])} waiting handover(s)."
        )
        self.stdout.write(
            f"{verb}link {len(report['credited'])} visit(s)/training(s) to "
            "their package."
        )
        if report["unplaced"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(report['unplaced'])} item(s) have no package to count "
                    "in (no Core plan for that year, or no open slot)."
                )
            )
        if not apply:
            self.stdout.write("Dry run — nothing was written. Re-run with --apply.")
