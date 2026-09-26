"""Partner-facilitated trainings on Partner Monitoring (owner, 2026-09-26).

"All trainings assigned to partners should be under Partner Oversight as
well, and the cost is the training fee. The table has Cluster name,
District, Training Name, SSA Intervention, Training Date, Salesforce ID and
Evidence, Status (Upcoming or Completed), Cost (facilitation fee). Once the
staff enter the training, upload the attendance and complete with the
Salesforce ID, the status changes to Completed and the Action is Confirm
Verification or Return. Confirm Verification completes the activity; Return
asks for reasons — especially a Salesforce ID with no participants in
Salesforce."
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activities.return_notes import COMMON_REASONS
from apps.clusters.models import Cluster
from apps.evidence.models import EvidenceRecord
from apps.planning import partner_oversight_service as svc
from apps.planning.test_partner_oversight import PartnerOversightFixture

NO_PARTICIPANTS = "Salesforce ID entered, but no participants in Salesforce"


class FacilitatedTrainingsTest(PartnerOversightFixture):
    FEE = 150_000

    def train(self, *, cceo=None, partner=None, when=None, status="scheduled"):
        cceo = cceo or self.cceo
        partner = partner or self.partner
        planned = when or (date.today() + timedelta(days=5))
        cluster = Cluster.objects.create(
            name="Kira Cluster",
            region=self.region,
            district=self.district,
            responsible_staff_id=cceo.id,
        )
        activity = Activity.objects.create(
            activity_type="cluster_training",
            cluster=cluster,
            fy=self.fy,
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month,
            status=status,
            delivery_type="staff",
            responsible_staff_id=cceo.id,
            facilitating_partner_id=partner.id,
            focus_intervention="financial_health",
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="group_training_facilitation_fee",
            label="Facilitation fee",
            unit_cost=self.FEE,
            quantity=1,
            amount=self.FEE,
            line_item_type="facilitation",
            partner_id=partner.id,
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="group_training_venue_cost",
            label="Venue",
            unit_cost=30_000,
            quantity=1,
            amount=30_000,
            line_item_type="venue",
        )
        return activity

    def complete(self, activity):
        """The officer's completion: attendance uploaded, Salesforce ID in."""
        activity.status = "submitted_to_pl"
        activity.salesforce_activity_id = "TS-FAC-0001"
        activity.save(update_fields=["status", "salesforce_activity_id"])
        EvidenceRecord.objects.create(
            activity=activity, kind="attendance_form", uri="fac/attendance.pdf"
        )
        return activity

    def page(self, user):
        self.client.force_login(user)
        response = self.client.get("/partner-oversight/")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    # -- the table ------------------------------------------------------------

    def test_the_lead_reads_it_under_the_facilitating_partner(self):
        self.train()
        body = self.page(self.pl_user)
        # The Partner has a tab although nothing is assigned to it.
        self.assertIn("Partner X", body)
        self.assertIn("Trainings facilitated (1)", body)
        table = body.split("data-partner-trainings-table", 1)[1].split("</table>", 1)[0]
        headers = re.findall(r"<th scope=\"col\"[^>]*>([^<]+)</th>", table)
        self.assertEqual(
            headers,
            [
                "Cluster Name",
                "District",
                "Training Name",
                "SSA Intervention",
                "Training Date",
                "Salesforce ID",
                "Evidence",
                "Status",
                "Cost",
                "Action",
            ],
        )
        self.assertIn("Kira Cluster", table)
        self.assertIn("Kampala", table)
        self.assertIn("UGX 150,000", table)  # the fee, not the whole budget
        self.assertIn(">Upcoming<", table)
        self.assertIn("Not in SF", table)
        self.assertIn("No Evidence Uploaded", table)
        # The Partner's own three tables are unchanged.
        self.assertEqual(body.count("data-partner-monitoring-table"), 3)

    def test_completed_it_offers_the_lead_confirm_verification_or_return(self):
        training = self.complete(self.train())
        body = self.page(self.pl_user)
        table = body.split("data-partner-trainings-table", 1)[1].split("</table>", 1)[0]
        self.assertIn(">Completed<", table)
        self.assertIn("TS-FAC-0001", table)
        self.assertIn("Attendance", table)
        self.assertIn(
            f'hx-get="/pl/review-queue/{training.id}/drawer?from=partner-trainings"',
            table,
        )
        self.assertIn(f'hx-get="/pl/review-queue/{training.id}/return-drawer"', table)
        self.assertIn("Confirm Verification", table)
        # The page still only reads: both open drawers.
        self.assertNotIn("hx-post", table)

    def test_the_officer_reads_it_but_does_not_decide_it(self):
        self.complete(self.train())
        body = self.page(self.cceo_user)
        table = body.split("data-partner-trainings-table", 1)[1].split("</table>", 1)[0]
        self.assertIn(">Completed<", table)
        self.assertNotIn("Confirm Verification", table)
        self.assertNotIn("return-drawer", table)

    def test_another_team_does_not_see_it(self):
        self.complete(self.train())
        body = self.page(self.rival_pl_user)
        self.assertNotIn("data-partner-trainings-table", body)

    def test_an_overdue_training_reads_overdue(self):
        self.train(when=date.today() - timedelta(days=3))
        [row] = svc.facilitated_trainings(self.pl_user, fys=(self.fy,))
        self.assertEqual(row.status_label, "Overdue")
        self.assertEqual(row.fee, self.FEE)

    # -- the decision ---------------------------------------------------------

    def test_confirm_verification_completes_the_training(self):
        training = self.complete(self.train())
        self.client.force_login(self.pl_user)
        drawer = self.client.get(
            f"/pl/review-queue/{training.id}/drawer?from=partner-trainings"
        ).content.decode()
        self.assertIn(">Confirm Verification</button>", drawer)
        self.client.post(f"/pl/review-queue/{training.id}/confirm")
        training.refresh_from_db()
        self.assertEqual(training.status, "ia_verified")
        [row] = svc.facilitated_trainings(self.pl_user, fys=(self.fy,))
        self.assertEqual(row.status_label, "Verified")

    def test_return_asks_for_reasons_including_no_participants(self):
        training = self.complete(self.train())
        self.client.force_login(self.pl_user)
        drawer = self.client.get(
            f"/pl/review-queue/{training.id}/return-drawer"
        ).content.decode()
        self.assertIn(NO_PARTICIPANTS, drawer)
        self.assertEqual(COMMON_REASONS[0], NO_PARTICIPANTS)
        self.assertEqual(
            len(re.findall(r'<input type="checkbox"[^>]*name="reasons"', drawer)),
            len(COMMON_REASONS),
        )

        self.client.post(
            f"/pl/review-queue/{training.id}/return", {"reasons": [NO_PARTICIPANTS]}
        )
        training.refresh_from_db()
        self.assertEqual(training.status, "returned_by_pl")
        self.assertEqual(training.pl_review_note, NO_PARTICIPANTS)
        [row] = svc.facilitated_trainings(self.pl_user, fys=(self.fy,))
        self.assertEqual(row.status_label, "Returned")

    def test_reasons_and_a_written_note_travel_together(self):
        training = self.complete(self.train())
        self.client.force_login(self.pl_user)
        self.client.post(
            f"/pl/review-queue/{training.id}/return",
            {"reasons": [NO_PARTICIPANTS], "reason": "Enter the 24 teachers."},
        )
        training.refresh_from_db()
        self.assertEqual(
            training.pl_review_note, f"{NO_PARTICIPANTS} — Enter the 24 teachers."
        )

    def test_a_return_with_no_reason_is_refused(self):
        training = self.complete(self.train())
        self.client.force_login(self.pl_user)
        self.client.post(f"/pl/review-queue/{training.id}/return", {})
        training.refresh_from_db()
        self.assertEqual(training.status, "submitted_to_pl")
