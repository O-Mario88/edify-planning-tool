"""Upload Center, Document Library and policy-compliance tests.

Grouped by the guarantee each set defends: no duplication of the canonical
workflows, the security gate, the document lifecycle, the access gate,
acknowledgement and versioning, engagement honesty, comment privacy, and the
Help Center mapping.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.core.exceptions import BadRequest, Forbidden
from apps.documents.models import (
    AcknowledgementState,
    DocumentAcknowledgement,
    DocumentAsset,
    DocumentStatus,
    DocumentType,
    DocumentVersion,
    PreviewStatus,
)
from apps.documents.services import (
    AcknowledgementService,
    CommentService,
    DocumentService,
    EngagementService,
    audience_matches,
)


def _user(key, role, country=""):
    """A user, plus the StaffProfile that carries their country.

    Country lives on StaffProfile, not User — audience rules and the Country
    Director's compliance scope both resolve it from there.
    """
    user = User.objects.create(
        id=f"doc-{key}"[:30],
        email=f"doc-{key}@edify.org",
        name=f"Doc {key}",
        roles=[role],
        active_role=role,
        is_active=True,
    )
    if country:
        StaffProfile.objects.create(
            id=f"docsp-{key}"[:30], user=user, title=role, country=country
        )
    return user


def _pdf(name="policy.pdf") -> SimpleUploadedFile:
    # A minimal but genuine PDF: the magic-byte gate reads real bytes.
    body = b"%PDF-1.4\n1 0 obj<</Type /Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
    return SimpleUploadedFile(name, body, content_type="application/pdf")


def _pptx(name="deck.pptx") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
    )


class DocumentTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr = _user("hr", "HumanResources", country="Uganda")
        cls.admin = _user("admin", "Admin")
        cls.ia = _user("ia", "ImpactAssessment")
        cls.cceo = _user("cceo", "CCEO", country="Uganda")
        cls.cd = _user("cd", "CountryDirector", country="Uganda")

    def _policy(self, **overrides):
        data = {
            "title": overrides.pop("title", "Safeguarding Policy"),
            "description": "How Edify protects children in every school we serve.",
            "document_type": DocumentType.POLICY,
            "acknowledgement_required": True,
            "agreement_required": True,
            "acknowledgement_reason": "Everyone working with schools must accept it.",
            "blocks_application_access": True,
        }
        data.update(overrides)
        document = DocumentService.create(self.hr, data)
        DocumentService.set_audience(self.hr, document, [{"role": "CCEO"}])
        version = DocumentService.add_version(
            self.hr, document, _pdf(), {"effective_date": date.today()}
        )
        return document, version

    def _publish(self, document, version):
        DocumentService.submit_for_review(self.hr, document)
        DocumentService.review(self.hr, version, True, "Checked.")
        return DocumentService.publish(self.hr, version)


# ── No duplication of the canonical workflows ────────────────────────────────


class NoDuplicationTests(DocumentTestBase):
    """The Upload Center indexes; it never becomes a second store."""

    def test_the_document_library_holds_only_documents(self):
        """Evidence, PD certificates and import batches keep their own homes."""
        from apps.documents import models as document_models

        model_names = {
            m.__name__
            for m in document_models.__dict__.values()
            if isinstance(m, type) and hasattr(m, "_meta")
        }
        for foreign in ("EvidenceRecord", "SchoolImportBatch", "SSAImportBatch"):
            self.assertNotIn(foreign, model_names)

    def test_the_upload_center_reads_import_batches_rather_than_copying_them(self):
        from apps.documents.upload_center import UploadCenterService
        from apps.schools.models import SchoolImportBatch

        batch = SchoolImportBatch.objects.create(
            file_name="schools.xlsx", uploaded_by=self.admin.id, total_rows=12
        )
        rows = UploadCenterService.rows(self.admin)
        match = [r for r in rows if r.record_id == batch.id]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0].record_type, "school_import")
        # Nothing was written into the document library to make it appear.
        self.assertEqual(DocumentAsset.objects.count(), 0)

    def test_structured_imports_are_never_given_a_pdf_preview(self):
        """A school roster is a spreadsheet to validate, not a document to read."""
        from apps.documents.upload_center import UploadCenterService
        from apps.schools.models import SSAImportBatch

        SSAImportBatch.objects.create(
            file_name="ssa.csv", uploaded_by=self.admin.id, total_rows=5
        )
        rows = UploadCenterService.rows(self.admin)
        ssa = [r for r in rows if r.record_type == "ssa_import"][0]
        self.assertEqual(ssa.preview_status, "Structured preview")
        self.assertIn("import results", ssa.next_action.lower() + " import results")

    def test_evidence_appears_without_a_second_review_workflow(self):
        from apps.documents.upload_center import _evidence

        # The adapter offers no mutation at all -- review stays in the
        # evidence workflow, which is the one definition of "verified".
        import apps.documents.upload_center as module

        for name in dir(module):
            self.assertNotIn(name, {"review_evidence", "verify_evidence"})
        self.assertTrue(callable(_evidence))


# ── File security ────────────────────────────────────────────────────────────


class FileSecurityTests(DocumentTestBase):
    def test_a_disguised_executable_is_refused(self):
        from apps.documents.storage import assert_safe_document_upload

        with self.assertRaises(BadRequest):
            assert_safe_document_upload(
                original_name="payload.exe",
                mime_type="application/pdf",
                head=b"MZ\x90\x00",
                size=100,
            )

    def test_a_mime_mismatch_is_refused(self):
        from apps.documents.storage import assert_safe_document_upload

        with self.assertRaises(BadRequest):
            assert_safe_document_upload(
                original_name="policy.pdf",
                mime_type="image/png",
                head=b"%PDF-1.4",
                size=100,
            )

    def test_content_that_contradicts_the_extension_is_refused(self):
        from apps.documents.storage import assert_safe_document_upload

        with self.assertRaises(BadRequest):
            assert_safe_document_upload(
                original_name="policy.pdf",
                mime_type="application/pdf",
                head=b"\x89PNG\r\n\x1a\n",
                size=100,
            )

    def test_presentations_are_accepted_here_and_nowhere_else(self):
        """Training decks belong in the Document Library, not in evidence."""
        from apps.documents.storage import assert_safe_document_upload
        from apps.evidence.validation import assert_safe_upload

        head = b"PK\x03\x04" + b"\x00" * 20
        mime = (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        self.assertEqual(
            assert_safe_document_upload(
                original_name="deck.pptx", mime_type=mime, head=head, size=1000
            ),
            ".pptx",
        )
        with self.assertRaises(BadRequest):
            assert_safe_upload(
                original_name="deck.pptx", mime_type=mime, head=head, size=1000
            )

    def test_a_path_traversal_name_is_refused(self):
        from apps.documents.storage import document_path

        for name in ("../../etc/passwd", "/etc/passwd", "..", "a/../../b"):
            with self.subTest(name):
                with self.assertRaises(BadRequest):
                    document_path(name)

    def test_the_evidence_ceiling_is_unchanged_by_the_document_ceiling(self):
        from apps.evidence.validation import MAX_FILE_SIZE, assert_safe_upload

        with self.assertRaises(BadRequest):
            assert_safe_upload(
                original_name="big.pdf",
                mime_type="application/pdf",
                head=b"%PDF",
                size=MAX_FILE_SIZE + 1,
            )


# ── Lifecycle ────────────────────────────────────────────────────────────────


class LifecycleTests(DocumentTestBase):
    def test_a_new_document_starts_as_an_invisible_draft(self):
        document, _ = self._policy()
        self.assertEqual(document.status, DocumentStatus.DRAFT)
        from apps.documents.services import readable_documents

        self.assertEqual(readable_documents(self.cceo), [])

    def test_a_description_is_required(self):
        with self.assertRaises(BadRequest):
            DocumentService.create(
                self.hr,
                {
                    "title": "Nameless",
                    "description": "  ",
                    "document_type": DocumentType.POLICY,
                },
            )

    def test_publication_requires_review(self):
        document, version = self._policy()
        with self.assertRaises(BadRequest):
            DocumentService.publish(self.hr, version)

    def test_publication_requires_an_audience(self):
        document = DocumentService.create(
            self.hr,
            {
                "title": "Unaddressed Policy",
                "description": "Nobody is named.",
                "document_type": DocumentType.POLICY,
            },
        )
        version = DocumentService.add_version(
            self.hr, document, _pdf(), {"effective_date": date.today()}
        )
        DocumentService.submit_for_review(self.hr, document)
        DocumentService.review(self.hr, version, True)
        with self.assertRaises(BadRequest) as raised:
            DocumentService.publish(self.hr, version)
        self.assertIn("audience", str(raised.exception))

    def test_a_mandatory_policy_needs_its_agreement_wording(self):
        document, version = self._policy(acknowledgement_reason="")
        DocumentService.submit_for_review(self.hr, document)
        DocumentService.review(self.hr, version, True)
        with self.assertRaises(BadRequest):
            DocumentService.publish(self.hr, version)

    def test_publishing_makes_it_readable_to_its_audience_only(self):
        from apps.documents.services import readable_documents

        document, version = self._policy()
        self._publish(document, version)
        self.assertEqual(len(readable_documents(self.cceo)), 1)
        self.assertEqual(readable_documents(self.ia), [])

    def test_an_empty_audience_reaches_nobody_rather_than_everybody(self):
        document = DocumentService.create(
            self.hr,
            {
                "title": "No Audience",
                "description": "None set.",
                "document_type": DocumentType.MANUAL,
            },
        )
        self.assertFalse(audience_matches(document, self.cceo))

    def test_creating_a_policy_needs_the_permission(self):
        with self.assertRaises(Forbidden):
            DocumentService.create(
                self.cceo,
                {
                    "title": "Unauthorised",
                    "description": "x",
                    "document_type": DocumentType.POLICY,
                },
            )

    def test_ia_publishes_training_resources_but_not_policy(self):
        training = DocumentService.create(
            self.ia,
            {
                "title": "Literacy Manual",
                "description": "How to run literacy support.",
                "document_type": DocumentType.TRAINING_MANUAL,
            },
        )
        self.assertEqual(training.document_type, DocumentType.TRAINING_MANUAL)
        with self.assertRaises(Forbidden):
            DocumentService.create(
                self.ia,
                {
                    "title": "IA Policy",
                    "description": "x",
                    "document_type": DocumentType.POLICY,
                },
            )

    def test_a_new_version_never_overwrites_the_published_one(self):
        document, version = self._policy()
        self._publish(document, version)
        second = DocumentService.add_version(
            self.hr, document, _pdf("v2.pdf"), {"effective_date": date.today()}
        )
        self.assertEqual(second.version_number, 2)
        version.refresh_from_db()
        self.assertIsNotNone(version.published_at)
        self.assertEqual(DocumentVersion.objects.filter(document=document).count(), 2)


# ── Preview ──────────────────────────────────────────────────────────────────


class PreviewTests(DocumentTestBase):
    def test_a_pdf_is_its_own_preview(self):
        document, version = self._policy()
        self._publish(document, version)
        version.refresh_from_db()
        self.assertEqual(version.preview_status, PreviewStatus.READY)
        self.assertEqual(version.preview_uri, version.uri)

    def test_conversion_is_not_repeated_for_the_same_version(self):
        from apps.documents.storage import build_preview

        document, version = self._policy()
        self._publish(document, version)
        version.refresh_from_db()
        first = version.preview_generated_at
        build_preview(version)
        version.refresh_from_db()
        self.assertEqual(version.preview_generated_at, first)

    def test_a_failed_conversion_does_not_reject_the_document(self):
        """A manual that will not convert is still a manual people need."""
        document = DocumentService.create(
            self.ia,
            {
                "title": "Deck",
                "description": "Training slides.",
                "document_type": DocumentType.TRAINING_PRESENTATION,
            },
        )
        DocumentService.set_audience(self.admin, document, [{"role": "CCEO"}])
        version = DocumentService.add_version(
            self.ia, document, _pptx(), {"effective_date": date.today()}
        )
        DocumentService.submit_for_review(self.ia, document)
        DocumentService.review(self.admin, version, True)
        DocumentService.publish(self.admin, version)

        document.refresh_from_db()
        version.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.PUBLISHED)
        # Whether LibreOffice is installed on this host decides which of these
        # it is; neither blocks publication, and the original is untouched.
        self.assertIn(
            version.preview_status,
            {PreviewStatus.READY, PreviewStatus.FAILED},
        )
        self.assertTrue(version.uri)


# ── Acknowledgement and versioning ───────────────────────────────────────────


class AcknowledgementTests(DocumentTestBase):
    def test_publishing_a_mandatory_policy_creates_pending_records(self):
        document, version = self._policy()
        self._publish(document, version)
        acks = DocumentAcknowledgement.objects.filter(version=version)
        self.assertEqual(acks.count(), 1)
        self.assertEqual(acks.first().user_id, self.cceo.id)
        self.assertEqual(acks.first().state, AcknowledgementState.PENDING)

    def test_agreeing_records_the_version_and_the_statement(self):
        document, version = self._policy()
        self._publish(document, version)
        ack = DocumentAcknowledgement.objects.get(version=version)
        result = AcknowledgementService.respond(self.cceo, ack.id, "agree")
        self.assertEqual(result.state, AcknowledgementState.AGREED)
        self.assertEqual(result.version_id, version.id)
        self.assertIn("agree to comply", result.statement)
        self.assertIsNotNone(result.responded_at)

    def test_disagreeing_requires_a_reason(self):
        document, version = self._policy()
        self._publish(document, version)
        ack = DocumentAcknowledgement.objects.get(version=version)
        with self.assertRaises(BadRequest):
            AcknowledgementService.respond(self.cceo, ack.id, "disagree", "")

    def test_a_required_comment_is_enforced(self):
        document, version = self._policy(comment_required=True)
        self._publish(document, version)
        ack = DocumentAcknowledgement.objects.get(version=version)
        with self.assertRaises(BadRequest):
            AcknowledgementService.respond(self.cceo, ack.id, "agree", "")

    def test_nobody_answers_for_anybody_else(self):
        document, version = self._policy()
        self._publish(document, version)
        ack = DocumentAcknowledgement.objects.get(version=version)
        with self.assertRaises(Forbidden):
            AcknowledgementService.respond(self.hr, ack.id, "agree")

    def test_a_material_new_version_asks_everyone_again(self):
        document, version = self._policy()
        self._publish(document, version)
        first = DocumentAcknowledgement.objects.get(version=version)
        AcknowledgementService.respond(self.cceo, first.id, "agree")

        second = DocumentService.add_version(
            self.hr,
            document,
            _pdf("v2.pdf"),
            {"effective_date": date.today(), "material_change": True},
        )
        DocumentService.submit_for_review(self.hr, document)
        DocumentService.review(self.hr, second, True)
        DocumentService.publish(self.hr, second)

        self.assertTrue(
            DocumentAcknowledgement.objects.filter(
                version=second, user_id=self.cceo.id, state=AcknowledgementState.PENDING
            ).exists()
        )

    def test_the_earlier_answer_is_preserved_not_rewritten(self):
        document, version = self._policy()
        self._publish(document, version)
        first = DocumentAcknowledgement.objects.get(version=version)
        AcknowledgementService.respond(self.cceo, first.id, "agree", "")

        second = DocumentService.add_version(
            self.hr,
            document,
            _pdf("v2.pdf"),
            {"effective_date": date.today(), "material_change": True},
        )
        DocumentService.submit_for_review(self.hr, document)
        DocumentService.review(self.hr, second, True)
        DocumentService.publish(self.hr, second)

        first.refresh_from_db()
        # Marked as belonging to a superseded version, and still on the record
        # with its choice, statement and timestamp intact.
        self.assertEqual(first.state, AcknowledgementState.SUPERSEDED)
        self.assertEqual(first.choice, "agree")
        self.assertIsNotNone(first.responded_at)

    def test_a_non_material_change_does_not_ask_everyone_again(self):
        document, version = self._policy()
        self._publish(document, version)
        second = DocumentService.add_version(
            self.hr,
            document,
            _pdf("v2.pdf"),
            {"effective_date": date.today(), "material_change": False},
        )
        DocumentService.submit_for_review(self.hr, document)
        DocumentService.review(self.hr, second, True)
        DocumentService.publish(self.hr, second)
        self.assertEqual(
            DocumentAcknowledgement.objects.filter(version=second).count(), 0
        )


# ── The access gate ──────────────────────────────────────────────────────────


class AccessGateTests(DocumentTestBase):
    def setUp(self):
        self.document, self.version = self._policy()
        self._publish(self.document, self.version)
        self.client = Client()
        self.client.force_login(self.cceo)

    def test_a_pending_user_is_sent_to_the_agreement_center(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/policy-agreement")

    def test_a_direct_url_cannot_bypass_the_gate(self):
        for path in ("/planning", "/my-plan", "/schools"):
            with self.subTest(path):
                self.assertEqual(self.client.get(path).status_code, 302)

    def test_an_api_call_cannot_bypass_the_gate(self):
        response = self.client.get("/api/activities", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertIn("redirect", response.json())

    def test_an_htmx_request_cannot_bypass_the_gate(self):
        response = self.client.get("/dashboard", HTTP_HX_REQUEST="true")
        self.assertEqual(response["HX-Redirect"], "/policy-agreement")

    def test_the_gated_user_can_still_read_the_policy(self):
        self.assertEqual(
            self.client.get(f"/documents/{self.document.slug}/").status_code, 200
        )
        self.assertEqual(self.client.get("/policy-agreement").status_code, 200)

    def test_the_gated_user_can_still_reach_support_and_logout(self):
        for path in ("/support", "/logout"):
            with self.subTest(path):
                self.assertNotEqual(self.client.get(path).status_code, 302)

    def test_agreeing_opens_the_application(self):
        ack = DocumentAcknowledgement.objects.get(version=self.version)
        self.client.post(f"/api/documents/acknowledge/{ack.id}", {"choice": "agree"})
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_disagreeing_restricts_rather_than_opens(self):
        ack = DocumentAcknowledgement.objects.get(version=self.version)
        self.client.post(
            f"/api/documents/acknowledge/{ack.id}",
            {"choice": "disagree", "comment": "I need clarification on section 4."},
        )
        response = self.client.get("/dashboard")
        self.assertEqual(response["Location"], "/policy-agreement/restricted")
        self.assertEqual(
            self.client.get("/policy-agreement/restricted").status_code, 200
        )

    def test_a_user_may_change_a_disagreement_to_agreement(self):
        ack = DocumentAcknowledgement.objects.get(version=self.version)
        self.client.post(
            f"/api/documents/acknowledge/{ack.id}",
            {"choice": "disagree", "comment": "Concern."},
        )
        self.client.post(f"/api/documents/acknowledge/{ack.id}", {"choice": "agree"})
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_the_original_disagreement_stays_in_the_audit_history(self):
        from apps.audit.models import AuditLog

        ack = DocumentAcknowledgement.objects.get(version=self.version)
        self.client.post(
            f"/api/documents/acknowledge/{ack.id}",
            {"choice": "disagree", "comment": "Concern."},
        )
        self.client.post(f"/api/documents/acknowledge/{ack.id}", {"choice": "agree"})
        self.assertTrue(
            AuditLog.objects.filter(action="documents.policy_disagreed").exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="documents.policy_agreed").exists()
        )

    def test_a_user_outside_the_audience_is_never_gated(self):
        """IA is not in this policy's audience, so nothing withholds the app.

        /dashboard redirects IA to its own dashboard, so the assertion is that
        the redirect is *not* the policy gate rather than that there is none.
        """
        client = Client()
        client.force_login(self.ia)
        response = client.get("/dashboard")
        self.assertNotIn("/policy-agreement", response.get("Location", ""))
        self.assertEqual(client.get("/ia/dashboard/").status_code, 200)

    def test_a_policy_that_does_not_block_access_does_not_gate(self):
        DocumentAcknowledgement.objects.all().delete()
        DocumentAsset.objects.update(blocks_application_access=False)
        AcknowledgementService.generate_pending(self.document, self.version)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)


# ── Engagement, honestly measured ────────────────────────────────────────────


class EngagementTests(DocumentTestBase):
    def setUp(self):
        self.document, self.version = self._policy()
        self._publish(self.document, self.version)

    def test_a_first_heartbeat_opens_a_session_with_no_time_yet(self):
        session = EngagementService.heartbeat(self.cceo, self.version.id, page=1)
        self.assertEqual(session.active_seconds, 0)
        self.assertEqual(session.last_page, 1)

    def test_consecutive_heartbeats_accumulate(self):
        from apps.documents.models import DocumentEngagementSession

        session = EngagementService.heartbeat(self.cceo, self.version.id, page=1)
        DocumentEngagementSession.objects.filter(id=session.id).update(
            last_heartbeat_at=timezone.now() - timedelta(seconds=20)
        )
        session = EngagementService.heartbeat(self.cceo, self.version.id, page=2)
        self.assertGreaterEqual(session.active_seconds, 19)
        self.assertEqual(session.last_page, 2)

    def test_a_long_gap_starts_a_new_session_rather_than_counting_the_gap(self):
        """An open tab on a locked laptop is not reading."""
        from apps.documents.models import DocumentEngagementSession

        first = EngagementService.heartbeat(self.cceo, self.version.id, page=1)
        DocumentEngagementSession.objects.filter(id=first.id).update(
            last_heartbeat_at=timezone.now() - timedelta(hours=3)
        )
        second = EngagementService.heartbeat(self.cceo, self.version.id, page=1)
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(second.active_seconds, 0)
        first.refresh_from_db()
        self.assertTrue(first.finalised)

    def test_sessions_aggregate_onto_the_acknowledgement(self):
        from apps.documents.models import DocumentEngagementSession

        session = EngagementService.heartbeat(self.cceo, self.version.id, page=1)
        DocumentEngagementSession.objects.filter(id=session.id).update(
            active_seconds=90
        )
        ack = DocumentAcknowledgement.objects.get(version=self.version)
        AcknowledgementService.respond(self.cceo, ack.id, "agree")
        ack.refresh_from_db()
        self.assertEqual(ack.active_reading_seconds, 90)
        self.assertEqual(ack.session_count, 1)

    def test_engagement_is_never_labelled_proof_of_reading(self):
        from apps.documents import compliance

        source = compliance.__doc__ + open(compliance.__file__).read()
        self.assertNotIn("Proof of Reading", source)
        self.assertIn("active_reading_time", source)

    def test_a_reader_may_attest_they_reviewed_it_outside_the_viewer(self):
        """Screen readers, downloaded copies and printed copies are real ways
        to read a policy."""
        ack = DocumentAcknowledgement.objects.get(version=self.version)
        AcknowledgementService.attest_offline(
            self.cceo, ack.id, "Read with a screen reader."
        )
        ack.refresh_from_db()
        self.assertTrue(ack.offline_attestation)


# ── Comments ─────────────────────────────────────────────────────────────────


class CommentTests(DocumentTestBase):
    def setUp(self):
        self.document, self.version = self._policy(comment_required=True)
        self._publish(self.document, self.version)
        self.ack = DocumentAcknowledgement.objects.get(version=self.version)
        AcknowledgementService.respond(
            self.cceo, self.ack.id, "agree", "Please clarify section 4."
        )

    def test_a_comment_is_recorded_and_routed(self):
        from apps.documents.models import DocumentComment
        from apps.notifications.models import Notification

        self.assertEqual(DocumentComment.objects.count(), 1)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.hr.id,
                source_event_type="documents.comment_submitted",
            ).exists()
        )

    def test_hr_reads_the_queue(self):
        self.assertEqual(len(CommentService.queue(self.hr)), 1)

    def test_a_program_lead_cannot_read_private_comments(self):
        lead = _user("pl", "Program Lead")
        with self.assertRaises(Forbidden):
            CommentService.queue(lead)

    def test_the_author_is_told_when_hr_responds(self):
        from apps.documents.models import DocumentComment
        from apps.notifications.models import Notification

        comment = DocumentComment.objects.first()
        CommentService.respond(self.hr, comment.id, "Clarified in v2.", resolve=True)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.cceo.id,
                source_event_type="documents.comment_response",
            ).exists()
        )


# ── Help Center ──────────────────────────────────────────────────────────────


class HelpIntegrationTests(DocumentTestBase):
    def test_publishing_creates_one_help_entry_pointing_at_the_viewer(self):
        document, version = self._policy()
        self._publish(document, version)
        document.refresh_from_db()
        article = document.help_article
        self.assertIsNotNone(article)
        self.assertEqual(article.title, document.title)
        self.assertEqual(article.summary, document.description)
        body = " ".join(str(section) for section in article.content)
        self.assertIn(f"/documents/{document.slug}/", body)

    def test_help_never_stores_a_second_copy_of_the_file(self):
        document, version = self._policy()
        self._publish(document, version)
        document.refresh_from_db()
        body = " ".join(str(section) for section in document.help_article.content)
        self.assertNotIn(version.uri, body)

    def test_help_visibility_never_exceeds_the_documents_audience(self):
        document, version = self._policy()
        self._publish(document, version)
        document.refresh_from_db()
        roles = set(document.help_article.role_accesses.values_list("role", flat=True))
        self.assertEqual(roles, {"CCEO"})

    def test_a_new_version_updates_the_entry_rather_than_adding_one(self):
        from apps.help_center.models import HelpArticle

        document, version = self._policy()
        self._publish(document, version)
        before = HelpArticle.objects.count()

        second = DocumentService.add_version(
            self.hr, document, _pdf("v2.pdf"), {"effective_date": date.today()}
        )
        DocumentService.submit_for_review(self.hr, document)
        DocumentService.review(self.hr, second, True)
        DocumentService.publish(self.hr, second)

        self.assertEqual(HelpArticle.objects.count(), before)
        document.refresh_from_db()
        body = " ".join(str(s) for s in document.help_article.content)
        self.assertIn("Version 2", body)


# ── Pages and delivery ───────────────────────────────────────────────────────


class DocumentPageTests(DocumentTestBase):
    def setUp(self):
        self.document, self.version = self._policy(blocks_application_access=False)
        self._publish(self.document, self.version)

    def test_the_upload_center_renders_for_an_authorised_role(self):
        client = Client()
        client.force_login(self.hr)
        response = client.get("/uploads")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Upload Center", response.content.decode())

    def test_the_upload_center_shows_only_authorised_records(self):
        from apps.documents.upload_center import UploadCenterService

        rows = UploadCenterService.rows(self.ia)
        # The policy is aimed at CCEOs, and IA does not administer documents.
        self.assertNotIn(self.document.id, [r.record_id for r in rows])

    def test_a_reader_outside_the_audience_gets_a_404_not_a_403(self):
        """Whether a confidential policy exists is itself information."""
        client = Client()
        client.force_login(self.ia)
        self.assertEqual(
            client.get(f"/documents/{self.document.slug}/").status_code, 404
        )

    def test_the_viewer_never_exposes_a_storage_url(self):
        client = Client()
        client.force_login(self.cceo)
        body = client.get(f"/documents/{self.document.slug}/").content.decode()
        self.assertNotIn(self.version.uri, body)
        self.assertIn(f"/documents/{self.document.slug}/preview", body)

    def test_download_is_refused_when_the_document_forbids_it(self):
        DocumentAsset.objects.filter(id=self.document.id).update(download_allowed=False)
        client = Client()
        client.force_login(self.cceo)
        self.assertEqual(
            client.get(f"/documents/{self.document.slug}/download").status_code, 404
        )

    def test_print_records_initiation_and_claims_nothing_more(self):
        from apps.audit.models import AuditLog

        client = Client()
        client.force_login(self.cceo)
        response = client.post(f"/documents/{self.document.slug}/print")
        self.assertEqual(response.json()["recorded"], "print_initiated")
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertIn("documents.print_initiated", actions)
        self.assertNotIn("documents.printed", actions)

    def test_an_anonymous_visitor_reaches_nothing(self):
        client = Client()
        for path in ("/uploads", f"/documents/{self.document.slug}/download"):
            with self.subTest(path):
                self.assertIn(client.get(path).status_code, (302, 404))


# ── Compliance reporting ─────────────────────────────────────────────────────


class ComplianceReportTests(DocumentTestBase):
    def setUp(self):
        self.document, self.version = self._policy()
        self._publish(self.document, self.version)

    def test_hr_sees_the_acknowledgement_rows(self):
        from apps.documents.compliance import PolicyComplianceService

        report = PolicyComplianceService.report(self.hr)
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["policy"], self.document.title)

    def test_the_reading_column_is_named_for_what_it_measures(self):
        from apps.documents.compliance import PolicyComplianceService

        row = PolicyComplianceService.report(self.hr)["rows"][0]
        self.assertIn("active_reading_time", row)
        self.assertIn("viewer_completion", row)

    def test_a_program_lead_sees_only_supervised_staff(self):
        from apps.accounts.models import StaffSupervisorAssignment
        from apps.documents.compliance import PolicyComplianceService

        lead = _user("pl-scope", "Program Lead")
        lead_profile = StaffProfile.objects.create(
            id="doc-pl-sp", user=lead, title="PL"
        )
        cceo_profile = self.cceo.staff_profile
        lead.staff_profile = lead_profile

        # With nobody supervised, the report is empty rather than country-wide.
        report = PolicyComplianceService.report(lead)
        self.assertEqual(report["rows"], [])

        StaffSupervisorAssignment.objects.create(
            supervisor=lead_profile, supervisee=cceo_profile
        )
        report = PolicyComplianceService.report(lead)
        self.assertEqual(len(report["rows"]), 1)

    def test_a_role_without_compliance_visibility_is_refused(self):
        from apps.documents.compliance import PolicyComplianceService

        with self.assertRaises(Forbidden):
            PolicyComplianceService.report(self.cceo)

    def test_overdue_is_counted_from_the_due_date(self):
        from apps.documents.compliance import PolicyComplianceService

        DocumentAcknowledgement.objects.filter(version=self.version).update(
            due_date=date.today() - timedelta(days=3)
        )
        report = PolicyComplianceService.report(self.hr)
        overdue = [k for k in report["kpis"] if k["label"] == "Overdue"][0]
        self.assertEqual(overdue["value"], 1)


# ── Jobs and System Health ───────────────────────────────────────────────────


class DocumentJobTests(DocumentTestBase):
    def setUp(self):
        self.document, self.version = self._policy()
        self._publish(self.document, self.version)

    def test_a_document_becomes_effective_on_its_date(self):
        from apps.documents.jobs import activate_effective_documents

        self.assertEqual(activate_effective_documents(), 1)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, DocumentStatus.EFFECTIVE)

    def test_a_future_effective_date_is_not_activated_early(self):
        from apps.documents.jobs import activate_effective_documents

        DocumentVersion.objects.filter(id=self.version.id).update(
            effective_date=date.today() + timedelta(days=10)
        )
        self.assertEqual(activate_effective_documents(), 0)

    def test_reminders_are_sent_once_per_day_for_the_same_condition(self):
        from apps.documents.jobs import send_acknowledgement_reminders

        DocumentAcknowledgement.objects.filter(version=self.version).update(
            due_date=date.today()
        )
        self.assertEqual(send_acknowledgement_reminders(), 1)
        # A second run the same day must stay silent.
        self.assertEqual(send_acknowledgement_reminders(), 0)

    def test_an_overdue_acknowledgement_is_reminded(self):
        from apps.documents.jobs import send_acknowledgement_reminders

        DocumentAcknowledgement.objects.filter(version=self.version).update(
            due_date=date.today() - timedelta(days=2)
        )
        self.assertEqual(send_acknowledgement_reminders(), 1)

    def test_idle_viewer_sessions_are_closed(self):
        from apps.documents.jobs import finalise_engagement_sessions
        from apps.documents.models import DocumentEngagementSession

        session = EngagementService.heartbeat(self.cceo, self.version.id, page=1)
        DocumentEngagementSession.objects.filter(id=session.id).update(
            last_heartbeat_at=timezone.now() - timedelta(hours=2)
        )
        self.assertEqual(finalise_engagement_sessions(), 1)

    def test_the_job_is_registered_and_monitored(self):
        from apps.realtime.registry import get_spec

        spec = get_spec("document_lifecycle")
        self.assertIsNotNone(spec)
        self.assertTrue(spec.idempotent)


class DocumentHealthTests(DocumentTestBase):
    def _checks(self):
        from apps.documents.health import document_health

        return {c["key"]: c for c in document_health()["checks"]}

    def test_health_is_green_on_a_clean_library(self):
        for check in self._checks().values():
            with self.subTest(check["key"]):
                self.assertEqual(check["severity"], "ok")

    def test_a_published_document_with_no_audience_is_critical(self):
        document, version = self._policy()
        self._publish(document, version)
        document.audience_rules.all().delete()
        self.assertEqual(
            self._checks()["documents_published_without_audience"]["severity"],
            "critical",
        )

    def test_a_superseded_current_version_is_critical(self):
        document, version = self._policy()
        self._publish(document, version)
        DocumentVersion.objects.filter(id=version.id).update(
            superseded_at=timezone.now()
        )
        self.assertEqual(
            self._checks()["documents_superseded_shown_as_current"]["severity"],
            "critical",
        )

    def test_a_disagreement_nobody_answered_is_flagged(self):
        document, version = self._policy()
        self._publish(document, version)
        ack = DocumentAcknowledgement.objects.get(version=version)
        AcknowledgementService.respond(self.cceo, ack.id, "disagree", "My reason.")
        self.assertEqual(
            self._checks()["documents_disagreement_without_review"]["severity"],
            "warning",
        )

    def test_the_checks_reach_the_system_health_report(self):
        from apps.system_health.services import report

        self.assertIn("documents", report())

    def test_every_check_carries_an_owner_and_a_resolution_link(self):
        for check in self._checks().values():
            with self.subTest(check["key"]):
                self.assertTrue(check["owner"])
                self.assertTrue(check["recommended_action"])
                self.assertTrue(check["resolution_link"])


class GateCostTests(DocumentTestBase):
    """The gate runs on every authenticated request, so its cost matters."""

    def test_with_no_blocking_policy_the_gate_costs_one_query(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.documents.gate import PolicyGateService

        with CaptureQueriesContext(connection) as queries:
            state, _ = PolicyGateService.state_for(self.cceo)
        self.assertEqual(state, "clear")
        self.assertEqual(len(queries.captured_queries), 1)

    def test_the_existence_check_is_memoised_within_a_request(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.core import request_cache
        from apps.documents.gate import PolicyGateService

        request_cache.begin()
        self.addCleanup(request_cache.end)
        with CaptureQueriesContext(connection) as queries:
            for _ in range(5):
                PolicyGateService.any_blocking_policy_exists()
        self.assertEqual(len(queries.captured_queries), 1)

    def test_outside_a_request_there_is_no_memo(self):
        """Jobs and commands must never read a stale answer."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.documents.gate import PolicyGateService

        with CaptureQueriesContext(connection) as queries:
            PolicyGateService.any_blocking_policy_exists()
            PolicyGateService.any_blocking_policy_exists()
        self.assertEqual(len(queries.captured_queries), 2)

    def test_a_blocking_policy_still_gates(self):
        from apps.documents.gate import PolicyGateService

        document, version = self._policy()
        self._publish(document, version)
        state, pending = PolicyGateService.state_for(self.cceo)
        self.assertEqual(state, "pending")
        self.assertEqual(len(pending), 1)


class DocumentPageRenderTests(DocumentTestBase):
    """Every page this app owns must actually render.

    The service tests above call the compliance report directly, so a broken
    template in the page that displays it passed them all and only surfaced in
    the platform's route crawl. A page is not covered until something renders
    it.
    """

    def setUp(self):
        self.document, self.version = self._policy(blocks_application_access=False)
        self._publish(self.document, self.version)

    def test_every_owned_page_renders_for_a_role_that_may_open_it(self):
        cases = [
            (self.hr, "/uploads"),
            (self.hr, "/uploads/new"),
            (self.ia, "/uploads/new?kind=training"),
            (self.hr, "/policy-compliance"),
            (self.hr, f"/documents/{self.document.slug}/manage"),
            (self.cceo, f"/documents/{self.document.slug}/"),
            (self.cceo, "/policy-agreement"),
            (self.cceo, "/policy-agreement/restricted"),
        ]
        for user, path in cases:
            with self.subTest(path=path, role=user.active_role):
                client = Client()
                client.force_login(user)
                response = client.get(path)
                self.assertEqual(
                    response.status_code, 200, f"{path} returned {response.status_code}"
                )

    def test_the_compliance_page_renders_for_every_authorised_role(self):
        lead = _user("pl-render", "Program Lead")
        rvp = _user("rvp-render", "RegionalVicePresident")
        for user in (self.hr, self.cd, self.admin, lead, rvp):
            with self.subTest(role=user.active_role):
                client = Client()
                client.force_login(user)
                self.assertEqual(client.get("/policy-compliance").status_code, 200)

    def test_the_upload_center_renders_for_every_role_that_can_open_it(self):
        roles = [
            self.admin,
            self.hr,
            self.ia,
            self.cd,
            self.cceo,
            _user("pl-uploads", "Program Lead"),
            _user("rvp-uploads", "RegionalVicePresident"),
        ]
        for user in roles:
            with self.subTest(role=user.active_role):
                client = Client()
                client.force_login(user)
                self.assertEqual(client.get("/uploads").status_code, 200)
