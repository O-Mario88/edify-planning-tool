"""The month's money is counted once on the Disbursements page.

Found by the 2026-10-07 calculation check (owner: "make sure every data
stats, kpi ... costs, budget, weekly advance request ... are all accurate and
not missleading"). Scheduling keeps an automatic *draft* monthly request in
step with the month's work, and the weekly advance requests carry the very
same cost lines. The Accountant's page listed the draft as "Pending Approval"
and added it to the weekly requests: UGX 1.5M "in the approval chain" where
UGX 722K had been asked for.
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.fund_requests import disbursement_dashboard_service as svc
from apps.fund_requests.models import FundRequest, WeeklyFundRequest
from apps.fund_requests.test_disbursement_dashboard import (
    FY,
    MONTH,
    DisbursementFixture,
)


class DraftsAreNotRequestsTest(DisbursementFixture):
    def draft(self, amount=250_000):
        return FundRequest.objects.create(
            fy=FY,
            period="monthly",
            period_key=f"{FY}-M{MONTH}",
            scope="own",
            submitted_by_user_id=self.cceo.id,
            submitted_by_role="CCEO",
            total_amount=amount,
            activity_count=1,
            status="draft",
        )

    def weekly(self, amount=250_000):
        start = date(int(FY), MONTH, 6)
        start -= timedelta(days=start.weekday())
        return WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=start,
            week_end_date=start + timedelta(days=6),
            responsible_user=self.cceo.id,
            responsible_role="CCEO",
            total_amount=amount,
            status="pending_responsible_confirmation",
        )

    def dashboard(self):
        return svc.get_disbursement_dashboard(self.acct_p, {"fy": FY, "month": MONTH})

    def test_an_unsubmitted_draft_is_not_on_the_queue(self):
        self.draft()

        kinds = [item["kind"] for item in self.dashboard()["queue"]]

        self.assertNotIn("monthly", kinds)

    def test_the_week_s_money_is_not_added_to_its_own_draft(self):
        self.draft(250_000)
        self.weekly(250_000)

        queue = self.dashboard()["queue"]

        self.assertEqual([item["kind"] for item in queue], ["weekly"])
        self.assertEqual(sum(item["amount"] for item in queue), 250_000)

    def test_a_submitted_plan_is_on_the_queue(self):
        plan = self._approved_plan()

        queue = self.dashboard()["queue"]

        self.assertIn(f"fr:{plan.id}", [item["key"] for item in queue])
