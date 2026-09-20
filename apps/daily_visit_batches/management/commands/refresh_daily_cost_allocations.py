"""Upgrade editable planned days to exact daily allocation snapshots."""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.exceptions import BadRequest
from apps.daily_visit_batches.models import DailyVisitBatch
from apps.daily_visit_batches.services import (
    _is_locked,
    _recalculate_and_write_lines,
    batch_needs_repricing,
    attach_activity_to_batch,
    batch_poolable,
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
        from apps.activities.models import Activity
        from apps.activities.services import _funding_owner_id
        from apps.accounts.models import User
        from apps.daily_visit_batches.pricing import DAILY_BATCH_ELIGIBLE_TYPES, DAY_POOL_EXTRA_TYPES

        # Older individually priced work (including core visits) must join its
        # owner's existing day before its neighbours can receive the correct share.
        unbatched = Activity.objects.filter(
            daily_visit_batch__isnull=True, deleted_at__isnull=True,
            status__in=["planned", "scheduled", "rescheduled"],
            delivery_type="staff", planned_date__isnull=False,
            activity_type__in=DAILY_BATCH_ELIGIBLE_TYPES | DAY_POOL_EXTRA_TYPES,
            paired_in_school_training__isnull=True,
        ).select_related("school__district", "cluster__district", "event_district")
        if options["fy"]:
            unbatched = unbatched.filter(fy=options["fy"])
        unattached = attached = skipped = 0
        for activity in unbatched.order_by("planned_date", "id"):
            if not batch_poolable(activity):
                continue
            owner_id = _funding_owner_id(activity, None)
            if not owner_id or not User.objects.filter(pk=owner_id).exists():
                skipped += 1
                continue
            unattached += 1
            day_batch = DailyVisitBatch.objects.filter(
                responsible_user=owner_id, visit_date=activity.planned_date
            ).first()
            completed_day = day_batch and day_batch.activities.filter(deleted_at__isnull=True).exclude(
                status__in=["planned", "scheduled", "rescheduled", "cancelled", "deferred", "rejected"]
            ).exists()
            if _is_locked(owner_id, activity.planned_date) or completed_day:
                skipped += 1
                continue
            if options["apply"]:
                try:
                    with transaction.atomic():
                        if attach_activity_to_batch(activity, responsible_user_id=owner_id):
                            attached += 1
                        else:
                            skipped += 1
                except BadRequest as exc:
                    skipped += 1
                    self.stdout.write(f"Skipped activity {activity.id}: {exc}")
        self.stdout.write(f"Unbatched eligible={unattached}, attached={attached}, skipped={skipped}.")
        self.stdout.write(
            f"{'APPLY' if options['apply'] else 'DRY RUN'}: "
            f"outdated={found}, refreshed={refreshed}, locked_or_blocked={locked}. "
            "Approved/disbursed requests are preserved; return editable requests before retrying."
        )
