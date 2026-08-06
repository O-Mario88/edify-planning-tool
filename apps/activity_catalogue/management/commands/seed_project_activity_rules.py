import json

from django.core.management.base import BaseCommand

from apps.activity_catalogue.project_seeding import (
    seed_known_project_activity_rules,
)


class Command(BaseCommand):
    help = "Seed explicit, code-owned Special Project Activity Catalogue rules."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        result = seed_known_project_activity_rules(
            actor_id="management-command",
            dry_run=options["dry_run"],
        )
        result["dryRun"] = options["dry_run"]
        self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
