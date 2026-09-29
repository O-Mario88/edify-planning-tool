"""Bulk withdraw from Partner Monitoring (owner, 2026-09-29).

"Allow the staff to bulk withdraw schools from project or partner assignment.
They can go to the project profile or partner monitoring and check all the
schools they want to withdraw and be able to withdraw."

Each ticked school goes through the single withdrawal's own rules: a Program
Lead withdraws; a CCEO withdraws unscheduled work and asks the Program Lead
about work the partner has already scheduled; work outside the reader's team,
or already settled, is left and said so.
"""

from __future__ import annotations

from apps.accounts.models import StaffSchoolAssignment
from apps.partners.models import PartnerAssignment
from apps.partners.withdrawal_models import PartnerAssignmentWithdrawal
from apps.planning.test_partner_oversight_page import PageFixture
from apps.schools.models import School

REASONS = {
    "reason_category": "not_scheduled",
    "partner_facing_reason": "The school's support is moving back to Edify staff this term.",
    "disposition": "return_to_planning",
}


class PartnerBulkWithdrawalTest(PageFixture):
    def setUp(self):
        self.school_b = School.objects.create(
            school_id="s1b", name="School B", district=self.district, region=self.region
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo, school_id=self.school_b.id
        )

    def _post(self, ids, **extra):
        return self.client.post(
            "/partner-oversight/withdraw/bulk",
            {"assignment_ids": ids, **REASONS, **extra},
            HTTP_HX_REQUEST="true",
        )

    def _flash(self) -> str:
        from django.contrib.messages import get_messages

        page = self.client.get("/partner-oversight/")
        return " ".join(str(m) for m in get_messages(page.wsgi_request)) or (
            page.content.decode()
        )

    def test_nothing_withdrawn_keeps_the_drawer_open_with_the_reasons(self):
        theirs = self.assign(cceo=self.rival_cceo, school=self.rival_school)
        self.sign_in(self.pl_user)
        response = self._post([theirs.id])
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("data-drawer-stay-open", body)
        self.assertIn("not in your team", body)

    def test_the_tables_offer_a_tick_for_withdrawable_rows(self):
        first = self.assign()
        self.sign_in(self.pl_user)
        body = self.client.get("/partner-oversight/").content.decode()
        self.assertIn("data-bulk-withdraw-table", body)
        self.assertIn(f'data-withdraw-pick value="{first.id}"', body)
        self.assertIn("Withdraw selected", body)

    def test_settled_work_has_no_tick(self):
        a = self.assign()
        activity = self.schedule(a)
        activity.status = "ia_verified"
        activity.payment_status = "paid"
        activity.save()
        self.sign_in(self.pl_user)
        body = self.client.get("/partner-oversight/").content.decode()
        self.assertNotIn(f'data-withdraw-pick value="{a.id}"', body)

    def test_the_program_lead_withdraws_every_ticked_school(self):
        first = self.assign()
        second = self.assign(school=self.school_b)
        self.sign_in(self.pl_user)

        drawer = self.client.get(
            "/partner-oversight/withdraw/bulk",
            {"assignment_ids": [first.id, second.id]},
        ).content.decode()
        self.assertIn("School A", drawer)
        self.assertIn("School B", drawer)
        self.assertIn("Withdraw 2 schools", drawer)

        response = self._post([first.id, second.id])
        # Done: the drawer closes and the page reloads with the summary.
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Refresh"], "true")
        self.assertIn("Withdrew 2 schools", self._flash())
        self.assertEqual(
            PartnerAssignmentWithdrawal.objects.filter(
                assignment_id__in=[first.id, second.id]
            ).count(),
            2,
        )

    def test_a_cceo_withdraws_unscheduled_work_and_asks_about_scheduled_work(self):
        open_work = self.assign()
        scheduled = self.assign(school=self.school_b)
        self.schedule(scheduled)
        self.sign_in(self.cceo_user)

        drawer = self.client.get(
            "/partner-oversight/withdraw/bulk",
            {"assignment_ids": [open_work.id, scheduled.id]},
        ).content.decode()
        self.assertIn("Request to Program Lead", drawer)

        self._post([open_work.id, scheduled.id])
        body = self._flash()
        self.assertIn("Withdrew 1 school", body)
        self.assertIn("sent 1 to your Program Lead", body)
        # The scheduled one is only asked: its activity is untouched.
        scheduled.refresh_from_db()
        self.assertEqual(scheduled.status, "partner_scheduled")

    def test_work_outside_the_team_is_left_and_said_so(self):
        mine = self.assign()
        theirs = self.assign(cceo=self.rival_cceo, school=self.rival_school)
        self.sign_in(self.pl_user)

        self._post([mine.id, theirs.id])
        body = self._flash()
        self.assertIn("1 not withdrawn", body)
        self.assertIn("not in your team", body)
        self.assertFalse(
            PartnerAssignmentWithdrawal.objects.filter(assignment=theirs).exists()
        )
        self.assertEqual(PartnerAssignment.objects.get(id=theirs.id).status, "assigned")

    def test_nothing_ticked_is_refused(self):
        self.sign_in(self.pl_user)
        response = self.client.get("/partner-oversight/withdraw/bulk")
        self.assertEqual(response.status_code, 400)
