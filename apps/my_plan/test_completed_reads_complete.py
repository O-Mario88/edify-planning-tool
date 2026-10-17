"""Completed work reads complete on My Plan (owner, 2026-10-17).

"The completed activities are still not showing complete it says awaiting PL
approval ... All completed activity should show status complete and fix the
table too. NO wrapping. Include the Salesforce ID and the completion date."

Pinned here:

  1. Work the Programme Lead has approved is done: it leaves "Waiting on
     Approval" (it sat there beside its own "PL Approved") and its status
     reads "Complete".
  2. Work handed in and waiting for the lead stays on "Waiting on Approval",
     its status "Complete" and its approval stage a badge beside it.
  3. Approved work whose money is still with finance stays on the card.
  4. The card shows the Salesforce ID and the Completed Date; its status
     strip no longer repeats the ID, so it holds one line (pages.css,
     .mp-badges).
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.my_plan.services import get_frontend_context
from apps.pl_review.test_completion_reviews import ReviewFixture

COMPLETE = "Complete"


class CompletedWorkReadsComplete(ReviewFixture):
    def _context(self):
        return get_frontend_context(self.james_user, {"fy": "2026", "period": "fy"})

    def _approved(self, sf_id, **extra):
        values = {
            "status": "ia_verified",
            "ia_verification_status": "confirmed",
            "salesforce_activity_id": sf_id,
            "actual_delivery_date": date.today() - timedelta(days=2),
        }
        values.update(extra)
        return self._completion(self.james.id, **values)

    def _handed_in(self, sf_id):
        return self._completion(
            self.james.id,
            status="submitted_to_pl",
            ia_verification_status="pending",
            salesforce_activity_id=sf_id,
            actual_delivery_date=date.today() - timedelta(days=2),
        )

    @staticmethod
    def _rows(context, key):
        return {row["id"]: row for row in context[key]}

    def test_approved_work_is_off_the_card_and_reads_complete(self):
        work = self._approved("SVE-8101")
        context = self._context()

        self.assertNotIn(work.id, self._rows(context, "waiting_on_approval"))
        row = self._rows(context, "school_visits")[work.id]
        self.assertEqual(row["status_label"], COMPLETE)
        self.assertEqual(row["status_tone"], "green")
        labels = [label for label, _ in row["badges"]]
        self.assertEqual(labels.count("PL Approved"), 1)
        self.assertNotIn(COMPLETE, labels)

    def test_handed_in_work_waits_on_the_card_and_reads_complete(self):
        work = self._handed_in("SVE-8102")
        context = self._context()

        row = self._rows(context, "waiting_on_approval")[work.id]
        self.assertEqual(row["status_label"], COMPLETE)
        self.assertIn(("PL Pending", "purple"), row["badges"])

    def test_handed_in_work_past_its_day_is_not_past_due(self):
        # The banner said "past their date and not yet completed" of it,
        # while the Dashboard list it points to left it out.
        self._handed_in("SVE-8105")
        self._approved("SVE-8106")
        self.assertEqual(self._context()["past_due_count"], 0)

    def test_approved_work_whose_money_is_with_finance_stays_on_the_card(self):
        work = self._approved("SVE-8103", payment_status="pending_ia")
        self.assertIn(work.id, self._rows(self._context(), "waiting_on_approval"))

    def test_the_card_shows_the_salesforce_id_and_the_completed_date(self):
        work = self._handed_in("SVE-8104")
        response = self.as_user(self.james_user).get("/my-plan/", {"fy": "2026"})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        start = html.index('data-card="waiting-approval"')
        card = html[start : html.index("</table>", start)]

        self.assertIn("<th>Salesforce ID</th>", card)
        self.assertIn("SVE-8104", card)
        self.assertIn("<th>Completed Date</th>", card)
        delivered = work.actual_delivery_date
        self.assertIn(f"{delivered:%b} {delivered.day}, {delivered:%a}", card)
        # The ID has its column; the status strip does not repeat it.
        self.assertNotIn("SF ID complete", card)
