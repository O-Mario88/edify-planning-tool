"""Credit partner-delivered SSA assessments to the partner that collected them.

Until 2026-09-12 completing a partner's SSA Support recorded the assessment
with the keyer as collector and no partner, so the partner's fieldwork was
invisible to "SSA performance by partner". Every completion is audited with
the SSA record it wrote (action ``complete_partner_ssa_support``, payload
``ssa_record_id``), so the repair is exact: it touches only those records, and
only where no partner is recorded yet. Verification status is left as it is.

    python manage.py repair_partner_ssa_attribution            # report only
    python manage.py repair_partner_ssa_attribution --apply    # write
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Record the partner on SSA assessments completed from partner SSA Support."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Write; otherwise report only."
        )

    def handle(self, *args, **options):
        from apps.activities.models import Activity
        from apps.audit.models import AuditLog
        from apps.ssa.models import SsaRecord

        pairs = []
        for entry in AuditLog.objects.filter(
            action="complete_partner_ssa_support", success=True
        ).only("subject_id", "payload"):
            record_id = (entry.payload or {}).get("ssa_record_id")
            if record_id and entry.subject_id:
                pairs.append((str(record_id), str(entry.subject_id)))
        partners = dict(
            Activity.objects.filter(
                id__in={activity for _, activity in pairs},
                assigned_partner_id__isnull=False,
            ).values_list("id", "assigned_partner_id")
        )
        updates = {
            record: partners[activity]
            for record, activity in pairs
            if activity in partners
        }
        missing = list(
            SsaRecord.objects.filter(
                id__in=list(updates), collected_by_partner_id__isnull=True
            ).values_list("id", flat=True)
        )
        self.stdout.write(
            f"partner SSA completions audited: {len(pairs)}; "
            f"records without their partner: {len(missing)}"
        )
        if not options["apply"]:
            self.stdout.write("report only — pass --apply to write")
            return
        with transaction.atomic():
            for record_id in missing:
                SsaRecord.objects.filter(
                    id=record_id, collected_by_partner_id__isnull=True
                ).update(collected_by_partner_id=updates[record_id])
        self.stdout.write(self.style.SUCCESS(f"credited {len(missing)} records"))
