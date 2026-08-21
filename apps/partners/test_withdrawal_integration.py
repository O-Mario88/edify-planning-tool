"""Withdrawal has to reach the places the work actually shows up.

A withdrawal that only changes a status is worse than none: the record says
the work stopped, and the partner's day still tells them to go. These prove
the decision propagates to the surfaces people actually read — the partner's
Today page, the assignment picker, and the drawer where the next partner is
chosen.
"""

from __future__ import annotations

from datetime import date

from django.test import Client

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.core.exceptions import ConflictError
from apps.core.rbac import EdifyRole
from apps.partners import withdrawal_service as svc
from apps.partners.models import PartnerAssignment
from apps.partners.test_withdrawal import WithdrawalFixture
from apps.partners.withdrawal_models import WithdrawalDisposition, WithdrawalReason


class WithdrawnWorkLeavesThePartnersDayTest(WithdrawalFixture):
    """The failure this exists to prevent: told to stop, still told to go."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.partner_user = User.objects.create(
            email="officer@w.test",
            name="Partner Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            status="active",
            is_active=True,
        )
        cls.partner.user = cls.partner_user
        cls.partner.save(update_fields=["user"])

    def _today_page(self):
        # /partner/today retired 2026-08-20 — the partner's day lives on the
        # unified My Plan.
        client = Client()
        client.force_login(self.partner_user)
        return client.get("/my-plan")

    def test_todays_work_is_listed_before_it_is_withdrawn(self):
        a = self.assign()
        self.schedule(a, when=date.today())

        response = self._today_page()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Alpha Primary", response.content.decode())

    def test_recalled_work_disappears_from_the_partners_day(self):
        a = self.assign()
        self.schedule(a, when=date.today())
        svc.withdraw(
            a.id,
            self.payload(reason_category=WithdrawalReason.CAPACITY),
            self.pl_user,
        )

        response = self._today_page()

        self.assertNotIn("Alpha Primary", response.content.decode())

    def test_the_activity_still_exists_it_is_just_not_theirs_to_do(self):
        """Gone from the day, kept in the record."""
        a = self.assign()
        activity = self.schedule(a, when=date.today())
        svc.withdraw(
            a.id,
            self.payload(reason_category=WithdrawalReason.CAPACITY),
            self.pl_user,
        )

        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")
        self.assertTrue(Activity.objects.filter(id=activity.id).exists())


class HeldPartnersLeaveTheAssignmentPickerTest(WithdrawalFixture):
    """Offering a choice the system will refuse teaches people the error is
    arbitrary. The picker and the API must agree with the guard."""

    def _hold_the_partner(self):
        from datetime import timedelta

        return svc.place_hold(
            self.partner.id,
            {
                "reason_category": WithdrawalReason.REPEATED_EVIDENCE_RETURN,
                "reason": "Three evidence packs returned; pausing new work.",
                "review_on": date.today() + timedelta(days=30),
            },
            self.pl_user,
        )

    def test_an_assignable_partner_is_offered(self):
        from apps.partners.services import assignable_partners

        self.assertIn(self.partner, list(assignable_partners()))

    def test_a_held_partner_is_not_offered(self):
        from apps.partners.services import assignable_partners

        self._hold_the_partner()

        names = [p.name for p in assignable_partners()]
        self.assertNotIn("Partner X", names)
        self.assertIn("Partner Y", names)

    def test_the_api_agrees_with_the_picker(self):
        """A rule enforced only in the HTML picker is not a rule."""
        from apps.partners.services import eligible

        self._hold_the_partner()

        self.assertNotIn("Partner X", [p["name"] for p in eligible({})])

    def test_the_guard_still_refuses_if_something_gets_past_the_picker(self):
        self._hold_the_partner()

        with self.assertRaises(ConflictError):
            self.assign()

    def test_a_partner_with_withdrawn_history_is_still_offered(self):
        """Losing one assignment to a closed school is not a disqualification.

        Hiding them would be a performance judgement made by a query, and one
        nobody could see or argue with.
        """
        from apps.partners.services import assignable_partners

        svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.SCHOOL_UNAVAILABLE),
            self.pl_user,
        )

        self.assertIn(self.partner, list(assignable_partners()))


class TheNextAssignerSeesTheHistoryTest(WithdrawalFixture):
    def test_prior_withdrawals_are_surfaced_for_this_school(self):
        from apps.frontend.views.planning_views import _prior_withdrawals

        svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.CAPACITY),
            self.pl_user,
        )

        history = _prior_withdrawals(self.school)

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["partner"], "Partner X")
        self.assertTrue(history[0]["counts_against_partner"])

    def test_a_non_partner_cause_is_labelled_as_such(self):
        from apps.frontend.views.planning_views import _prior_withdrawals

        svc.withdraw(
            self.assign().id,
            self.payload(reason_category=WithdrawalReason.SCHOOL_UNAVAILABLE),
            self.pl_user,
        )

        entry = _prior_withdrawals(self.school)[0]

        self.assertFalse(entry["counts_against_partner"])
        self.assertEqual(entry["attribution"], "School-attributable")

    def test_a_rejected_request_is_not_shown_as_history(self):
        """It never took effect, so it is not a thing that happened here."""
        from apps.frontend.views.planning_views import _prior_withdrawals

        a = self.assign()
        self.schedule(a)
        w = svc.request_withdrawal(
            a.id,
            self.payload(reason_category=WithdrawalReason.POOR_QUALITY),
            self.cceo_user,
        )
        svc.review_request(w.id, {"decision": "reject"}, self.pl_user)

        self.assertEqual(_prior_withdrawals(self.school), [])


class ReassignmentReachesTheNewPartnerTest(WithdrawalFixture):
    def test_the_replacement_appears_as_unscheduled_work_for_the_new_partner(self):
        a = self.assign()
        w = svc.withdraw(
            a.id,
            self.payload(
                disposition=WithdrawalDisposition.REASSIGN_PARTNER,
                replacement_partner_id=self.replacement.id,
            ),
            self.pl_user,
        )

        theirs = PartnerAssignment.objects.filter(
            partner=self.replacement,
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        )
        self.assertEqual([x.id for x in theirs], [w.replacement_assignment_id])

    def test_the_old_partner_keeps_none_of_it(self):
        a = self.assign()
        svc.withdraw(
            a.id,
            self.payload(
                disposition=WithdrawalDisposition.REASSIGN_PARTNER,
                replacement_partner_id=self.replacement.id,
            ),
            self.pl_user,
        )

        self.assertFalse(
            PartnerAssignment.objects.filter(
                partner=self.partner,
                status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
            ).exists()
        )
