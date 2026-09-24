"""Verified and Return, with the reason carried to the officer and back.

Owner, 2026-09-24: "PL and IA verification workflow should have two buttons,
Verified and Return. Return is if the PL or IA does not confirm the activity in
Salesforce — for training and school visit. For example if I have uploaded the
training attendance form and training ID but when the approver checks and finds
the participants are not entered. The reason for returning should be clearly
stated. The staff can resubmit after fixing the issue."
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.activities import return_notes
from apps.activities.ia_models import IAVerification
from apps.activities.ia_services import ActivityReturnService
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.my_plan.services import get_frontend_context
from apps.pl_review import services
from apps.pl_review.test_completion_reviews import QUEUE_URL, ReviewFixture, _staff

REASON = "The 25 participants are not entered in Salesforce for TS-1001."


class TheReasonIsRequiredTest(ReviewFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ia_user, _ = _staff("vr-ia@t.test", "Ivy IA", EdifyRole.IMPACT_ASSESSMENT)

    def _awaiting_ia(self, **extra):
        return self._completion(
            self.james.id, status="awaiting_ia_verification", **extra
        )

    def test_ia_cannot_return_without_saying_why(self):
        work = self._awaiting_ia()
        for comment in ("", "   "):
            with self.subTest(comment=comment):
                with self.assertRaises(BadRequest):
                    ActivityReturnService.return_activity(
                        work,
                        ["Participants not entered in Salesforce"],
                        comment,
                        self.ia_user.id,
                    )
        work.refresh_from_db()
        self.assertEqual(work.status, "awaiting_ia_verification")

    def test_an_ia_return_writes_the_reason_where_the_officer_reads_it(self):
        work = self._awaiting_ia()
        ActivityReturnService.return_activity(
            work, ["Participants not entered in Salesforce"], REASON, self.ia_user.id
        )
        work.refresh_from_db()
        self.assertEqual(work.status, "returned_by_ia")
        self.assertEqual(
            return_notes.note_for(work),
            f"Participants not entered in Salesforce — {REASON}",
        )
        self.assertEqual(return_notes.returned_by(work), "Impact Assessment")

    def test_the_pl_return_still_refuses_a_blank_reason(self):
        work = self._completion(self.james.id)
        with self.assertRaises(BadRequest):
            services.return_activity(work.id, {"reason": "  "}, self.pl_user)

    def test_a_long_partner_instruction_is_cut_to_fit_not_refused(self):
        long_note = return_notes.compose(["x"], "y" * 900)
        self.assertEqual(len(long_note), return_notes.NOTE_MAX)
        self.assertTrue(long_note.endswith("…"))


class TheOfficerSeesWhyAndResubmitsTest(ReviewFixture):
    def _returned_by_pl(self):
        # Delivered last week: a returned visit with a past date used to drop
        # off My Plan altogether, taking its reason with it.
        work = self._completion(
            self.james.id,
            planned_date=date.today() - timedelta(days=6),
            salesforce_activity_id="SV-4242",
        )
        self._evidence(work)
        services.return_activity(work.id, {"reason": REASON}, self.pl_user)
        work.refresh_from_db()
        return work

    def _evidence(self, work):
        EvidenceRecord.objects.create(
            activity=work,
            kind="attendance_form",
            uri="attendance.pdf",
            original_name="attendance.pdf",
            uploaded_by=self.james_user.id,
        )

    def test_my_plan_lists_the_returned_work_with_the_lead_s_reason(self):
        work = self._returned_by_pl()
        context = get_frontend_context(self.james_user, {"fy": work.fy, "period": "fy"})
        rows = {row["id"]: row for row in context["returned_needs_correction"]}
        self.assertIn(work.id, rows)
        self.assertEqual(rows[work.id]["return_reason"], REASON)
        self.assertEqual(rows[work.id]["returned_by"], "Programme Lead")

    def test_the_activity_page_states_the_reason_while_it_is_returned(self):
        work = self._returned_by_pl()
        response = self.as_user(self.james_user).get(f"/my-plan/{work.id}")
        self.assertContains(response, "data-return-note")
        self.assertContains(response, "Returned by Programme Lead:")
        self.assertContains(response, REASON)

    def test_resubmitting_sends_it_back_to_the_lead_and_clears_returned(self):
        from apps.activities.services import submit_for_review

        work = self._returned_by_pl()
        submit_for_review(work.id, self.james_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")
        self.assertNotEqual(work.ia_verification_status, "returned")

        # The fixed completion no longer tells its officer it was returned.
        response = self.as_user(self.james_user).get(f"/my-plan/{work.id}")
        self.assertNotContains(response, "data-return-note")
        # And the lead can decide it again.
        self.assertTrue(services.may_review(self.pl_user, work))

    def test_resubmitting_after_an_ia_return_clears_the_ia_record(self):
        from apps.activities.services import submit_for_review

        ia_user, _ = _staff("vr-ia2@t.test", "Iris IA", EdifyRole.IMPACT_ASSESSMENT)
        work = self._completion(
            self.james.id,
            status="awaiting_ia_verification",
            salesforce_activity_id="SV-5151",
        )
        self._evidence(work)
        ActivityReturnService.return_activity(
            work, ["Participants not entered in Salesforce"], REASON, ia_user.id
        )
        submit_for_review(work.id, self.james_user)
        work.refresh_from_db()
        self.assertEqual(work.ia_verification_status, "pending")
        self.assertEqual(IAVerification.objects.get(activity=work).status, "pending")


class BothDecisionsOnEverySurfaceTest(ReviewFixture):
    def test_the_register_offers_verified_and_return(self):
        work = self._completion(self.james.id)
        response = self.as_user(self.pl_user).get(QUEUE_URL)
        self.assertContains(response, ">Verified</button>")
        self.assertContains(response, f"{QUEUE_URL}/{work.id}/return-drawer")

    def test_the_return_drawer_asks_why_with_an_example(self):
        work = self._completion(self.james.id)
        response = self.as_user(self.pl_user).get(
            f"{QUEUE_URL}/{work.id}/return-drawer", headers={"HX-Request": "true"}
        )
        self.assertContains(response, "Why are you returning it?")
        self.assertContains(response, "not entered in Salesforce")
        self.assertContains(response, "required")

    def test_cluster_oversight_offers_the_lead_verified_and_return(self):
        from apps.core.fy import get_operational_fy

        fy = get_operational_fy()
        session = Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=self.cluster,
            responsible_staff_id=self.james.id,
            fy=fy,
            planned_date=date.today() - timedelta(days=2),
            status="submitted_to_pl",
        )
        response = self.as_user(self.pl_user).get("/cluster-oversight/", {"fy": fy})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"/pl/review-queue/{session.id}/confirm")
        self.assertContains(response, f"/pl/review-queue/{session.id}/return-drawer")
        self.assertContains(response, "data-session-return")

    def test_the_ia_workspace_offers_verified_and_return_with_the_example(self):
        ia_user, _ = _staff("vr-ia3@t.test", "Ian IA", EdifyRole.IMPACT_ASSESSMENT)
        work = self._completion(
            self.james.id,
            status="awaiting_ia_verification",
            salesforce_activity_id="SV-6161",
        )
        response = self.as_user(ia_user).get(f"/ia/verification/{work.id}/?return=1")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(">\nVerified\n</button>", html)
        self.assertIn(">\nReturn\n</button>", html)
        self.assertIn("Participants not entered in Salesforce", html)
        self.assertIn("Why are you returning it? (required)", html)
        # ?return=1 opens the reason panel, the door Cluster Oversight's
        # Return link uses.
        self.assertIn("returnOpen: true,", html)

    def test_an_ia_return_posted_without_a_reason_keeps_the_work(self):
        ia_user, _ = _staff("vr-ia4@t.test", "Ina IA", EdifyRole.IMPACT_ASSESSMENT)
        work = self._completion(
            self.james.id,
            status="awaiting_ia_verification",
            salesforce_activity_id="SV-7171",
        )
        response = self.as_user(ia_user).post(
            f"/ia/verification/{work.id}/return",
            {"reasons": ["Participants not entered in Salesforce"], "comment": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("?return=1", response["Location"])
        work.refresh_from_db()
        self.assertEqual(work.status, "awaiting_ia_verification")
