"""SEC-A1 — an unauthenticated visitor is not a member of any audience.

"Everyone" is written as a present audience rule with no field set. Every
per-field check in `audience_matches` is a `continue` on mismatch, so a rule
constraining nothing fell through to `return True` for whoever asked —
including `AnonymousUser`. The document routes are audience-gated rather than
role-gated by design and carry no `@require_page_permission`, and no
middleware requires a session, so a published organisation-wide document was
readable and its file downloadable off the open internet.

The production seed migration for the first-login agreements
(`0002_seed_first_login_agreements`) creates precisely that rule and returns
early when `settings.IS_TESTING`, so no test database ever held the shape that
would have exposed this. These tests build it explicitly.
"""

from __future__ import annotations

from django.contrib.auth.models import AnonymousUser
from django.core.files.base import ContentFile
from django.test import Client, TestCase
from django.utils import timezone
from uuid import uuid4

from apps.core.private_storage import best_effort_delete, save_file
from apps.documents.models import (
    DocumentAsset,
    DocumentAudienceRule,
    DocumentVersion,
)
from apps.documents.services import audience_matches
from apps.documents.storage import DOCUMENT_NAMESPACE


def _published_document(slug: str, *, uri: str, download_allowed: bool = True):
    """A published document whose audience rule constrains nothing."""
    document = DocumentAsset.objects.create(
        slug=slug,
        title=f"Policy {slug}",
        description="fixture",
        category="Safeguarding",
        status="published",
        acknowledgement_required=False,
        download_allowed=download_allowed,
        print_allowed=True,
        created_by="system",
    )
    version = DocumentVersion.objects.create(
        document=document,
        version_number=1,
        uri=uri,
        original_filename="policy.pdf",
        mime_type="application/pdf",
        file_size=26,
        checksum="c" * 64,
        effective_date=timezone.localdate(),
        change_summary="fixture",
        material_change=True,
        uploaded_by="system",
        reviewed_by="system",
        reviewed_at=timezone.now(),
        review_decision="approved",
        published_by="system",
        published_at=timezone.now(),
        preview_status="not_required",
        scan_status="clean",
    )
    document.current_version = version
    document.save(update_fields=["current_version"])
    # Exactly what the production seed migration writes for "everyone".
    DocumentAudienceRule.objects.create(document=document)
    return document


class AnonymousIsNeverInAnAudienceTest(TestCase):
    def test_unconstrained_rule_does_not_match_anonymous(self):
        document = _published_document("probe-universal", uri="probe-universal.pdf")
        self.assertFalse(audience_matches(document, AnonymousUser()))

    def test_anonymous_cannot_open_the_document_viewer(self):
        document = _published_document("probe-viewer", uri="probe-viewer.pdf")
        response = Client().get(f"/documents/{document.slug}/")
        self.assertEqual(response.status_code, 404)

    def test_anonymous_cannot_download_the_file_body(self):
        """The regression that mattered: the bytes came back over HTTP 200."""
        # Object storage is not covered by the test transaction, so the name
        # is unique per run and removed afterwards. A fixture that survives
        # its own test fails the second time it is run.
        stored_name = f"probe-download-{uuid4().hex}.pdf"
        save_file(
            DOCUMENT_NAMESPACE,
            stored_name,
            ContentFile(b"CONFIDENTIAL-DOCUMENT-BODY"),
        )
        self.addCleanup(best_effort_delete, DOCUMENT_NAMESPACE, stored_name)
        document = _published_document("probe-download", uri=stored_name)
        response = Client().get(f"/documents/{document.slug}/download")
        self.assertEqual(response.status_code, 404)
        body = (
            b"".join(response.streaming_content)
            if getattr(response, "streaming", False)
            else response.content
        )
        self.assertNotIn(b"CONFIDENTIAL-DOCUMENT-BODY", body)

    def test_anonymous_cannot_reach_the_preview_stream(self):
        document = _published_document("probe-preview", uri="probe-preview.pdf")
        response = Client().get(f"/documents/{document.slug}/preview")
        self.assertEqual(response.status_code, 404)

    def test_an_authenticated_user_still_matches_the_everyone_rule(self):
        """The fix must not close the audience it was written to open."""
        from apps.accounts.models import User

        document = _published_document("probe-still-open", uri="probe-open.pdf")
        user = User.objects.create(
            email="audience-probe@edify.test",
            password="x",
            is_active=True,
        )
        self.assertTrue(audience_matches(document, user))


class StaleDeepLinksAndSignedOutLandingTest(TestCase):
    """SEC-A2/A3 — a dead acknowledgement link and the restricted landing page.

    `AcknowledgementService.respond` and `attest_offline` fetch by id with no
    guard. A superseded or withdrawn acknowledgement leaves live deep links
    behind it — in the reminder mail, in a To-Do, in a bookmark — and following
    one answered 500 rather than saying what happened. `restricted_view`
    answered 200 to a signed-out caller, where the Agreement Center beside it
    redirects to the login form.
    """

    def test_unknown_acknowledgement_does_not_500(self):
        for path in (
            "/api/documents/acknowledge/does-not-exist",
            "/api/documents/attest/does-not-exist",
        ):
            response = Client().post(path)
            self.assertNotEqual(response.status_code, 500, path)

    def test_restricted_landing_sends_a_signed_out_reader_to_login(self):
        response = Client().get("/policy-agreement/restricted")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")
