"""The ways a withdrawal comes apart without anything visibly breaking.

Each check here watches a combination that stays plausible on screen while
being wrong underneath: a page that renders, totals that add up, and a school
quietly owed support nobody owns.
"""

from __future__ import annotations

from datetime import date

from apps.partners.models import PartnerAssignment
from apps.partners.test_withdrawal import WithdrawalFixture
from apps.partners.withdrawal_models import (
    PartnerAssignmentWithdrawal,
    WithdrawalAttribution,
    WithdrawalDisposition,
    WithdrawalReason,
)
from apps.system_health import planning_oversight_health as health
from apps.partners import withdrawal_service as svc


class WithdrawalHealthTest(WithdrawalFixture):
    def _check(self, key):
        return next(c for c in health.report()["checks"] if c["key"] == key)

    def test_a_clean_withdrawal_reports_nothing(self):
        a = self.assign()
        self.schedule(a)
        svc.withdraw(
            a.id, self.payload(reason_category=WithdrawalReason.CAPACITY), self.pl_user
        )

        for key in (
            "withdrawn_work_still_executable",
            "duplicate_support_slot_holders",
            "replacement_inherited_cost",
            "locked_withdrawal_without_amendment",
            "withdrawal_attribution_mismatch",
        ):
            with self.subTest(check=key):
                self.assertEqual(self._check(key)["count"], 0)

    def test_an_activity_left_live_after_withdrawal_is_an_error(self):
        """The worst failure: the partner still sees work nobody owns."""
        a = self.assign()
        activity = self.schedule(a)
        svc.withdraw(
            a.id, self.payload(reason_category=WithdrawalReason.CAPACITY), self.pl_user
        )
        # Simulate the drift this check exists to catch.
        activity.status = "partner_scheduled"
        activity.save(update_fields=["status"])

        finding = self._check("withdrawn_work_still_executable")

        self.assertEqual(finding["count"], 1)
        self.assertEqual(finding["severity"], "error")
        self.assertIn("still", finding["examples"][0]["actual"])

    def test_two_partners_on_one_slot_is_an_error(self):
        self.assign(support_type="core_visit", visit_number="3")
        self.assign(
            partner=self.replacement, support_type="core_visit", visit_number="3"
        )

        finding = self._check("duplicate_support_slot_holders")

        self.assertEqual(finding["count"], 1)
        self.assertIn("Partner X", finding["examples"][0]["actual"])
        self.assertIn("Partner Y", finding["examples"][0]["actual"])

    def test_a_withdrawn_holder_does_not_count_as_holding_the_slot(self):
        """Otherwise every reassignment would look like a duplicate."""
        a = self.assign(support_type="core_visit", visit_number="3")
        svc.withdraw(
            a.id,
            self.payload(
                disposition=WithdrawalDisposition.REASSIGN_PARTNER,
                replacement_partner_id=self.replacement.id,
            ),
            self.pl_user,
        )

        self.assertEqual(self._check("duplicate_support_slot_holders")["count"], 0)

    def test_the_schema_already_forbids_sharing_the_old_activity(self):
        """Two assignments cannot point at one activity — it is a OneToOne.

        Worth asserting rather than assuming: this is the strongest form of
        the "replacement inherited the old cost" failure, and the database
        refuses it outright. The health check below covers the form that is
        still reachable.
        """
        from django.db import IntegrityError, transaction

        a = self.assign()
        self.schedule(a, cost=180_000)
        w = svc.withdraw(
            a.id,
            self.payload(
                reason_category=WithdrawalReason.CAPACITY,
                disposition=WithdrawalDisposition.REASSIGN_PARTNER,
                replacement_partner_id=self.replacement.id,
            ),
            self.pl_user,
        )

        replacement = w.replacement_assignment
        replacement.scheduled_activity = w.linked_activity
        with self.assertRaises(IntegrityError), transaction.atomic():
            replacement.save(update_fields=["scheduled_activity"])

    def test_a_replacement_priced_before_scheduling_is_an_error(self):
        """The reachable form: its own activity, carrying cost, still unscheduled.

        A replacement is created with no activity at all, so anything priced
        against it before its partner picks a date came from somewhere that
        bypassed the service — and that price is a figure nobody quoted,
        sitting in a live budget.
        """
        from apps.activities.models import Activity, ActivityScheduleCostLine

        a = self.assign()
        w = svc.withdraw(
            a.id,
            self.payload(
                disposition=WithdrawalDisposition.REASSIGN_PARTNER,
                replacement_partner_id=self.replacement.id,
            ),
            self.pl_user,
        )
        replacement = w.replacement_assignment

        premature = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=date.today(),
            planned_month=date.today().month,
            status="partner_scheduled",
            delivery_type="partner",
            assigned_partner_id=self.replacement.id,
        )
        ActivityScheduleCostLine.objects.create(
            activity=premature,
            cost_setting_key="partner_visit_lump_sum",
            label="Copied forward",
            unit_cost=180_000,
            quantity=1,
            amount=180_000,
        )
        replacement.scheduled_activity = premature
        replacement.save(update_fields=["scheduled_activity"])

        finding = self._check("replacement_inherited_cost")

        self.assertEqual(finding["count"], 1)
        self.assertEqual(finding["severity"], "error")
        self.assertIn("180,000", finding["examples"][0]["actual"])

    def test_attribution_that_disagrees_with_its_reason_is_reported(self):
        """A partner marked down for a closed school does not self-correct."""
        a = self.assign()
        w = svc.withdraw(
            a.id,
            self.payload(reason_category=WithdrawalReason.SCHOOL_UNAVAILABLE),
            self.pl_user,
        )
        PartnerAssignmentWithdrawal.objects.filter(id=w.id).update(
            attribution=WithdrawalAttribution.PARTNER
        )

        finding = self._check("withdrawal_attribution_mismatch")

        self.assertEqual(finding["count"], 1)
        self.assertIn("should be school", finding["examples"][0]["actual"])


class RepairCommandTest(WithdrawalFixture):
    def test_the_audit_reports_without_writing(self):
        from io import StringIO

        from django.core.management import call_command

        a = self.assign()
        activity = self.schedule(a)
        svc.withdraw(
            a.id, self.payload(reason_category=WithdrawalReason.CAPACITY), self.pl_user
        )
        activity.status = "partner_scheduled"
        activity.save(update_fields=["status"])

        out = StringIO()
        call_command("audit_partner_withdrawals", stdout=out)

        activity.refresh_from_db()
        self.assertIn("Report only", out.getvalue())
        self.assertEqual(activity.status, "partner_scheduled", "a dry run wrote")

    def test_the_repair_brings_the_activity_into_line_with_the_decision(self):
        from io import StringIO

        from django.core.management import call_command

        a = self.assign()
        activity = self.schedule(a)
        svc.withdraw(
            a.id, self.payload(reason_category=WithdrawalReason.CAPACITY), self.pl_user
        )
        activity.status = "partner_scheduled"
        activity.save(update_fields=["status"])

        call_command("audit_partner_withdrawals", "--repair", stdout=StringIO())

        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")

    def test_the_repair_is_idempotent(self):
        from io import StringIO

        from django.core.management import call_command

        a = self.assign()
        activity = self.schedule(a)
        svc.withdraw(
            a.id, self.payload(reason_category=WithdrawalReason.CAPACITY), self.pl_user
        )
        activity.status = "partner_scheduled"
        activity.save(update_fields=["status"])

        call_command("audit_partner_withdrawals", "--repair", stdout=StringIO())
        second = StringIO()
        call_command("audit_partner_withdrawals", "--repair", stdout=second)

        self.assertIn("Cancelled 0 activity", second.getvalue())


class PartnerPerformanceTest(WithdrawalFixture):
    """A withdrawal rate that counts bad luck is a measure of bad luck."""

    def _record(self, partner=None):
        from apps.partners import performance_service

        target = (partner or self.partner).id
        return next(
            r
            for r in performance_service.build_records(partner_ids=[target])
            if r.partner_id == target
        )

    def test_a_partner_failure_counts(self):
        svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.NOT_SCHEDULED),
            self.pl_user,
        )

        record = self._record()

        self.assertEqual(record.attributable, 1)
        self.assertEqual(record.not_attributable, 0)

    def test_a_closed_school_does_not_count_against_them(self):
        svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.SCHOOL_UNAVAILABLE),
            self.pl_user,
        )

        record = self._record()

        self.assertEqual(record.attributable, 0)
        self.assertEqual(record.not_attributable, 1)
        self.assertEqual(record.withdrawal_rate, 0.0)

    def test_our_own_mistake_does_not_count_against_them(self):
        svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.INCORRECT_ASSIGNMENT),
            self.pl_user,
        )

        self.assertEqual(self._record().attributable, 0)

    def test_a_rejected_request_never_happened_to_the_partner(self):
        a = self.assign()
        self.schedule(a)
        w = svc.request_withdrawal(
            a.id,
            self.payload(reason_category=WithdrawalReason.POOR_QUALITY),
            self.cceo_user,
        )
        svc.review_request(w.id, {"decision": "reject"}, self.pl_user)

        record = self._record()

        self.assertEqual(record.attributable, 0)
        self.assertEqual(record.not_attributable, 0)

    def test_a_partner_holding_nothing_has_no_rate_rather_than_a_perfect_one(self):
        """0% would read as a flawless record instead of an empty one."""
        record = self._record(partner=self.replacement)

        self.assertEqual(record.total_assignments, 0)
        self.assertIsNone(record.withdrawal_rate)

    def test_one_withdrawal_is_not_a_pattern(self):
        """The spec forbids terminating on the strength of a single event."""
        svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.NOT_SCHEDULED),
            self.pl_user,
        )

        self.assertFalse(self._record().has_pattern)

    def test_a_repeated_attributable_pattern_is_flagged_for_review(self):
        from apps.partners import performance_service

        for _ in range(3):
            svc.withdraw(
                self.assign().id,
                self.payload(reason_category=WithdrawalReason.NOT_SCHEDULED),
                self.pl_user,
            )

        record = self._record()
        self.assertTrue(record.has_pattern)
        flagged = performance_service.partners_needing_review([record])
        self.assertEqual([r.partner_id for r in flagged], [self.partner.id])

    def test_repeated_bad_luck_is_never_a_pattern(self):
        """Four closed schools is a real problem, but not a performance one."""
        for _ in range(4):
            svc.withdraw(
                self.assign().id,
                self.payload(reason_category=WithdrawalReason.SCHOOL_UNAVAILABLE),
                self.pl_user,
            )

        record = self._record()

        self.assertFalse(record.has_pattern)
        self.assertEqual(record.not_attributable, 4)
        self.assertEqual(record.withdrawal_rate, 0.0)


class PartnerHoldTest(WithdrawalFixture):
    """A hold stops NEW work. It must never touch work already in flight."""

    def _hold(self, principal=None, **over):
        from datetime import date, timedelta

        payload = {
            "reason_category": WithdrawalReason.REPEATED_EVIDENCE_RETURN,
            "reason": "Three evidence packs returned this term; pausing new work.",
            "effective_from": date.today(),
            "review_on": date.today() + timedelta(days=30),
        }
        payload.update(over)
        return svc.place_hold(self.partner.id, payload, principal or self.pl_user)

    def test_a_hold_blocks_new_assignments(self):
        from apps.core.exceptions import ConflictError

        self._hold()

        with self.assertRaises(ConflictError) as caught:
            self.assign()

        self.assertIn("on hold", str(caught.exception))

    def test_a_hold_leaves_existing_work_completely_alone(self):
        """The whole distinction between holding a partner and withdrawing."""
        existing = self.assign()
        activity = self.schedule(existing)

        self._hold()

        existing.refresh_from_db()
        activity.refresh_from_db()
        self.assertEqual(existing.status, PartnerAssignment.STATUS_SCHEDULED)
        self.assertEqual(activity.status, "partner_scheduled")
        self.assertEqual(PartnerAssignmentWithdrawal.objects.count(), 0)

    def test_another_partner_is_unaffected(self):
        self._hold()
        self.assign(partner=self.replacement)  # must not raise

    def test_a_hold_needs_a_review_date(self):
        """Without one it is a quiet offboarding nobody decided to make."""
        from apps.core.exceptions import BadRequest

        with self.assertRaises(BadRequest) as caught:
            self._hold(review_on=None)

        self.assertIn("review date", str(caught.exception))

    def test_lifting_the_hold_lets_new_work_through_again(self):
        self._hold()
        svc.lift_hold(self.partner.id, self.pl_user)

        self.assign()  # must not raise

    def test_holding_twice_keeps_one_live_hold(self):
        first = self._hold()
        second = self._hold()

        self.assertEqual(first.id, second.id)

    def test_a_role_without_the_permission_cannot_hold_a_partner(self):
        from apps.core.exceptions import Forbidden

        with self.assertRaises(Forbidden):
            self._hold(principal=self.cceo_user)

    def test_a_held_partner_cannot_receive_a_reassignment_either(self):
        """Otherwise withdrawal becomes a side door into a held partner."""
        from apps.core.exceptions import ConflictError

        a = self.assign()
        svc.place_hold(
            self.replacement.id,
            {
                "reason_category": WithdrawalReason.CAPACITY,
                "reason": "Partner has told us they are at capacity this term.",
                "review_on": __import__("datetime").date.today(),
            },
            self.pl_user,
        )

        with self.assertRaises(ConflictError):
            svc.withdraw(
                a.id,
                self.payload(
                    disposition=WithdrawalDisposition.REASSIGN_PARTNER,
                    replacement_partner_id=self.replacement.id,
                ),
                self.pl_user,
            )
