import json

from django.core.management.base import BaseCommand

from apps.hr.priority_seeding import seed_fy2027_priorities


class Command(BaseCommand):
    help = "Idempotently import the five FY2027 RVP priorities and source milestones."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--actor-id", default="management-command")

    def handle(self, *args, **options):
        report = seed_fy2027_priorities(
            actor_id=options["actor_id"], dry_run=options["dry_run"]
        )
        report["dryRun"] = options["dry_run"]
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
