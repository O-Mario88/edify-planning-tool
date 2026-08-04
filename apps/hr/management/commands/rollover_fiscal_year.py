import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.hr.fiscal_year_rollover import rollover_fiscal_year


class Command(BaseCommand):
    help = "Idempotently open the current FY while preserving prior-FY history."

    def add_arguments(self, parser):
        parser.add_argument("--fy")
        parser.add_argument("--date", dest="as_of")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--actor-id", default="management-command")

    def handle(self, *args, **options):
        try:
            as_of = date.fromisoformat(options["as_of"]) if options["as_of"] else None
            report = rollover_fiscal_year(
                fy=options["fy"],
                as_of=as_of,
                initiated_by=options["actor_id"],
                dry_run=options["dry_run"],
            )
        except (ValueError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
