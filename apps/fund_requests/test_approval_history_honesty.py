"""The Traceability Ledger must not attest to approvals that never happened.

`/accounts/approval-history` calls itself an "audit trail of fund requests
routing through PL, CD, RVP, and accountant sign-off stages". It rendered three
literal green "Approved" cells on every row, over an unfiltered queryset — so a
request still awaiting its owner's confirmation displayed three sign-offs that
did not exist, on the one page whose purpose is proving they did.

It also carried an RVP column, which could never be truthful: the RVP approves
the country envelope, not an individual weekly request.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.fund_requests.models import WeeklyFundRequest


class ApprovalHistoryReflectsRealStateTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.accountant = User.objects.create_user(
            email="ledger-acct@edify.org",
            name="Ledger Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(
            user=cls.accountant, staff_number="LG-1", title="Accountant"
        )
        monday = date.today() - timedelta(days=date.today().weekday())
        cls.unapproved = WeeklyFundRequest.objects.create(
            fy="2027",
            week_start_date=monday,
            week_end_date=monday + timedelta(days=6),
            responsible_user="ledger-owner",
            total_amount=50_000,
            status="pending_responsible_confirmation",
        )

    def test_an_unapproved_request_is_not_shown_as_approved(self):
        self.client.force_login(self.accountant)
        response = self.client.get("/accounts/approval-history")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()

        self.assertIn(
            "Awaiting",
            body,
            "the ledger does not show the real state of a request that nobody "
            "has confirmed yet",
        )
        # The row must not claim any approval. "Approved" may legitimately
        # appear for a record that has one — this fixture has none, so any
        # occurrence in the table is fabricated.
        table = body.split("<tbody", 1)[-1].split("</tbody>", 1)[0]
        self.assertNotIn(
            ">Approved<",
            table,
            "an unapproved fund request is still rendered as approved — the "
            "Traceability Ledger is attesting to a sign-off that never happened",
        )

    def test_the_ledger_does_not_claim_an_rvp_sign_off_on_weekly_requests(self):
        self.client.force_login(self.accountant)
        body = self.client.get("/accounts/approval-history").content.decode()
        self.assertNotIn(
            "RVP Approval",
            body,
            "weekly requests never route to the RVP (they approve the country "
            "envelope), so the column can only ever be untrue",
        )
