"""Fill every empty Special Project baseline the confirmed evidence supports.

Idempotent: it only fills baselines that are empty, from confirmed readings
dated on or before the enrolment (apps.projects.baselines), so running it again
changes nothing. `--dry-run` reports what it would fill.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.projects.baselines import (
    NOT_CAPTURED,
    _assignments,
    baseline_states,
    capture_missing_baselines,
)


class Command(BaseCommand):
    help = (
        "Capture empty Special Project baselines from the latest confirmed SSA "
        "dated before each enrolment. Never overwrites a captured baseline."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many enrolments would be filled, and write nothing.",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Also re-classify the follow-up of each school that gained a baseline.",
        )

    def handle(self, *args, **options):
        states = baseline_states(_assignments())
        ready = [aid for aid, state in states.items() if state == NOT_CAPTURED]
        waiting = len(states) - len(ready)
        if options["dry_run"]:
            self.stdout.write(
                f"{len(ready)} enrolment(s) can take a baseline now; "
                f"{waiting} have no confirmed SSA before they joined or no "
                "intervention to measure."
            )
            return
        school_ids = set()
        if options["refresh"] and ready:
            from apps.projects.models import ProjectSchoolAssignment

            school_ids = set(
                ProjectSchoolAssignment.objects.filter(id__in=ready).values_list(
                    "school_id", flat=True
                )
            )
        filled = capture_missing_baselines()
        if school_ids:
            from apps.projects.handlers import refresh_school_impact

            for school_id in sorted(school_ids):
                with transaction.atomic():
                    refresh_school_impact(school_id)
        self.stdout.write(
            self.style.SUCCESS(
                f"Captured {filled} baseline(s); {waiting} enrolment(s) still "
                "wait for a confirmed SSA or an intervention."
            )
        )
