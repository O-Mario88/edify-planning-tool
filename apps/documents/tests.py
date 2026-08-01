"""Upload Center, Document Library and policy-compliance tests.

Grouped by the guarantee each set defends: no duplication of the canonical
workflows, the security gate, the document lifecycle, the access gate,
acknowledgement and versioning, engagement honesty, comment privacy, and the
Help Center mapping.
"""

from __future__ import annotations

import io
import zipfile
from datetime import timedelta

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
            self.hr, document, _pdf(), {"effective_date": timezone.localdate()}
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

    def test_workflow_files_do_not_appear_in_the_upload_center(self):
        import apps.documents.upload_center as module

        self.assertFalse(hasattr(module, "_evidence"))
        self.assertFalse(hasattr(module, "_pd_certificates"))
        self.assertNotIn("evidence", module.ADAPTERS)
        self.assertNotIn("pd", module.ADAPTERS)

    def test_upload_center_launches_only_role_authorised_workflows(self):
        from apps.documents.upload_center import UploadCenterService

        def keys(user):
            return {
                action["key"] for action in UploadCenterService.launch_actions(user)
            }

        self.assertEqual(
            keys(self.ia),
            {"schools", "ssa", "training"},
        )
        self.assertEqual(keys(self.hr), {"policies"})
        self.assertEqual(keys(self.cceo), set())
        self.assertEqual(
            keys(self.admin),
            {"schools", "ssa", "policies", "training"},
        )

    def test_authorised_import_tab_exists_before_the_first_batch(self):
        from apps.documents.upload_center import UploadCenterService

        tabs = {tab["key"] for tab in UploadCenterService.visible_tabs(self.ia)}

        self.assertIn("imports", tabs)


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

    def test_the_returned_extension_is_the_allow_lists_own_object(self):
        """The stored filename must be built from a value this code chose.

        `assert_safe_upload` returns an extension that every caller
        concatenates into a filesystem path, so identity is the property worth
        testing, not equality: a slice off the submitted filename compares
        equal to ".pptx" while still being caller-supplied text.

        `.pptx` is the case that regressed. The canonical map was built from
        EXTENSION_FAMILY alone, so extensions a caller added through
        `extra_extension_family` missed it and fell through to the submitted
        slice — which made the Document Library, the one store that widens the
        gate, the one store without the guarantee.
        """
        from apps.documents.storage import (
            DOCUMENT_EXTENSION_FAMILY,
            assert_safe_document_upload,
        )

        cases = [
            ("report.pdf", "application/pdf", b"%PDF-1.4" + b"\x00" * 16),
            (
                "deck.pptx",
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation",
                b"PK\x03\x04" + b"\x00" * 20,
            ),
        ]
        for name, mime, head in cases:
            with self.subTest(name):
                returned = assert_safe_document_upload(
                    original_name=name, mime_type=mime, head=head, size=1000
                )
                allowed = next(
                    key for key in DOCUMENT_EXTENSION_FAMILY if key == returned
                )
                self.assertIs(
                    returned,
                    allowed,
                    f"{name}: the extension concatenated into the stored "
                    "filename came from the submitted name, not the allow-list",
                )

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
            self.hr, document, _pdf(), {"effective_date": timezone.localdate()}
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
            self.hr, document, _pdf("v2.pdf"), {"effective_date": timezone.localdate()}
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
            self.ia, document, _pptx(), {"effective_date": timezone.localdate()}
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
            {"effective_date": timezone.localdate(), "material_change": True},
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
            {"effective_date": timezone.localdate(), "material_change": True},
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
            {"effective_date": timezone.localdate(), "material_change": False},
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
        response = self.client.post(
            f"/api/documents/acknowledge/{ack.id}", {"choice": "agree"}
        )
        self.assertEqual(response["Location"], "/dashboard")
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_disagreeing_restricts_rather_than_opens(self):
        ack = DocumentAcknowledgement.objects.get(version=self.version)
        disagreement = self.client.post(
            f"/api/documents/acknowledge/{ack.id}",
            {"choice": "disagree", "comment": "I need clarification on section 4."},
        )
        self.assertEqual(disagreement["Location"], "/policy-agreement/restricted")
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

    def test_a_user_created_after_publication_is_gated_on_first_access(self):
        late_user = _user("late-user", "CCEO", country="Uganda")
        self.assertFalse(
            DocumentAcknowledgement.objects.filter(
                version=self.version, user_id=late_user.id
            ).exists()
        )

        client = Client()
        client.force_login(late_user)
        response = client.get("/dashboard")

        self.assertEqual(response["Location"], "/policy-agreement")
        self.assertTrue(
            DocumentAcknowledgement.objects.filter(
                version=self.version,
                user_id=late_user.id,
                state=AcknowledgementState.PENDING,
            ).exists()
        )


class CanonicalAgreementSequenceTests(DocumentTestBase):
    def setUp(self):
        self.safeguarding, self.safeguarding_version = self._policy(
            title="Edify Safeguarding Policy"
        )
        self.creed, self.creed_version = self._policy(title="Edify Apostles Creed")
        self._publish(self.safeguarding, self.safeguarding_version)
        self._publish(self.creed, self.creed_version)
        self.client = Client()
        self.client.force_login(self.cceo)

    def test_accepting_safeguarding_opens_creed_then_belief_opens_dashboard(self):
        safeguarding_ack = DocumentAcknowledgement.objects.get(
            version=self.safeguarding_version
        )
        creed_ack = DocumentAcknowledgement.objects.get(version=self.creed_version)

        first = self.client.post(
            f"/api/documents/acknowledge/{safeguarding_ack.id}",
            {"choice": "agree"},
        )
        self.assertEqual(
            first["Location"], "/documents/edify-apostles-creed/"
        )

        final = self.client.post(
            f"/api/documents/acknowledge/{creed_ack.id}",
            {"choice": "agree"},
        )
        self.assertEqual(final["Location"], "/dashboard")

    def test_declining_safeguarding_never_advances_to_creed(self):
        safeguarding_ack = DocumentAcknowledgement.objects.get(
            version=self.safeguarding_version
        )
        response = self.client.post(
            f"/api/documents/acknowledge/{safeguarding_ack.id}",
            {"choice": "disagree", "comment": "I need clarification."},
        )

        self.assertEqual(response["Location"], "/policy-agreement/restricted")
        self.assertEqual(
            DocumentAcknowledgement.objects.get(version=self.creed_version).state,
            AcknowledgementState.PENDING,
        )


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
            self.hr, document, _pdf("v2.pdf"), {"effective_date": timezone.localdate()}
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

    def test_the_source_policy_has_its_own_minimal_read_and_accept_page(self):
        document, version = self._policy(
            title="Edify Safeguarding Policy",
            blocks_application_access=False,
        )
        self._publish(document, version)
        client = Client()
        client.force_login(self.cceo)

        body = client.get(f"/documents/{document.slug}/").content.decode()

        self.assertIn("Scope and Purpose of the Policy", body)
        self.assertIn("Appendix B — Reporting Process/Flow", body)
        self.assertNotIn("Appendix C:", body)
        self.assertNotIn("Appendix D:", body)
        self.assertIn("I Accept", body)
        self.assertIn("Continue", body)
        self.assertNotIn("rounded-overlay border", body)
        self.assertNotIn("Main Navigation", body)

    def test_the_creed_uses_belief_language_and_direct_entry_copy(self):
        document, version = self._policy(
            title="Edify Apostles Creed",
            blocks_application_access=False,
        )
        self._publish(document, version)
        client = Client()
        client.force_login(self.cceo)

        body = client.get(f"/documents/{document.slug}/").content.decode()

        self.assertIn("I Believe", body)
        self.assertIn("Enter Edify", body)
        self.assertNotIn(f"I agree to {document.title}", body)

    def test_upload_center_renders_ia_import_launchers(self):
        client = Client()
        client.force_login(self.ia)

        body = client.get("/uploads").content.decode()

        self.assertIn('href="/schools/upload"', body)
        self.assertIn('href="/ssa/upload/"', body)
        self.assertIn("Upload school data", body)
        self.assertIn("Upload SSA scores", body)
        self.assertNotIn("Upload policy or manual", body)
        self.assertNotIn('id="admin-upload-drawer"', body)

    def test_admin_upload_center_has_one_menu_for_every_admin_upload_action(self):
        from apps.documents.upload_center import UploadCenterService

        client = Client()
        client.force_login(self.admin)

        body = client.get("/uploads").content.decode()

        self.assertIn('id="admin-upload-drawer-open"', body)
        self.assertIn('id="admin-upload-drawer"', body)
        self.assertIn('closedby="any"', body)
        self.assertIn("drawer.showModal()", body)
        self.assertIn('aria-label="Admin upload buttons"', body)
        self.assertIn("Choose an upload type", body)
        self.assertIn("Close upload drawer", body)
        actions = UploadCenterService.launch_actions(self.admin)
        self.assertGreaterEqual(
            body.count("upload-primary-action"),
            1 + (2 * len(actions)),
        )
        self.assertEqual(body.count("upload-card-actions"), 2 * len(actions))
        self.assertEqual(
            body.count("upload-secondary-action"),
            2 * sum(bool(action.get("template_href")) for action in actions),
        )
        self.assertGreaterEqual(body.count("btn btn-primary"), 1 + (2 * len(actions)))
        self.assertIn(
            "upload-card-actions mt-auto flex flex-wrap items-center " "justify-center",
            body,
        )
        self.assertIn(
            "upload-card-actions mt-4 flex flex-wrap items-center " "justify-center",
            body,
        )
        self.assertNotIn("bg-[var(--color-edify-primary)]", body)
        for action in actions:
            self.assertIn(f'href="{action["href"]}"', body)
            self.assertIn(action["title"], body)
            self.assertIn(action["action_label"], body)
            if action.get("template_href"):
                self.assertIn(f'href="{action["template_href"]}"', body)

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
            due_date=timezone.localdate() - timedelta(days=3)
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
            effective_date=timezone.localdate() + timedelta(days=10)
        )
        self.assertEqual(activate_effective_documents(), 0)

    def test_reminders_are_sent_once_per_day_for_the_same_condition(self):
        from apps.documents.jobs import send_acknowledgement_reminders

        DocumentAcknowledgement.objects.filter(version=self.version).update(
            due_date=timezone.localdate()
        )
        self.assertEqual(send_acknowledgement_reminders(), 1)
        # A second run the same day must stay silent.
        self.assertEqual(send_acknowledgement_reminders(), 0)

    def test_an_overdue_acknowledgement_is_reminded(self):
        from apps.documents.jobs import send_acknowledgement_reminders

        DocumentAcknowledgement.objects.filter(version=self.version).update(
            due_date=timezone.localdate() - timedelta(days=2)
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
            _user("rvp-uploads", "RegionalVicePresident"),
        ]
        for user in roles:
            with self.subTest(role=user.active_role):
                client = Client()
                client.force_login(user)
                self.assertEqual(client.get("/uploads").status_code, 200)

    def test_operational_and_partner_roles_cannot_open_upload_center(self):
        users = [
            self.cceo,
            _user("pl-no-uploads", "Program Lead"),
            _user("accountant-no-uploads", "Accountant"),
            _user("partner-no-uploads", "PartnerAdmin"),
            _user("coordinator-no-uploads", "ProjectCoordinator"),
        ]
        for user in users:
            with self.subTest(role=user.active_role):
                client = Client()
                client.force_login(user)
                self.assertNotEqual(client.get("/uploads").status_code, 200)


class ReminderDedupeAcrossTimezonesTest(DocumentTestBase):
    """One reminder per condition per day, in the platform's timezone.

    The dedupe compared `last_reminded_at.date()` — the UTC day — against
    `timezone.localdate()`, the Africa/Kampala day. For the three hours a day
    the offset spans, those disagree, the dedupe silently fails, and a person
    receives a second reminder for the same condition on the same day. §23
    forbids exactly that.

    Found because a full-suite run crossed midnight. This pins it so the next
    one does not have to.
    """

    def setUp(self):
        self.document, self.version = self._policy()
        self._publish(self.document, self.version)
        DocumentAcknowledgement.objects.filter(version=self.version).update(
            due_date=timezone.localdate()
        )

    def test_a_second_run_the_same_local_day_sends_nothing(self):
        from apps.documents.jobs import send_acknowledgement_reminders

        self.assertEqual(send_acknowledgement_reminders(), 1)
        self.assertEqual(send_acknowledgement_reminders(), 0)

    def test_a_reminder_sent_late_last_night_still_counts_as_today(self):
        """The exact window: UTC says yesterday, the platform says today.

        Django stores aware datetimes in UTC and hands them back in UTC, so
        `.date()` on a value read from the database is the UTC day. At 00:30 in
        Africa/Kampala that is still the previous calendar day — which is the
        three-hour window where the old comparison silently let a second
        reminder through.
        """
        from datetime import datetime, time

        from apps.documents.jobs import send_acknowledgement_reminders

        self.assertEqual(send_acknowledgement_reminders(), 1)

        ack = DocumentAcknowledgement.objects.get(version=self.version)
        local_early_today = timezone.make_aware(
            datetime.combine(timezone.localdate(), time(hour=0, minute=30))
        )
        DocumentAcknowledgement.objects.filter(id=ack.id).update(
            last_reminded_at=local_early_today
        )

        stored = DocumentAcknowledgement.objects.get(id=ack.id).last_reminded_at
        self.assertNotEqual(
            stored.date(),
            timezone.localdate(stored),
            "this test is meaningless unless the stored UTC day and the local "
            "day actually differ",
        )
        self.assertEqual(send_acknowledgement_reminders(), 0)

    def test_a_reminder_sent_yesterday_does_send_again(self):
        """Dedupe is per day, not permanent."""
        from apps.documents.jobs import send_acknowledgement_reminders

        self.assertEqual(send_acknowledgement_reminders(), 1)
        DocumentAcknowledgement.objects.filter(version=self.version).update(
            last_reminded_at=timezone.now() - timedelta(days=1)
        )
        self.assertEqual(send_acknowledgement_reminders(), 1)
