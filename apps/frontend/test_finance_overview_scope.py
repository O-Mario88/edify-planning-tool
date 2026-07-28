"""Two finance cards, five identical rows, two different populations of money.

The Accountant home dashboard and the Disbursements workspace each carried a
card titled "This Month Overview" with the same five rows -- Waiting for
Approval, Returned, Approved (Not Disbursed), Disbursed, Reconciled.

They were never comparable. `accountant_dashboard_view` scopes every figure on
its page to WeeklyFundRequest, while the Disbursements workspace sums the
consolidated queue: monthly fund plans, weekly advances, partner payments and
reimbursements. On the seed that is UGX 1.25M against UGX 3.3M+ -- most of the
money missing from the card an Accountant lands on.

This surfaced while investigating a narrower question: whether "Held" money
belongs in Approved (Not Disbursed). It does -- a hold pauses approved money
rather than rejecting it -- but the question was moot here, because
`_weekly_status` has no Held branch at all. A weekly advance cannot be held, so
the two cards never disagreed *about Held*. They disagreed about what they
counted.

The fix is titles that name their population. These tests keep them named.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.fund_requests.disbursement_dashboard_service import _weekly_status

ROOT = Path(settings.BASE_DIR)
ACCOUNTANT_CARD = ROOT / "templates" / "pages" / "accounts" / "dashboard.html"
DISBURSEMENTS_CARD = ROOT / "templates" / "partials" / "disbursements" / "root.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class OverviewCardsNameTheirPopulationTest(SimpleTestCase):
    def test_the_accountant_card_says_it_covers_weekly_advances(self):
        self.assertIn("Weekly Advances This Month", _read(ACCOUNTANT_CARD))

    def test_the_disbursements_card_says_it_covers_every_fund_type(self):
        self.assertIn("All Fund Types This Month", _read(DISBURSEMENTS_CARD))

    def test_neither_card_reverts_to_the_ambiguous_shared_title(self):
        """"This Month Overview" told the reader nothing about which money."""
        for path in (ACCOUNTANT_CARD, DISBURSEMENTS_CARD):
            with self.subTest(path.name):
                self.assertNotIn(">This Month Overview<", _read(path))

    def test_the_two_titles_are_still_distinct(self):
        accountant = "Weekly Advances This Month"
        disbursements = "All Fund Types This Month"
        self.assertNotEqual(accountant, disbursements)
        self.assertNotIn(disbursements, _read(ACCOUNTANT_CARD))
        self.assertNotIn(accountant, _read(DISBURSEMENTS_CARD))


class WeeklyAdvancesCannotBeHeldTest(SimpleTestCase):
    """Why the Held question does not arise on the Accountant's card.

    A hold is a pause on approved money, so it belongs inside "Approved (Not
    Disbursed)" -- which is what the Disbursements workspace already does. But
    the classifier behind the Accountant card has no Held branch, so adding
    Held to that page would sum a bucket that can never be produced.
    """

    class _Weekly:
        def __init__(self, status):
            self.status = status
            self.accountability_submitted_at = None
            self.accountability_reviewed_at = None

    def test_no_weekly_status_maps_to_held(self):
        statuses = (
            "pending_responsible_confirmation",
            "confirmed_for_advance",
            "disbursed",
            "returned_by_accountant",
            "returned",
            "accounted",
            "held",
            "something_unrecognised",
        )
        produced = {_weekly_status(self._Weekly(s)) for s in statuses}
        self.assertNotIn(
            "Held",
            produced,
            "a weekly advance has no held state; summing one would always be 0",
        )

    def test_an_approved_undisbursed_weekly_advance_is_pending_disbursement(self):
        self.assertEqual(
            _weekly_status(self._Weekly("confirmed_for_advance")),
            "Pending Disbursement",
        )

    def test_an_unrecognised_status_falls_back_to_pending_approval(self):
        self.assertEqual(
            _weekly_status(self._Weekly("held")),
            "Pending Approval",
            "even the literal 'held' status is not a Held bucket here",
        )
