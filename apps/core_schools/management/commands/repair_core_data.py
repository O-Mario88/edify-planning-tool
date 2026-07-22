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
        from apps.ssa.models import SsaRecord
        from apps.ssa.services import _recompute_readiness

        apply = opts["apply"]
        real = set(School.objects.values_list("school_id", flat=True))
        orphans = CorePlan.objects.exclude(school_id__in=real).exclude(
            status="Archived"
        )
        lower = CoreActivitySlot.objects.filter(status="planned")
        bad_status = Activity.objects.filter(status="verified")

        # Stale readiness: current_fy_ssa_status drives PLANNING eligibility,
        # so a flag left at "done" after its SSA was superseded shows a school
        # as ready when it is not. Recompute from the SsaRecord rows through
        # the canonical function rather than writing the field directly.
        from apps.core.fy import get_operational_fy

        fy = get_operational_fy()
        confirmed = set(
            SsaRecord.objects.filter(
                fy=fy, verification_status="confirmed", deleted_at__isnull=True
            ).values_list("school_id", flat=True)
        )
        # Duplicate Salesforce Activity IDs. The ID is the external system's
        # unique key for the work; two activities sharing one means the
        # verification chain cannot tell them apart. Keep the oldest row's
        # claim and clear the later duplicates, which returns them to the
        # normal "needs a Salesforce ID" state rather than deleting work.
        from django.db.models import Count

        dup_ids = [
            r["salesforce_activity_id"]
            for r in Activity.objects.exclude(salesforce_activity_id__isnull=True)
            .exclude(salesforce_activity_id="")
            .values("salesforce_activity_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        ]
        dup_losers = []
        for sf in dup_ids:
            rows = list(
                Activity.objects.filter(salesforce_activity_id=sf).order_by(
                    "created_at", "id"
                )
            )
            dup_losers.extend(rows[1:])

        stale = [
            s
            for s in School.objects.filter(
                current_fy_ssa_status="done", deleted_at__isnull=True
            )
            if s.id not in confirmed
        ]

        self.stdout.write(
            f"orphan CorePlans: {orphans.count()} | lowercase slots: "
            f"{lower.count()} | activities status='verified': {bad_status.count()} "
            f"| stale readiness flags: {len(stale)} "
            f"| duplicate SF ids: {len(dup_ids)} groups / {len(dup_losers)} rows"
        )
        if not apply:
            self.stdout.write("DRY RUN — pass --apply to write.")
            return

        with transaction.atomic():
            n1 = orphans.update(status="Archived")
            n2 = lower.update(status="Planned")
            n3 = bad_status.update(status="ia_verified")
            n5 = 0
            for a in dup_losers:
                # Never strip an id off a CLOSED activity — the check
                # constraint requires one, and closure is the audited end
                # state. Those need a human decision.
                if a.status == "closed":
                    continue
                a.salesforce_activity_id = None
                a.save(update_fields=["salesforce_activity_id", "updated_at"])
                n5 += 1
            n4 = 0
            for school in stale:
                _recompute_readiness(school)
                n4 += 1
        from apps.audit.services import log as audit_log

        audit_log(
            action="system.core_data_repair",
            subject_kind="CorePlan",
            subject_id="bulk",
            payload={
                "archived_orphans": n1,
                "slot_casings": n2,
                "statuses": n3,
                "readiness_recomputed": n4,
                "salesforce_dups_cleared": n5,
            },
        )
        self.stdout.write(
            f"APPLIED: archived={n1} recased={n2} restatused={n3} "
            f"readiness={n4} sf_dups_cleared={n5}"
        )
