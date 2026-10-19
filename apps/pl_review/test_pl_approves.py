"""The Programme Lead approves; Impact Assessment approves no CCEO or PL work
(owner, 2026-10-15).

"as long as the activity is completed and entered in salesforce, completed
using salesforce ID it is counted and marked as completed from my Plan and
everywhere they appear. On the activity status on my plan can you make sure
the column is PL approved not IA approved. Any activity not approved by PL
should not be counted PL should be alerted to approve it. IA does not approve
any activity. it is the PL who approves for CCEO and theirs are approved
automatically."

Asked, the owner chose: a CCEO's work with its Salesforce ID in is marked
completed at once and counted once the lead approves it; IA keeps partner work
and other staff's.

Pinned here:

  1. A lead's own work is approved the moment it is handed in.
  2. A CCEO's waits with the lead, who is told.
  3. Entering the Salesforce ID on staff work completes it, whatever day it
     was planned for — it used to save the ID and leave the work "started".
  4. Work already holding its ID that was never handed in is handed in now
     (the deploy's data migration runs the same function).
  5. My Plan's Verification column reads "PL Approved", never "IA complete",
     on a CCEO's or a lead's work; partner work keeps IA's words. Its status
     reads "Complete" either way (owner, 2026-10-17).
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.core.rbac import EdifyRole
from apps.my_plan.services import (
    get_activity_status_label_and_class,
    verification_label,
)
from apps.notifications.models import Notification
from apps.pl_review import services
from apps.pl_review.handed_in import hand_in_entered_work
from apps.pl_review.test_completion_reviews import ReviewFixture, _staff


class _Fixture(ReviewFixture):
    def _started(self, owner_id, **extra):
        values = {
            "status": "completion_started",
            "planned_date": date.today() + timedelta(days=9),
        }
        values.update(extra)
        return self._completion(owner_id, **values)


class ALeadsOwnWorkIsApprovedWhenHandedIn(_Fixture):
    def test_through_complete(self):
        from apps.activities.services import complete

        work = self._started(self.pl.id)
        complete(work.id, {"salesforceId": "SVE-7101"}, self.pl_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "ia_verified")
        self.assertEqual(work.ia_verification_status, "confirmed")
        self.assertEqual(work.pl_reviewed_by, self.pl_user.id)
        listed = [row["id"] for row in services.review_register(self.pl_user)["rows"]]
        self.assertNotIn(work.id, listed)

    def test_through_submit(self):
        from apps.activities.services import submit_for_review

        work = self._started(self.pl.id, salesforce_activity_id="SVE-7102")
        submit_for_review(work.id, self.pl_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "ia_verified")

    def test_an_acting_lead_s_own_work_still_goes_to_their_lead(self):
        # Acting for a month is following up, not approving (owner,
        # 2026-10-07): the officer's own work is a CCEO's.
        from apps.activities.services import complete

        self.james_user.roles = [EdifyRole.CCEO.value]
        self.james_user.active_role = EdifyRole.COUNTRY_PROGRAM_LEAD.value
        work = self._started(self.james.id)
        complete(work.id, {"salesforceId": "SVE-7103"}, self.james_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")


class ACceosWorkWaitsForTheLead(_Fixture):
    def test_handed_in_ahead_of_its_day_it_waits_and_the_lead_is_told(self):
        from apps.activities.services import complete

        work = self._started(self.james.id)
        complete(work.id, {"salesforceId": "SVE-7201"}, self.james_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")
        listed = [row["id"] for row in services.review_register(self.pl_user)["rows"]]
        self.assertIn(work.id, listed)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.pl_user.id, context_id=work.id
            ).exists()
        )


class EnteringTheIdCompletesStaffWork(_Fixture):
    def _enter(self, user, work, sf_id):
        return self.as_user(user).post(
            f"/activities/{work.id}/salesforce-id/action",
            {"salesforce_id": sf_id},
            headers={"HX-Request": "true"},
        )

    def test_work_planned_for_later_is_handed_in(self):
        work = self._completion(
            self.james.id,
            status="scheduled",
            planned_date=date.today() + timedelta(days=9),
        )
        response = self._enter(self.james_user, work, "SVE-7301")
        self.assertEqual(response.status_code, 200, response.content)
        work.refresh_from_db()
        self.assertEqual(work.salesforce_activity_id, "SVE-7301")
        self.assertEqual(work.status, "submitted_to_pl")

    def test_work_already_begun_is_handed_in(self):
        work = self._started(self.james.id, status="evidence_uploaded")
        self._enter(self.james_user, work, "SVE-7302")
        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")

    def test_a_training_without_attendance_reaches_the_lead_and_says_why(self):
        # Owner, 2026-10-19: completed work with its Salesforce ID "MUST show
        # for the PLs to approve". It used to keep the ID and stay started,
        # on no lead's table.
        work = self._started(self.james.id, activity_type="cluster_training")
        response = self._enter(self.james_user, work, "TS-7303")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "attendance")
        work.refresh_from_db()
        self.assertEqual(work.salesforce_activity_id, "TS-7303")
        self.assertEqual(work.status, "submitted_to_pl")


class WorkHoldingItsIdIsHandedIn(_Fixture):
    def test_the_backfill(self):
        cceo = self._started(
            self.james.id, status="evidence_uploaded", salesforce_activity_id="SV-7401"
        )
        lead = self._started(self.pl.id, salesforce_activity_id="SV-7402")
        waiting = self._completion(
            self.pl.id, status="submitted_to_pl", salesforce_activity_id="SV-7403"
        )
        no_id = self._started(self.james.id)
        partner = self._started(
            None,
            delivery_type="partner",
            monitored_by_staff_id=self.james.id,
            salesforce_activity_id="SV-7404",
        )
        _, coordinator = _staff(
            "hi-pc@t.test", "Pat Coordinator", EdifyRole.PROJECT_COORDINATOR
        )
        theirs = self._started(coordinator.id, salesforce_activity_id="SV-7405")

        dry = hand_in_entered_work(apply=False)
        self.assertEqual({row["id"] for row in dry}, {cceo.id, lead.id, waiting.id})
        cceo.refresh_from_db()
        self.assertEqual(cceo.status, "evidence_uploaded", "a dry run writes nothing")

        hand_in_entered_work(apply=True)
        expected = {
            cceo: "submitted_to_pl",
            lead: "ia_verified",
            waiting: "ia_verified",
            no_id: "completion_started",
            partner: "completion_started",
            theirs: "completion_started",
        }
        for work, status in expected.items():
            work.refresh_from_db()
            self.assertEqual(work.status, status, work.salesforce_activity_id)
        self.assertEqual(hand_in_entered_work(apply=True), [])


class MyPlanReadsPlApproved(_Fixture):
    def test_the_status_column(self):
        today = date.today()
        cceo = self._completion(
            self.james.id,
            status="ia_verified",
            ia_verification_status="confirmed",
            salesforce_activity_id="SV-7501",
        )
        partner = self._completion(
            None,
            status="ia_verified",
            delivery_type="partner",
            salesforce_activity_id="SV-7502",
            ia_verification_status="confirmed",
        )
        # Completed work reads complete whoever approved it (owner,
        # 2026-10-17); "PL Approved" is the Verification column's below.
        self.assertEqual(
            get_activity_status_label_and_class(cceo, today)[0], "Complete"
        )
        self.assertEqual(
            get_activity_status_label_and_class(partner, today)[0],
            "Complete",
        )

    def test_the_verification_column(self):
        approved = self._completion(
            self.james.id,
            status="ia_verified",
            ia_verification_status="confirmed",
            salesforce_activity_id="SV-7503",
        )
        waiting = self._completion(
            self.james.id,
            status="submitted_to_pl",
            ia_verification_status="pending",
            salesforce_activity_id="SV-7504",
        )
        partner = self._completion(
            None,
            status="awaiting_ia_verification",
            delivery_type="partner",
            ia_verification_status="pending",
        )
        # Whoever reads it: it read "IA pending" to a lead.
        self.assertEqual(verification_label(approved)[0], "PL Approved")
        self.assertEqual(verification_label(waiting)[0], "PL Pending")
        self.assertEqual(verification_label(partner)[0], "IA Pending")
