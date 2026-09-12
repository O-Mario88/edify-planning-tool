"""Remove the advances that were opened for vendor-direct cost lines.

Until 2026-09-12 every cost line opened a staff advance, including the
school-visit transport that is paid straight to the vendor and that the
weekly fund request deliberately leaves out. Such an advance can never be
requested, so it sat "pending responsible confirmation" in the Accountant's
queue for good. This removes them where no money ever moved.

    python manage.py repair_vendor_direct_advances            # report only
    python manage.py repair_vendor_direct_advances --apply    # delete them
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.fund_requests.fundable import vendor_direct_filter
from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

NEVER_MOVED = (
    AdvanceRequestStatus.DRAFT_FROM_SCHEDULE,
    AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION,
    AdvanceRequestStatus.RETURNED,
)


class Command(BaseCommand):
    help = (
        "Delete advances opened for vendor-direct cost lines whose money never moved."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Delete; otherwise report only."
        )

    def handle(self, *args, **options):
        from apps.activities.models import ActivityScheduleCostLine

        vendor_lines = ActivityScheduleCostLine.objects.filter(
            vendor_direct_filter()
        ).values("id")
        orphans = AdvanceRequest.objects.filter(
            budget_line_id__in=vendor_lines, status__in=NEVER_MOVED
        )
        moved = AdvanceRequest.objects.filter(budget_line_id__in=vendor_lines).exclude(
            status__in=NEVER_MOVED
        )
        count = orphans.count()
        self.stdout.write(f"vendor-direct advances that never moved money: {count}")
        if moved.exists():
            self.stdout.write(
                f"left alone because money moved: {moved.count()} "
                "(they settle through accountability)"
            )
        if not options["apply"]:
            self.stdout.write("report only — pass --apply to delete them")
            return
        with transaction.atomic():
            deleted, _ = orphans.delete()
        self.stdout.write(self.style.SUCCESS(f"deleted {deleted} advance rows"))
