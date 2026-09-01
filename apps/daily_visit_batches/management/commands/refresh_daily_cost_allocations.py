"""Upgrade editable planned days to exact daily allocation snapshots."""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.exceptions import BadRequest
from apps.daily_visit_batches.models import DailyVisitBatch
from apps.daily_visit_batches.services import (
    _is_locked,
    _recalculate_and_write_lines,
    batch_needs_repricing,
)


class Command(BaseCommand):
    help = (
        "Refresh old daily splits and training/meeting costs; dry run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--fy", help="Limit to the activities' fiscal year.")

    def handle(self, *args, **options):
        batches = DailyVisitBatch.objects.all().order_by("visit_date", "id")
        if options["fy"]:
            batches = batches.filter(activities__fy=options["fy"]).distinct()
        found = refreshed = locked = 0
        for batch in batches:
            if not batch_needs_repricing(batch):
                continue
            found += 1
            if (
                _is_locked(batch.responsible_user, batch.visit_date)
                or batch.activities.filter(
                    deleted_at__isnull=True,
                )
                .exclude(
                    status__in=[
                        "planned",
                        "scheduled",
                        "rescheduled",
                        "cancelled",
                        "deferred",
                        "rejected",
                    ]
                )
                .exists()
            ):
                locked += 1
                continue
            if not options["apply"]:
                continue
            try:
                with transaction.atomic():
                    batch = DailyVisitBatch.objects.select_for_update().get(pk=batch.pk)
                    if _is_locked(batch.responsible_user, batch.visit_date):
                        raise BadRequest("The weekly request is no longer editable.")
                    _recalculate_and_write_lines(batch, None, batch.responsible_user)
                refreshed += 1
            except BadRequest as exc:
                locked += 1
                self.stdout.write(f"Skipped {batch.id}: {exc}")
        self.stdout.write(
            f"{'APPLY' if options['apply'] else 'DRY RUN'}: "
            f"outdated={found}, refreshed={refreshed}, locked_or_blocked={locked}. "
            "Approved/disbursed requests are preserved; return editable requests before retrying."
        )
