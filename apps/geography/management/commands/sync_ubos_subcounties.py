from django.core.management.base import BaseCommand

from apps.geography.ubos_registry import ensure_ubos_subcounties


class Command(BaseCommand):
    help = (
        "Add missing coded UBOS NPHC 2024 sub-counties to the School Directory "
        "geography. Existing rows and school assignments are never rewritten."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without changing the database.",
        )

    def handle(self, *args, **options):
        stats = ensure_ubos_subcounties(dry_run=options["dry_run"])
        mode = "Dry run" if options["dry_run"] else "Sync"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: {stats['created']} created; "
                f"{stats['planned_create']} missing identities found; "
                f"{stats['matched_by_name']} matched by existing name; "
                f"{stats['already_coded']} already coded; "
                f"{stats['missing_parent_district']} missing parent districts; "
                f"{stats['non_spatial_excluded']} non-spatial reporting rows excluded."
            )
        )
