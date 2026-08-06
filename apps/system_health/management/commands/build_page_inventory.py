"""Build the human- and machine-readable platform page inventory."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.system_health.page_inventory import (
    build_page_inventory,
    inventory_as_json,
    inventory_as_markdown,
)


class Command(BaseCommand):
    help = "Build docs/platform-page-inventory.json and .md from live routing metadata."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default=str(Path(settings.BASE_DIR) / "docs"),
            help="Directory for generated inventory artifacts.",
        )

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        inventory = build_page_inventory()

        json_path = output_dir / "platform-page-inventory.json"
        markdown_path = output_dir / "platform-page-inventory.md"
        json_path.write_text(inventory_as_json(inventory), encoding="utf-8")
        markdown_path.write_text(inventory_as_markdown(inventory), encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(
                f"Inventoried {inventory['summary']['routed_surfaces']} routed surfaces: "
                f"{json_path} and {markdown_path}"
            )
        )
