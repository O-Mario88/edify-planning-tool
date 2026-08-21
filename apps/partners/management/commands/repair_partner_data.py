"""Repair partner-chain ownership conventions in seeded/legacy data.

2026-08-19 audit F12 found two classes of seed damage on the dev/demo data:

1. Partner-delivered activities carrying ``responsible_staff_id`` — one seed
   batch (4 Aug 2026) predates the ownership convention. Partner work is
   owned via ``assigned_partner_id``; the staff side of the handoff lives on
   ``monitored_by_staff_id`` ONLY. No money or credit leaked (the fund and
   target laws key on ``delivery_type``), but every surface keyed on
   ownership reads these rows wrong.

2. Assignments still in an UNSCHEDULED status while already linked to a
   ``scheduled_activity`` — contradictory: the link is only ever written by
   scheduling. The status moves to ``partner_scheduled`` to match reality.

Dry-run by default; ``--apply`` writes, inside one transaction, audited.
"""

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Repair partner-chain ownership conventions (audit F12). Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the repairs (default is a dry-run report).",
        )

    def handle(self, *args, **options):
        from apps.activities.models import Activity
        from apps.partners.models import PartnerAssignment

        apply = options["apply"]

        owned = Activity.objects.filter(
            delivery_type="partner",
            deleted_at__isnull=True,
            responsible_staff_id__isnull=False,
        ).exclude(responsible_staff_id="")
        contradictory = PartnerAssignment.objects.filter(
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
            scheduled_activity__isnull=False,
        )

        self.stdout.write(
            f"partner activities carrying responsible_staff_id: {owned.count()}"
        )
        self.stdout.write(
            f"unscheduled assignments with a linked activity:  {contradictory.count()}"
        )

        if not apply:
            self.stdout.write(
                self.style.WARNING("Dry-run — nothing written. Use --apply.")
            )
            return

        with transaction.atomic():
            # Preserve the staff pairing on monitored_by where it is missing,
            # then clear the ownership field.
            moved = 0
            for a in owned.filter(monitored_by_staff_id__isnull=True):
                a.monitored_by_staff_id = a.responsible_staff_id
                a.responsible_staff_id = None
                a.save(
                    update_fields=[
                        "monitored_by_staff_id",
                        "responsible_staff_id",
                        "updated_at",
                    ]
                )
                moved += 1
            cleared = owned.update(responsible_staff_id=None)
            # "partner_scheduled" is what the canonical scheduler writes
            # (_partner_schedule_from_assignment) — the model's legacy
            # STATUS_SCHEDULED constant ("scheduled") is a different, older
            # spelling that no current writer produces.
            fixed = contradictory.update(status="partner_scheduled")
            try:
                from apps.audit.services import log as audit_log

                audit_log(
                    action="repair_partner_data",
                    subject_kind="Partner",
                    subject_id="seed-batch",
                    actor_id="system",
                    actor_role="Admin",
                    success=True,
                    reason=(
                        f"F12 repair: {cleared} activities moved to partner "
                        f"ownership ({moved} monitors backfilled); {fixed} "
                        "assignment status(es) aligned to their scheduled activity."
                    ),
                )
            except Exception:  # noqa: BLE001 — repair result still stands
                pass

        self.stdout.write(
            self.style.SUCCESS(
                f"Repaired: {cleared} activities ({moved} monitors backfilled), "
                f"{fixed} assignment(s)."
            )
        )
