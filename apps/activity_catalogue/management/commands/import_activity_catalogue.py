import json

from django.core.management.base import BaseCommand, CommandError

from apps.activity_catalogue.importer import import_catalogue


class Command(BaseCommand):
    help = "Preview or commit an authorized Activity Catalogue CSV/XLSX import."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--actor-id", default="management-command")

    def handle(self, *args, **options):
        result = import_catalogue(
            options["path"],
            actor_id=options["actor_id"],
            commit=options["commit"],
        )
        self.stdout.write(json.dumps(result, indent=2, default=str))
        if not result["valid"]:
            raise CommandError("Catalogue import validation failed; nothing committed.")
