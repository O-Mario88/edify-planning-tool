"""Price the in-school Trainings whose School Visit was called off or removed
and that still carry no cost (``apps.activities.pair_costing``). Budget
migration 0025 runs it on deploy.

DRY RUN BY DEFAULT. Pass --apply to write.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Price in-school Trainings whose companion School Visit no longer makes "
        "the journey (dry run unless --apply)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the changes.")

    def handle(self, *args, **options):
        from apps.activities.models import Activity
        from apps.activities.pair_costing import (
            find_stranded_pair_trainings,
            price_stranded_pair_trainings,
        )

        ids = find_stranded_pair_trainings()
        if not options["apply"]:
            for activity in Activity.objects.filter(id__in=ids).select_related(
                "school"
            ):
                self.stdout.write(
                    f"{activity.id}: {getattr(activity.school, 'name', '')} "
                    f"{activity.planned_date}"
                )
            self.stdout.write(
                f"Would price {len(ids)} Training(s). Dry run: nothing was "
                "changed. Pass --apply to write."
            )
            return
        result = price_stranded_pair_trainings(ids, write=self.stdout.write)
        self.stdout.write(
            f"Priced {len(result['priced'])}, kept {len(result['kept'])}."
        )
