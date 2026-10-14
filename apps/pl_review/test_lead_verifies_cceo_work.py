"""Program Leads verify their CCEOs' field work (owner, 2026-10-12).

"Program Leads are the ones to verify CCEO field activities (visits, trainings
and Cluster meetings). PL should click verify, then the uploaded form. Can you
change verification from IA to PL so that the PL can clear for their members."

Pinned here:

  1. Verify opens the completion WITH the uploaded forms — each file shown and
     openable — and Verified is decided there, never from a row.
  2. A CCEO's staff-delivered completion is the lead's whichever status filed
     it: one an older path left with Impact Assessment is listed on Completion
     Reviews, cleared there, and gone from IA's queue and IA's Verify.
  3. Routing reads the owner: a completion somebody else submits for a CCEO
     still goes to the CCEO's lead. Partner work, and a lead's own field work,
     stay with Impact Assessment.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from apps.activities.ia_models import IAVerification
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.pl_review import services
from apps.pl_review.test_completion_reviews import QUEUE_URL, ReviewFixture, _staff


class VerifyOpensTheSalesforceIdTest(ReviewFixture):
    """UPLOAD-OFF (owner, 2026-10-13: "remove the upload and use strictly
    visit ID and training IDs to complete the activities"). Verify used to
    open the uploaded form; it opens the ID the completion stands on."""

    def test_the_drawer_shows_the_id_and_a_form_held_as_one_button(self):
        """Staff no longer upload. Where a completion still holds a form from
        before, the lead is offered it as ONE button that opens one PDF in a
        popup, however many times it was uploaded (owner, 2026-10-14: "it
        displays list of all the uploads even if the same document is uploaded
        3 tines ... fix it to show only one upload")."""
        work = self._completion(self.james.id, salesforce_activity_id="SVE-4040")
        forms = [
            EvidenceRecord.objects.create(
                activity=work,
                kind="visit_form",
                uri="visit.pdf",
                original_name="visit-form.pdf",
                mime_type="application/pdf",
                uploaded_by=self.james_user.id,
            )
            for _ in range(3)
        ]

        response = self.as_user(self.pl_user).get(
            f"{QUEUE_URL}/{work.id}/drawer", headers={"HX-Request": "true"}
        )
        html = response.content.decode()
        self.assertIn("data-completion-id", html)
        self.assertIn("Visit ID", html)
        self.assertIn("SVE-4040", html)
        # One button for the form, not a list of the three records behind it,
        # and no picture of it in the drawer.
        self.assertEqual(html.count("View Uploaded Visit Form</span>"), 1)
        self.assertEqual(html.count("data-uploaded-form-popup"), 1)
        self.assertIn(f"/api/evidence/activity/{work.id}/form", html)
        self.assertNotIn("data-uploaded-forms", html)
        for form in forms:
            self.assertNotIn(form.id, html)
        self.assertNotIn("visit-form.pdf", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("<embed", html)
        # Then decides: Verified posts the confirm; Return opens the reason.
        self.assertIn(f'action="{QUEUE_URL}/{work.id}/confirm"', html)
        self.assertIn(">Verified</button>", html)
        self.assertIn(f'hx-get="{QUEUE_URL}/{work.id}/return-drawer"', html)

    def test_with_the_id_and_no_form_the_drawer_offers_verified(self):
        work = self._completion(self.james.id, salesforce_activity_id="SVE-4041")
        response = self.as_user(self.pl_user).get(
            f"{QUEUE_URL}/{work.id}/drawer", headers={"HX-Request": "true"}
        )
        self.assertNotContains(response, "data-no-evidence")
        self.assertNotContains(response, "Visit Form — missing")
        # Nothing was uploaded, and nothing is asked for: no button either.
        self.assertNotContains(response, "View Uploaded")
        self.assertContains(response, ">Verified</button>")
        self.assertContains(response, ">Return</button>")

    def test_without_the_id_the_drawer_offers_return_not_verified(self):
        work = self._completion(self.james.id)
        response = self.as_user(self.pl_user).get(
            f"{QUEUE_URL}/{work.id}/drawer", headers={"HX-Request": "true"}
        )
        self.assertContains(response, "data-no-salesforce-id")
        self.assertNotContains(response, ">Verified</button>")
        self.assertContains(response, ">Return</button>")

    def test_a_training_reads_training_id(self):
        work = self._completion(
            self.james.id,
            activity_type="cluster_training",
            salesforce_activity_id="TS-4042",
        )
        response = self.as_user(self.pl_user).get(
            f"{QUEUE_URL}/{work.id}/drawer", headers={"HX-Request": "true"}
        )
        self.assertContains(response, "Training ID")
        self.assertContains(response, "TS-4042")


class TheLeadClearsWorkLeftWithIaTest(ReviewFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ia_user, _ = _staff("lv-ia@t.test", "Ivy IA", EdifyRole.IMPACT_ASSESSMENT)

    def _stuck(self, owner_id, **extra):
        """A completion an older path routed to Impact Assessment."""
        return self._completion(
            owner_id,
            status="awaiting_ia_verification",
            salesforce_activity_id=extra.pop("salesforce_activity_id", "SVE-9001"),
            submitted_to_ia_at=timezone.now() - timedelta(days=2),
            **extra,
        )

    def test_it_is_listed_on_completion_reviews_and_verified_there(self):
        work = self._stuck(self.james.id)
        IAVerification.objects.create(activity=work, status="pending")
        EvidenceRecord.objects.create(
            activity=work, kind="visit_form", uri="v.pdf", uploaded_by="u"
        )

        rows = services.review_register(self.pl_user)["rows"]
        self.assertEqual([row["id"] for row in rows], [work.id])
        self.assertEqual(rows[0]["days_waiting"], 2)

        client = self.as_user(self.pl_user)
        response = self.register(client)
        self.assertContains(response, f'data-review-row="{work.id}"')
        response = client.post(f"{QUEUE_URL}/{work.id}/confirm", {"next": QUEUE_URL})
        self.assertEqual(response.status_code, 302)
        work.refresh_from_db()
        self.assertEqual(work.status, "ia_verified")
        self.assertEqual(work.pl_reviewed_by, self.pl_user.id)
        self.assertEqual(work.ia_confirmed_by, self.pl_user.id)
        # The IA workspace's own record no longer reads pending.
        record = IAVerification.objects.get(activity=work)
        self.assertEqual(record.status, "confirmed")
        self.assertEqual(record.verified_by, self.pl_user.id)

    def test_impact_assessment_no_longer_holds_it(self):
        from apps.frontend.views.ia_views import _ia_staff_queue

        work = self._stuck(self.james.id)
        own = self._stuck(self.pl.id, salesforce_activity_id="SVE-9002")

        class _Request:
            user = self.ia_user

        queued = set(_ia_staff_queue(_Request()).values_list("id", flat=True))
        self.assertNotIn(work.id, queued, "a CCEO's completion is the lead's")
        self.assertIn(own.id, queued, "a lead's own field work stays with IA")

        client = self.as_user(self.ia_user)
        response = client.get(f"/ia/verification/{work.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-lead-verifies")
        self.assertNotContains(response, 'form="verify-form" type="submit"')
        response = client.post(
            f"/ia/verification/{work.id}/verify", {"evidence_exists": "on"}
        )
        self.assertEqual(response.status_code, 403)
        work.refresh_from_db()
        self.assertEqual(work.status, "awaiting_ia_verification")

    def test_the_lead_cannot_take_partner_work_or_a_leads_own_work(self):
        partner_work = self._stuck(
            None,
            delivery_type="partner",
            monitored_by_staff_id=self.james.id,
            assigned_partner_id="p1",
            salesforce_activity_id="",
        )
        with self.assertRaises(BadRequest) as refused:
            services.confirm(partner_work.id, self.pl_user)
        self.assertIn("Impact Assessment", str(refused.exception.detail))
        self.assertNotIn(
            partner_work.id,
            [row["id"] for row in services.review_register(self.admin_user)["rows"]],
        )
        own = self._stuck(self.rival_pl.id, salesforce_activity_id="SVE-9003")
        self.assertNotIn(
            own.id,
            [row["id"] for row in services.review_register(self.admin_user)["rows"]],
        )
        with self.assertRaises(BadRequest):
            services.confirm(own.id, self.admin_user)


class RoutingReadsTheOwnerTest(ReviewFixture):
    def _submittable(self, owner_id, **extra):
        values = {
            "status": "evidence_uploaded",
            "salesforce_activity_id": "SVE-7007",
            "planned_date": date.today() - timedelta(days=1),
        }
        values.update(extra)
        work = self._completion(owner_id, **values)
        EvidenceRecord.objects.create(
            activity=work, kind="visit_form", uri="v.pdf", uploaded_by="u"
        )
        return work

    def test_a_submission_pressed_for_a_cceo_still_goes_to_their_lead(self):
        from apps.activities.services import submit_for_review

        work = self._submittable(self.james.id)
        submit_for_review(work.id, self.admin_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")

    def test_a_leads_own_submission_goes_to_impact_assessment(self):
        from apps.activities.services import submit_for_review

        work = self._submittable(self.pl.id, salesforce_activity_id="SVE-7008")
        submit_for_review(work.id, self.pl_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "awaiting_ia_verification")

    def test_the_rule_as_a_predicate(self):
        cceo_work = self._completion(self.james.id)
        lead_work = self._completion(self.pl.id)
        partner_work = self._completion(
            None, delivery_type="partner", monitored_by_staff_id=self.james.id
        )
        self.assertTrue(services.routes_to_lead(cceo_work, self.admin_user))
        self.assertTrue(services.routes_to_lead(lead_work, self.james_user))
        self.assertFalse(services.routes_to_lead(lead_work, self.pl_user))
        self.assertFalse(services.routes_to_lead(partner_work, self.james_user))
        self.assertTrue(services.lead_verifies(cceo_work))
        self.assertFalse(services.lead_verifies(partner_work))
        self.assertFalse(services.lead_verifies(lead_work))
        self.assertTrue(
            Activity.objects.filter(
                services.lead_verified_q(), id=cceo_work.id
            ).exists()
        )
        self.assertFalse(
            Activity.objects.filter(
                services.lead_verified_q(), id=lead_work.id
            ).exists()
        )
