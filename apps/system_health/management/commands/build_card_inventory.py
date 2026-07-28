"""Build the machine-readable card inventory the card audit works from."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.system_health.card_inventory import build_inventory


class Command(BaseCommand):
    help = "Build docs/platform-card-inventory.json from template card surfaces."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default=str(Path(settings.BASE_DIR) / "docs"),
            help="Directory for the generated inventory.",
        )
        parser.add_argument(
            "--duplicates-only",
            action="store_true",
            help="Print same-page duplicate card titles and write nothing.",
        )

    def handle(self, *args, **options):
        inventory = build_inventory()

        if options["duplicates_only"]:
            duplicates = inventory.duplicate_titles_within_a_template()
            for template, titles in duplicates.items():
                self.stdout.write(template)
                for title in titles:
                    self.stdout.write(f"    {title}")
            self.stdout.write(f"\n{len(duplicates)} template(s) repeat a card title")
            return

        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "platform-card-inventory.json"
        path.write_text(json.dumps(inventory.as_dict(), indent=1), encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"Wrote {path}"))
        for key, value in inventory.summary().items():
            self.stdout.write(f"  {key}: {value}")
