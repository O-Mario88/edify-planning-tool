"""The Programme Lead confirms staff SSA; a lead's own counts at once (owner,
2026-10-16).

SSA keyed on a visit's completion showed nowhere: every record landed pending
until an Impact Assessment officer other than the collector confirmed it, and
every page but the profile's header reads confirmed records only. On live, 11
records keyed on visits waited with nobody confirming them, and the schools
read 0.00. The owner: "I am a PL so mine should show already only those of
CCEOs should awaits approval ... when PL approves they will reflect. Any SSA
entered and approved by PL should reflect immediately not show 0,0". And, of
the Core Schools page's Assessment cell: "Core package only track visits and
trainings. Once assessment is done and entered, it should be recorded and
reflect everywhere."

Pinned here:

  1. SSA a Programme Lead enters is confirmed at once (not a partner's).
  2. A CCEO's SSA keyed on a visit waits, and is confirmed when the lead
     approves the visit; keyed after the approval, it is confirmed at once.
  3. A lead confirms a supervised CCEO's SSA in the SSA queue, never another
     lead's officer's; Impact Assessment still may.
  4. Partner SSA stays with Impact Assessment, whoever approves the visit.
  5. The Core package's assessment follows the school's confirmed SSA.
  6. Records left pending by the old rule are confirmed by the deploy.
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.accounts.models import StaffSchoolAssignment
from apps.core.enums import SsaIntervention
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.core_schools.models import CorePlan
from apps.pl_review import services as reviews
from apps.pl_review.test_completion_reviews import ReviewFixture, _staff
from apps.ssa import services as ssa
from apps.ssa.models import SsaRecord
from apps.ssa.pl_confirmation import (
    confirm_left_pending,
    core_assessment_cells,
    sync_core_assessment,
)

CODES = [code for code, _label in SsaIntervention.choices]


class _Fixture(ReviewFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ia_user, _ = _staff("rev-ia@t.test", "Impact", EdifyRole.IMPACT_ASSESSMENT)
        StaffSchoolAssignment.objects.create(staff=cls.pl, school_id=cls.school.id)

    def _key(self, principal, *, school=None, activity=None, **extra):
        payload = {
            "schoolId": (school or self.school).school_id,
            "dateOfSsa": (date.today() - timedelta(days=3)).isoformat(),
            "scores": [{"intervention": code, "score": 7.0} for code in CODES],
            "collectorType": "staff",
        }
        if activity is not None:
            payload["sourceActivityId"] = activity.id
        payload.update(extra)
        return SsaRecord.objects.get(pk=ssa.upload(payload, principal)["id"])

    def _visit(self, owner_id, **extra):
        values = {"status": "completion_started"}
        values.update(extra)
        return self._completion(owner_id, **values)


class ALeadsOwnSsaCountsAtOnce(_Fixture):
    def test_scores_a_lead_keys_are_confirmed(self):
        record = self._key(self.pl_user)
        self.assertEqual(record.verification_status, "confirmed")
        self.assertEqual(record.verified_by_user_id, self.pl_user.id)
        self.assertIsNotNone(record.verified_at)

    def test_keyed_on_the_lead_s_own_visit_they_are_confirmed(self):
        from apps.activities.services import complete

        work = self._visit(self.pl.id)
        record = self._key(self.pl_user, activity=work)
        complete(work.id, {"salesforceId": "SVE-8101"}, self.pl_user)
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "confirmed")

    def test_the_school_reads_them(self):
        self._key(self.pl_user)
        self.assertIsNotNone(ssa.latest_applicable_record(self.school))

    def test_the_year_s_ssa_page_reads_them_under_their_year(self):
        # Owner, same day: "where FY27 scores are needed it should fetch from
        # database record". Scores taken in FY 2026/27 are filed as "2027"
        # and the SSA page for that year counts them.
        from apps.analytics.ssa_performance_service import build_dashboard
        from apps.core.fy import get_operational_fy

        record = self._key(self.pl_user)
        self.assertEqual(record.fy, get_operational_fy(record.date_of_ssa))
        page = build_dashboard(self.pl_user, {"fy": record.fy})
        self.assertEqual(page["kpis"]["assessed"], 1)
        self.assertEqual(
            build_dashboard(self.pl_user, {"fy": "2020"})["kpis"]["assessed"], 0
        )

    def test_a_partner_s_scores_the_lead_keys_still_wait_for_ia(self):
        record = self._key(self.pl_user, collectorType="partner")
        self.assertEqual(record.verification_status, "pending")


class ACceosSsaWaitsForTheLeadsApproval(_Fixture):
    def test_pending_until_the_lead_approves_the_visit(self):
        from apps.activities.services import complete

        work = self._visit(self.james.id)
        record = self._key(self.james_user, activity=work)
        complete(work.id, {"salesforceId": "SVE-8201"}, self.james_user)
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "pending")

        reviews.confirm(work.id, self.pl_user)
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "confirmed")
        self.assertEqual(record.verified_by_user_id, self.pl_user.id)
        self.assertIsNotNone(ssa.latest_applicable_record(self.school))

    def test_keyed_after_the_approval_they_are_confirmed(self):
        work = self._visit(self.james.id, status="submitted_to_pl")
        reviews.confirm(work.id, self.pl_user)
        record = self._key(self.james_user, activity=work)
        self.assertEqual(record.verification_status, "confirmed")
        self.assertEqual(record.verified_by_user_id, self.pl_user.id)

    def test_keyed_without_a_visit_they_wait(self):
        record = self._key(self.james_user)
        self.assertEqual(record.verification_status, "pending")


class TheLeadConfirmsInTheQueue(_Fixture):
    def test_the_lead_confirms_a_supervised_cceo_s_scores(self):
        record = self._key(self.james_user)
        self.assertIn(record, ssa.verifiable_records(self.pl_user))
        ssa.verify_record(record, self.pl_user)
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "confirmed")

    def test_not_another_lead_s_officer(self):
        record = self._key(self.rival_user, school=self.rival_school)
        self.assertNotIn(record, ssa.verifiable_records(self.pl_user))
        with self.assertRaises(Forbidden):
            ssa.verify_record(record, self.pl_user)

    def test_the_queue_page_lets_the_lead_confirm(self):
        record = self._key(self.james_user)
        response = self.as_user(self.pl_user).post(
            "/ssa/verification/", {"record_id": record.id, "action": "verify"}
        )
        self.assertIn(response.status_code, (200, 302), response.content[:300])
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "confirmed")

    def test_the_lead_is_asked_on_their_to_dos(self):
        from apps.ssa.collection_todos import collection_todos

        self._key(self.james_user)
        rows = collection_todos(
            self.pl_user, EdifyRole.COUNTRY_PROGRAM_LEAD.value, date.today()
        )
        self.assertIn(
            "Confirm 1 SSA record your officers entered", [r["title"] for r in rows]
        )

    def test_impact_assessment_still_may(self):
        record = self._key(self.james_user)
        ssa.verify_record(record, self.ia_user)
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "confirmed")


class PartnerSsaStaysWithIa(_Fixture):
    def test_approving_partner_work_leaves_its_scores_pending(self):
        work = self._visit(
            self.james.id, status="submitted_to_pl", delivery_type="partner"
        )
        record = self._key(self.james_user, activity=work, collectorType="partner")
        reviews._approve(work, self.pl_user.id)
        record.refresh_from_db()
        self.assertEqual(record.verification_status, "pending")


class TheCorePackageFollowsTheSsa(_Fixture):
    def _plan(self, fy):
        return CorePlan.objects.create(
            id=f"cplan-{self.school.school_id}-{fy}",
            school_id=self.school.school_id,
            fy=fy,
        )

    def test_a_confirmed_ssa_completes_the_core_assessment(self):
        record = self._key(self.james_user)
        plan = self._plan(record.fy)
        self.assertEqual(plan.assessment_completed, 0)
        ssa.verify_record(record, self.pl_user)
        plan.refresh_from_db()
        self.assertEqual(plan.assessment_completed, 1)

    def test_a_returned_ssa_takes_it_back(self):
        record = self._key(self.pl_user)
        plan = self._plan(record.fy)
        sync_core_assessment(self.school, record.fy)
        plan.refresh_from_db()
        self.assertEqual(plan.assessment_completed, 1)
        ssa.return_record(record, self.ia_user, "Scores do not add up")
        plan.refresh_from_db()
        self.assertEqual(plan.assessment_completed, 0)

    def test_a_slot_recount_keeps_it(self):
        from apps.core_schools.services import resync_plan_completion

        record = self._key(self.pl_user)
        plan = self._plan(record.fy)
        sync_core_assessment(self.school, record.fy)
        resync_plan_completion(plan)
        plan.refresh_from_db()
        self.assertEqual(plan.assessment_completed, 1)

    def test_the_core_row_reads_the_year_s_record(self):
        pending = self._key(self.james_user)
        cells = core_assessment_cells([self.school.id], pending.fy)
        self.assertEqual(cells[self.school.id]["status"], "Awaiting Approval")
        ssa.verify_record(pending, self.pl_user)
        cells = core_assessment_cells([self.school.id], pending.fy)
        self.assertEqual(cells[self.school.id]["status"], "Complete")
        # Another year's package does not read this year's record.
        other_year = str(int(pending.fy) - 1)
        self.assertEqual(
            core_assessment_cells([self.school.id], other_year)[self.school.id][
                "status"
            ],
            "Missing",
        )


class RecordsLeftPendingAreConfirmed(_Fixture):
    def _leave_pending(self, record):
        SsaRecord.objects.filter(pk=record.pk).update(
            verification_status="pending", verified_by_user_id=None, verified_at=None
        )
        record.refresh_from_db()
        return record

    def test_a_lead_s_own_and_an_approved_visit_s_are_confirmed(self):
        own = self._leave_pending(self._key(self.pl_user))
        StaffSchoolAssignment.objects.create(
            staff=self.james, school_id=self.mary_school.id
        )
        work = self._visit(
            self.james.id, status="submitted_to_pl", school=self.mary_school
        )
        reviews.confirm(work.id, self.pl_user)
        cceo = self._leave_pending(
            self._key(self.james_user, school=self.mary_school, activity=work)
        )

        rows = confirm_left_pending(apply=True)

        self.assertEqual({row["id"] for row in rows}, {own.id, cceo.id})
        own.refresh_from_db()
        cceo.refresh_from_db()
        self.assertEqual(own.verification_status, "confirmed")
        self.assertEqual(cceo.verification_status, "confirmed")
        self.assertEqual(cceo.verified_by_user_id, self.pl_user.id)

    def test_an_unapproved_visit_waits_and_a_dry_run_changes_nothing(self):
        work = self._visit(self.james.id)
        waiting = self._key(self.james_user, activity=work)
        own = self._leave_pending(self._key(self.pl_user, school=self.mary_school))

        self.assertEqual([row["id"] for row in confirm_left_pending()], [own.id])
        own.refresh_from_db()
        self.assertEqual(own.verification_status, "pending")
        confirm_left_pending(apply=True)
        waiting.refresh_from_db()
        self.assertEqual(waiting.verification_status, "pending")
