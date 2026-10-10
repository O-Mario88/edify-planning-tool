"""File parked SSA rows whose School ID now names a school."""

from django.core.management.base import BaseCommand

from apps.ssa.unmatched_service import refile_known


class Command(BaseCommand):
    help = (
        "File the rows of the Unmatched SSA queue whose School ID now exists "
        "in the School Directory (exact match only). Reports without writing "
        "unless --apply is given."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the records.")

    def handle(self, *args, **options):
        result = refile_known(apply=options["apply"])
        verb = "Filed" if options["apply"] else "Would file"
        self.stdout.write(f"{verb}: {len(result['filed'])}")
        for school_id in result["filed"]:
            self.stdout.write(f"  {school_id}")
        self.stdout.write(f"Left in the queue: {len(result['skipped'])}")
        for school_id, reason in result["skipped"]:
            self.stdout.write(f"  {school_id}: {reason}")
