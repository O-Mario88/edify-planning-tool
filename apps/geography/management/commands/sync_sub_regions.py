from django.core.management.base import BaseCommand

from apps.geography.subregions import sync


class Command(BaseCommand):
    help = (
        "Attach every district to its UBOS sub-region. Idempotent -- re-run "
        "after importing or amending districts."
    )

    def handle(self, *args, **options):
        stats = sync()
        self.stdout.write(
            f"  sub-regions: {stats['subregions']}  "
            f"districts attached: {stats['districts']}"
        )
        if stats["unmatched"]:
            # Named, not silently dropped: an unmatched district is either new
            # and needs adding to the mapping, or it is test residue.
            self.stdout.write(
                self.style.WARNING(
                    f"  {stats['unmatched']} district(s) not in the mapping -- "
                    f"left unassigned"
                )
            )
        if stats["no_region"]:
            self.stdout.write(
                self.style.WARNING(
                    f"  {stats['no_region']} sub-region(s) skipped: parent "
                    f"region missing"
                )
            )
