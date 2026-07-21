"""Repair the measured data-integrity defects (verification audit, Tier 1).

Idempotent, dry-run by default, every change counted and audited:
  * 222 CorePlans whose school_id matches no School row (archived, not deleted)
  * CoreActivitySlot.status casing split ('Planned' vs 'planned')
  * Activity rows with status='verified' — not a member of ActivityStatus;
    the real chain's equivalent is ia_verified.
"""

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Repair orphan CorePlans, slot-status casing, and out-of-enum activity statuses."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes.")

    def handle(self, *args, **opts):
        from apps.activities.models import Activity
        from apps.core_schools.models import CoreActivitySlot, CorePlan
        from apps.schools.models import School

        apply = opts["apply"]
        real = set(School.objects.values_list("school_id", flat=True))
        orphans = CorePlan.objects.exclude(school_id__in=real).exclude(
            status="Archived"
        )
        lower = CoreActivitySlot.objects.filter(status="planned")
        bad_status = Activity.objects.filter(status="verified")

        self.stdout.write(
            f"orphan CorePlans: {orphans.count()} | lowercase slots: "
            f"{lower.count()} | activities status='verified': {bad_status.count()}"
        )
        if not apply:
            self.stdout.write("DRY RUN — pass --apply to write.")
            return

        with transaction.atomic():
            n1 = orphans.update(status="Archived")
            n2 = lower.update(status="Planned")
            n3 = bad_status.update(status="ia_verified")
        from apps.audit.services import log as audit_log

        audit_log(
            action="system.core_data_repair",
            subject_kind="CorePlan",
            subject_id="bulk",
            payload={"archived_orphans": n1, "slot_casings": n2, "statuses": n3},
        )
        self.stdout.write(f"APPLIED: archived={n1} recased={n2} restatused={n3}")
