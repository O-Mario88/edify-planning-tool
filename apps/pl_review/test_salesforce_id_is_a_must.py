"""No visit or training is completed without its Salesforce ID, and every one
completed with it reaches its Programme Lead (owner, 2026-10-19).

"Salesforce ID is a MUST. Any activity without salesforce ID CANNOT be
completed." and "any activity that were completed and has salesforce ID that
are not showing on the execution and completion table MUST show for the PLs
to approve".

Pinned here:

  1. A school visit filed under the SSA data-gathering record type is a visit
     like any other: Complete and Submit refuse it without its ID, IA cannot
     verify it without one, and it does not count toward a milestone without
     one. Only admin and field events (record type NONE) carry no ID.
  2. Entering the ID on a CCEO's work hands it to the lead even when the
     hand-in finds something missing (a training's attendance): the work
     shows on the Execution & Completion table for the lead to approve or
     return, and the officer is told what the lead will see missing.
  3. The scheduled sweep hands in any work that holds its ID and was left
     behind, so the table and the counts never miss completed work.
  4. Nobody verifies work that came in without its ID, whatever the door:
     the Programme Lead's Verified, posted directly, and Impact Assessment's
     confirmation of staff work both refuse it (owner, 2026-10-19: "make
     sure that all completion should have salesforce ID").
"""

from __future__ import annotations

from pathlib import Path

from apps.activities.services import (
    complete,
    sf_kind_for_activity,
    start_completion,
    submit_for_review,
)
from apps.core.exceptions import BadRequest
from apps.pl_review.test_completion_reviews import QUEUE_URL
from apps.pl_review.test_pl_approves import _Fixture

SSA_GATHERING = "SSA_DATA_GATHERING"


class AnSsaDataGatheringVisitNeedsItsId(_Fixture):
    def _visit(self, **extra):
        return self._started(
            self.james.id, salesforce_record_type_snapshot=SSA_GATHERING, **extra
        )

    def test_it_is_a_visit_for_salesforce(self):
        self.assertEqual(sf_kind_for_activity(self._visit()), "visit")

    def test_admin_and_field_events_still_carry_none(self):
        work = self._started(self.james.id, salesforce_record_type_snapshot="NONE")
        self.assertIsNone(sf_kind_for_activity(work))

    def test_complete_refuses_it_without_the_id_and_moves_nothing(self):
        work = self._visit()
        with self.assertRaises(BadRequest):
            complete(work.id, {"salesforceId": ""}, self.james_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "completion_started")

    def test_complete_accepts_it_with_the_id(self):
        work = self._visit()
        complete(work.id, {"salesforceId": "SVE-8101"}, self.james_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")
        self.assertEqual(work.salesforce_activity_id, "SVE-8101")

    def test_submit_refuses_it_without_the_id(self):
        work = self._visit()
        with self.assertRaises(BadRequest):
            submit_for_review(work.id, self.james_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "completion_started")

    def test_ia_cannot_verify_it_without_the_id(self):
        from apps.activities.ia_services import _assert_verifiable

        work = self._visit(status="awaiting_ia_verification")
        with self.assertRaises(BadRequest):
            _assert_verifiable(work)

    def test_it_counts_toward_a_milestone_only_with_the_id(self):
        from apps.hr.milestone_progress import _salesforce_reference_satisfied

        work = self._visit()
        self.assertFalse(_salesforce_reference_satisfied(work))
        work.salesforce_activity_id = "SVE-8102"
        self.assertTrue(_salesforce_reference_satisfied(work))


class TheDrawersAskForTheId(_Fixture):
    """Seen live (2026-10-19): "School Visit + SSA Collection" visits opened a
    Complete drawer with no ID field, and reached the lead's Verify drawer
    saying they had no Salesforce record, with Verified offered."""

    def test_the_complete_drawer_asks_an_ssa_data_gathering_visit_for_its_id(self):
        work = self._started(
            self.james.id, salesforce_record_type_snapshot=SSA_GATHERING
        )
        response = self.as_user(self.james_user).get(
            f"/my-plan/{work.id}/complete-drawer", headers={"HX-Request": "true"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="salesforce_id"')
        self.assertContains(response, "Visit ID")
        self.assertNotContains(response, "has no Salesforce record")

    def test_the_verify_drawer_returns_one_handed_in_without_it(self):
        work = self._completion(
            self.james.id, salesforce_record_type_snapshot=SSA_GATHERING
        )
        response = self.as_user(self.pl_user).get(
            f"{QUEUE_URL}/{work.id}/drawer", headers={"HX-Request": "true"}
        )
        self.assertContains(response, "data-no-salesforce-id")
        self.assertNotContains(response, "has no Salesforce record")
        self.assertNotContains(response, ">Verified</button>")
        self.assertContains(response, ">Return</button>")

    def test_a_field_event_still_completes_without_one(self):
        work = self._started(self.james.id, salesforce_record_type_snapshot="NONE")
        response = self.as_user(self.james_user).get(
            f"/my-plan/{work.id}/complete-drawer", headers={"HX-Request": "true"}
        )
        self.assertNotContains(response, 'name="salesforce_id"')
        self.assertContains(response, "has no Salesforce record")


class NobodyVerifiesWorkWithoutItsId(_Fixture):
    """Seen live (2026-10-19): two "School Visit + SSA Collection" visits were
    handed in with no ID and waited on the lead's Verified."""

    def test_the_lead_cannot_verify_a_visit_handed_in_without_it(self):
        from apps.pl_review import services

        work = self._completion(
            self.james.id, salesforce_record_type_snapshot=SSA_GATHERING
        )
        with self.assertRaises(BadRequest):
            services.confirm(work.id, self.pl_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")

    def test_posting_verified_directly_moves_nothing(self):
        work = self._completion(self.james.id)
        self.as_user(self.pl_user).post(
            f"{QUEUE_URL}/{work.id}/confirm", headers={"HX-Request": "true"}
        )
        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")

    def test_the_lead_verifies_it_once_the_id_is_in(self):
        from apps.pl_review import services

        work = self._completion(
            self.james.id,
            salesforce_record_type_snapshot=SSA_GATHERING,
            salesforce_activity_id="SVE-8301",
        )
        services.confirm(work.id, self.pl_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "ia_verified")

    def test_a_field_event_is_verified_without_one(self):
        from apps.pl_review import services

        work = self._completion(self.james.id, salesforce_record_type_snapshot="NONE")
        services.confirm(work.id, self.pl_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "ia_verified")

    def test_ia_cannot_confirm_staff_work_without_it(self):
        from apps.activities.salesforce import ENTRY_SOURCE_IA_CONFIRMATION
        from apps.activities.services import _confirm_activity_after_authorization

        work = self._completion(self.james.id, status="awaiting_ia_verification")
        with self.assertRaises(BadRequest):
            _confirm_activity_after_authorization(
                work, {}, self.pl_user, entry_source=ENTRY_SOURCE_IA_CONFIRMATION
            )
        work.refresh_from_db()
        self.assertEqual(work.status, "awaiting_ia_verification")


class StartedWorkCannotSkipTheId(_Fixture):
    def test_a_started_visit_stays_started_until_its_id_is_in(self):
        work = self._completion(self.james.id, status="scheduled")
        start_completion(work.id, principal=self.james_user)
        with self.assertRaises(BadRequest):
            complete(work.id, {}, self.james_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "completion_started")


class EnteringTheIdAlwaysReachesTheLead(_Fixture):
    def test_a_training_without_attendance_goes_to_the_lead_and_says_so(self):
        work = self._started(self.james.id, activity_type="cluster_training")
        response = self.as_user(self.james_user).post(
            f"/activities/{work.id}/salesforce-id/action",
            {"salesforce_id": "TS-8201"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, "attendance")
        work.refresh_from_db()
        self.assertEqual(work.salesforce_activity_id, "TS-8201")
        self.assertEqual(work.status, "submitted_to_pl")
        page = self.register(self.as_user(self.pl_user), list="awaiting_pl", fy=work.fy)
        self.assertContains(page, work.id)


class TheSweepHandsInWhatWasLeftBehind(_Fixture):
    def test_the_job_hands_in_work_holding_its_id(self):
        from apps.realtime.jobs import _do_hand_in_entered_work

        left = self._started(self.james.id, salesforce_activity_id="SVE-8301")
        legacy = self._completion(
            self.james.id, status="completed", salesforce_activity_id="SVE-8302"
        )
        no_id = self._started(self.james.id)

        self.assertEqual(_do_hand_in_entered_work(), 2)
        for work, status in (
            (left, "submitted_to_pl"),
            (legacy, "submitted_to_pl"),
            (no_id, "completion_started"),
        ):
            work.refresh_from_db()
            self.assertEqual(work.status, status)
        self.assertEqual(_do_hand_in_entered_work(), 0)

    def test_the_job_is_registered_and_scheduled(self):
        from apps.realtime import jobs
        from apps.realtime.registry import JOB_NAMES

        self.assertIn("hand_in_entered_work", JOB_NAMES)
        self.assertTrue(callable(jobs.hand_in_entered_work_job))
        scheduler = Path(jobs.__file__).parent / "management/commands/runscheduler.py"
        self.assertIn(
            '"hand_in_entered_work": jobs.hand_in_entered_work_job',
            scheduler.read_text(),
        )
