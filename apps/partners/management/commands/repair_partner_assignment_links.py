"""Backfill PartnerAssignment.scheduled_activity for rows written before it existed.

Assignments scheduled before the field was added recorded only that they were
scheduled, never which activity they became. Planning oversight does not need
the link to stay correct — it treats a scheduled assignment as represented by
its activity either way, so nothing is double counted — but with the link the
assignment's handover history can be shown on the activity it became, and
System Health can tell a genuinely unpaired row from an unbackfilled one.

The pairing is only asserted where it is unambiguous. Where several activities
could be the one, the row is reported for manual review rather than guessed at:
a wrong pairing would attach one school's handover history to another's.

    manage.py repair_partner_assignment_links            # dry run, changes nothing
    manage.py repair_partner_assignment_links --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.activities.models import Activity
from apps.partners.models import PartnerAssignment

# Statuses that mean "the partner has scheduled this", across the spellings
# live data actually carries.
SCHEDULED_STATUSES = (
    "partner_scheduled",
    "scheduled",
    "completed",
)


class Command(BaseCommand):
    help = "Pair scheduled PartnerAssignments with the Activity they became."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the links. Without it the command only reports.",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options.get("apply"))

        candidates = (
            PartnerAssignment.objects.filter(
                status__in=SCHEDULED_STATUSES,
                scheduled_activity__isnull=True,
            )
            .select_related("school", "cluster")
            .order_by("created_at")
        )

        repairable: list[tuple[PartnerAssignment, Activity]] = []
        manual: list[tuple[PartnerAssignment, str]] = []

        # Activities already claimed by another assignment must not be claimed
        # twice — the field is one-to-one, and a second claim would raise at
        # save time rather than being reported here.
        claimed = set(
            PartnerAssignment.objects.filter(
                scheduled_activity__isnull=False
            ).values_list("scheduled_activity_id", flat=True)
        )

        for pa in candidates:
            matches = self._candidate_activities(pa, claimed)
            if len(matches) == 1:
                repairable.append((pa, matches[0]))
                claimed.add(matches[0].id)
            elif not matches:
                manual.append((pa, "no activity matches this assignment"))
            else:
                manual.append(
                    (pa, f"{len(matches)} activities match; cannot choose safely")
                )

        self.stdout.write("")
        self.stdout.write(
            f"Scheduled assignments with no linked activity: {len(candidates)}"
        )
        self.stdout.write(f"  Repairable (exactly one match): {len(repairable)}")
        self.stdout.write(f"  Manual review required:         {len(manual)}")

        for pa, reason in manual[:20]:
            context = getattr(pa.school, "name", None) or getattr(
                pa.cluster, "name", None
            )
            self.stdout.write(f"    - {pa.id} ({context or 'no context'}): {reason}")
        if len(manual) > 20:
            self.stdout.write(f"    … and {len(manual) - 20} more")

        if not apply_changes:
            self.stdout.write("")
            self.stdout.write("Dry run — nothing written. Re-run with --apply.")
            return

        with transaction.atomic():
            for pa, activity in repairable:
                pa.scheduled_activity = activity
                pa.save(update_fields=["scheduled_activity", "updated_at"])

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Linked {len(repairable)} assignment(s).")
        )
        if manual:
            self.stdout.write(
                f"{len(manual)} still unlinked — these need a human decision. "
                "Oversight counts them correctly regardless; only the handover "
                "history is missing from the activity."
            )

    def _candidate_activities(
        self, pa: PartnerAssignment, claimed: set
    ) -> list[Activity]:
        """Activities that could be what this assignment became.

        Deliberately narrow. Partner, context and date must all agree: the date
        is what separates two assignments handed to the same partner for the
        same school, which is the case a looser match gets wrong.
        """
        if not pa.partner_id or not pa.scheduled_date:
            return []

        qs = Activity.objects.filter(
            deleted_at__isnull=True,
            assigned_partner_id=pa.partner_id,
            planned_date=pa.scheduled_date,
        ).exclude(id__in=claimed)

        if pa.school_id:
            qs = qs.filter(school_id=pa.school_id)
        elif pa.cluster_id:
            qs = qs.filter(cluster_id=pa.cluster_id)
        else:
            return []

        return list(qs.order_by("created_at")[:5])
