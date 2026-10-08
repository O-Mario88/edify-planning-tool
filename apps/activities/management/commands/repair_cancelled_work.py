"""Put right what earlier cancellations left behind.

Core package slots still pointing at cancelled work are given back and the
package renumbered, and hand-overs left "scheduled by the partner" on a
cancelled activity are put back to waiting for the partner's date (or closed,
where staff had booked them or the year has closed). See
``apps.activities.cancelled_work``.

DRY RUN BY DEFAULT. Pass --apply to write.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Give back Core package slots held by cancelled work, renumber those "
        "packages, and settle partner hand-overs left scheduled on a cancelled "
        "activity (dry run unless --apply)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def handle(self, *args, **options):
        from apps.activities import cancelled_work

        apply = options["apply"]
        report = cancelled_work.repair(write=apply, out=self.stdout.write)
        self.stdout.write(
            f"{'Repaired' if apply else 'Would repair'}: {report['slots']} slot(s) "
            f"given back, {report['renumbered']} renumbered, {report['reopened']} "
            f"hand-over(s) waiting again, {report['closed']} closed, "
            f"{report['skipped']} left."
        )
        if not apply:
            self.stdout.write("Dry run: nothing was changed. Pass --apply to write.")
