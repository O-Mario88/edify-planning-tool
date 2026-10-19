"""A visit that collects the SSA is complete once the SSA is in (owner,
2026-10-17).

"if the visit purpose was to collect data (e.g. core school SSA Support or SSA
support), It is not complete until the SSA scores are entered so the status
should say "Awaiting SSA Scores" and Action is "Enter SSA Scores" ... There are
two ways of entering SSA, Upload of ssa data or manual entry ... if the ssa is
uploaded and reflected, the status should change to complete and green."

Pinned here:

  1. Handed in without its school's SSA for the year, the visit reads
     "Awaiting SSA Scores", is not green, sorts with the work still open, and
     offers "Enter SSA Scores" — the profile's SSA drawer, for this visit.
  2. Once the school's SSA is in, by upload or by hand (any record holding
     the year), the same visit reads "Complete" and green.
  3. Entering the scores from that action keys them on the visit, so the
     visit reads "Complete".
  4. A Champion school takes no SSA: its visit is complete without one.
  5. Completed rows carry a green tint as well as green ink.
"""

from __future__ import annotations

import itertools
import re
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import StaffSchoolAssignment
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.my_plan.services import get_frontend_context
from apps.pl_review.test_completion_reviews import ReviewFixture
from apps.ssa.models import SsaRecord

FY = str(get_operational_fy())
CODES = [code for code, _label in SsaIntervention.choices]
_SF_IDS = itertools.count(8200)


class SsaVisitsAwaitTheirScores(ReviewFixture):
    def _context(self):
        return get_frontend_context(self.james_user, {"fy": FY, "period": "fy"})

    def _visit(self, *, ssa=True, school=None, **extra):
        values = {
            "status": "ia_verified",
            "ia_verification_status": "confirmed",
            "salesforce_activity_id": f"SVE-{next(_SF_IDS)}",
            "fy": FY,
            "quarter": "Q1",
            "planned_date": date.today() - timedelta(days=3),
            "actual_delivery_date": date.today() - timedelta(days=1),
        }
        if ssa:
            values.update(purpose_type="ssa_support", ssa_collection_expected=True)
        values.update(extra)
        return self._completion(self.james.id, school=school, **values)

    def _ssa(self, school, status="pending"):
        return SsaRecord.objects.create(
            school=school,
            date_of_ssa=timezone.now(),
            fy=FY,
            quarter="Q1",
            uploaded_by=self.pl_user.id,
            verification_status=status,
        )

    def _row(self, work):
        context = self._context()
        tables = [context["school_visits"], context["core_school_visits"]]
        tables += [group["rows"] for group in context["programme_school_work"]]
        rows = {row["id"]: row for table in tables for row in table}
        return rows[work.id]

    def test_without_its_ssa_the_visit_awaits_its_scores(self):
        open_work = self._visit(
            ssa=False,
            status="scheduled",
            salesforce_activity_id=None,
            planned_date=date.today() + timedelta(days=4),
            actual_delivery_date=None,
        )
        done = self._visit(ssa=False)
        work = self._visit()

        rows = self._context()["school_visits"]
        row = {r["id"]: r for r in rows}[work.id]
        self.assertEqual(row["status_label"], "Awaiting SSA Scores")
        self.assertEqual(row["status_tone"], "amber")
        self.assertEqual(row["row_state"], "")
        self.assertFalse(row["shows_complete"])
        self.assertEqual(row["next_action"]["text"], "Enter SSA Scores")
        self.assertEqual(
            row["next_action"]["url"],
            f"/schools/{self.school.id}/ssa-entry?activity={work.id}",
        )
        # Open work first, the visit awaiting its scores with it, the
        # complete visit last.
        order = [r["id"] for r in rows]
        self.assertLess(order.index(work.id), order.index(done.id))
        self.assertLess(order.index(open_work.id), order.index(done.id))

    def test_once_the_school_has_its_ssa_the_visit_is_complete(self):
        work = self._visit()
        self._ssa(self.school, status="pending")

        row = self._row(work)
        self.assertEqual(row["status_label"], "Complete")
        self.assertEqual(row["row_state"], "done")
        self.assertTrue(row["shows_complete"])

    def test_a_returned_ssa_does_not_complete_the_visit(self):
        work = self._visit()
        self._ssa(self.school, status="returned")
        self.assertEqual(self._row(work)["status_label"], "Awaiting SSA Scores")

    def test_entering_the_scores_from_the_action_completes_the_visit(self):
        work = self._visit()
        client = self.as_user(self.james_user)
        url = f"/schools/{self.school.id}/ssa-entry?activity={work.id}"

        self.assertContains(client.get(url), "Save SSA")
        data = {"date_of_ssa": date.today().isoformat()}
        data.update({f"score_{code}": "6.5" for code in CODES})
        self.assertEqual(client.post(url, data).status_code, 200)

        record = SsaRecord.objects.get(
            school=self.school, fy=FY, deleted_at__isnull=True
        )
        self.assertEqual(record.source_activity_id, work.id)
        self.assertEqual(self._row(work)["status_label"], "Complete")

    def test_a_champion_school_takes_no_ssa(self):
        champion = self._school("REV-CH", "Champion Primary")
        champion.school_type = "champion"
        champion.save(update_fields=["school_type"])
        StaffSchoolAssignment.objects.create(staff=self.james, school_id=champion.id)
        work = self._visit(school=champion)
        self.assertEqual(self._row(work)["status_label"], "Complete")

    def test_the_my_plan_actions_cell_offers_the_scores(self):
        work = self._visit()
        response = self.as_user(self.james_user).get("/my-plan/", {"fy": FY})
        html = response.content.decode()
        self.assertIn(f"/schools/{self.school.id}/ssa-entry?activity={work.id}", html)
        self.assertIn("Enter SSA Scores", html)


class CompletedRowsAreTintedGreen(ReviewFixture):
    def test_a_done_row_takes_the_success_tint(self):
        css = (
            Path(settings.BASE_DIR) / "static/css/components/row-state.css"
        ).read_text()
        self.assertRegex(
            css,
            re.compile(
                r"tr\[data-done\]\s*\{[^}]*"
                r"--edify-table-row-tint:\s*var\(--edify-success-light\)"
            ),
        )
