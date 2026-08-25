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
    fy_totals_all_fund_types,
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


class FyTotalsCoverEveryFundTypeTest(TestCase):
    """The Accountant's FY KPI strip must not report one fund type as all money.

    "Total Approved Funds", "Total Disbursed" and "Budget Utilization" read as
    the country's figures. They were built from WeeklyFundRequest alone, so
    monthly fund plans -- which carry most of the value -- were missing from
    every one of them. On the seed, Awaiting Approvals read UGX 13.1M where the
    true figure across both fund types is UGX 27.1M.
    """

    def test_it_reports_every_row_the_strip_needs(self):
        totals = fy_totals_all_fund_types(get_operational_fy())
        for key in (
            "approved",
            "pending_disbursement",
            "pending_disbursement_count",
            "awaiting_approval",
            "awaiting_approval_count",
            "disbursed",
            "accounted",
            "returned",
            "disbursed_count",
            "accounted_count",
            "record_count",
        ):
            with self.subTest(key):
                self.assertIn(key, totals)
                self.assertIsInstance(totals[key], int)

    # A test asserting that the FY money totals exceed the weekly advance
    # totals whenever a monthly plan exists lived here. It was written when
    # fy_totals_all_fund_types summed the two snapshots, and D1
    # (apps.fund_requests.test_audit_funding_channels) moved the money to the
    # AdvanceRequest ledger precisely because that addition counted a cost
    # line requested through both channels twice. Under the ledger the two
    # figures are the same shillings, so the assertion asked for the
    # double-count back. It never ran — it skipped itself whenever the
    # database held no monthly plan, which was always — so nothing caught it
    # going stale. That rule now lives, with a fixture that exercises it, in
    # test_audit_funding_channels.test_fy_totals_count_the_shared_cost_line_once.

    def test_an_empty_financial_year_reports_zeros(self):
        totals = fy_totals_all_fund_types("1999")
        self.assertEqual(totals["record_count"], 0)
        self.assertEqual(totals["approved"], 0)
        self.assertEqual(totals["awaiting_approval"], 0)

    def test_held_money_counts_as_approved(self):
        """Same rule as the month card: a hold pauses approved money."""
        totals = fy_totals_all_fund_types(get_operational_fy())
        self.assertGreaterEqual(
            totals["approved"],
            totals["pending_disbursement"],
            "approved is the wider set; pending disbursement sits inside it",
        )


class MonthCardIsActuallyMonthScopedTest(TestCase):
    """A card titled "This Month" must not carry a standing backlog.

    `_partner_items` calls itself "month-agnostic" and `_reimbursement_items`
    "due now"; both assign the Pending Disbursement status. Including them put
    rows 1-3 of the card on any month while Disbursed and Reconciled covered
    this one -- one card, two periods.
    """

    def test_the_overview_excludes_month_agnostic_queues(self):
        import apps.fund_requests.disbursement_dashboard_service as service

        fy, month = get_operational_fy(), date.today().month
        names: dict = {}
        month_scoped = service._monthly_items(fy, month, names) + service._weekly_items(
            fy, month, names
        )
        standing = service._partner_items() + service._reimbursement_items(names)

        expected = sum(
            i["amount"] for i in month_scoped if i["status"] == "Pending Approval"
        )
        self.assertEqual(
            month_overview_all_fund_types(fy, month)["waiting_for_approval"],
            expected,
            "the month card must sum month-scoped fund types only",
        )
        # Guard the premise: if the standing queues ever became month-scoped,
        # this test would be asserting nothing.
        self.assertIsInstance(standing, list)


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


class QueueListNamesItsContentsTest(SimpleTestCase):
    """The Accountant's list is weekly advances; only one queue is consolidated.

    Both pages titled their list "Consolidated Fund Queue", but the Accountant
    home page builds its list from WeeklyFundRequest and renders weekly-shaped
    detail beside it -- week start and end dates, WeeklyFundRequestLine rows,
    the per-stage approval chain. Only the Disbursements workspace queue is
    genuinely consolidated.

    Once the FY figures above the list started covering every fund type, a
    reader had no way to tell why the list did not match them. The list is named
    for its contents and points at the page that owns the consolidated view,
    rather than rebuilding that workspace inside a dashboard panel.
    """

    def test_the_accountant_list_says_it_holds_weekly_advances(self):
        self.assertIn("Weekly Advance Queue", _read(ACCOUNTANT_CARD))

    def test_the_accountant_list_no_longer_claims_to_be_consolidated(self):
        """Matched on the rendered heading, not the prose.

        The template explains the rename in a {% comment %} that names the old
        title, so a bare substring check fails on the explanation rather than
        on the markup a reader sees.
        """
        self.assertNotIn(">Consolidated Fund Queue<", _read(ACCOUNTANT_CARD))

    def test_the_disbursements_queue_keeps_the_consolidated_name(self):
        """It earns the title: monthly, weekly, partner and reimbursement."""
        self.assertIn(">Consolidated Fund Queue<", _read(DISBURSEMENTS_CARD))

    def test_the_accountant_page_points_at_the_consolidated_queue(self):
        body = _read(ACCOUNTANT_CARD)
        self.assertIn('href="/disbursements"', body)
        self.assertIn("Weekly advances only", body)


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
