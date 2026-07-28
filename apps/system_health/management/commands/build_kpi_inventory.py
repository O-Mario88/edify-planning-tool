"""Build the machine-readable KPI inventory the metric audit works from."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.system_health.kpi_inventory import build_inventory


class Command(BaseCommand):
    help = "Build docs/platform-kpi-inventory.json from KPI-building source."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default=str(Path(settings.BASE_DIR) / "docs"),
            help="Directory for the generated inventory.",
        )
        parser.add_argument(
            "--duplicates-only",
            action="store_true",
            help="Print labels built in more than one module and write nothing.",
        )

    def handle(self, *args, **options):
        inventory = build_inventory()
        duplicates = inventory.labels_built_in_several_modules()

        if options["duplicates_only"]:
            for label, modules in duplicates.items():
                self.stdout.write(f"{label}")
                for module in modules:
                    self.stdout.write(f"    {module}")
            self.stdout.write(f"\n{len(duplicates)} label(s) built in >1 module")
            return

        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "platform-kpi-inventory.json"
        path.write_text(json.dumps(inventory.as_dict(), indent=1), encoding="utf-8")

        summary = inventory.summary()
        self.stdout.write(self.style.SUCCESS(f"Wrote {path}"))
        for key, value in summary.items():
            self.stdout.write(f"  {key}: {value}")
