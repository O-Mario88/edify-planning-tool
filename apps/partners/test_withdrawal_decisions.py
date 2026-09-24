"""A withdrawal records the decision it made.

A withdrawn handover is left ``returned_to_staff`` — the status a Partner's own
hand-back uses — and used to carry no decision. Partner Monitoring then offered
Resolve Exception on it, and resolving it again could open a second
replacement for the same support slot. The withdrawal's disposition already
decided what happens next, so that decision is recorded on the handover; holds
and escalations decide nothing and stay open.
"""

from __future__ import annotations

from importlib import import_module

from django.apps import apps as django_apps
from django.utils import timezone

from apps.partners import withdrawal_service
from apps.partners.models import PartnerAssignment
from apps.partners.services import resolve_returned_assignment
from apps.partners.withdrawal_models import PartnerAssignmentWithdrawal
from apps.planning import partner_oversight_service as svc
from apps.planning.test_partner_oversight import PartnerOversightFixture

REASON = {
    "reason_category": "capacity",
    "partner_facing_reason": "The partner cannot staff this term's visits.",
}


class _Fixture(PartnerOversightFixture):
    def withdraw(self, assignment, disposition, **extra):
        return withdrawal_service.withdraw(
            assignment.id,
            {**REASON, "disposition": disposition, **extra},
            self.pl_user,
        )

    def page(self):
        self.client.force_login(self.pl_user)
        return self.client.get(
            "/partner-oversight/", {"partner": self.partner.id}
        ).content.decode()

    def row(self, body, assignment):
        start = body.index(f'data-assignment="{assignment.id}"')
        return body[start : body.index('<tr id="partner-row-details-', start)]


class TheDispositionIsTheDecisionTest(_Fixture):
    def test_each_disposition_records_its_decision(self):
        expected = {
            "reassign_partner": PartnerAssignment.RESOLUTION_REASSIGNED,
            "return_to_planning": PartnerAssignment.RESOLUTION_STAFF_DELIVERY,
            "schedule_as_staff": PartnerAssignment.RESOLUTION_STAFF_DELIVERY,
            "cancel_support": PartnerAssignment.RESOLUTION_SUPPORT_CLOSED,
        }
        for disposition, resolution in expected.items():
            with self.subTest(disposition=disposition):
                assignment = self.assign()
                extra = (
                    {"replacement_partner_id": self.other_partner.id}
                    if disposition == "reassign_partner"
                    else {}
                )
                self.withdraw(assignment, disposition, **extra)
                assignment.refresh_from_db()
                self.assertEqual(assignment.status, "returned_to_staff")
                self.assertEqual(assignment.resolution, resolution)
                self.assertIsNotNone(assignment.resolved_at)
                self.assertEqual(assignment.resolved_by, self.pl_user.id)

    def test_holding_or_escalating_leaves_the_decision_open(self):
        for disposition in ("hold_for_review", "escalate"):
            with self.subTest(disposition=disposition):
                assignment = self.assign()
                self.withdraw(assignment, disposition)
                assignment.refresh_from_db()
                self.assertEqual(assignment.resolution, "")
                self.assertIsNone(assignment.resolved_at)


class NoSecondDecisionTest(_Fixture):
    def test_a_reassigned_withdrawal_offers_no_resolve_and_makes_one_replacement(
        self,
    ):
        assignment = self.assign()
        self.withdraw(
            assignment,
            "reassign_partner",
            replacement_partner_id=self.other_partner.id,
        )

        item = svc.build_item_by_assignment(assignment.id)
        self.assertFalse(item.awaits_staff_decision)
        row = self.row(self.page(), assignment)
        self.assertNotIn("Resolve Exception", row)
        self.assertIn(">Returned<", row)

        # Resolving it again reports the decision already made and creates
        # nothing — never a second replacement for the same slot.
        result = resolve_returned_assignment(
            assignment.id,
            {"resolution": "reassigned", "partner_id": self.other_partner.id},
            self.pl_user,
        )
        self.assertEqual(result["resolution"], "reassigned")
        self.assertEqual(
            PartnerAssignment.objects.filter(replaces_assignment=assignment).count(),
            1,
        )
        self.assertEqual(
            PartnerAssignment.objects.filter(school=self.school)
            .exclude(status="returned_to_staff")
            .count(),
            1,
        )

    def test_a_partners_own_return_still_waits_on_staff(self):
        returned = self.assign(
            status="returned_to_staff",
            return_reason_category="capacity",
            return_reason="No facilitator this term.",
        )

        item = svc.build_item_by_assignment(returned.id)
        self.assertTrue(item.awaits_staff_decision)
        self.assertIn("Resolve Exception", self.row(self.page(), returned))


class EarlierWithdrawalsAreBackfilledTest(_Fixture):
    migration = import_module(
        "apps.partners.migrations.0026_record_withdrawal_decisions"
    )

    def withdrawn_before_the_fix(self, disposition):
        """A handover withdrawn the old way: returned, with no decision."""
        assignment = self.assign()
        extra = (
            {"replacement_partner_id": self.other_partner.id}
            if disposition == "reassign_partner"
            else {}
        )
        self.withdraw(assignment, disposition, **extra)
        PartnerAssignment.objects.filter(id=assignment.id).update(
            resolution="", resolution_note="", resolved_at=None, resolved_by=None
        )
        return assignment

    def test_the_backfill_records_the_decision_from_the_withdrawal(self):
        reassigned = self.withdrawn_before_the_fix("reassign_partner")
        held = self.withdrawn_before_the_fix("hold_for_review")
        partner_return = self.assign(status="returned_to_staff")
        decided = self.assign(
            status="returned_to_staff",
            resolution=PartnerAssignment.RESOLUTION_SUPPORT_CLOSED,
            resolved_at=timezone.now(),
        )

        self.migration.record_withdrawal_decisions(django_apps, None)

        for assignment in (reassigned, held, partner_return, decided):
            assignment.refresh_from_db()
        effective = PartnerAssignmentWithdrawal.objects.get(
            assignment=reassigned
        ).effective_at
        self.assertEqual(reassigned.resolution, "reassigned")
        self.assertEqual(reassigned.resolved_at, effective)
        self.assertEqual(held.resolution, "")
        self.assertIsNone(partner_return.resolved_at)
        self.assertEqual(decided.resolution, "support_closed")
