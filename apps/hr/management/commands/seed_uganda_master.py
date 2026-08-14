import json

from django.core.management.base import BaseCommand

from apps.hr.uganda_master_seeding import seed_uganda_master


class Command(BaseCommand):
    help = (
        "Idempotently import the Uganda Master Priority Plan (country-level "
        "milestones from Priorities.docx) in draft for CD confirmation."
    )

    def add_arguments(self, parser):
        parser.add_argument("--fy", default="2027")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--actor-id", default="management-command")

    def handle(self, *args, **options):
        report = seed_uganda_master(
            fy=options["fy"],
            actor_id=options["actor_id"],
            dry_run=options["dry_run"],
        )
        report["dryRun"] = options["dry_run"]
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
