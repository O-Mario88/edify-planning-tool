import json

from django.core.management.base import BaseCommand

from apps.activity_catalogue.seeding import seed_activity_catalogue


class Command(BaseCommand):
    help = "Idempotently seed the governed 28-item Edify Activity Catalogue."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--actor-id", default="management-command")

    def handle(self, *args, **options):
        result = seed_activity_catalogue(
            actor_id=options["actor_id"],
            dry_run=options["dry_run"],
        )
        result["dryRun"] = options["dry_run"]
        self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
