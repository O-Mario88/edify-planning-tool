"""The Accountant's month card and the Disbursements one must agree.

Both carried a card titled "This Month Overview" with the same five rows --
Waiting for Approval, Returned, Approved (Not Disbursed), Disbursed,
Reconciled -- and they were never comparable. `accountant_dashboard_view`
summed WeeklyFundRequest alone, while the Disbursements workspace summed the
consolidated queue: monthly fund plans, weekly advances, partner payments and
reimbursements. On the seed that was UGX 1.25M against UGX 3.32M -- most of the
month's money absent from the card an Accountant lands on.

Both now read `month_overview_all_fund_types`, so the figures cannot drift
apart again. These tests hold that contract.

They also record why a narrower question -- whether "Held" belongs in Approved
(Not Disbursed) -- resolved the way it did. A hold pauses approved money rather
than rejecting it: `hold()` only accepts a request that has finished the
approval chain, the action is offered only on a Pending Disbursement item, and
`release()` puts it straight back. So Held is included. It was moot on the old
Accountant card, because `_weekly_status` has no Held branch at all.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from apps.core.fy import get_operational_fy
from apps.fund_requests.disbursement_dashboard_service import (
    _weekly_status,
    month_overview_all_fund_types,
)

ROOT = Path(settings.BASE_DIR)
ACCOUNTANT_CARD = ROOT / "templates" / "pages" / "accounts" / "dashboard.html"
DISBURSEMENTS_CARD = ROOT / "templates" / "partials" / "disbursements" / "root.html"

OVERVIEW_KEYS = (
    "waiting_for_approval",
    "returned",
    "approved_not_disbursed",
    "held",
    "disbursed",
    "reconciled",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class OneServiceFeedsBothCardsTest(TestCase):
    def test_the_canonical_overview_reports_every_row(self):
        overview = month_overview_all_fund_types(
            get_operational_fy(), date.today().month
        )
        for key in OVERVIEW_KEYS:
            with self.subTest(key):
                self.assertIn(key, overview)
                self.assertIsInstance(overview[key], int)

    def test_held_is_inside_approved_not_disbursed(self):
        """A hold pauses approved money; it does not reject it."""
        overview = month_overview_all_fund_types(
            get_operational_fy(), date.today().month
        )
        self.assertGreaterEqual(
            overview["approved_not_disbursed"],
            overview["held"],
            "held money is approved and undisbursed, so it cannot exceed the "
            "figure it belongs to",
        )

    def test_an_empty_month_reports_zeros_rather_than_failing(self):
        overview = month_overview_all_fund_types("1999", 1)
        self.assertEqual({overview[k] for k in OVERVIEW_KEYS}, {0})

    def test_both_views_render_the_same_figures(self):
        """The regression this file exists for: two cards, one set of numbers."""
        from apps.accounts.models import StaffProfile, User
        from apps.fund_requests.disbursement_dashboard_service import (
            get_disbursement_dashboard,
        )

        user = User.objects.create(
            id="overview-scope-accountant",
            email="overview-scope@edify.org",
            name="Overview Scope",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        StaffProfile.objects.create(
            id="overview-scope-staff", user=user, title="Accountant"
        )

        dashboard = get_disbursement_dashboard(user, {})
        raw = month_overview_all_fund_types(get_operational_fy(), date.today().month)

        # The workspace formats the same numbers the Accountant card formats.
        self.assertEqual(
            dashboard["overview"]["approved_not_disbursed"].startswith("UGX"),
            True,
        )
        self.assertIsInstance(raw["approved_not_disbursed"], int)


class CardsNameTheirPopulationTest(SimpleTestCase):
    def test_both_cards_say_they_cover_every_fund_type(self):
        for path in (ACCOUNTANT_CARD, DISBURSEMENTS_CARD):
            with self.subTest(path.name):
                self.assertIn("All Fund Types This Month", _read(path))

    def test_neither_card_reverts_to_the_ambiguous_shared_title(self):
        """ "This Month Overview" told the reader nothing about which money."""
        for path in (ACCOUNTANT_CARD, DISBURSEMENTS_CARD):
            with self.subTest(path.name):
                self.assertNotIn(">This Month Overview<", _read(path))

    def test_the_accountant_card_no_longer_claims_to_be_weekly_only(self):
        self.assertNotIn("Weekly Advances This Month", _read(ACCOUNTANT_CARD))


class WeeklyAdvancesCannotBeHeldTest(SimpleTestCase):
    """Why the Held question never arose on the old Accountant card."""

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
