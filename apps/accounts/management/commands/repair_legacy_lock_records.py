"""Repair command for the "legacy_lock_records" System Health check
(apps.accounts.health.auth_lockout_health) — re-runs the same idempotent
logic as migration 0016_migrate_legacy_permanent_locks against the CURRENT
database, for accounts that started using the pre-Issue-3 "far-future
locked_until = permanent lock" convention after that migration already ran
(e.g. a data import or fixture load).

Usage:
  python manage.py repair_legacy_lock_records            # apply
  python manage.py repair_legacy_lock_records --dry-run   # report only
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User


class Command(BaseCommand):
    help = (
        "Migrate accounts using the legacy far-future locked_until convention "
        "to lockout_escalated=True."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report affected accounts without changing them.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() + timedelta(days=30)
        legacy_locked = User.objects.filter(
            locked_until__gt=cutoff,
            lockout_escalated=False,
        )
        count = legacy_locked.count()

        if count == 0:
            self.stdout.write(
                self.style.SUCCESS("No inconsistent legacy lock records found.")
            )
            return

        for email in legacy_locked.values_list("email", flat=True):
            self.stdout.write(f"  {email}")

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(f"{count} account(s) would be migrated (dry run).")
            )
            return

        legacy_locked.update(lockout_escalated=True, lockout_cycle_count=1)
        self.stdout.write(
            self.style.SUCCESS(
                f"{count} account(s) migrated to lockout_escalated=True."
            )
        )
