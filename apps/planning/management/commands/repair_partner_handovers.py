"""Reconcile partner-delivered activities with the handover records that own them.

Partner Oversight reads PartnerAssignment. An activity that no assignment
points at is invisible there — the work happened, the money moved, and the
person answerable for partner delivery sees neither.

Two conditions reach that state, and they are not the same problem:

    linkable       the activity names a partner. The handover was simply never
                   opened (or was opened and never linked). A command can fix
                   this exactly: there is one organisation it can only be.

    no partner     the activity's delivery channel says "partner" and no
                   partner is named. There is nothing to link it to. The row
                   is internally contradictory: priced at partner rates,
                   attributed to a member of staff, with no organisation on
                   the hook. Restating the channel is the honest correction —
                   and the channel decides the price, so it is opt-in and
                   re-prices through the canonical costing service rather than
                   editing a field and leaving the money behind.

Reports by default and changes nothing:

    manage.py repair_partner_handovers                    # dry run
    manage.py repair_partner_handovers --repair           # open missing handovers
    manage.py repair_partner_handovers --restate-channel  # + re-cost the rest
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Reconcile partner activities with their handover records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--repair",
            action="store_true",
            help="Open the missing handover for activities that name a partner.",
        )
        parser.add_argument(
            "--attribute-partner",
            default="",
            help=(
                "Comma-separated partner id(s) to record as the deliverers of "
                "activities that claim partner delivery and name nobody. Opens "
                "each handover and leaves the cost untouched. The operator "
                "names the partners; where several are given the command "
                "distributes deterministically among exactly those, so it "
                "never chooses which organisations are on the hook."
            ),
        )
        parser.add_argument(
            "--restate-channel",
            action="store_true",
            help=(
                "Also restate delivery_type to 'staff' for partner-delivered "
                "activities naming no partner, and re-price them. Touches money."
            ),
        )

    def handle(self, *args, **options):
        from django.db.models import Q

        from apps.activities.models import Activity
        from apps.partners.models import PartnerAssignment

        # `assigned_partner_id` is a plain CharField, so "no partner" is both
        # NULL and the empty string — a filter that checks only one of them
        # reports half the rows and calls the rest healthy.
        no_partner = Q(assigned_partner_id__isnull=True) | Q(assigned_partner_id="")

        claimed = set(
            PartnerAssignment.objects.filter(
                scheduled_activity__isnull=False
            ).values_list("scheduled_activity_id", flat=True)
        )
        partner_work = Activity.objects.filter(
            deleted_at__isnull=True, delivery_type="partner"
        ).exclude(status__in=("cancelled", "draft"))

        linkable = [
            a
            for a in partner_work.exclude(no_partner)
            if a.id not in claimed
        ]
        orphaned = list(partner_work.filter(no_partner))

        self.stdout.write("")
        self.stdout.write("PARTNER HANDOVER RECONCILIATION")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  partner-delivered activities   {partner_work.count()}")
        self.stdout.write(f"  missing a handover (linkable)  {len(linkable)}")
        self.stdout.write(f"  delivery=partner, no partner   {len(orphaned)}")
        self.stdout.write("")

        if linkable:
            for a in linkable[:10]:
                self.stdout.write(
                    f"  [linkable] {a.id} · {a.activity_type} · {a.status}"
                )
            if len(linkable) > 10:
                self.stdout.write(f"  … and {len(linkable) - 10} more")

        if options["repair"] and linkable:
            opened = self._open_handovers(linkable)
            self.stdout.write(
                self.style.SUCCESS(f"Opened {opened} handover record(s).")
            )
        elif linkable:
            self.stdout.write("  Re-run with --repair to open these handovers.")

        if not orphaned:
            return

        self.stdout.write("")
        self.stdout.write(
            f"{len(orphaned)} activit(ies) claim partner delivery and name no "
            "partner. There is nobody to hand them to, so no handover can be "
            "opened for them."
        )
        partner_id = (options["attribute_partner"] or "").strip()
        if partner_id:
            attributed = self._attribute(orphaned, partner_id)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Recorded {attributed} activit(ies) against the named "
                    "partner(s) and opened their handovers. Costs unchanged."
                )
            )
            return

        if not options["restate_channel"]:
            self.stdout.write("")
            self.stdout.write("  Two ways to settle these, and they are different claims:")
            self.stdout.write(
                "    --attribute-partner <ids>  a partner did deliver this work "
                "and the record simply never said which. Opens the handover; "
                "the partner-rate cost stands."
            )
            self.stdout.write(
                "    --restate-channel          no partner delivered it, so the "
                "channel is wrong. Sets delivery_type='staff' and re-prices "
                "through the costing service."
            )
            self._report_exposure(orphaned)
            return

        restated, repriced = self._restate(orphaned)
        self.stdout.write(
            self.style.SUCCESS(
                f"Restated {restated} activit(ies) to staff delivery; "
                f"{repriced} re-priced."
            )
        )

    # ── linkable ────────────────────────────────────────────────────────────
    def _open_handovers(self, activities) -> int:
        from apps.activities.services import _ensure_partner_handover

        opened = 0
        for activity in activities:
            with transaction.atomic():
                _ensure_partner_handover(activity, {})
            opened += 1
        return opened

    def _attribute(self, activities, partner_ids: str) -> int:
        """Name the partner that delivered work the record left anonymous.

        The operator supplies the ids. A command that reached for "any active
        partner" would put real work — and the money attached to it — against
        an organisation that never did it, which is why there is no default
        and no heuristic. Given several, work is spread round-robin over
        exactly the ones named, in a stable order, so the same input always
        produces the same attribution.
        """
        from apps.activities.services import _ensure_partner_handover
        from apps.audit.services import log
        from apps.partners.models import Partner

        wanted = [p.strip() for p in partner_ids.split(",") if p.strip()]
        partners = list(Partner.objects.filter(id__in=wanted).order_by("id"))
        missing = set(wanted) - {p.id for p in partners}
        if missing:
            self.stderr.write(f"No partner with id {', '.join(sorted(missing))}.")
        if not partners:
            return 0

        done = 0
        for index, activity in enumerate(activities):
            partner = partners[index % len(partners)]
            with transaction.atomic():
                activity.assigned_partner_id = partner.id
                activity.save(update_fields=["assigned_partner_id", "updated_at"])
                _ensure_partner_handover(activity, {})
                log(
                    action="partner_handover.partner_attributed",
                    subject_kind="Activity",
                    subject_id=activity.id,
                    payload={"partner_id": partner.id, "partner": partner.name},
                )
            done += 1
        return done

    # ── no partner named ────────────────────────────────────────────────────
    def _report_exposure(self, activities) -> None:
        """What restating would move, before anybody decides to move it."""
        from apps.activities.models import ActivityScheduleCostLine

        total = (
            ActivityScheduleCostLine.objects.filter(
                activity_id__in=[a.id for a in activities]
            )
            .values_list("amount", flat=True)
        )
        amounts = [x for x in total if x is not None]
        self.stdout.write(
            f"  current recorded cost across those activities: "
            f"UGX {sum(amounts):,.0f} over {len(amounts)} cost line(s)"
        )

    def _restate(self, activities) -> tuple[int, int]:
        from apps.audit.services import log

        restated = repriced = 0
        for activity in activities:
            with transaction.atomic():
                previous = activity.delivery_type
                activity.delivery_type = "staff"
                activity.executor_type = "staff"
                activity.save(
                    update_fields=["delivery_type", "executor_type", "updated_at"]
                )
                restated += 1
                if self._reprice(activity):
                    repriced += 1
                log(
                    action="partner_handover.channel_restated",
                    subject_kind="Activity",
                    subject_id=activity.id,
                    payload={
                        "from": previous,
                        "to": "staff",
                        "reason": "delivery channel named no partner",
                    },
                )
        return restated, repriced

    @staticmethod
    def _reprice(activity) -> bool:
        """Re-cost through the canonical service, never by editing amounts."""
        try:
            from apps.budget.costing_service import apply_to_activity

            apply_to_activity(
                activity,
                {
                    "activityType": activity.activity_type,
                    "deliveryType": "staff",
                    "districtType": "primary",
                    "teachersAttended": activity.teachers_attended or 0,
                    "leadersAttended": activity.leaders_attended or 0,
                    "otherParticipants": activity.other_participants or 0,
                    "nights": 0,
                    "fy": activity.fy,
                },
                responsible_user_id=activity.responsible_staff_id,
            )
            return True
        except Exception:  # noqa: BLE001 - a repricing failure must be visible
            return False
