import json

from django.core.management.base import BaseCommand, CommandError

from apps.help_center.services import documentation_drift_report, sync_route_contexts


class Command(BaseCommand):
    help = "Audit Knowledge Center route/status coverage and fail on documentation drift."

    def add_arguments(self, parser):
        parser.add_argument("--sync-routes", action="store_true", help="Create missing canonical route mappings before auditing.")
        parser.add_argument("--strict", action="store_true", help="Return non-zero if coverage, status or publication checks fail.")

    def handle(self, *args, **options):
        if options["sync_routes"]:
            self.stdout.write(self.style.SUCCESS(f"Route mappings: {sync_route_contexts()}"))
        report = documentation_drift_report()
        self.stdout.write(json.dumps(report, indent=2, default=str))
        failures = (
            report["missing_routes"] or report["unknown_statuses"] or report["broken_links"]
            or report["published_without_version"]
        )
        if options["strict"] and failures:
            raise CommandError("Knowledge Center documentation drift detected.")
