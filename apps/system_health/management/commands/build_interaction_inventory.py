"""Build the committed interaction inventory from the live templates and routes."""

from django.core.management.base import BaseCommand

from apps.system_health.interaction_inventory import (
    MANIFEST,
    build_interaction_inventory,
    inventory_as_json,
    inventory_as_markdown,
)


class Command(BaseCommand):
    help = (
        "Build docs/platform-interaction-inventory.json and .md: every template "
        "control with its route, request, roles and automated test evidence."
    )

    def handle(self, *args, **options):
        inventory = build_interaction_inventory()
        MANIFEST.write_text(inventory_as_json(inventory), encoding="utf-8")
        MANIFEST.with_suffix(".md").write_text(
            inventory_as_markdown(inventory), encoding="utf-8"
        )
        summary = inventory["summary"]
        self.stdout.write(
            self.style.SUCCESS(
                f"Inventoried {summary['controls']} controls in "
                f"{summary['templates_scanned']} templates; "
                f"{summary['untested']} with no automated evidence."
            )
        )
