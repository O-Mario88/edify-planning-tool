"""Journey 12 — Policy lifecycle, walked end to end.

Journey 12 of the mandate's twenty-two: Upload, Review, Return, Approval,
Publication, Employee acknowledgment, Reminder, Superseding version.

Its steps are individually covered in `apps.documents.tests` — the review
two-person rule, the reminder job, the superseded-version health check. What
none of them asks is the question the last step exists for: **after a material
new version is published, is the person who agreed to the old one obliged to
read the new one?**

Getting that wrong is a compliance failure with legal weight rather than a
display bug. Everyone appears to have accepted a safeguarding policy they have
never seen, and the record says so.

The platform's design is right: `DocumentAcknowledgement` is documented as
"one person's answer to one exact version — keyed on the version, never the
document". But being right in the writer is not the same as being right in the
reader; D8, the CorePlan status and the metric registry were each a correct
writer with a reader that disagreed.

There is a specific seam worth naming here. Two paths create obligations, and
they divide the work between them:

- `generate_pending`, on publish, creates a row per targeted user for the new
  version and marks the previous AGREED answers SUPERSEDED.
- `ensure_pending_for`, lazily on access, backfills people who have **no**
  record for the document at all — and deliberately skips anyone who has one,
  because "material new versions are handled by publish".

So the backfill cannot repair a miss by publish. If `generate_pending` ever
fails to reach somebody who answered v1, that person is invisible to both
paths for ever: they hold an acknowledgement, so the backfill passes over
them, and they never got a v2 row to be overdue on. This walks both halves and
asserts the obligation actually returns.
"""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.documents.models import (
    AcknowledgementState,
    DocumentAcknowledgement,
    DocumentType,
)
from apps.documents.services import AcknowledgementService, DocumentService


def _user(key, role, country=""):
    user = User.objects.create(
        id=f"pj-{key}"[:30],
        email=f"pj-{key}@edify.org",
        name=f"PJ {key}",
        roles=[role],
        active_role=role,
        is_active=True,
    )
    if country:
        StaffProfile.objects.create(
            id=f"pjsp-{key}"[:30], user=user, title=role, country=country
        )
    return user


def _pdf(name="policy.pdf") -> SimpleUploadedFile:
    body = b"%PDF-1.4\n1 0 obj<</Type /Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
    return SimpleUploadedFile(name, body, content_type="application/pdf")


class PolicyLifecycleJourneyTest(TestCase):
    """Upload → review → publish → acknowledge → supersede → obliged again."""

    @classmethod
    def setUpTestData(cls):
        cls.hr = _user("hr", "HumanResources", country="Uganda")
        # A policy's reviewer may not be its uploader.
        cls.hr_reviewer = _user("hr2", "HumanResources", country="Uganda")
        cls.cceo = _user("cceo", "CCEO", country="Uganda")

    def _policy(self):
        document = DocumentService.create(
            self.hr,
            {
                "title": "Safeguarding Policy",
                "description": "How Edify protects children in every school.",
                "document_type": DocumentType.POLICY,
                "acknowledgement_required": True,
                "agreement_required": True,
                "acknowledgement_reason": "Everyone working with schools must accept it.",
                "blocks_application_access": True,
                "require_reacknowledgement_on_new_version": True,
                "required_reading_minutes": 1,
            },
        )
        DocumentService.set_audience(self.hr, document, [{"role": "CCEO"}])
        version = DocumentService.add_version(
            self.hr, document, _pdf(), {"effective_date": timezone.localdate()}
        )
        return document, version

    def _publish(self, document, version):
        DocumentService.submit_for_review(self.hr, document)
        DocumentService.review(self.hr_reviewer, version, True, "Checked.")
        return DocumentService.publish(self.hr, version)

    def _pending_ids(self):
        return {a.id for a in AcknowledgementService.pending_for(self.cceo)}

    def test_a_material_new_version_obliges_the_person_who_agreed_to_the_old_one(self):
        # ── 1-5. Upload, review, approve, publish ─────────────────────────
        document, v1 = self._policy()
        self._publish(document, v1)

        # ── 6. Employee acknowledgment ────────────────────────────────────
        pending = AcknowledgementService.pending_for(self.cceo)
        self.assertEqual(
            len(pending),
            1,
            "publishing a mandatory policy created no obligation for its "
            "audience, so nothing below would be testing a superseding rule",
        )
        first = pending[0]
        self.assertEqual(first.version_id, v1.id)
        AcknowledgementService.respond(
            self.cceo, first.id, "agree", typed_name="PJ cceo"
        )
        first.refresh_from_db()
        self.assertEqual(first.state, AcknowledgementState.AGREED)
        self.assertEqual(
            self._pending_ids(),
            set(),
            "the person still has an outstanding obligation after agreeing",
        )

        # ── 8. Superseding version ────────────────────────────────────────
        v2 = DocumentService.add_version(
            self.hr,
            document,
            _pdf("policy-v2.pdf"),
            {"effective_date": timezone.localdate(), "material_change": True},
        )
        DocumentService.submit_for_review(self.hr, document)
        DocumentService.review(self.hr_reviewer, v2, True, "Material revision.")
        DocumentService.publish(self.hr, v2)

        # The v1 answer is preserved as the record of what they agreed to —
        # never rewritten, only marked as belonging to a superseded version.
        first.refresh_from_db()
        self.assertEqual(
            first.state,
            AcknowledgementState.SUPERSEDED,
            "the earlier answer was rewritten or left standing as current; it "
            "must be kept, and kept as history",
        )
        self.assertEqual(first.version_id, v1.id)

        # The obligation returns. This is the whole journey: agreeing to v1
        # must not make anyone compliant with v2.
        pending_after = AcknowledgementService.pending_for(self.cceo)
        self.assertEqual(
            len(pending_after),
            1,
            "publishing a material new version left the person with no "
            "obligation to read it — they agreed to a policy that no longer "
            "exists and the record calls them compliant",
        )
        self.assertEqual(
            pending_after[0].version_id,
            v2.id,
            "the returned obligation points at the wrong version",
        )
        self.assertTrue(
            AcknowledgementService.blocking_for(self.cceo),
            "a blocking policy's new version does not withhold the "
            "application, so the obligation has no force",
        )

    def test_the_lazy_backfill_cannot_repair_a_missed_superseding_obligation(self):
        """Naming the seam rather than assuming it holds.

        `ensure_pending_for` skips anyone who holds any acknowledgement for
        the document. So if the publish path ever fails to reach someone who
        answered v1, no later access repairs it. This asserts the division of
        responsibility explicitly, so a future change that makes publish
        conditional has something to break.
        """
        document, v1 = self._policy()
        self._publish(document, v1)
        pending = AcknowledgementService.pending_for(self.cceo)
        AcknowledgementService.respond(
            self.cceo, pending[0].id, "agree", typed_name="PJ cceo"
        )

        # Simulate the publish path having missed this person for v2: the
        # version exists and is current, but no row was created for them.
        v2 = DocumentService.add_version(
            self.hr,
            document,
            _pdf("policy-v2.pdf"),
            {"effective_date": timezone.localdate(), "material_change": True},
        )
        DocumentService.submit_for_review(self.hr, document)
        DocumentService.review(self.hr_reviewer, v2, True, "Material revision.")
        DocumentService.publish(self.hr, v2)
        DocumentAcknowledgement.objects.filter(
            version=v2, user_id=self.cceo.id
        ).delete()

        # The backfill runs on their next access and does NOT restore it.
        AcknowledgementService.ensure_pending_for(self.cceo)
        self.assertEqual(
            DocumentAcknowledgement.objects.filter(
                version=v2, user_id=self.cceo.id
            ).count(),
            0,
            "ensure_pending_for now backfills people who already hold an "
            "acknowledgement. That is a behaviour change worth a deliberate "
            "decision: it would make the publish path's completeness less "
            "load-bearing, which is an improvement, but this test records "
            "which path is responsible today.",
        )
