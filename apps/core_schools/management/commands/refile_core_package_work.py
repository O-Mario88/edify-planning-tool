"""Put Core package work in the package of the year it is planned for.

Owner, 2026-10-02: first and second visits staff had planned were not showing
as V1..V4 on Core Schools, and trainings read four out of four. Work planned
in September for October was booked into the FY2026 package; cluster meetings
and data collection visits took package slots; and group trainings took them
whatever the 2 + 2 split. New work is filed correctly as it is saved
(apps.core_schools.package_year); this moves what is already there — the same
repair migration core_schools 0008 applies on deploy, for a database that
gains misfiled work some other way (an import, a restore).

DRY RUN BY DEFAULT. Pass --apply to write.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Move Core School visits and trainings to the package of the fiscal "
        "year they are dated in, give back the slots held by cluster meetings "
        "and data collection visits, and put group trainings on the half of "
        "whoever delivers them (dry run unless --apply)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")
        parser.add_argument(
            "--from-fy",
            default=None,
            help="Earliest fiscal year whose packages are cleared of them "
            "(default: the running year).",
        )

    def handle(self, *args, **options):
        from apps.activities.models import Activity, ClusterActivityAttendance
        from apps.core.fy import get_operational_fy
        from apps.core_schools import package_year
        from apps.core_schools.models import CoreActivitySlot, CorePlan
        from apps.projects.models import projects_outside_ssa
        from apps.schools.models import School

        apply = options["apply"]
        report = package_year.refile(
            CorePlan,
            CoreActivitySlot,
            Activity,
            ClusterActivityAttendance,
            School,
            from_fy=str(options["from_fy"] or get_operational_fy()),
            write=apply,
            out=self.stdout.write,
            outside_projects=projects_outside_ssa(),
        )
        if report["unplaced"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(report['unplaced'])} item(s) were left where they are."
                )
            )
        if not apply:
            self.stdout.write("Dry run — nothing was written. Re-run with --apply.")
