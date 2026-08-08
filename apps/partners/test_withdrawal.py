"""Taking work back from a partner, without losing anything in the process.

The rules here are the ones that cost real money or real accountability if
they break: an unscheduled handover must cost nothing to withdraw, a scheduled
one must actually leave the budget, the school must not end up owed the same
support twice, and a partner must not be marked down for a school that was
closed.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, ConflictError, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners import withdrawal_service as svc
from apps.partners.models import Partner, PartnerAssignment
from apps.partners.withdrawal_models import (
    PartnerAssignmentWithdrawal,
    WithdrawalAttribution,
    WithdrawalDisposition,
    WithdrawalKind,
    WithdrawalReason,
    WithdrawalState,
)
from apps.schools.models import School

EXPLANATION = "Partner has not responded for three weeks and the term is ending."


class WithdrawalFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.pl_user, cls.pl = cls._staff(
            "mary@w.test", "Mary", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.cceo_user, cls.cceo = cls._staff("james@w.test", "James", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=cls.pl)

        cls.other_pl_user, cls.other_pl = cls._staff(
            "rival@w.test", "Rival Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.other_cceo_user, cls.other_cceo = cls._staff(
            "peter@w.test", "Peter", EdifyRole.CCEO
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.other_cceo, supervisor=cls.other_pl
        )

        cls.school = School.objects.create(
            school_id="s1",
            name="Alpha Primary",
            district=cls.district,
            region=cls.region,
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo, school_id=cls.school.id)
        cls.partner = Partner.objects.create(name="Partner X", active_status=True)
        cls.replacement = Partner.objects.create(name="Partner Y", active_status=True)

    @classmethod
    def _staff(cls, email, name, role):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            status="active",
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=name)

    def assign(self, *, cceo=None, partner=None, support_type="school_visit", **kw):
        return PartnerAssignment.objects.create(
            school=self.school,
            partner=partner or self.partner,
            assigning_staff_id=(cceo or self.cceo).id,
            monitoring_staff_id=(cceo or self.cceo).id,
            expected_activity_type="school_visit",
            focus_intervention="financial_health",
            support_type=support_type,
            status=PartnerAssignment.STATUS_ASSIGNED,
            **kw,
        )

    def schedule(
        self, assignment, *, cost=180_000, when=None, status="partner_scheduled"
    ):
        planned = when or (date.today() + timedelta(days=7))
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=assignment.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month,
            scheduled_date=planned,
            status=status,
            delivery_type="partner",
            assigned_partner_id=assignment.partner_id,
            monitored_by_staff_id=assignment.monitoring_staff_id,
            responsible_staff_id=assignment.monitoring_staff_id,
        )
        if cost:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key="partner_visit_lump_sum",
                label="Partner visit",
                unit_cost=cost,
                quantity=1,
                amount=cost,
                fiscal_year=self.fy,
                month=planned.month,
            )
        assignment.status = PartnerAssignment.STATUS_SCHEDULED
        assignment.scheduled_activity = activity
        assignment.scheduled_date = planned
        assignment.save()
        return activity

    def payload(self, **over):
        base = {
            "reason_category": WithdrawalReason.NOT_SCHEDULED,
            "partner_facing_reason": EXPLANATION,
            "disposition": WithdrawalDisposition.RETURN_TO_PLANNING,
        }
        base.update(over)
        return base


class StateDecidesTheWorkflowTest(WithdrawalFixture):
    """One action, several workflows — chosen by the record, not the reader."""

    def test_an_unscheduled_handover_is_an_outright_withdrawal(self):
        self.assertEqual(
            svc.resolve_kind(self.assign()), WithdrawalKind.WITHDRAW_UNSCHEDULED
        )

    def test_a_scheduled_but_unstarted_activity_is_a_recall(self):
        a = self.assign()
        self.schedule(a)
        self.assertEqual(svc.resolve_kind(a), WithdrawalKind.RECALL_SCHEDULED)

    def test_work_under_way_is_a_suspension_not_a_withdrawal(self):
        a = self.assign()
        self.schedule(a, status="in_progress")
        self.assertEqual(svc.resolve_kind(a), WithdrawalKind.SUSPEND_IN_PROGRESS)

    def test_submitted_evidence_is_a_quality_review(self):
        a = self.assign()
        act = self.schedule(a, status="evidence_uploaded")
        act.evidence_status = "uploaded"
        act.save()
        self.assertEqual(svc.resolve_kind(a), WithdrawalKind.QUALITY_REVIEW)

    def test_verified_work_awaiting_payment_is_a_payment_hold(self):
        a = self.assign()
        self.schedule(a, status="ia_verified")
        self.assertEqual(svc.resolve_kind(a), WithdrawalKind.PAYMENT_HOLD)

    def test_paid_work_offers_no_withdrawal_at_all(self):
        a = self.assign()
        act = self.schedule(a, status="ia_verified")
        act.payment_status = "paid"
        act.save()
        self.assertEqual(svc.resolve_kind(a), WithdrawalKind.BLOCKED)

    def test_withdrawing_paid_work_is_refused(self):
        a = self.assign()
        act = self.schedule(a, status="ia_verified")
        act.payment_status = "paid"
        act.save()

        with self.assertRaises(ConflictError):
            svc.withdraw(a.id, self.payload(), self.pl_user)


class UnscheduledCostsNothingTest(WithdrawalFixture):
    def test_no_activity_is_created_and_no_money_moves(self):
        a = self.assign()

        w = svc.withdraw(a.id, self.payload(), self.pl_user)

        self.assertEqual(w.kind, WithdrawalKind.WITHDRAW_UNSCHEDULED)
        self.assertEqual(w.original_planned_cost, 0)
        self.assertIsNone(w.linked_activity_id)
        self.assertEqual(Activity.objects.count(), 0)
        self.assertEqual(ActivityScheduleCostLine.objects.count(), 0)

    def test_the_assignment_is_kept_not_deleted(self):
        a = self.assign()

        svc.withdraw(a.id, self.payload(), self.pl_user)

        a.refresh_from_db()
        self.assertEqual(a.status, PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        self.assertTrue(PartnerAssignment.objects.filter(id=a.id).exists())

    def test_the_preview_promises_what_the_withdrawal_delivers(self):
        a = self.assign()

        preview = svc.preview(self.pl_user, a.id)
        w = svc.withdraw(a.id, self.payload(), self.pl_user)

        self.assertEqual(preview["planned_cost"], 0)
        self.assertEqual(preview["budget_removed"], 0)
        self.assertFalse(preview["budget_amendment_required"])
        self.assertEqual(preview["kind"], w.kind)


class ScheduledRecallUnwindsTheBudgetTest(WithdrawalFixture):
    def test_the_activity_is_cancelled_rather_than_deleted(self):
        a = self.assign()
        act = self.schedule(a)

        svc.withdraw(
            a.id, self.payload(reason_category=WithdrawalReason.CAPACITY), self.pl_user
        )

        act.refresh_from_db()
        self.assertEqual(act.status, "cancelled")
        self.assertTrue(Activity.objects.filter(id=act.id).exists())

    def test_the_cost_lines_survive_as_history(self):
        """Aggregates exclude cancelled work; the evidence of what it cost stays."""
        a = self.assign()
        act = self.schedule(a, cost=180_000)

        w = svc.withdraw(
            a.id, self.payload(reason_category=WithdrawalReason.CAPACITY), self.pl_user
        )

        self.assertEqual(w.original_planned_cost, 180_000)
        self.assertTrue(
            ActivityScheduleCostLine.objects.filter(activity=act).exists(),
            "the historical cost snapshot was destroyed",
        )

    def test_the_preview_names_the_amount_that_will_leave_the_budget(self):
        a = self.assign()
        self.schedule(a, cost=95_000)

        preview = svc.preview(self.pl_user, a.id)

        self.assertEqual(preview["planned_cost"], 95_000)
        self.assertEqual(preview["budget_removed"], 95_000)
        self.assertTrue(preview["activity_will_be_cancelled"])
        self.assertFalse(preview["financially_locked"])


class TheSupportSlotHasOneIdentityTest(WithdrawalFixture):
    def test_a_replacement_points_at_the_assignment_it_replaces(self):
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
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.replaces_assignment_id, a.id)
        self.assertEqual(replacement.reassignment_sequence, 1)
        self.assertEqual(replacement.partner_id, self.replacement.id)

    def test_the_replacement_carries_the_same_slot_not_a_new_one(self):
        a = self.assign(support_type="core_visit", visit_number="3")

        w = svc.withdraw(
            a.id,
            self.payload(
                disposition=WithdrawalDisposition.REASSIGN_PARTNER,
                replacement_partner_id=self.replacement.id,
            ),
            self.pl_user,
        )

        r = w.replacement_assignment
        self.assertEqual(r.school_id, a.school_id)
        self.assertEqual(r.support_type, "core_visit")
        self.assertEqual(r.visit_number, "3")

    def test_only_one_assignment_holds_the_slot_at_a_time(self):
        a = self.assign()
        w = svc.withdraw(
            a.id,
            self.payload(
                disposition=WithdrawalDisposition.REASSIGN_PARTNER,
                replacement_partner_id=self.replacement.id,
            ),
            self.pl_user,
        )

        live = PartnerAssignment.objects.filter(school=self.school).exclude(
            status=PartnerAssignment.STATUS_RETURNED_TO_STAFF
        )
        self.assertEqual([x.id for x in live], [w.replacement_assignment_id])

    def test_the_replacement_has_no_activity_and_no_cost(self):
        """Price depends on who schedules and when, so it cannot exist yet."""
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

        r = w.replacement_assignment
        self.assertIsNone(r.scheduled_activity_id)
        self.assertIsNone(r.scheduled_date)
        self.assertEqual(
            ActivityScheduleCostLine.objects.filter(
                activity__assigned_partner_id=self.replacement.id
            ).count(),
            0,
            "the old partner's cost was copied to the replacement",
        )

    def test_reassigning_to_the_same_partner_is_refused(self):
        a = self.assign()

        with self.assertRaises(BadRequest):
            svc.withdraw(
                a.id,
                self.payload(
                    disposition=WithdrawalDisposition.REASSIGN_PARTNER,
                    replacement_partner_id=self.partner.id,
                ),
                self.pl_user,
            )

    def test_reassignment_needs_a_partner_to_reassign_to(self):
        a = self.assign()

        with self.assertRaises(BadRequest):
            svc.withdraw(
                a.id,
                self.payload(disposition=WithdrawalDisposition.REASSIGN_PARTNER),
                self.pl_user,
            )


class EntitlementIsNotDuplicatedTest(WithdrawalFixture):
    def test_cancelling_the_old_activity_frees_the_allowance(self):
        """Otherwise the replacement partner cannot schedule at all.

        `assert_partner_activity_allowance` counts one non-core partner
        activity per school per FY, excluding cancelled. If withdrawal left the
        old activity live, the school would have spent its entitlement on work
        nobody is doing.
        """
        from apps.partners.services import assert_partner_activity_allowance

        a = self.assign()
        self.schedule(a)

        with self.assertRaises(BadRequest):
            assert_partner_activity_allowance(
                self.partner.id, self.school.id, "school_visit", self.fy
            )

        svc.withdraw(
            a.id, self.payload(reason_category=WithdrawalReason.CAPACITY), self.pl_user
        )

        # Freed — and for the replacement partner too.
        assert_partner_activity_allowance(
            self.replacement.id, self.school.id, "school_visit", self.fy
        )
        assert_partner_activity_allowance(
            self.partner.id, self.school.id, "school_visit", self.fy
        )


class AttributionProtectsThePartnerTest(WithdrawalFixture):
    def test_a_partner_failure_is_attributed_to_the_partner(self):
        w = svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.NOT_SCHEDULED),
            self.pl_user,
        )

        self.assertEqual(w.attribution, WithdrawalAttribution.PARTNER)
        self.assertTrue(w.counts_against_partner)

    def test_a_closed_school_is_not_the_partners_fault(self):
        w = svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.SCHOOL_UNAVAILABLE),
            self.pl_user,
        )

        self.assertEqual(w.attribution, WithdrawalAttribution.SCHOOL)
        self.assertFalse(w.counts_against_partner)

    def test_our_own_filing_error_is_not_the_partners_fault(self):
        w = svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.INCORRECT_ASSIGNMENT),
            self.pl_user,
        )

        self.assertEqual(w.attribution, WithdrawalAttribution.EDIFY)
        self.assertFalse(w.counts_against_partner)

    def test_asking_to_be_released_early_is_not_counted_as_failure(self):
        """Telling us early is the behaviour we want; penalising it buys silence."""
        w = svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.PARTNER_REQUESTED_RELEASE),
            self.pl_user,
        )

        self.assertFalse(w.counts_against_partner)

    def test_the_catch_all_reason_does_not_quietly_blame_the_partner(self):
        w = svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.OTHER),
            self.pl_user,
        )

        self.assertFalse(w.counts_against_partner)

    def test_every_reason_has_an_attribution(self):
        """A missing mapping would default to blaming somebody."""
        from apps.partners.withdrawal_models import REASON_ATTRIBUTION

        for reason in WithdrawalReason:
            with self.subTest(reason=reason.value):
                self.assertIn(reason.value, REASON_ATTRIBUTION)


class AuthorityTest(WithdrawalFixture):
    def test_a_cceo_may_withdraw_their_own_unscheduled_assignment(self):
        w = svc.withdraw(self.assign().id, self.payload(), self.cceo_user)
        self.assertEqual(w.requested_by_role, EdifyRole.CCEO.value)

    def test_a_cceo_may_not_cancel_work_the_partner_has_planned(self):
        a = self.assign()
        self.schedule(a)

        with self.assertRaises(Forbidden) as caught:
            svc.withdraw(
                a.id,
                self.payload(reason_category=WithdrawalReason.CAPACITY),
                self.cceo_user,
            )

        self.assertIn("Program Lead", str(caught.exception))

    def test_a_cceo_may_not_touch_another_cceos_assignment(self):
        a = self.assign(cceo=self.other_cceo)

        with self.assertRaises(Forbidden):
            svc.withdraw(a.id, self.payload(), self.cceo_user)

    def test_a_program_lead_may_recall_a_supervised_cceos_scheduled_work(self):
        a = self.assign()
        self.schedule(a)

        w = svc.withdraw(
            a.id, self.payload(reason_category=WithdrawalReason.CAPACITY), self.pl_user
        )

        self.assertEqual(w.kind, WithdrawalKind.RECALL_SCHEDULED)

    def test_another_program_lead_may_not(self):
        a = self.assign()

        with self.assertRaises(Forbidden):
            svc.withdraw(a.id, self.payload(), self.other_pl_user)


class ValidationTest(WithdrawalFixture):
    def test_a_reason_category_is_required(self):
        with self.assertRaises(BadRequest):
            svc.withdraw(
                self.assign().id, self.payload(reason_category=""), self.pl_user
            )

    def test_an_explanation_is_required_and_whitespace_does_not_count(self):
        with self.assertRaises(BadRequest):
            svc.withdraw(
                self.assign().id,
                self.payload(partner_facing_reason="   " * 20),
                self.pl_user,
            )

    def test_a_next_disposition_is_required(self):
        """A withdrawal that does not say where the support goes leaves the
        school worse off than before anyone intervened."""
        with self.assertRaises(BadRequest):
            svc.withdraw(self.assign().id, self.payload(disposition=""), self.pl_user)


class RestrictedReasonsTest(WithdrawalFixture):
    def test_a_safeguarding_reason_is_not_sent_to_the_partner(self):
        detail = "Allegation involving a named child reported by the head teacher."

        w = svc.withdraw(
            self.assign().id,
            self.payload(
                reason_category=WithdrawalReason.SAFEGUARDING,
                partner_facing_reason=detail,
            ),
            self.pl_user,
        )

        self.assertNotIn("child", w.partner_facing_reason)
        self.assertIn("under management review", w.partner_facing_reason)

    def test_the_internal_note_never_becomes_partner_facing(self):
        w = svc.withdraw(
            self.assign().id,
            self.payload(
                internal_note="Third failure this term; consider offboarding."
            ),
            self.pl_user,
        )

        self.assertNotIn("offboarding", w.partner_facing_reason)
        self.assertIn("offboarding", w.internal_note)


class IdempotenceTest(WithdrawalFixture):
    def test_a_second_withdrawal_returns_the_first_rather_than_opening_another(self):
        a = self.assign()
        self.schedule(a, status="in_progress")

        first = svc.withdraw(
            a.id,
            self.payload(reason_category=WithdrawalReason.POOR_QUALITY),
            self.pl_user,
        )
        second = svc.withdraw(
            a.id,
            self.payload(reason_category=WithdrawalReason.POOR_QUALITY),
            self.pl_user,
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(PartnerAssignmentWithdrawal.objects.count(), 1)


class HoldsDoNotReleaseTheSlotTest(WithdrawalFixture):
    def test_suspending_in_progress_work_keeps_the_assignment_live(self):
        """The school may still be owed the rest of this very activity."""
        a = self.assign()
        self.schedule(a, status="in_progress")

        w = svc.withdraw(
            a.id,
            self.payload(reason_category=WithdrawalReason.POOR_QUALITY),
            self.pl_user,
        )

        a.refresh_from_db()
        self.assertEqual(w.state, WithdrawalState.SUSPENDED)
        self.assertNotEqual(a.status, PartnerAssignment.STATUS_RETURNED_TO_STAFF)

    def test_evidence_is_never_destroyed_by_a_quality_review(self):
        a = self.assign()
        act = self.schedule(a, status="evidence_uploaded")
        act.evidence_status = "uploaded"
        act.save()

        svc.withdraw(
            a.id,
            self.payload(reason_category=WithdrawalReason.POOR_EVIDENCE),
            self.pl_user,
        )

        act.refresh_from_db()
        self.assertEqual(act.evidence_status, "uploaded")
        self.assertNotEqual(act.status, "cancelled")


class RequestAndReviewTest(WithdrawalFixture):
    """Once a partner has committed to a date, the CCEO asks rather than acts."""

    def test_the_cceo_request_changes_nothing_by_itself(self):
        a = self.assign()
        act = self.schedule(a)

        w = svc.request_withdrawal(
            a.id,
            self.payload(reason_category=WithdrawalReason.POOR_QUALITY),
            self.cceo_user,
        )

        a.refresh_from_db()
        act.refresh_from_db()
        self.assertEqual(w.state, WithdrawalState.REQUESTED)
        self.assertEqual(a.status, PartnerAssignment.STATUS_SCHEDULED)
        self.assertEqual(act.status, "partner_scheduled")

    def test_the_request_lands_with_the_supervising_program_lead(self):
        a = self.assign()
        self.schedule(a)

        w = svc.request_withdrawal(
            a.id,
            self.payload(reason_category=WithdrawalReason.POOR_QUALITY),
            self.cceo_user,
        )

        self.assertEqual(w.supervising_pl_id, self.pl.id)

    def test_requesting_unscheduled_work_is_refused_because_they_can_just_do_it(self):
        a = self.assign()

        with self.assertRaises(BadRequest) as caught:
            svc.request_withdrawal(a.id, self.payload(), self.cceo_user)

        self.assertIn("withdraw it yourself", str(caught.exception))

    def test_approval_performs_the_withdrawal_under_the_leads_authority(self):
        a = self.assign()
        act = self.schedule(a)
        w = svc.request_withdrawal(
            a.id,
            self.payload(reason_category=WithdrawalReason.CAPACITY),
            self.cceo_user,
        )

        performed = svc.review_request(w.id, {"decision": "approve"}, self.pl_user)

        a.refresh_from_db()
        act.refresh_from_db()
        self.assertEqual(a.status, PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        self.assertEqual(act.status, "cancelled")
        self.assertEqual(performed.state, WithdrawalState.RETURNED_TO_PLANNING)

    def test_rejection_leaves_the_partners_work_alone(self):
        a = self.assign()
        act = self.schedule(a)
        w = svc.request_withdrawal(
            a.id,
            self.payload(reason_category=WithdrawalReason.CAPACITY),
            self.cceo_user,
        )

        decided = svc.review_request(
            w.id,
            {"decision": "reject", "note": "Partner has confirmed the date."},
            self.pl_user,
        )

        a.refresh_from_db()
        act.refresh_from_db()
        self.assertEqual(decided.state, WithdrawalState.REJECTED)
        self.assertEqual(act.status, "partner_scheduled")
        self.assertEqual(a.status, PartnerAssignment.STATUS_SCHEDULED)

    def test_another_teams_lead_cannot_decide_it(self):
        a = self.assign()
        self.schedule(a)
        w = svc.request_withdrawal(
            a.id,
            self.payload(reason_category=WithdrawalReason.CAPACITY),
            self.cceo_user,
        )

        with self.assertRaises(Forbidden):
            svc.review_request(w.id, {"decision": "approve"}, self.other_pl_user)

    def test_a_cceo_cannot_approve_their_own_request(self):
        """Otherwise the routing to the PL buys nothing."""
        a = self.assign()
        self.schedule(a)
        w = svc.request_withdrawal(
            a.id,
            self.payload(reason_category=WithdrawalReason.CAPACITY),
            self.cceo_user,
        )

        with self.assertRaises(Forbidden):
            svc.review_request(w.id, {"decision": "approve"}, self.cceo_user)

    def test_deciding_twice_reports_the_first_decision(self):
        a = self.assign()
        self.schedule(a)
        w = svc.request_withdrawal(
            a.id,
            self.payload(reason_category=WithdrawalReason.CAPACITY),
            self.cceo_user,
        )
        svc.review_request(w.id, {"decision": "reject"}, self.pl_user)

        again = svc.review_request(w.id, {"decision": "approve"}, self.pl_user)

        self.assertEqual(again.state, WithdrawalState.REJECTED)


class PermissionGateTest(WithdrawalFixture):
    def test_a_role_without_the_permission_is_refused_regardless_of_scope(self):
        """A hidden button is not a permission."""
        accountant, _ = self._staff(
            "acc@w.test", "Book Keeper", EdifyRole.PROGRAM_ACCOUNTANT
        )
        a = self.assign()

        with self.assertRaises(Forbidden) as caught:
            svc.withdraw(a.id, self.payload(), accountant)

        self.assertIn("cannot withdraw", str(caught.exception))

    def test_the_country_director_does_not_do_routine_team_withdrawals(self):
        """They review escalated cases; routine team work belongs to the PL."""
        cd, _ = self._staff("cd@w.test", "Director", EdifyRole.COUNTRY_DIRECTOR)
        a = self.assign()

        with self.assertRaises(Forbidden):
            svc.withdraw(a.id, self.payload(), cd)
